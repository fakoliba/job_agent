from __future__ import annotations

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def validate_upload(filename: str, size_bytes: int, max_mb: int = 15) -> tuple[bool, str]:
    name = filename.lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Only {', '.join(sorted(ALLOWED_EXTENSIONS))} files are supported."
    if size_bytes > max_mb * 1024 * 1024:
        return False, f"File too large (max {max_mb} MB)."
    return True, ""
