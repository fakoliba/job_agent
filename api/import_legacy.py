from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api.database import SessionLocal
from api.models import Application, JobMonitor, LegacyImport, ResumeVersion, User, utc_now
from api.storage import save_upload
from modules.auth import default_profile, normalize_email
from modules.tracker import APPLICATION_STATUSES


def read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return utc_now()


def already_imported(db, source_key: str) -> bool:
    return db.scalar(select(LegacyImport.id).where(LegacyImport.source_key == source_key)) is not None


def mark_imported(db, source_key: str) -> None:
    db.add(LegacyImport(id=str(uuid.uuid4()), source_key=source_key))
    db.commit()


def import_user(db, row: dict[str, Any]) -> User | None:
    source_id = str(row.get("id") or row.get("username") or row.get("email") or "").strip()
    if not source_id:
        return None
    source_key = f"users/{source_id}"
    email = normalize_email(str(row.get("email") or row.get("username") or ""))
    if not email:
        return None
    existing = db.scalar(select(User).where((User.email == email) | (User.username == email)))
    if existing:
        if not already_imported(db, source_key):
            mark_imported(db, source_key)
        return existing
    salt, password_hash = row.get("salt"), row.get("password_hash")
    if not salt or not password_hash:
        print(f"Skipped legacy user {email}: password hash was not present.")
        return None
    user = User(
        id=source_id if len(source_id) <= 36 else str(uuid.uuid4()),
        username=email,
        email=email,
        first_name=str(row.get("first_name") or ""),
        last_name=str(row.get("last_name") or ""),
        profile={**default_profile(), **(row.get("profile") or {})},
        password_salt=str(salt),
        password_hash=str(password_hash),
        created_at=parse_timestamp(row.get("created_at")),
        updated_at=parse_timestamp(row.get("updated_at")),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    mark_imported(db, source_key)
    return user


def user_for_username(db, username: str, fallback_email: str = "") -> User | None:
    identity = normalize_email(username)
    if identity:
        user = db.scalar(select(User).where((User.username == identity) | (User.email == identity)))
        if user:
            return user
    if fallback_email:
        fallback = normalize_email(fallback_email)
        return db.scalar(select(User).where((User.username == fallback) | (User.email == fallback)))
    return None


def import_applications(db, data_dir: Path, default_user_email: str) -> int:
    rows = read_json(data_dir / "applications.json", [])
    imported = 0
    for row in rows:
        source_id = str(row.get("id") or "").strip()
        if not source_id:
            continue
        source_key = f"applications/{source_id}"
        if already_imported(db, source_key):
            continue
        if db.get(Application, source_id) is not None:
            mark_imported(db, source_key)
            continue
        user = user_for_username(db, str(row.get("username") or ""), default_user_email)
        if user is None:
            print(f"Skipped application {source_id}: no matching user; use --default-user-email if appropriate.")
            continue
        status_value = str(row.get("status") or "Saved")
        record = Application(
            id=source_id,
            user_id=user.id,
            company=str(row.get("company") or ""),
            role_title=str(row.get("role_title") or ""),
            job_url=str(row.get("job_url") or ""),
            location=str(row.get("location") or ""),
            job_description=str(row.get("job_description") or ""),
            resume_version=str(row.get("resume_version") or ""),
            match_score=max(0, min(100, int(row.get("match_score") or 0))),
            status=status_value if status_value in APPLICATION_STATUSES else "Saved",
            notes=str(row.get("notes") or ""),
            source=str(row.get("source") or ""),
            follow_up_date=str(row.get("follow_up_date") or ""),
            created_at=parse_timestamp(row.get("created_at")),
            updated_at=parse_timestamp(row.get("updated_at")),
        )
        db.add(record)
        db.commit()
        mark_imported(db, source_key)
        imported += 1
    return imported


def import_monitors(db, data_dir: Path, default_user_email: str) -> int:
    rows = read_json(data_dir / "job_monitors.json", [])
    imported = 0
    for row in rows:
        source_id = str(row.get("id") or "").strip()
        if not source_id:
            continue
        source_key = f"job_monitors/{source_id}"
        if already_imported(db, source_key):
            continue
        if db.get(JobMonitor, source_id) is not None:
            mark_imported(db, source_key)
            continue
        user = user_for_username(db, str(row.get("username") or ""), default_user_email)
        if user is None:
            print(f"Skipped monitor {source_id}: no matching user; use --default-user-email if appropriate.")
            continue
        record = JobMonitor(
            id=source_id,
            user_id=user.id,
            name=str(row.get("name") or "Job Monitor"),
            target_companies=str(row.get("target_companies") or ""),
            job_query=str(row.get("job_query") or ""),
            resume_label=str(row.get("resume_label") or ""),
            max_jobs=max(1, min(100, int(row.get("max_jobs") or 10))),
            max_pages=max(1, min(20, int(row.get("max_pages") or 2))),
            seen_urls=list(row.get("seen_urls") or []),
            last_run_at=str(row.get("last_run_at") or ""),
            last_new_count=max(0, int(row.get("last_new_count") or 0)),
            created_at=parse_timestamp(row.get("created_at")),
            updated_at=parse_timestamp(row.get("updated_at")),
        )
        db.add(record)
        db.commit()
        mark_imported(db, source_key)
        imported += 1
    return imported


def import_resumes(db, data_dir: Path, owner_email: str) -> int:
    files = sorted((data_dir / "structured").glob("*.json"))
    if files and not owner_email:
        print(f"Found {len(files)} legacy resume(s), but their original owner is not recorded.")
        print("They were not imported. Re-run with --resume-owner-email after choosing the correct account.")
        return 0
    user = user_for_username(db, owner_email) if owner_email else None
    if files and user is None:
        print(f"Resume owner account {owner_email!r} was not found; no resumes were imported.")
        return 0
    imported = 0
    for path in files:
        source_key = f"structured/{path.name}"
        if already_imported(db, source_key):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Skipped {path.name}: {exc}")
            continue
        payload.pop("_source_path", None)
        metadata = payload.get("metadata") or {}
        resume_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"job-agent:{user.id}:{path.name}"))
        if db.get(ResumeVersion, resume_id) is not None:
            mark_imported(db, source_key)
            continue
        filename = Path(str(payload.get("source_file") or path.stem)).name
        record = ResumeVersion(
            id=resume_id,
            user_id=user.id,
            source_file=filename,
            version_name=str(metadata.get("version_name") or path.stem),
            notes=str(metadata.get("notes") or ""),
            target_roles=list(payload.get("target_roles") or []),
            payload=payload,
            created_at=parse_timestamp(metadata.get("created_at")),
            updated_at=parse_timestamp(metadata.get("created_at")),
        )
        original = data_dir / "resumes" / filename
        if original.is_file():
            try:
                record.storage_key = save_upload(user.id, resume_id, filename, original.read_bytes())
            except OSError as exc:
                print(f"Imported parsed resume {path.name}, but skipped its original file: {exc}")
        db.add(record)
        db.commit()
        mark_imported(db, source_key)
        imported += 1
    return imported


def import_legacy_data(data_dir: Path, default_user_email: str = "", resume_owner_email: str = "") -> None:
    data_dir = data_dir.resolve()
    with SessionLocal() as db:
        users = read_json(data_dir / "users.json", [])
        users_imported = sum(1 for row in users if import_user(db, row))
        applications_imported = import_applications(db, data_dir, default_user_email)
        monitors_imported = import_monitors(db, data_dir, default_user_email)
        resumes_imported = import_resumes(db, data_dir, resume_owner_email)
    print(
        "Import complete: "
        f"{users_imported} users, {resumes_imported} resumes, "
        f"{applications_imported} applications, {monitors_imported} monitors imported."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotently import the legacy JSON data directory.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--default-user-email", default="", help="Owner for legacy records with no username.")
    parser.add_argument("--resume-owner-email", default="", help="Owner for resumes, which had no user association.")
    args = parser.parse_args()
    import_legacy_data(args.data_dir, args.default_user_email, args.resume_owner_email)


if __name__ == "__main__":
    main()
