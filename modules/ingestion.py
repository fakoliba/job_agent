from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from pydantic import ValidationError

from modules.paths import JOBS_FILE, ensure_data_dirs
from modules.resume_store import load_index, load_parsed
from modules.schemas import Job, JobsFile, StructuredResume


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jobs() -> JobsFile:
    ensure_data_dirs()
    if not JOBS_FILE.exists():
        return JobsFile()
    try:
        return JobsFile.model_validate_json(JOBS_FILE.read_text())
    except (ValidationError, json.JSONDecodeError):
        return JobsFile()


def save_jobs(data: JobsFile) -> None:
    ensure_data_dirs()
    JOBS_FILE.write_text(data.model_dump_json(indent=2))


def add_job(
    title: str,
    company: str,
    description: str,
    source: str | None = None,
    url: str | None = None,
    selected_resume_id: str | None = None,
    match_score_10: int | None = None,
    match_feedback: str | None = None,
    match_resume_id: str | None = None,
    resume_scores: dict[str, dict] | None = None,
    suggested_resume_id: str | None = None,
    suggestion_low_confidence: bool | None = None,
) -> Job:
    data = load_jobs()
    idx = load_index()
    default_rid = idx.default_resume_id
    sel = selected_resume_id if selected_resume_id else default_rid
    job = Job(
        id=str(uuid.uuid4()),
        title=title.strip(),
        company=company.strip(),
        description=description.strip(),
        source=source,
        url=url,
        ingested_at=_utc_now(),
        selected_resume_id=sel,
        suggested_resume_id=suggested_resume_id,
        resume_scores=resume_scores,
        suggestion_low_confidence=suggestion_low_confidence,
        match_score_10=match_score_10,
        match_feedback=match_feedback,
        match_resume_id=match_resume_id,
    )
    data.jobs.append(job)
    save_jobs(data)
    return job


def get_job(job_id: str) -> Job | None:
    for j in load_jobs().jobs:
        if j.id == job_id:
            return j
    return None


def update_job(job: Job) -> None:
    data = load_jobs()
    for i, j in enumerate(data.jobs):
        if j.id == job.id:
            data.jobs[i] = job
            save_jobs(data)
            return
    raise KeyError(job.id)


def delete_job(job_id: str) -> None:
    data = load_jobs()
    data.jobs = [j for j in data.jobs if j.id != job_id]
    save_jobs(data)


def apply_match_narrative_to_job(
    client: OpenAI,
    chat_model: str,
    job: Job,
    resume: StructuredResume,
    hybrid: float,
) -> Job:
    from modules import generator
    from modules.scoring import hybrid_to_score_10

    s10 = hybrid_to_score_10(hybrid)
    narrative = generator.match_narrative(
        client, chat_model, resume, job, s10
    )
    job.match_score_10 = s10
    job.match_feedback = narrative
    job.match_resume_id = job.selected_resume_id
    update_job(job)
    return job


def match_preview_for_resume(
    client: OpenAI,
    embedding_model: str,
    chat_model: str,
    job: Job,
    resume_id: str,
    resume: StructuredResume,
    tags: list[str] | None = None,
) -> tuple[float, int, str]:
    """Compute hybrid (0-100), score /10, and narrative without persisting job."""
    from modules import embeddings as emb
    from modules.matcher import match_job_to_resume
    from modules.scoring import hybrid_to_score_10
    from modules import generator

    jvec, _ = emb.embed_job_if_needed(client, embedding_model, job)
    result = match_job_to_resume(
        client, embedding_model, resume_id, resume, job, jvec, tags
    )
    s10 = hybrid_to_score_10(result.hybrid)
    narrative = generator.match_narrative(
        client, chat_model, resume, job, s10
    )
    return result.hybrid, s10, narrative


def recompute_job_matches(
    client: OpenAI, embedding_model: str, chat_model: str, job: Job
) -> Job:
    from modules import embeddings as emb
    from modules.matcher import match_job_to_all_resumes
    from modules.resume_selector import suggest_resume

    jvec, h = emb.embed_job_if_needed(client, embedding_model, job)
    job.job_embedding_hash = h
    results = match_job_to_all_resumes(
        client, embedding_model, job, job_vec=jvec
    )
    sug, low, _ = suggest_resume(results)
    job.suggested_resume_id = sug
    job.suggestion_low_confidence = low
    job.resume_scores = {
        r.resume_id: {
            "hybrid": r.hybrid,
            "semantic": r.semantic,
            "rules": r.rules,
        }
        for r in results
    }
    update_job(job)
    rid = job.selected_resume_id
    if rid and job.resume_scores and rid in job.resume_scores:
        pr = load_parsed(rid)
        if pr:
            hy = float(job.resume_scores[rid]["hybrid"])
            job = get_job(job.id) or job
            apply_match_narrative_to_job(client, chat_model, job, pr, hy)
    return get_job(job.id) or job
