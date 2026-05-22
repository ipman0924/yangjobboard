"""
Yang's Job Board — Streamlit web app.

Reads qualified jobs from Notion. Lets Yang manage status, generate
cover letters and tailored resumes, and ignore irrelevant listings.
"""

import os
import io
from datetime import datetime
from typing import Optional
import httpx
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NOTION_KEY = os.environ.get("NOTION_API_KEY", st.secrets.get("NOTION_API_KEY", ""))
NOTION_DB  = os.environ.get("NOTION_DATABASE_ID", st.secrets.get("NOTION_DATABASE_ID", ""))
os.environ.setdefault("ANTHROPIC_API_KEY",
    st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")))

_d = NOTION_DB.replace("-", "")
DB_UUID = f"{_d[:8]}-{_d[8:12]}-{_d[12:16]}-{_d[16:20]}-{_d[20:]}" if len(_d) == 32 else NOTION_DB

HEADERS = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

STATUS_OPTIONS  = ["New", "Applied", "Interview", "Offer", "Rejected"]
STATUS_COLOURS  = {
    "New": "🔵", "Applied": "🟡", "Interview": "🟠",
    "Offer": "🟢", "Rejected": "🔴", "Ignored": "⚫",
}
SCORE_COLOURS = {
    range(8, 20): "🟢",
    range(5, 8):  "🟡",
    range(0, 5):  "🔴",
}


def score_badge(score: int) -> str:
    for r, emoji in SCORE_COLOURS.items():
        if score in r:
            return f"{emoji} {score}"
    return str(score)


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def _extract_text(prop: dict) -> str:
    for key in ("title", "rich_text"):
        items = prop.get(key, [])
        if items:
            return "".join(i.get("plain_text", "") for i in items)
    return ""


def fetch_jobs() -> list[dict]:
    jobs, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = httpx.post(f"https://api.notion.com/v1/databases/{DB_UUID}/query",
                       headers=HEADERS, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            status = (props.get("Status", {}).get("select") or {}).get("name", "New")
            jobs.append({
                "id":           page["id"],
                "title":        _extract_text(props.get("Title", {})),
                "company":      _extract_text(props.get("Company", {})),
                "location":     _extract_text(props.get("Location", {})),
                "url":          props.get("URL", {}).get("url", ""),
                "score":        props.get("Score", {}).get("number", 0) or 0,
                "source":       (props.get("Source", {}).get("select") or {}).get("name", ""),
                "match_flag":   (props.get("MatchFlag", {}).get("select") or {}).get("name", ""),
                "description":  _extract_text(props.get("KeywordsMatched", {})),
                "date_posted":  (props.get("DatePosted", {}).get("date") or {}).get("start", ""),
                "status":       status,
                "status_log":   _extract_text(props.get("StatusLog", {})),
                "docs_done":    props.get("DocsGenerated", {}).get("checkbox", False),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return sorted(jobs, key=lambda j: j["score"], reverse=True)


def update_status(page_id: str, new_status: str, old_log: str) -> None:
    date_str = datetime.now().strftime("%-d %b %Y")
    entry    = f"{date_str} — {new_status}"
    new_log  = f"{old_log}\n{entry}".strip() if old_log else entry
    httpx.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {
            "Status":    {"select": {"name": new_status}},
            "StatusLog": {"rich_text": [{"text": {"content": new_log[:2000]}}]},
        }},
        timeout=30,
    )


def archive_job(page_id: str) -> None:
    httpx.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {"Status": {"select": {"name": "Ignored"}}}},
        timeout=30,
    )


def unignore_job(page_id: str, old_log: str) -> None:
    date_str = datetime.now().strftime("%-d %b %Y")
    entry    = f"{date_str} — Unignored"
    new_log  = f"{old_log}\n{entry}".strip() if old_log else entry
    httpx.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {
            "Status":    {"select": {"name": "New"}},
            "StatusLog": {"rich_text": [{"text": {"content": new_log[:2000]}}]},
        }},
        timeout=30,
    )


def mark_docs_generated(page_id: str) -> None:
    httpx.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {"DocsGenerated": {"checkbox": True}}},
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Document generation (imported lazily to avoid slowing page load)
# ---------------------------------------------------------------------------

def _gen_cover_letter(job: dict) -> str:
    from cover_letter import generate
    return generate(job)


def _gen_resume_docx(job: dict) -> bytes:
    from document_builder import build_resume_docx
    return build_resume_docx(job)


def _gen_cover_letter_docx(text: str) -> bytes:
    from document_builder import build_cover_letter_docx
    return build_cover_letter_docx(text)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _safe_filename(s: str, maxlen: int = 40) -> str:
    return re.sub(r'[^\w\s-]', '', s).strip().replace(' ', '_')[:maxlen]


import re


