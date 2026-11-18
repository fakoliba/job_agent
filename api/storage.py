from __future__ import annotations

import os
from pathlib import Path


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "data/uploads")).resolve()


def save_upload(user_id: str, resume_id: str, filename: str, content: bytes) -> str:
    relative_key = Path(user_id) / resume_id / filename
    target = (UPLOAD_DIR / relative_key).resolve()
    if UPLOAD_DIR not in target.parents:
        raise ValueError("Invalid upload path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative_key.as_posix()


def delete_upload(storage_key: str) -> None:
    target = (UPLOAD_DIR / storage_key).resolve()
    if UPLOAD_DIR not in target.parents:
        raise ValueError("Invalid upload path.")
    target.unlink(missing_ok=True)
    parent = target.parent
    while parent != UPLOAD_DIR and parent.is_dir():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
