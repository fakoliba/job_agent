from __future__ import annotations

from dataclasses import dataclass
from openai import OpenAI

from modules import embeddings as emb
from modules.resume_store import load_index, load_parsed
from modules.schemas import Job, StructuredResume

SYNONYMS: dict[str, list[str]] = {
    "observability": ["monitoring", "o11y", "metrics", "tracing", "logging"],
    "sre": ["site reliability", "reliability engineering", "production engineering"],
    "kubernetes": ["k8s", "kube"],
    "llm": ["large language model", "gpt", "generative ai", "genai"],
    "ml": ["machine learning", "ai", "model training"],
}

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SRE": ("sre", "reliability", "on-call", "incident", "sla", "kubernetes", "terraform", "observability", "monitoring"),
    "AI": ("llm", "machine learning", "ml", "ai", "rag", "embedding", "model", "pytorch", "tensorflow", "nlp"),
    "Leadership": ("lead", "manager", "management", "mentor", "org", "team", "director", "head of", "vp"),
}


def _expand_tokens(text: str) -> set[str]:
    low = text.lower()
    toks = set()
    for w in low.replace("/", " ").replace(",", " ").split():
        w = w.strip(".,;:()[]{}")
        if len(w) > 2:
            toks.add(w)
    for key, syns in SYNONYMS.items():
        if key in low or any(s in low for s in syns):
            toks.add(key)
            toks.update(syns)
    return toks


def rules_score_0_100(resume: StructuredResume, job: Job) -> tuple[float, dict]:
    resume_text = emb.flatten_resume(resume).lower()
    jd = f"{job.title}\n{job.company}\n{job.description}".lower()
    jd_toks = _expand_tokens(jd)
    res_toks = _expand_tokens(resume_text)

    breakdown: dict[str, float] = {}
    total_w = 0.0
    acc = 0.0
    weights = {"SRE": 1.2, "AI": 1.2, "Leadership": 1.4}
    for cat, kws in CATEGORY_KEYWORDS.items():
        w = weights.get(cat, 1.0)
        total_w += w
        hits = 0
        max_hits = len(kws)
        for kw in kws:
            if kw in jd and kw in resume_text:
                hits += 1
            elif kw in jd_toks and kw in res_toks:
                hits += 1
        cat_score = (hits / max(max_hits, 1)) * 100
        breakdown[cat] = round(cat_score, 1)
        acc += cat_score * w
    base = acc / total_w if total_w else 0.0
    overlap = len(jd_toks & res_toks)
    overlap_boost = min(30.0, overlap * 1.5)
    raw = min(100.0, base * 0.75 + overlap_boost * 0.25)
    breakdown["keyword_overlap"] = float(overlap)
    return round(raw, 1), breakdown


@dataclass
class MatchResult:
    resume_id: str
    hybrid: float
    semantic: float | None
    rules: float
    rules_breakdown: dict


def hybrid_score(semantic: float | None, rules: float, semantic_weight: float = 0.45) -> float:
    if semantic is None:
        return rules
    w = semantic_weight
    return round(w * semantic + (1 - w) * rules, 1)


def _tag_boost(tags: list[str], job: Job) -> float:
    jd = f"{job.title} {job.company} {job.description}".lower()
    boost = 0.0
    if "AI-focused" in tags and any(k in jd for k in ("ai", "ml", "llm", "model", "learning")):
        boost += 2.0
    if "SRE-focused" in tags and any(
        k in jd for k in ("sre", "reliability", "on-call", "incident", "kubernetes", "observability")
    ):
        boost += 2.0
    if "Leadership" in tags and any(
        k in jd for k in ("lead", "manager", "director", "head", "manage team")
    ):
        boost += 2.0
    return min(boost, 5.0)


def match_job_to_resume(
    client: OpenAI | None,
    embedding_model: str | None,
    resume_id: str,
    resume: StructuredResume,
    job: Job,
    job_vec: list[float] | None,
    tags: list[str] | None = None,
) -> MatchResult:
    rules, br = rules_score_0_100(resume, job)
    sem_100: float | None = None
    if client and embedding_model and job_vec:
        rvec = emb.embed_resume_if_needed(client, embedding_model, resume_id, resume)
        if rvec:
            sim = emb.cosine_similarity(job_vec, rvec)
            sem_100 = emb.semantic_score_0_100(sim)
    hy = hybrid_score(sem_100, rules)
    hy = min(100.0, hy + _tag_boost(tags or [], job))
    return MatchResult(
        resume_id=resume_id,
        hybrid=round(hy, 1),
        semantic=sem_100,
        rules=rules,
        rules_breakdown=br,
    )


def match_job_to_all_resumes(
    client: OpenAI | None,
    embedding_model: str | None,
    job: Job,
    job_vec: list[float] | None = None,
) -> list[MatchResult]:
    index = load_index()
    jvec = job_vec
    if jvec is None and client and embedding_model:
        jvec, _ = emb.embed_job_if_needed(client, embedding_model, job)
    results: list[MatchResult] = []
    for entry in index.resumes:
        rid = entry.resume_id
        parsed = load_parsed(rid)
        if not parsed:
            continue
        results.append(
            match_job_to_resume(
                client, embedding_model, rid, parsed, job, jvec, entry.tags
            )
        )
    results.sort(key=lambda r: r.hybrid, reverse=True)
    return results