def job_card(job: dict, archived: bool = False) -> None:
    score  = job["score"]
    status = job["status"]
    badge  = score_badge(score)
    emoji  = STATUS_COLOURS.get(status, "")
    flag   = " 🏆" if job.get("match_flag") == "HIGH MATCH" else ""

    with st.expander(f"{badge}  {job['title']} @ {job['company']}{flag}  {emoji} {status}"):

        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"📍 {job['location']}  ·  📅 {job['date_posted']}  ·  🔎 {job['source']}")
            if job.get("description"):
                st.markdown(f"**Keywords matched:** {job['description']}")
            if job.get("url"):
                st.markdown(f"[🔗 View on job board]({job['url']})")

        with col2:
            if job.get("docs_done"):
                st.caption("📄 Docs generated")

        st.divider()

        if not archived:
            # Status update
            st.markdown("**Application status**")
            new_status = st.selectbox(
                "Update status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(status) if status in STATUS_OPTIONS else 0,
                key=f"status_{job['id']}",
                label_visibility="collapsed",
            )
            if new_status != status:
                if st.button("Save status", key=f"save_{job['id']}"):
                    update_status(job["id"], new_status, job["status_log"])
                    st.success(f"Status updated to {new_status}")
                    st.cache_data.clear()
                    st.rerun()

            if job.get("status_log"):
                with st.expander("Status history"):
                    for line in job["status_log"].split("\n"):
                        if line.strip():
                            st.caption(line.strip())

            st.divider()

            # Document generation
            st.markdown("**Generate documents**")
            col_cl, col_cv = st.columns(2)

            with col_cl:
                if st.button("📝 Cover Letter", key=f"cl_{job['id']}"):
                    with st.spinner("Writing cover letter..."):
                        try:
                            cl_text = _gen_cover_letter(job)
                            cl_docx = _gen_cover_letter_docx(cl_text)
                            st.session_state[f"cl_text_{job['id']}"] = cl_text
                            st.session_state[f"cl_docx_{job['id']}"] = cl_docx
                            mark_docs_generated(job["id"])
                        except Exception as e:
                            st.error(f"Error: {e}")

            with col_cv:
                if st.button("📄 Resume", key=f"cv_{job['id']}"):
                    with st.spinner("Tailoring resume..."):
                        try:
                            cv_docx = _gen_resume_docx(job)
                            st.session_state[f"cv_docx_{job['id']}"] = cv_docx
                            mark_docs_generated(job["id"])
                        except Exception as e:
                            st.error(f"Error: {e}")

            # Download buttons — appear after generation
            slug = f"{datetime.now().strftime('%Y%m%d')}_{_safe_filename(job['company'])}_{_safe_filename(job['title'])}"

            if f"cl_text_{job['id']}" in st.session_state:
                st.text_area("Cover letter preview",
                             st.session_state[f"cl_text_{job['id']}"],
                             height=250, key=f"cl_preview_{job['id']}")
                st.download_button(
                    "⬇️ Download Cover Letter (.docx)",
                    data=st.session_state[f"cl_docx_{job['id']}"],
                    file_name=f"{slug}_cover_letter.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_cl_{job['id']}",
                )

            if f"cv_docx_{job['id']}" in st.session_state:
                st.download_button(
                    "⬇️ Download Resume (.docx)",
                    data=st.session_state[f"cv_docx_{job['id']}"],
                    file_name=f"{slug}_resume.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_cv_{job['id']}",
                )

            st.divider()

            # Ignore
            if st.button("🚫 Ignore this opportunity", key=f"ignore_{job['id']}"):
                archive_job(job["id"])
                st.cache_data.clear()
                st.rerun()

        else:
            # Archived view
            st.caption(job.get("status_log", ""))
            if st.button("↩️ Unignore", key=f"unignore_{job['id']}"):
                unignore_job(job["id"], job["status_log"])
                st.cache_data.clear()
                st.rerun()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Yang's Job Board",
    page_icon="💼",
    layout="wide",
)

st.title("💼 Yang's Job Board")
st.caption("Qualified opportunities — updated every 24 hours")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=300)
def load_jobs():
    return fetch_jobs()

try:
    all_jobs = load_jobs()
except Exception as e:
    st.error(f"Could not load jobs from Notion: {e}")
    st.stop()

active   = [j for j in all_jobs if j["status"] != "Ignored"]
ignored  = [j for j in all_jobs if j["status"] == "Ignored"]

tab_active, tab_ignored = st.tabs([
    f"Active opportunities ({len(active)})",
    f"Ignored ({len(ignored)})",
])

with tab_active:
    if not active:
        st.info("No active opportunities at the moment. Check back after the next scan.")
    else:
        high = [j for j in active if j.get("match_flag") == "HIGH MATCH"]
        rest = [j for j in active if j.get("match_flag") != "HIGH MATCH"]

        if high:
            st.subheader("🏆 High Match")
            for job in high:
                job_card(job)
            st.divider()

        if rest:
            st.subheader("Other qualified roles")
            for job in rest:
                job_card(job)

with tab_ignored:
    if not ignored:
        st.info("Nothing ignored yet.")
    else:
        for job in ignored:
            job_card(job, archived=True)
