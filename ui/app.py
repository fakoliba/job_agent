from __future__ import annotations

import csv
import io
import os
import uuid

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from modules import generator
from modules import ingestion
from modules import resume_export
from modules import resume_pipeline
from modules import resume_store
from modules import resume_upload_manager
from modules import tracker
from modules.paths import ensure_data_dirs
from modules.schemas import Job, StructuredResume

load_dotenv()
ensure_data_dirs()

st.set_page_config(page_title="Job Agent", layout="wide")


@st.cache_resource
def get_openai() -> OpenAI | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key)


def chat_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def embedding_model() -> str:
    return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def resume_options() -> list[tuple[str, str]]:
    idx = resume_store.load_index()
    return [(e.resume_id, f"{e.label} ({e.resume_id[:8]}…)") for e in idx.resumes]


IMPROVE_SCORE_THRESHOLD = 7


def ensure_resume_ready(client: OpenAI, resume_id: str) -> StructuredResume | None:
    pr = resume_store.load_parsed(resume_id)
    if pr is not None:
        resume_pipeline.refresh_embeddings_for_resume(
            client, resume_id, pr, embedding_model()
        )
        return pr
    if not resume_store.raw_path(resume_id).exists():
        return None
    with st.spinner("Preparing resume (parse + embeddings)…"):
        try:
            return resume_pipeline.ensure_parsed_and_embedded(
                client, resume_id, chat_model(), embedding_model()
            )
        except Exception as e:
            st.error(f"Could not prepare resume: {e}")
            return None


api = get_openai()
if not api:
    st.error("Set `OPENAI_API_KEY` in `.env`.")
    st.stop()

st.title("Job Agent")
st.caption(
    "v1 flow: **Upload** (parse + match vectors run automatically) → **Match** (job + scores) → "
    "**Generate** (tailored resume + outreach)."
)

tab_resumes, tab_jobs = st.tabs(["Resumes", "Jobs"])

with tab_resumes:
    st.subheader("1. Upload resume (PDF / DOCX)")
    label = st.text_input("Display name", placeholder="Staff Eng — AI")
    up = st.file_uploader("File", type=["pdf", "docx"])
    if up and st.button("Add resume"):
        ok, msg = resume_upload_manager.validate_upload(up.name, up.size)
        if not ok:
            st.error(msg)
        else:
            rid = resume_store.create_resume_record(
                label or up.name, up.getvalue(), up.name
            )
            with st.spinner("Processing resume (parse + embeddings)…"):
                try:
                    resume_pipeline.process_uploaded_resume(
                        api, rid, chat_model(), embedding_model()
                    )
                    st.success("Resume is ready for matching.")
                except Exception as e:
                    st.exception(e)
            st.rerun()

    st.subheader("Your resumes")
    idx = resume_store.load_index()
    if not idx.resumes:
        st.info("No resumes yet. Upload a file above.")
    for entry in idx.resumes:
        parsed_ok = resume_store.load_parsed(entry.resume_id) is not None
        status = "Ready" if parsed_ok else "Incomplete"
        with st.expander(f"{entry.label} — `{entry.resume_id}` ({status})"):
            if st.button("Delete", key=f"del_{entry.resume_id}"):
                resume_store.delete_resume(entry.resume_id)
                st.rerun()

            tags = st.multiselect(
                "Tags",
                ["AI-focused", "SRE-focused", "Leadership"],
                default=[
                    t
                    for t in entry.tags
                    if t in ("AI-focused", "SRE-focused", "Leadership")
                ],
                key=f"tags_{entry.resume_id}",
            )
            if st.button("Save tags", key=f"svtags_{entry.resume_id}"):
                resume_store.set_tags(entry.resume_id, tags)
                st.success("Tags saved.")

            new_lbl = st.text_input(
                "Rename", value=entry.label, key=f"lbl_{entry.resume_id}"
            )
            if st.button("Save name", key=f"svlbl_{entry.resume_id}"):
                resume_store.update_entry(entry.resume_id, label=new_lbl)
                st.rerun()

            if st.button("Set as default for new jobs", key=f"def_{entry.resume_id}"):
                resume_store.set_default(entry.resume_id)
                st.success("Default set.")

            ver_label = st.text_input(
                "Version label", key=f"fvl_{entry.resume_id}"
            )
            ver_name = st.text_input(
                "Display name for new version", key=f"fvn_{entry.resume_id}"
            )
            if st.button("Version", key=f"fork_{entry.resume_id}"):
                try:
                    new_id = resume_store.fork_version(
                        entry.resume_id,
                        ver_label or "v2",
                        ver_name or ver_label or "Copy",
                    )
                    pr_new = resume_store.load_parsed(new_id)
                    if pr_new:
                        resume_pipeline.refresh_embeddings_for_resume(
                            api, new_id, pr_new, embedding_model()
                        )
                    st.success(f"New version: `{new_id}`")
                    st.rerun()
                except Exception as e:
                    st.exception(e)

