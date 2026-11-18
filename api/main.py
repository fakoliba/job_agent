from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.database import engine, get_db
from api.models import Application, JobMonitor, ResumeVersion, User, utc_now
from api.schemas import (
    ApplicationCreate,
    ApplicationUpdate,
    AuthResponse,
    LoginInput,
    MonitorCreate,
    ProfileUpdate,
    RegisterInput,
    ResumeMetadataUpdate,
    ResumeJobInput,
    CompanyPrepInput,
    CareerCoachInput,
    CompanyTargetInput,
    MarketIntelligenceInput,
    DiscoveryInput,
)
from api.security import bearer_scheme, create_session, get_current_user, revoke_session
from api.storage import UPLOAD_DIR, delete_upload, save_upload
from modules.auth import default_profile, hash_password, normalize_email
from modules.ingestion import safe_filename
from modules.parser import parse_resume_file, structure_resume
from modules.tracker import APPLICATION_STATUSES
from modules.matcher import score_resume_for_job
from modules.generator import (
    DraftRequest,
    generate_cover_letter,
    generate_outreach,
    generate_resume_bullets,
    generate_why_company,
)
from modules.interview import generate_interview_prep
from modules.company_intelligence import CompanyPrepRequest, build_company_interview_profile
from modules.career_intelligence import (
    build_career_coaching,
    build_market_intelligence,
    recommend_target_companies,
)
from modules.job_discovery import (
    LAST_DISCOVERY_CACHE_EVENTS,
    classify_careers_site,
    discover_jobs_for_targets,
    is_probable_job_link,
    is_probable_rendered_card,
    parse_company_targets,
)


app = FastAPI(title="Job Search Agent API", version="1.0.0")
api = APIRouter(prefix="/api/v1")
MAX_RESUME_BYTES = int(os.getenv("MAX_RESUME_BYTES", str(15 * 1024 * 1024)))
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".txt"}


def public_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "profile": {**default_profile(), **(user.profile or {})},
        "created_at": user.created_at.isoformat() if user.created_at else "",
    }


def auth_response(db: Session, user: User) -> dict[str, Any]:
    return {"access_token": create_session(db, user), "token_type": "bearer", "user": public_user(user)}


def resume_response(resume: ResumeVersion) -> dict[str, Any]:
    payload = dict(resume.payload or {})
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "version_name": resume.version_name,
            "notes": resume.notes,
            "created_at": metadata.get("created_at") or resume.created_at.isoformat(),
        }
    )
    payload.update(
        {
            "id": resume.id,
            "source_file": resume.source_file,
            "metadata": metadata,
            "target_roles": list(resume.target_roles or []),
            "_source_path": resume.id,
        }
    )
    return payload


