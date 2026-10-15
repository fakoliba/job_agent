from __future__ import annotations

import json
from io import BytesIO

from openai import OpenAI
from pypdf import PdfReader
from docx import Document

from modules.schemas import StructuredResume


def extract_text_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
    return "\n".join(parts).strip()


def extract_text_docx(data: bytes) -> str:
    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()


def extract_text(filename: str, data: bytes) -> str:
    low = filename.lower()
    if low.endswith(".pdf"):
        return extract_text_pdf(data)
    if low.endswith(".docx"):
        return extract_text_docx(data)
    raise ValueError("Unsupported file type")


SCHEMA_HINT = """
Return a JSON object with keys: summary (string), experience (array of strings),
skills (array of strings), impact (array of strings), leadership (array of strings).
Use empty strings or empty arrays where unknown. Each array item should be one concise bullet or phrase.
"""


def parse_resume_with_llm(client: OpenAI, model: str, raw_text: str) -> StructuredResume:
    text = raw_text[:120_000]
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You extract resume facts into structured JSON. " + SCHEMA_HINT,
            },
            {"role": "user", "content": f"Resume text:\n\n{text}"},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    return StructuredResume.model_validate(data)