with tab_jobs:
    opts_r = resume_options()
    idx_jobs = resume_store.load_index()
    id_to_label = {i: lab for i, lab in opts_r}
    rid_list_add = [o[0] for o in opts_r]

    st.subheader("2. Add job")
    if "preview_job_id" not in st.session_state:
        st.session_state["preview_job_id"] = str(uuid.uuid4())
    preview_job_id = st.session_state["preview_job_id"]

    jt = st.text_input("Title", key="add_job_title")
    jc = st.text_input("Company", key="add_job_company")
    jd = st.text_area("Job description", height=200, key="add_job_desc")
    if not rid_list_add:
        st.warning("Add a resume on the Resumes tab before adding a job.")
        add_resume_sel = None
    else:
        default_i = 0
        if idx_jobs.default_resume_id in rid_list_add:
            default_i = rid_list_add.index(idx_jobs.default_resume_id)
        add_resume_sel = st.selectbox(
            "Resume to match",
            rid_list_add,
            index=default_i,
            format_func=lambda x: id_to_label.get(x, x),
            key="add_job_resume",
        )

    c_m, c_s = st.columns(2)
    with c_m:
        if st.button("Match", key="add_job_match"):
            if not rid_list_add or not add_resume_sel:
                st.error("Select a resume first.")
            elif not (jt.strip() and jc.strip() and jd.strip()):
                st.error("Fill title, company, and job description.")
            else:
                pr_add = ensure_resume_ready(api, add_resume_sel)
                if not pr_add:
                    st.error("Could not prepare that resume.")
                else:
                    preview_job = Job(
                        id=preview_job_id,
                        title=jt.strip(),
                        company=jc.strip(),
                        description=jd.strip(),
                        ingested_at="",
                        selected_resume_id=add_resume_sel,
                    )
                    ent = resume_store.get_entry(idx_jobs, add_resume_sel)
                    tags = ent.tags if ent else []
                    try:
                        hybrid, s10, narrative = ingestion.match_preview_for_resume(
                            api,
                            embedding_model(),
                            chat_model(),
                            preview_job,
                            add_resume_sel,
                            pr_add,
                            tags,
                        )
                        st.session_state["add_job_preview"] = {
                            "hybrid": hybrid,
                            "s10": s10,
                            "narrative": narrative,
                            "resume_id": add_resume_sel,
                        }
                        st.success("Match preview ready below.")
                    except Exception as e:
                        st.exception(e)
    with c_s:
        if st.button("Save job", key="add_job_save"):
            if not rid_list_add or not add_resume_sel:
                st.error("Select a resume first.")
            elif not (jt.strip() and jc.strip() and jd.strip()):
                st.error("Fill title, company, and job description.")
            else:
                prev = st.session_state.get("add_job_preview")
                match_s10 = match_fb = match_rid = None
                scores_arg = sug_arg = low_arg = None
                if (
                    prev
                    and prev.get("resume_id") == add_resume_sel
                ):
                    match_s10 = prev.get("s10")
                    match_fb = prev.get("narrative")
                    match_rid = add_resume_sel
                job = ingestion.add_job(
                    jt.strip(),
                    jc.strip(),
                    jd.strip(),
                    selected_resume_id=add_resume_sel,
                    match_score_10=match_s10,
                    match_feedback=match_fb,
                    match_resume_id=match_rid,
                    resume_scores=scores_arg,
                    suggested_resume_id=sug_arg,
                    suggestion_low_confidence=low_arg,
                )
                if prev and prev.get("resume_id") == add_resume_sel:
                    pr_new = ensure_resume_ready(api, add_resume_sel)
                    if pr_new:
                        try:
                            ingestion.recompute_job_matches(
                                api,
                                embedding_model(),
                                chat_model(),
                                job,
                            )
                        except Exception:
                            pass
                st.session_state.pop("add_job_preview", None)
                st.session_state["preview_job_id"] = str(uuid.uuid4())
                st.success("Job saved.")
                st.rerun()

    prev_ui = st.session_state.get("add_job_preview")
    if prev_ui:
        st.info(
            f"**Your resume matches this job {prev_ui['s10']}/10**\n\n"
            f"{prev_ui['narrative']}"
        )

    jobs = ingestion.load_jobs().jobs
    if st.button("Update match scores for all jobs"):
        progress = st.progress(0.0)
        for i, job in enumerate(jobs):
            rid = job.selected_resume_id
            if rid:
                ensure_resume_ready(api, rid)
            try:
                ingestion.recompute_job_matches(
                    api, embedding_model(), chat_model(), job
                )
            except Exception as e:
                st.warning(f"Job {job.id}: {e}")
            progress.progress((i + 1) / max(len(jobs), 1))
        st.success("Done.")
        st.rerun()

    with st.expander("Applications export"):
        apps = tracker.load_applications().applications
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "id",
                "job_id",
                "resume_id",
                "ab_variant",
                "status",
                "outcome",
                "notes",
                "updated_at",
            ]
        )
        for a in apps:
            w.writerow(
                [
                    a.id,
                    a.job_id,
                    a.resume_id,
                    a.ab_variant or "",
                    a.status,
                    a.outcome or "",
                    a.notes,
                    a.updated_at,
                ]
            )
        st.download_button(
            "Download applications.csv", buf.getvalue(), "applications.csv"
        )

    st.subheader("3. Match and generate")
    if not jobs:
        st.info("No saved jobs yet.")
    id_to_label_saved = id_to_label

    for job in jobs:
        sel_list = [o[0] for o in opts_r]
        if not sel_list:
            continue
        cur = job.selected_resume_id or sel_list[0]
        if cur not in sel_list:
            cur = sel_list[0]
        score_line = ""
        if (
            job.match_score_10 is not None
            and job.match_resume_id == cur
            and job.match_feedback
        ):
            score_line = f" — {job.match_score_10}/10 match"
        with st.expander(f"{job.company} — {job.title}{score_line}"):
            sel = st.selectbox(
                "Resume for this job",
                sel_list,
                index=sel_list.index(cur),
                format_func=lambda x: id_to_label_saved.get(x, x),
                key=f"sel_{job.id}",
            )
            if st.button("Save resume choice", key=f"svsel_{job.id}"):
                job.selected_resume_id = sel
                job.match_score_10 = None
                job.match_feedback = None
                job.match_resume_id = None
                ingestion.update_job(job)
                st.rerun()

            pr = ensure_resume_ready(api, sel)
            if not pr:
                st.warning(
                    "Could not load or prepare this resume. "
                    "Check the Resumes tab or pick another resume."
                )
            else:
                stale = (
                    job.match_resume_id != sel
                    or job.match_feedback is None
                    or job.match_score_10 is None
                )
                if not stale and job.match_feedback:
                    st.markdown(
                        f"### Your resume matches this job **{job.match_score_10}/10**\n\n"
                        f"{job.match_feedback}"
                    )
                elif stale:
                    st.caption("Run **Update match** to refresh score and feedback.")

                if (
                    job.suggested_resume_id
                    and job.suggested_resume_id != sel
                    and len(sel_list) > 1
                ):
                    if st.button(
                        "Use recommended resume",
                        key=f"acc_{job.id}",
                    ):
                        job.selected_resume_id = job.suggested_resume_id
                        ingestion.update_job(job)
                        st.rerun()

                if st.button("Update match", key=f"sug_{job.id}"):
                    try:
                        job.selected_resume_id = sel
                        ingestion.update_job(job)
                        ingestion.recompute_job_matches(
                            api, embedding_model(), chat_model(), job
                        )
                        st.rerun()
                    except Exception as e:
                        st.exception(e)

                if (
                    pr
                    and job.match_score_10 is not None
                    and job.match_resume_id == sel
                    and job.match_score_10 < IMPROVE_SCORE_THRESHOLD
                ):
                    if st.button(
                        "Improve this resume for this job",
                        key=f"imp_{job.id}",
                    ):
                        with st.spinner("Improving resume…"):
                            try:
                                improved = generator.resume_improve_for_job(
                                    api, chat_model(), pr, job
                                )
                                resume_store.save_parsed(sel, improved)
                                resume_pipeline.refresh_embeddings_for_resume(
                                    api,
                                    sel,
                                    improved,
                                    embedding_model(),
                                )
                                refreshed = ingestion.get_job(job.id) or job
                                ingestion.recompute_job_matches(
                                    api,
                                    embedding_model(),
                                    chat_model(),
                                    refreshed,
                                )
                                st.success("Resume updated. Match refreshed.")
                                st.rerun()
                            except Exception as e:
                                st.exception(e)

                st.markdown("#### Generate")
                if st.button(
                    "Build tailored resume (.docx)",
                    type="primary",
                    key=f"btn_build_tailored_{job.id}",
                ):
                    with st.spinner("Building documents…"):
                        tailored = generator.tailored_resume_structured(
                            api, chat_model(), pr, job
                        )
                        st.session_state[f"tailored_docx_{job.id}"] = (
                            resume_export.structured_resume_to_docx(
                                tailored,
                                f"{job.title} — {job.company}",
                            )
                        )
                        st.session_state[f"tailored_pdf_{job.id}"] = (
                            resume_export.structured_resume_to_pdf(
                                tailored,
                                f"{job.title} — {job.company}",
                            )
                        )
                if st.button(
                    "Recruiter outreach",
                    type="primary",
                    key=f"ro_{job.id}",
                ):
                    with st.spinner("Generating outreach…"):
                        st.session_state[f"outreach_{job.id}"] = (
                            generator.recruiter_outreach(
                                api, chat_model(), pr, job
                            )
                        )

                if f"tailored_docx_{job.id}" in st.session_state:
                    st.download_button(
                        "Download tailored_resume.docx",
                        st.session_state[f"tailored_docx_{job.id}"],
                        file_name=f"tailored_{job.id[:8]}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dldocx_{job.id}",
                    )
                if f"tailored_pdf_{job.id}" in st.session_state:
                    st.download_button(
                        "Download tailored_resume.pdf",
                        st.session_state[f"tailored_pdf_{job.id}"],
                        file_name=f"tailored_{job.id[:8]}.pdf",
                        mime="application/pdf",
                        key=f"dlpdf_{job.id}",
                    )
                if f"outreach_{job.id}" in st.session_state:
                    st.markdown(st.session_state[f"outreach_{job.id}"])

                with st.expander("More outputs"):
                    company_blurb = st.text_input(
                        "Company notes (optional)",
                        key=f"blur_{job.id}",
                        value="",
                    )
                    if st.button("Tailored bullets", key=f"tb_{job.id}"):
                        with st.spinner("Generating…"):
                            st.session_state[f"bullets_{job.id}"] = (
                                generator.tailored_bullets(
                                    api, chat_model(), pr, job
                                )
                            )
                    if st.button("Why company?", key=f"wc_{job.id}"):
                        with st.spinner("Generating…"):
                            st.session_state[f"why_{job.id}"] = (
                                generator.why_company(
                                    api,
                                    chat_model(),
                                    pr,
                                    job,
                                    company_blurb,
                                )
                            )
                    if f"bullets_{job.id}" in st.session_state:
                        st.markdown(st.session_state[f"bullets_{job.id}"])
                    if f"why_{job.id}" in st.session_state:
                        st.markdown(st.session_state[f"why_{job.id}"])

            st.divider()
            st.caption("Tracker")
            colt1, colt2, colt3 = st.columns(3)
            with colt1:
                st_out = st.selectbox(
                    "Status",
                    ["new", "shortlisted", "applied", "closed"],
                    key=f"st_{job.id}",
                )
            with colt2:
                outc = st.selectbox(
                    "Outcome",
                    [
                        "",
                        "submitted",
                        "rejected",
                        "interview",
                        "offer",
                        "withdrawn",
                    ],
                    key=f"oc_{job.id}",
                )
            with colt3:
                note = st.text_input("Notes", key=f"nt_{job.id}")
            entry = resume_store.get_entry(resume_store.load_index(), sel)
            abv = entry.ab_variant if entry else None
            if st.button("Save application row", key=f"trk_{job.id}"):
                tracker.upsert_application(
                    job.id,
                    sel,
                    status=st_out,
                    outcome=outc or None,
                    notes=note,
                    ab_variant=abv,
                )
                st.success("Saved.")

            if st.button("Delete job", key=f"dj_{job.id}"):
                ingestion.delete_job(job.id)
                st.rerun()
