from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from modules.paths import (
    RESUMES_EMB,
    RESUMES_INDEX,
    RESUMES_PARSED,
    RESUMES_RAW,
    ensure_data_dirs,
)
from modules.schemas import ResumeIndex, ResumeIndexEntry, StructuredResume


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resume_hash(resume: StructuredResume) -> str:
    import hashlib

    raw = json.dumps(resume.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def load_index() -> ResumeIndex:
    ensure_data_dirs()
    if not RESUMES_INDEX.exists():
        return ResumeIndex()
    try:
        return ResumeIndex.model_validate_json(RESUMES_INDEX.read_text())
    except (ValidationError, json.JSONDecodeError):
        return ResumeIndex()


def save_index(index: ResumeIndex) -> None:
    ensure_data_dirs()
    RESUMES_INDEX.write_text(index.model_dump_json(indent=2))


def parsed_path(resume_id: str) -> Path:
    return RESUMES_PARSED / f"{resume_id}.json"


def raw_path(resume_id: str) -> Path:
    return RESUMES_RAW / f"{resume_id}.bin"


def embedding_path(resume_id: str) -> Path:
    return RESUMES_EMB / f"{resume_id}.json"


def get_entry(index: ResumeIndex, resume_id: str) -> ResumeIndexEntry | None:
    for e in index.resumes:
        if e.resume_id == resume_id:
            return e
    return None


def load_parsed(resume_id: str) -> StructuredResume | None:
    p = parsed_path(resume_id)
    if not p.exists():
        return None
    try:
        return StructuredResume.model_validate_json(p.read_text())
    except (ValidationError, json.JSONDecodeError):
        return None


def save_parsed(resume_id: str, resume: StructuredResume) -> None:
    ensure_data_dirs()
    parsed_path(resume_id).write_text(resume.model_dump_json(indent=2))
    index = load_index()
    entry = get_entry(index, resume_id)
    if entry:
        entry.content_hash = resume_hash(resume)
        save_index(index)


def save_raw(resume_id: str, data: bytes, filename: str) -> None:
    ensure_data_dirs()
    raw_path(resume_id).write_bytes(data)
    index = load_index()
    entry = get_entry(index, resume_id)
    if entry:
        entry.raw_filename = filename
        save_index(index)


def create_resume_record(label: str, raw_bytes: bytes, raw_filename: str) -> str:
    ensure_data_dirs()
    resume_id = str(uuid.uuid4())
    entry = ResumeIndexEntry(
        resume_id=resume_id,
        label=label or raw_filename,
        raw_filename=raw_filename,
    )
    index = load_index()
    index.resumes.append(entry)
    save_index(index)
    raw_path(resume_id).write_bytes(raw_bytes)
    return resume_id


def delete_resume(resume_id: str) -> None:
    index = load_index()
    index.resumes = [e for e in index.resumes if e.resume_id != resume_id]
    if index.default_resume_id == resume_id:
        index.default_resume_id = None
    save_index(index)
    for p in (parsed_path(resume_id), raw_path(resume_id), embedding_path(resume_id)):
        if p.exists():
            p.unlink()


def set_default(resume_id: str | None) -> None:
    index = load_index()
    index.default_resume_id = resume_id
    for e in index.resumes:
        e.is_default = e.resume_id == resume_id if resume_id else False
    save_index(index)


def update_entry(resume_id: str, **kwargs: object) -> None:
    index = load_index()
    entry = get_entry(index, resume_id)
    if not entry:
        return
    for k, v in kwargs.items():
        if k in ResumeIndexEntry.model_fields:
            setattr(entry, k, v)
    save_index(index)


def fork_version(resume_id: str, version_label: str, new_label: str) -> str:
    parsed = load_parsed(resume_id)
    if not parsed:
        raise ValueError("No parsed resume to fork")
    old = get_entry(load_index(), resume_id)
    raw_fn = old.raw_filename if old else "fork.bin"
    raw = raw_path(resume_id).read_bytes() if raw_path(resume_id).exists() else b""
    new_id = create_resume_record(new_label or version_label, raw, raw_fn)
    save_parsed(new_id, parsed)
    update_entry(
        new_id,
        parent_resume_id=resume_id,
        version_label=version_label,
    )
    return new_id


def link_ab_pair(resume_id_a: str, resume_id_b: str, group_id: str | None = None) -> str:
    gid = group_id or str(uuid.uuid4())
    update_entry(resume_id_a, ab_group_id=gid, ab_variant="A")
    update_entry(resume_id_b, ab_group_id=gid, ab_variant="B")
    return gid


def set_tags(resume_id: str, tags: list[str]) -> None:
    update_entry(resume_id, tags=tags)


def set_embedding_meta(resume_id: str, model: str) -> None:
    update_entry(
        resume_id,
        last_embedded_at=_utc_now(),
        embedding_model=model,
    )
