"""Upload → parse → embed: internal pipeline (no separate UI steps)."""

from __future__ import annotations

from openai import OpenAI

from modules import embeddings as emb
from modules import resume_store
from modules.resume_parser import extract_text, parse_resume_with_llm
from modules.schemas import StructuredResume


def process_uploaded_resume(
    client: OpenAI,
    resume_id: str,
    chat_model: str,
    embedding_model: str,
) -> StructuredResume:
    """Parse raw upload, save structured JSON, build embeddings."""
    raw_path = resume_store.raw_path(resume_id)
    if not raw_path.exists():
        raise FileNotFoundError("Resume raw file missing")
    entry = resume_store.get_entry(resume_store.load_index(), resume_id)
    filename = (entry.raw_filename if entry else None) or "resume.pdf"
    text = extract_text(filename, raw_path.read_bytes())
    if not text.strip():
        raise ValueError("No text extracted from file")
    parsed = parse_resume_with_llm(client, chat_model, text)
    resume_store.save_parsed(resume_id, parsed)
    emb.embed_resume_if_needed(client, embedding_model, resume_id, parsed)
    resume_store.set_embedding_meta(resume_id, embedding_model)
    return parsed


def refresh_embeddings_for_resume(
    client: OpenAI,
    resume_id: str,
    parsed: StructuredResume,
    embedding_model: str,
) -> None:
    emb.embed_resume_if_needed(client, embedding_model, resume_id, parsed)
    resume_store.set_embedding_meta(resume_id, embedding_model)


def ensure_parsed_and_embedded(
    client: OpenAI,
    resume_id: str,
    chat_model: str,
    embedding_model: str,
) -> StructuredResume | None:
    """If parsed exists, refresh embeddings; else parse from raw then embed."""
    existing = resume_store.load_parsed(resume_id)
    if existing:
        refresh_embeddings_for_resume(
            client, resume_id, existing, embedding_model
        )
        return existing
    raw_path = resume_store.raw_path(resume_id)
    if not raw_path.exists():
        return None
    entry = resume_store.get_entry(resume_store.load_index(), resume_id)
    filename = (entry.raw_filename if entry else None) or "resume.pdf"
    text = extract_text(filename, raw_path.read_bytes())
    if not text.strip():
        return None
    parsed = parse_resume_with_llm(client, chat_model, text)
    resume_store.save_parsed(resume_id, parsed)
    refresh_embeddings_for_resume(client, resume_id, parsed, embedding_model)
    return parsed