def application_response(record: Application, username: str) -> dict[str, Any]:
    return {
        "id": record.id,
        "company": record.company,
        "role_title": record.role_title,
        "job_url": record.job_url,
        "location": record.location,
        "job_description": record.job_description,
        "resume_version": record.resume_version,
        "match_score": record.match_score,
        "status": record.status,
        "notes": record.notes,
        "source": record.source,
        "follow_up_date": record.follow_up_date,
        "username": username,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def monitor_response(record: JobMonitor, username: str) -> dict[str, Any]:
    return {
        "id": record.id,
        "username": username,
        "name": record.name,
        "target_companies": record.target_companies,
        "job_query": record.job_query,
        "resume_label": record.resume_label,
        "resume_id": record.resume_id,
        "max_jobs": record.max_jobs,
        "max_pages": record.max_pages,
        "seen_urls": list(record.seen_urls or []),
        "last_run_at": record.last_run_at,
        "last_new_count": record.last_new_count,
        "last_results": list(record.last_results or []),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_ready(item) for item in value]
    return value


def resume_label(resume: ResumeVersion) -> str:
    metadata = (resume.payload or {}).get("metadata") or {}
    candidate = metadata.get("candidate_name") or resume.source_file or "Resume"
    version = resume.version_name or Path(resume.source_file).stem
    return f"{candidate} - {version}"


def run_job_discovery(
    resume: ResumeVersion,
    targets_text: str,
    fallback_company: str,
    fallback_url: str,
    max_jobs: int,
    max_pages: int,
    use_rendered_fallback: bool,
    use_cache: bool,
    job_query: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    targets = parse_company_targets(targets_text, fallback_company=fallback_company, fallback_url=fallback_url)
    if not targets:
        raise HTTPException(status_code=422, detail="Add at least one valid careers URL, including http:// or https://.")

    classifications = {target.careers_url: classify_careers_site(target.careers_url) for target in targets}
    needs_rendered = any(item.category in {"hosted_ats", "custom_spa"} for item in classifications.values())
    rendered_enabled = use_rendered_fallback or needs_rendered
    jobs = discover_jobs_for_targets(
        targets,
        resume.payload or {},
        max_jobs_per_company=max_jobs,
        max_pages_per_company=max_pages,
        use_rendered_fallback=rendered_enabled,
        use_cache=use_cache,
        job_query=job_query,
    )
    jobs = [job for job in jobs if is_probable_job_link(job.url, job.title) or is_probable_rendered_card(job.url, job.title)] or jobs
    serialized_jobs = [json_ready(asdict(job)) for job in jobs]
    debug = {
        "classifications": {
            target.company: {
                "category": classifications[target.careers_url].category,
                "confidence": classifications[target.careers_url].confidence,
                "reasons": classifications[target.careers_url].reasons,
                "url": target.careers_url,
            }
            for target in targets
        },
        "cache_events": list(LAST_DISCOVERY_CACHE_EVENTS),
        "rendered_enabled": rendered_enabled,
        "max_pages": max_pages,
        "max_jobs": max_jobs,
        "query": job_query,
    }
    return serialized_jobs, debug


@app.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}


@api.post("/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = normalize_email(str(payload.email))
    first_name, last_name = payload.first_name.strip(), payload.last_name.strip()
    if not first_name or not last_name:
        raise HTTPException(status_code=422, detail="First and last name are required.")
    if db.scalar(select(User.id).where((User.email == email) | (User.username == email))):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    salt, password_hash = hash_password(payload.password)
    user = User(
        id=str(uuid.uuid4()),
        username=email,
        email=email,
        first_name=first_name,
        last_name=last_name,
        profile=default_profile(),
        password_salt=salt,
        password_hash=password_hash,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    db.refresh(user)
    return auth_response(db, user)


@api.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    identity = normalize_email(payload.username)
    user = db.scalar(select(User).where((User.username == identity) | (User.email == identity)))
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    _, candidate_hash = hash_password(payload.password, user.password_salt)
    import hmac

    if not hmac.compare_digest(candidate_hash, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return auth_response(db, user)


@api.get("/auth/me")
def get_profile(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return public_user(user)


@api.patch("/auth/me")
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    values = payload.model_dump(exclude_unset=True)
    if "email" in values:
        requested_email = values.pop("email")
        if requested_email is not None:
            email = normalize_email(str(requested_email))
            other = db.scalar(select(User.id).where(User.email == email, User.id != user.id))
            if other:
                raise HTTPException(status_code=409, detail="An account with that email already exists.")
            user.email = email
            user.username = email
    for key in ("first_name", "last_name"):
        if key in values and values[key] is not None:
            setattr(user, key, values.pop(key).strip())
    profile = {**default_profile(), **(user.profile or {})}
    for key, value in values.items():
        if value is not None:
            profile[key] = value
    user.profile = profile
    user.updated_at = utc_now()
    db.commit()
    db.refresh(user)
    return public_user(user)


@api.delete("/auth/session", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> None:
    revoke_session(credentials, db)


@api.get("/resumes")
def list_resumes(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    records = db.scalars(
        select(ResumeVersion)
        .where(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.created_at.desc())
        .limit(limit)
    ).all()
    return [resume_response(record) for record in records]


@api.post("/resumes", status_code=status.HTTP_201_CREATED)
def upload_resume(
    file: UploadFile = File(...),
    version_name: str = Form(default=""),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    original_name = Path(file.filename or "resume.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload a PDF, DOCX, or TXT resume.")
    content = file.file.read(MAX_RESUME_BYTES + 1)
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail=f"Resume exceeds the {MAX_RESUME_BYTES // (1024 * 1024)} MB limit.")
    safe_name = safe_filename(original_name)
    try:
        with tempfile.TemporaryDirectory(prefix="job-agent-resume-") as temp_dir:
            temp_path = Path(temp_dir) / safe_name
            temp_path.write_bytes(content)
            raw_text = parse_resume_file(temp_path)
        if not raw_text.strip():
            raise HTTPException(status_code=422, detail="No readable text was found in the uploaded resume.")
        structured = structure_resume(
            raw_text=raw_text,
            source_file=safe_name,
            version_name=version_name.strip() or Path(safe_name).stem,
            use_llm=use_llm,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse resume: {exc}") from exc

    metadata = structured.setdefault("metadata", {})
    resume_id = str(uuid.uuid4())
    try:
        storage_key = save_upload(user.id, resume_id, safe_name, content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Resume storage is unavailable.") from exc
    record = ResumeVersion(
        id=resume_id,
        user_id=user.id,
        source_file=safe_name,
        storage_key=storage_key,
        version_name=metadata.get("version_name") or Path(safe_name).stem,
        notes="",
        target_roles=list(structured.get("target_roles") or []),
        payload=structured,
    )
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        delete_upload(storage_key)
        raise
    return resume_response(record)


@api.patch("/resumes/{resume_id}")
def update_resume(
    resume_id: str,
    payload: ResumeMetadataUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    record = db.scalar(select(ResumeVersion).where(ResumeVersion.id == resume_id, ResumeVersion.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    record.version_name = payload.version_name.strip() or Path(record.source_file).stem
    record.notes = payload.notes.strip()
    record.target_roles = [role.strip() for role in payload.target_roles if role.strip()]
    record.payload = {**(record.payload or {}), "target_roles": record.target_roles}
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return resume_response(record)


@api.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    record = db.scalar(select(ResumeVersion).where(ResumeVersion.id == resume_id, ResumeVersion.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    db.delete(record)
    db.commit()
    if record.storage_key:
        delete_upload(record.storage_key)


@api.get("/resumes/{resume_id}/file")
def download_resume_file(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    record = db.scalar(select(ResumeVersion).where(ResumeVersion.id == resume_id, ResumeVersion.user_id == user.id))
    if record is None or not record.storage_key:
        raise HTTPException(status_code=404, detail="Resume file not found.")
    path = (UPLOAD_DIR / record.storage_key).resolve()
    if UPLOAD_DIR not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Resume file not found.")
    return FileResponse(path, filename=record.source_file, media_type="application/octet-stream")


@api.get("/applications")
def list_applications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    records = db.scalars(
        select(Application).where(Application.user_id == user.id).order_by(Application.created_at)
    ).all()
    return [application_response(record, user.username) for record in records]


@api.post("/applications", status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if payload.status not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown application status.")
    record = Application(id=str(uuid.uuid4()), user_id=user.id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return application_response(record, user.username)


@api.patch("/applications/{application_id}")
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    record = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    values = payload.model_dump(exclude_unset=True)
    if values.get("status") is not None and values["status"] not in APPLICATION_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown application status.")
    for key, value in values.items():
        if value is not None:
            setattr(record, key, value)
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return application_response(record, user.username)


@api.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    record = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    db.delete(record)
    db.commit()


@api.get("/monitors")
def list_monitors(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    records = db.scalars(
        select(JobMonitor).where(JobMonitor.user_id == user.id).order_by(JobMonitor.created_at)
    ).all()
    return [monitor_response(record, user.username) for record in records]


@api.post("/monitors", status_code=status.HTTP_201_CREATED)
def create_monitor(
    payload: MonitorCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if payload.resume_id and db.scalar(
        select(ResumeVersion.id).where(ResumeVersion.id == payload.resume_id, ResumeVersion.user_id == user.id)
    ) is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    record = JobMonitor(id=str(uuid.uuid4()), user_id=user.id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return monitor_response(record, user.username)


@api.post("/monitors/{monitor_id}/runs")
def update_monitor_run(
    monitor_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    record = db.scalar(select(JobMonitor).where(JobMonitor.id == monitor_id, JobMonitor.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=404, detail="Monitor not found.")
    resume = None
    if record.resume_id:
        resume = db.scalar(select(ResumeVersion).where(ResumeVersion.id == record.resume_id, ResumeVersion.user_id == user.id))
    if resume is None:
        user_resumes = db.scalars(select(ResumeVersion).where(ResumeVersion.user_id == user.id)).all()
        resume = next((item for item in user_resumes if resume_label(item) == record.resume_label), None)
        if resume is None and len(user_resumes) == 1:
            resume = user_resumes[0]
    if resume is None:
        raise HTTPException(status_code=409, detail="This monitor has no linked resume. Create it again with a resume selected.")

    discovered_jobs, _debug = run_job_discovery(
        resume=resume,
        targets_text=record.target_companies,
        fallback_company="",
        fallback_url="",
        max_jobs=record.max_jobs,
        max_pages=record.max_pages,
        use_rendered_fallback=True,
        use_cache=True,
        job_query=record.job_query,
    )
    seen_urls = set(record.seen_urls or [])
    new_jobs = [job for job in discovered_jobs if job.get("url") and job["url"] not in seen_urls]
    record.seen_urls = sorted(seen_urls.union(job.get("url", "") for job in discovered_jobs if job.get("url")))
    record.last_run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record.last_new_count = len(new_jobs)
    record.last_results = new_jobs
    record.updated_at = utc_now()
    db.commit()
    db.refresh(record)
    return {
        "monitor": monitor_response(record, user.username),
        "discovered_jobs": discovered_jobs,
        "new_jobs": new_jobs,
    }


@api.post("/discovery")
def discover_jobs(
    payload: DiscoveryInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    resume = db.scalar(
        select(ResumeVersion).where(ResumeVersion.id == payload.resume_id, ResumeVersion.user_id == user.id)
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    jobs, debug = run_job_discovery(
        resume=resume,
        targets_text=payload.target_companies,
        fallback_company=payload.fallback_company,
        fallback_url=payload.fallback_url,
        max_jobs=payload.max_jobs,
        max_pages=payload.max_pages,
        use_rendered_fallback=payload.use_rendered_fallback,
        use_cache=payload.use_cache,
        job_query=payload.job_query,
    )
    return {"jobs": jobs, "debug": debug}


@api.post("/analysis/match")
def analyze_match(
    payload: ResumeJobInput,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del user
    return json_ready(score_resume_for_job(payload.resume, payload.job_description))


@api.post("/analysis/draft")
def generate_draft(
    payload: ResumeJobInput,
    draft_type: str = Query(..., pattern="^(Resume Bullets|Why Company|Recruiter Outreach|Cover Letter)$"),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    del user
    request = DraftRequest(payload.resume, payload.job_description, payload.company, payload.role_title)
    generators = {
        "Resume Bullets": generate_resume_bullets,
        "Why Company": generate_why_company,
        "Recruiter Outreach": generate_outreach,
        "Cover Letter": generate_cover_letter,
    }
    return {"draft": generators[draft_type](request)}


@api.post("/analysis/interview-prep")
def generate_interview_prep_api(
    payload: ResumeJobInput,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    del user
    request = DraftRequest(payload.resume, payload.job_description, payload.company, payload.role_title)
    return {"prep": generate_interview_prep(request)}


@api.post("/analysis/company-prep")
def company_prep(
    payload: CompanyPrepInput,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del user
    request = CompanyPrepRequest(
        company=payload.company,
        role_title=payload.role_title,
        job_description=payload.job_description,
        resume=payload.resume,
        careers_url=payload.careers_url,
        prep_focus=payload.prep_focus,
    )
    return json_ready(build_company_interview_profile(request))


@api.post("/analysis/career-coach")
def career_coach(
    payload: CareerCoachInput,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del user
    return build_career_coaching(payload.resumes, payload.applications)


@api.post("/analysis/company-targets")
def company_targets(
    payload: CompanyTargetInput,
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    del user
    return recommend_target_companies(
        payload.resume,
        preferred_role=payload.preferred_role,
        preferred_stage=payload.preferred_stage,
        limit=payload.limit,
    )


@api.post("/analysis/market-intelligence")
def market_intelligence(
    payload: MarketIntelligenceInput,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    del user
    return json_ready(
        build_market_intelligence(payload.resume, payload.role_family, payload.location, payload.seniority)
    )


app.include_router(api)
