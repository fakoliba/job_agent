from __future__ import annotations

import json

from openai import OpenAI

from modules.schemas import Job, StructuredResume


def match_narrative(
    client: OpenAI,
    model: str,
    resume: StructuredResume,
    job: Job,
    score_10: int,
) -> str:
    prompt = f"""You are a career coach. The candidate's resume vs this job has an internal match strength
of about {score_10}/10 (on a 0-10 scale).

Write exactly 1 or 2 short paragraphs (no bullets, no JSON):
- If it's a strong fit, say why (concrete overlaps with the JD).
- If it's a weak or mixed fit, say what's missing or risky and what still transfers.

JOB: {job.title} at {job.company}
JOB DESCRIPTION (excerpt): {job.description[:6000]}

RESUME SUMMARY: {resume.summary}
KEY SKILLS (sample): {", ".join(resume.skills[:20])}
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def resume_improve_for_job(
    client: OpenAI, model: str, resume: StructuredResume, job: Job
) -> StructuredResume:
    """Rewrite structured resume to better align with the JD; facts must stay plausible."""
    prompt = f"""Improve this resume for the target job. Return JSON only with keys:
summary (string), experience (array of strings), skills (array of strings),
impact (array of strings), leadership (array of strings).
Reword and reorder for relevance; do not invent employers or dates not implied by the source.

SOURCE_RESUME_JSON:
{resume.model_dump_json()}

JOB:
{job.title} at {job.company}
{job.description}
"""
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content or "{}"
    return StructuredResume.model_validate(json.loads(content))


def tailored_resume_structured(
    client: OpenAI, model: str, resume: StructuredResume, job: Job
) -> StructuredResume:
    raw = tailored_resume_document(client, model, resume, job)
    return StructuredResume.model_validate(json.loads(raw))


def tailored_bullets(
    client: OpenAI, model: str, resume: StructuredResume, job: Job
) -> str:
    payload = resume.model_dump_json(indent=2)
    prompt = f"""Given this structured resume JSON and the job description, return 5-8 tailored resume bullets
(star format, past tense) most relevant to this role. One bullet per line, no numbering.

RESUME_JSON:
{payload}

JOB_TITLE: {job.title}
COMPANY: {job.company}
JOB_DESCRIPTION:
{job.description}
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def why_company(
    client: OpenAI, model: str, resume: StructuredResume, job: Job, company_blurb: str = ""
) -> str:
    prompt = f"""Write a concise, authentic "Why {job.company}?" paragraph (4-6 sentences) for a job application.
Use the candidate summary and experience themes. Mention alignment with the role if clear.

SUMMARY:
{resume.summary}

STRUCTURED_RESUME:
{resume.model_dump_json()}

ROLE: {job.title} at {job.company}
JOB_DESCRIPTION:
{job.description}

COMPANY_NOTES (optional):
{company_blurb or "None provided."}
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def recruiter_outreach(
    client: OpenAI, model: str, resume: StructuredResume, job: Job
) -> str:
    prompt = f"""Write a short LinkedIn-style outreach message to a recruiter or hiring manager (under 120 words).
Reference the role and 2 concrete strengths from the resume.

RESUME_SUMMARY: {resume.summary}
TOP_SKILLS: {", ".join(resume.skills[:12])}

JOB: {job.title} at {job.company}
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def tailored_resume_document(
    client: OpenAI, model: str, resume: StructuredResume, job: Job
) -> str:
    """Returns JSON string: full tailored resume structure for this job."""
    prompt = f"""Produce an updated resume tailored to this job. Return JSON only with keys:
summary (string), experience (array of strings), skills (array of strings),
impact (array of strings), leadership (array of strings).
Prioritize relevance to the JD; you may reorder or rewrite bullets; keep facts plausible from the source.

SOURCE_RESUME_JSON:
{resume.model_dump_json()}

JOB:
{job.title} at {job.company}
{job.description}
"""
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or "{}"
