# Job Agent

A Streamlit application for uploading PDF/DOCX resumes, matching them to job descriptions, generating tailored resumes and recruiter outreach, and tracking applications.

## Run locally

Requires Python 3.10 or newer and an OpenAI API key.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r Requirements.txt
cp .env.example .env
# Set OPENAI_API_KEY in .env
streamlit run main.py
```

The model settings can be changed in `.env`. Parsing, embeddings, and text generation send resume/job content to the OpenAI API and may incur usage charges.

## Project layout

- `main.py`: Streamlit entry point
- `ui/app.py`: user interface
- `modules/`: parsing, storage, embeddings, matching, generation, exports, and tracking
- `data/`: local runtime storage, created automatically and excluded from Git

Secrets, uploaded resumes, generated application data, personal photos, Python caches, and virtual environments are excluded from the repository.


