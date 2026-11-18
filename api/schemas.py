from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    target_role_family: str | None = None
    target_seniority: str | None = None
    preferred_locations: str | None = None
    work_authorization: str | None = None
    needs_sponsorship: bool | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    current_title: str | None = None
    years_experience: int | None = Field(default=None, ge=0, le=100)
    open_to_relocation: bool | None = None


class ResumeMetadataUpdate(BaseModel):
    version_name: str = Field(default="", max_length=255)
    notes: str = Field(default="", max_length=10000)
    target_roles: list[str] = Field(default_factory=list, max_length=50)


class ApplicationCreate(BaseModel):
    company: str = Field(default="", max_length=255)
    role_title: str = Field(default="", max_length=255)
    job_url: str = Field(default="", max_length=4000)
    location: str = Field(default="", max_length=255)
    job_description: str = Field(default="", max_length=50000)
    resume_version: str = Field(default="", max_length=255)
    match_score: int = Field(default=0, ge=0, le=100)
    status: str = Field(default="Saved", max_length=64)
    notes: str = Field(default="", max_length=10000)
    source: str = Field(default="", max_length=255)
    follow_up_date: str = Field(default="", max_length=32)


class ApplicationUpdate(BaseModel):
    company: str | None = Field(default=None, max_length=255)
    role_title: str | None = Field(default=None, max_length=255)
    job_url: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=255)
    job_description: str | None = Field(default=None, max_length=50000)
    resume_version: str | None = Field(default=None, max_length=255)
    match_score: int | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=10000)
    source: str | None = Field(default=None, max_length=255)
    follow_up_date: str | None = Field(default=None, max_length=32)


class MonitorCreate(BaseModel):
    name: str = Field(default="Job Monitor", max_length=255)
    target_companies: str = Field(min_length=1, max_length=20000)
    job_query: str = Field(default="", max_length=2000)
    resume_label: str = Field(default="", max_length=255)
    resume_id: str = Field(default="", max_length=36)
    max_jobs: int = Field(default=10, ge=1, le=100)
    max_pages: int = Field(default=2, ge=1, le=20)


class DiscoveryInput(BaseModel):
    resume_id: str = Field(min_length=1, max_length=36)
    target_companies: str = Field(default="", max_length=20000)
    fallback_company: str = Field(default="", max_length=255)
    fallback_url: str = Field(default="", max_length=4000)
    job_query: str = Field(default="", max_length=2000)
    max_jobs: int = Field(default=10, ge=1, le=25)
    max_pages: int = Field(default=2, ge=1, le=10)
    use_rendered_fallback: bool = True
    use_cache: bool = True


class ResumeJobInput(BaseModel):
    resume: dict[str, Any]
    job_description: str = Field(min_length=1, max_length=100000)
    company: str = Field(default="", max_length=255)
    role_title: str = Field(default="", max_length=255)


class CompanyPrepInput(ResumeJobInput):
    careers_url: str = Field(default="", max_length=4000)
    prep_focus: str = Field(default="Full Loop", max_length=100)


class CareerCoachInput(BaseModel):
    resumes: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    applications: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class CompanyTargetInput(BaseModel):
    resume: dict[str, Any]
    preferred_role: str = Field(default="", max_length=255)
    preferred_stage: str = Field(default="Any", max_length=255)
    limit: int = Field(default=10, ge=1, le=100)


class MarketIntelligenceInput(BaseModel):
    resume: dict[str, Any]
    role_family: str = Field(max_length=255)
    location: str = Field(max_length=255)
    seniority: str = Field(max_length=100)


class ResumeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    source_file: str
    metadata: dict[str, Any]


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]
