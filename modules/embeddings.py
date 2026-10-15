from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from openai import OpenAI

from modules.paths import JOBS_EMB_DIR, RESUMES_EMB, ensure_data_dirs
from modules.resume_store import embedding_path, load_parsed, resume_hash
from modules.schemas import EmbeddingRecord, Job, StructuredResume


def _hash_text(*parts: str) -> str:
    joined = "\n".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()


def flatten_resume(resume: StructuredResume) -> str:
    chunks = [
        resume.summary,
        "\n".join(resume.experience),
        "\n".join(resume.skills),
        "\n".join(resume.impact),
        "\n".join(resume.leadership),
    ]
    return "\n\n".join(c for c in chunks if c).strip()


def jd_text_hash(job: Job) -> str:
    return _hash_text(job.title, job.company, job.description)


def job_embedding_file(job_id: str) -> Path:
    ensure_data_dirs()
    return JOBS_EMB_DIR / f"{job_id}.json"


def embed_text(client: OpenAI, model: str, text: str) -> list[float]:
    t = text.strip()[:25_000]
    if not t:
        return []
    resp = client.embeddings.create(model=model, input=t)
    return list(resp.data[0].embedding)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def semantic_score_0_100(sim: float) -> float:
    """Map cosine similarity in [0,1] to a 0-100 display score."""
    return round(max(0.0, min(100.0, sim * 100)), 1)


def save_embedding(path: Path, model: str, content_hash: str, vector: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = EmbeddingRecord(model=model, content_hash=content_hash, vector=vector)
    path.write_text(rec.model_dump_json(indent=2))


def load_embedding(path: Path) -> EmbeddingRecord | None:
    if not path.exists():
        return None
    try:
        return EmbeddingRecord.model_validate_json(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return None


def embed_resume_if_needed(
    client: OpenAI, embedding_model: str, resume_id: str, resume: StructuredResume
) -> list[float] | None:
    ensure_data_dirs()
    h = resume_hash(resume)
    path = embedding_path(resume_id)
    existing = load_embedding(path)
    if existing and existing.content_hash == h and existing.model == embedding_model:
        return existing.vector
    flat = flatten_resume(resume)
    if not flat:
        return None
    vec = embed_text(client, embedding_model, flat)
    if not vec:
        return None
    save_embedding(path, embedding_model, h, vec)
    return vec


def embed_job_if_needed(
    client: OpenAI, embedding_model: str, job: Job
) -> tuple[list[float] | None, str]:
    """Returns (vector, hash used)."""
    ensure_data_dirs()
    h = jd_text_hash(job)
    path = job_embedding_file(job.id)
    existing = load_embedding(path)
    if existing and existing.content_hash == h and existing.model == embedding_model:
        return existing.vector, h
    text = f"{job.title}\n{job.company}\n{job.description}"
    vec = embed_text(client, embedding_model, text)
    if vec:
        save_embedding(path, embedding_model, h, vec)
    return (vec if vec else None), h
