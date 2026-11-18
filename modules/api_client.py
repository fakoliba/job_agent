from __future__ import annotations

import os
from typing import Any
from types import SimpleNamespace

import httpx
import streamlit as st

from modules.tracker import APPLICATION_STATUSES


class ApiClientError(ValueError):
    pass


@st.cache_resource
def _http_client() -> httpx.Client:
    return httpx.Client(timeout=90.0)


def _base_url() -> str:
    value = os.getenv("API_BASE_URL", "")
    if not value:
        try:
            value = str(st.secrets.get("API_BASE_URL", ""))
        except Exception:
            value = ""
    return (value or "http://127.0.0.1:8000").rstrip("/")


def _namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace(item) for item in value]
    return value


def _request(
    method: str,
    path: str,
    *,
    authenticated: bool = True,
    **kwargs: Any,
) -> Any:
    headers = dict(kwargs.pop("headers", {}) or {})
    token = st.session_state.get("api_access_token")
    if authenticated and token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = _http_client().request(
            method,
            f"{_base_url()}/api/v1{path}",
            headers=headers,
            **kwargs,
        )
    except httpx.RequestError as exc:
        raise ApiClientError(
            "Could not reach the Job Search Agent API. Check API_BASE_URL and confirm the backend is running."
        ) from exc

    if response.status_code == 401 and authenticated:
        st.session_state.pop("api_access_token", None)
        st.session_state.pop("current_user", None)
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text
        if isinstance(detail, list):
            detail = "; ".join(str(item.get("msg", item)) for item in detail)
        raise ApiClientError(str(detail or f"API request failed ({response.status_code})."))
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _auth(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _request("POST", path, authenticated=False, json=payload)
    st.session_state["api_access_token"] = result["access_token"]
    return result["user"]


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    try:
        return _auth("/auth/login", {"username": username, "password": password})
    except ApiClientError as exc:
        if "Invalid username or password" in str(exc):
            return None
        raise


def create_user(
    username: str = "",
    password: str = "",
    first_name: str = "",
    last_name: str = "",
    email: str = "",
) -> dict[str, Any]:
    return _auth(
        "/auth/register",
        {
            "email": email or username,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
        },
    )


def update_user_profile(username: str = "", **profile_fields: Any) -> dict[str, Any]:
    del username  # User identity is derived from the authenticated API session.
    return _request("PATCH", "/auth/me", json=profile_fields)


def logout() -> None:
    try:
        _request("DELETE", "/auth/session")
    finally:
        st.session_state.pop("api_access_token", None)
        st.session_state.pop("current_user", None)


def load_structured_resumes() -> list[dict[str, Any]]:
    return _request("GET", "/resumes")


def upload_and_parse_resume(uploaded_file: Any, version_name: str, use_llm: bool) -> dict[str, Any]:
    filename = getattr(uploaded_file, "name", "resume.txt")
    content = uploaded_file.getvalue()
    return _request(
        "POST",
        "/resumes",
        files={"file": (filename, content)},
        data={"version_name": version_name, "use_llm": str(use_llm).lower()},
    )


def update_resume_metadata(
    resume_id: str,
    version_name: str,
    notes: str,
    target_roles: list[str],
) -> dict[str, Any]:
    return _request(
        "PATCH",
        f"/resumes/{resume_id}",
        json={"version_name": version_name, "notes": notes, "target_roles": target_roles},
    )


def delete_structured_resume(resume_id: str) -> None:
    _request("DELETE", f"/resumes/{resume_id}")


def resume_summary_rows(resumes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Version": resume.get("metadata", {}).get("version_name", ""),
            "Candidate": resume.get("metadata", {}).get("candidate_name", "Unknown Candidate"),
            "Parser": resume.get("metadata", {}).get("parser", "unknown"),
            "Skills": len(resume.get("skills", [])),
            "Impact Metrics": len(resume.get("impact_metrics", [])),
            "Target Roles": ", ".join(resume.get("target_roles", [])),
            "Notes": resume.get("metadata", {}).get("notes", ""),
        }
        for resume in resumes
    ]


def load_applications() -> list[dict[str, Any]]:
    return _request("GET", "/applications")


def add_application(
    company: str,
    role_title: str,
    job_url: str = "",
    location: str = "",
    job_description: str = "",
    resume_version: str = "",
    match_score: int = 0,
    notes: str = "",
    username: str = "",
) -> dict[str, Any]:
    del username
    return _request(
        "POST",
        "/applications",
        json={
            "company": company,
            "role_title": role_title,
            "job_url": job_url,
            "location": location,
            "job_description": job_description,
            "resume_version": resume_version,
            "match_score": match_score,
            "notes": notes,
        },
    )


