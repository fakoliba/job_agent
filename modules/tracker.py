from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from modules.paths import APPLICATIONS_FILE, ensure_data_dirs
from modules.schemas import Application, ApplicationsFile


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_applications() -> ApplicationsFile:
    ensure_data_dirs()
    if not APPLICATIONS_FILE.exists():
        return ApplicationsFile()
    try:
        return ApplicationsFile.model_validate_json(APPLICATIONS_FILE.read_text())
    except (ValidationError, json.JSONDecodeError):
        return ApplicationsFile()


def save_applications(data: ApplicationsFile) -> None:
    ensure_data_dirs()
    APPLICATIONS_FILE.write_text(data.model_dump_json(indent=2))


def upsert_application(
    job_id: str,
    resume_id: str,
    status: str = "new",
    outcome: str | None = None,
    notes: str = "",
    ab_variant: str | None = None,
) -> Application:
    data = load_applications()
    now = _utc_now()
    for app in data.applications:
        if app.job_id == job_id and app.resume_id == resume_id:
            app.status = status
            if outcome is not None:
                app.outcome = outcome
            if notes:
                app.notes = notes
            if ab_variant is not None:
                app.ab_variant = ab_variant
            app.updated_at = now
            save_applications(data)
            return app
    app = Application(
        id=str(uuid.uuid4()),
        job_id=job_id,
        resume_id=resume_id,
        ab_variant=ab_variant,
        status=status,
        outcome=outcome,
        notes=notes,
        updated_at=now,
    )
    data.applications.append(app)
    save_applications(data)
    return app
