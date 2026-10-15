from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESUMES_DIR = DATA_DIR / "resumes"
RESUMES_RAW = RESUMES_DIR / "raw"
RESUMES_PARSED = RESUMES_DIR / "parsed"
RESUMES_EMB = RESUMES_DIR / "embeddings"
RESUMES_INDEX = RESUMES_DIR / "index.json"
JOBS_FILE = DATA_DIR / "jobs.json"
APPLICATIONS_FILE = DATA_DIR / "applications.json"
JOBS_EMB_DIR = DATA_DIR / "jobs" / "embeddings"


def ensure_data_dirs() -> None:
    for p in (
        RESUMES_RAW,
        RESUMES_PARSED,
        RESUMES_EMB,
        JOBS_EMB_DIR,
    ):
        p.mkdir(parents=True, exist_ok=True)
