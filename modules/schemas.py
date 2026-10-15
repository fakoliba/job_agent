from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ResumeTag = Literal["AI-focused", "SRE-focused", "Leadership"]


class StructuredResume(BaseModel):
    summary: str = ""
    experience: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    impact: list[str] = Field(default_factory=list)
    leadership: list[str] = Field(default_factory=list)


class ResumeIndexEntry(BaseModel):
    resume_id: str
    label: str
    tags: list[str] = Field(default_factory=list)
    parent_resume_id: str | None = None
    version_label: str | None = None
    ab_group_id: str | None = None
    ab_variant: str | None = None
    is_default: bool = False
    content_hash: str = ""
    raw_filename: str = ""
    last_embedded_at: str | None = None
    embedding_model: str = ""


class ResumeIndex(BaseModel):
    resumes: list[ResumeIndexEntry] = Field(default_factory=list)
    default_resume_id: str | None = None


class Job(BaseModel):
    id: str
    title: str
    company: str
    description: str
    source: str | None = None
    url: str | None = None
    ingested_at: str = ""
    selected_resume_id: str | None = None
    suggested_resume_id: str | None = None
    resume_scores: dict[str, dict] | None = None
    job_embedding_hash: str | None = None
    suggestion_low_confidence: bool | None = None
    match_score_10: int | None = None
    match_feedback: str | None = None
    match_resume_id: str | None = None


class JobsFile(BaseModel):
    jobs: list[Job] = Field(default_factory=list)


class Application(BaseModel):
    id: str
    job_id: str
    resume_id: str
    ab_variant: str | None = None
    status: str = "new"
    outcome: str | None = None
    notes: str = ""
    updated_at: str = ""


class ApplicationsFile(BaseModel):
    applications: list[Application] = Field(default_factory=list)


class EmbeddingRecord(BaseModel):
    model: str
    content_hash: str
    vector: list[float]