def update_application_status(application_id: str, status: str) -> dict[str, Any]:
    return update_application_details(application_id, status=status)


def update_application_details(
    application_id: str,
    status: str | None = None,
    notes: str | None = None,
    follow_up_date: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    values = {
        key: value
        for key, value in {
            "status": status,
            "notes": notes,
            "follow_up_date": follow_up_date,
            "source": source,
        }.items()
        if value is not None
    }
    return _request("PATCH", f"/applications/{application_id}", json=values)


def load_monitors(username: str = "") -> list[dict[str, Any]]:
    del username
    monitors = _request("GET", "/monitors")
    for monitor in monitors:
        monitor["last_results"] = [_namespace(job) for job in monitor.get("last_results", [])]
    return monitors


def add_monitor(
    username: str,
    name: str,
    target_companies: str,
    job_query: str,
    resume_label: str,
    resume_id: str = "",
    max_jobs: int = 10,
    max_pages: int = 2,
) -> dict[str, Any]:
    del username
    return _request(
        "POST",
        "/monitors",
        json={
            "name": name,
            "target_companies": target_companies,
            "job_query": job_query,
            "resume_label": resume_label,
            "resume_id": resume_id,
            "max_jobs": max_jobs,
            "max_pages": max_pages,
        },
    )


def run_monitor(monitor_id: str) -> dict[str, Any]:
    result = _request("POST", f"/monitors/{monitor_id}/runs", timeout=360.0)
    result["discovered_jobs"] = [_namespace(job) for job in result["discovered_jobs"]]
    result["new_jobs"] = [_namespace(job) for job in result["new_jobs"]]
    return result


def discover_jobs(
    resume_id: str,
    target_companies: str,
    fallback_company: str,
    fallback_url: str,
    job_query: str,
    max_jobs: int,
    max_pages: int,
    use_rendered_fallback: bool,
    use_cache: bool,
) -> dict[str, Any]:
    result = _request(
        "POST",
        "/discovery",
        timeout=360.0,
        json={
            "resume_id": resume_id,
            "target_companies": target_companies,
            "fallback_company": fallback_company,
            "fallback_url": fallback_url,
            "job_query": job_query,
            "max_jobs": max_jobs,
            "max_pages": max_pages,
            "use_rendered_fallback": use_rendered_fallback,
            "use_cache": use_cache,
        },
    )
    result["jobs"] = [_namespace(job) for job in result["jobs"]]
    return result


def score_resume_for_job(resume: dict[str, Any], job_description: str) -> dict[str, Any]:
    result = _request("POST", "/analysis/match", json={"resume": resume, "job_description": job_description})
    return _namespace(result)


def generate_draft(
    resume: dict[str, Any], job_description: str, company: str, role_title: str, draft_type: str
) -> str:
    result = _request(
        "POST",
        "/analysis/draft",
        params={"draft_type": draft_type},
        json={"resume": resume, "job_description": job_description, "company": company, "role_title": role_title},
    )
    return result["draft"]


def generate_interview_prep(
    resume: dict[str, Any], job_description: str, company: str, role_title: str
) -> str:
    result = _request(
        "POST",
        "/analysis/interview-prep",
        json={"resume": resume, "job_description": job_description, "company": company, "role_title": role_title},
    )
    return result["prep"]


def build_company_interview_profile(
    resume: dict[str, Any],
    company: str,
    role_title: str,
    job_description: str,
    careers_url: str,
    prep_focus: str,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/analysis/company-prep",
        json={
            "resume": resume,
            "company": company,
            "role_title": role_title,
            "job_description": job_description,
            "careers_url": careers_url,
            "prep_focus": prep_focus,
        },
    )


def build_career_coaching(resumes: list[dict[str, Any]], applications: list[dict[str, Any]]) -> dict[str, Any]:
    return _request("POST", "/analysis/career-coach", json={"resumes": resumes, "applications": applications})


def recommend_target_companies(
    resume: dict[str, Any], preferred_role: str, preferred_stage: str, limit: int = 10
) -> list[dict[str, Any]]:
    return _request(
        "POST",
        "/analysis/company-targets",
        json={"resume": resume, "preferred_role": preferred_role, "preferred_stage": preferred_stage, "limit": limit},
    )


def build_market_intelligence(
    resume: dict[str, Any], role_family: str, location: str, seniority: str
) -> dict[str, Any]:
    result = _request(
        "POST",
        "/analysis/market-intelligence",
        json={"resume": resume, "role_family": role_family, "location": location, "seniority": seniority},
    )
    result["salary_band"] = SimpleNamespace(**result["salary_band"])
    return result
