# AI-Powered Job Search Agent

 workspace backed by a FastAPI service and PostgreSQL. FastAPI owns authentication, durable account data, resume parsing, role matching, job discovery, monitor runs, drafting, interview prep, and career insights. Streamlit renders the UI and calls the authenticated API.

## Features

- Upload PDF, DOCX, or TXT resumes; parse them with OpenAI or the local heuristic fallback.
- Score resumes against job descriptions and discover roles from company career pages.
- Generate resume bullets, outreach, cover letters, and interview preparation.
- Track applications, follow-ups, and company monitors.
- Keep user accounts and their saved data isolated in PostgreSQL.

## Run the full app locally

Docker Compose starts PostgreSQL, the FastAPI backend, and the Streamlit UI:

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env if you want OpenAI-backed features.
docker compose up --build
```

Open the Streamlit UI at `http://localhost:8501` and the API docs at `http://localhost:8000/docs`. The Compose configuration runs Alembic migrations before starting FastAPI and stores the database and uploaded resume files in named volumes.

The default database password in `.env.example` is for local development only. Use a generated secret for any shared environment.

## Run services without Docker

Create a virtual environment, install dependencies, and start PostgreSQL. Set `DATABASE_URL`, `UPLOAD_DIR`, and `API_BASE_URL` using `.env.example` as a template.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn api.main:app --reload
```

In a second terminal:

```bash
streamlit run app.py
```

The API uses `DATABASE_URL` for SQLAlchemy and `UPLOAD_DIR` for private uploaded resume files. Keep `UPLOAD_DIR` on persistent private storage in production. FastAPI exposes `/healthz` and `/readyz`; the latter checks database connectivity.

## Deploy

Deploy FastAPI as an ASGI service with a managed PostgreSQL database and persistent private file storage. Configure these backend environment values in the hosting provider:

- `DATABASE_URL`
- `UPLOAD_DIR`
- `OPENAI_API_KEY` (optional; enables AI resume parsing)
- `OPENAI_MODEL` and `OPENAI_RESUME_MODEL` (optional)
- `MAX_RESUME_BYTES` (optional; defaults to 15 MiB)

Run `alembic upgrade head` as a release/pre-start command. Do not expose the upload directory as static files. Require HTTPS and keep database credentials and OpenAI keys out of Git.

The existing Streamlit Community Cloud deployment can remain the UI. Set `API_BASE_URL` in its Secrets settings to the public FastAPI service URL. Configure the OpenAI key on the API service for resume parsing and AI drafting. Keep the key in Streamlit secrets only if browser-side discovery or embedding features still need it.

Community Cloud does not guarantee persistence for local file writes, so the backend must use persistent storage for PostgreSQL and uploaded source files. See [Streamlit data connections](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).

## Data model and API

The API is rooted at `/api/v1` and provides:

- `/auth/register`, `/auth/login`, `/auth/me`, and `/auth/session`
- `/resumes` for upload, list, metadata updates, file download, and deletion
- `/applications` for user-scoped application tracking
- `/monitors` for user-scoped monitor configuration, persisted run state, and saved results
- `/discovery` for authenticated company-career scans and ranked job results
- `/analysis/*` for authenticated role matching, drafting, interview preparation, coaching, targeting, and market intelligence

Passwords retain the app's salted PBKDF2-SHA256 format. API session tokens are random, expire after seven days, and are stored in the database as hashes. Every user-owned record is queried by the authenticated user's ID.

Resume uploads are parsed in the API process. The original file is kept in a private upload directory; parsed text and structured fields are stored in PostgreSQL. Deleting a resume removes the database record and source file.

## Import legacy JSON data

The old Streamlit version stored accounts, applications, monitors, and structured resumes in JSON files under `data/`. Once the target database has been migrated, run the importer against a copy of the old data directory:

```bash
alembic upgrade head
python -m api.import_legacy --data-dir /path/to/legacy/data
```

Structured resumes did not record an owner. Import them only after choosing the correct account:

```bash
python -m api.import_legacy \
  --data-dir /path/to/legacy/data \
  --resume-owner-email you@example.com
```

For legacy applications or monitors that have no username, provide `--default-user-email`. The importer is idempotent. Export any needed data from the deployed app before cutover; do not assume its local JSON files persisted across restarts.

## Project structure

```text
api/                 FastAPI routes, database models, migrations, and import utility
modules/             Shared application logic and Streamlit API client
app.py               Streamlit UI
tests/               Existing unit tests for domain modules
```
