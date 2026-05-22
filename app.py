"""
Yang's Job Board — Streamlit web app.
Interactive table + modal detail view. Clean dashboard design.
"""

import os
import re
from datetime import datetime
import httpx
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True)

# ── Page config (must be first) ───────────────────────────────────────────────
st.set_page_config(
    page_title="Yang's Job Board",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Secrets ───────────────────────────────────────────────────────────────────
def _secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, "")

NOTION_KEY = _secret("NOTION_API_KEY")
NOTION_DB  = _secret("NOTION_DATABASE_ID")
os.environ.setdefault("ANTHROPIC_API_KEY", _secret("ANTHROPIC_API_KEY"))
os.environ.setdefault("ADZUNA_APP_ID",     _secret("ADZUNA_APP_ID"))
os.environ.setdefault("ADZUNA_APP_KEY",    _secret("ADZUNA_APP_KEY"))

_d = NOTION_DB.replace("-", "")
DB_UUID = (f"{_d[:8]}-{_d[8:12]}-{_d[12:16]}-{_d[16:20]}-{_d[20:]}"
           if len(_d) == 32 else NOTION_DB)

HEADERS = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

STATUS_OPTIONS = ["New", "Applied", "Interview", "Offer", "Rejected"]
STATUS_EMOJI   = {
    "New": "🔵 New", "Applied": "🟡 Applied", "Interview": "🟠 Interview",
    "Offer": "🟢 Offer", "Rejected": "🔴 Rejected", "Ignored": "⚫ Ignored",
}

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Layout */
.main .block-container { padding: 1.5rem 2rem 2rem; max-width: 1400px; }

/* Header */
h1 { font-size: 1.9rem !important; font-weight: 800 !important; margin-bottom: 0 !important; }
.subtitle { color: #94a3b8; font-size: 0.85rem; margin-top: 0.1rem; margin-bottom: 1.5rem; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1rem 1.4rem;
}
[data-testid="stMetricLabel"] p { font-size: 0.72rem !important; color: #94a3b8 !important; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { font-size: 2rem !important; font-weight: 800 !important; }
[data-testid="stMetricDelta"] { font-size: 0.78rem !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 0; border-bottom: 2px solid #334155; margin-bottom: 1rem; }
.stTabs [data-baseweb="tab"] { padding: 0.65rem 1.6rem; font-weight: 500; color: #64748b; background: transparent; border: none; }
.stTabs [aria-selected="true"] { color: #f1f5f9 !important; border-bottom: 2px solid #3b82f6 !important; background: transparent !important; }

/* Dataframe — make rows look clickable */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #334155; }
[data-testid="stDataFrame"] table { font-size: 0.88rem; }

/* Buttons */
.stButton > button {
    border-radius: 8px; font-weight: 600; font-size: 0.85rem;
    padding: 0.4rem 1rem; transition: all 0.15s ease;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }

/* Download buttons */
.stDownloadButton > button {
    border-radius: 8px; font-weight: 600; font-size: 0.85rem;
    background: #059669 !important; border-color: #059669 !important; color: white !important;
}

/* Dialog */
[data-testid="stDialog"] > div { border-radius: 14px !important; border: 1px solid #334155; }

/* Sidebar */
[data-testid="stSidebar"] { background: #0f172a; border-right: 1px solid #1e293b; }
[data-testid="stSidebar"] h2 { font-size: 0.85rem !important; color: #64748b !important;
    text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600 !important; }
[data-testid="stSidebar"] label { font-size: 0.8rem !important; color: #94a3b8 !important; }

/* Info/tip boxes */
.tip-box {
    background: #1e293b; border-left: 3px solid #3b82f6;
    border-radius: 0 8px 8px 0; padding: 0.6rem 1rem;
    font-size: 0.82rem; color: #94a3b8; margin-bottom: 1rem;
}

/* Status pill in detail view */
.status-pill {
    display: inline-block; padding: 0.2rem 0.8rem;
    border-radius: 999px; font-size: 0.78rem; font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


# ── Notion helpers ────────────────────────────────────────────────────────────
def _text(prop: dict) -> str:
    for key in ("title", "rich_text"):
        items = prop.get(key, [])
        if items:
            return "".join(i.get("plain_text", "") for i in items)
    return ""


@st.cache_data(ttl=180, show_spinner=False)
def fetch_jobs() -> list:
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
            p = page.get("properties", {})
            status = (p.get("Status", {}).get("select") or {}).get("name", "New")
            score  = p.get("Score", {}).get("number") or 0
            jobs.append({
                "id":         page["id"],
                "title":      _text(p.get("Title", {})),
                "company":    _text(p.get("Company", {})),
                "location":   _text(p.get("Location", {})),
                "url":        p.get("URL", {}).get("url", ""),
                "score":      int(score),
                "source":     (p.get("Source", {}).get("select") or {}).get("name", ""),
                "match_flag": (p.get("MatchFlag", {}).get("select") or {}).get("name", ""),
                "keywords":   _text(p.get("KeywordsMatched", {})),
                "date_posted":(p.get("DatePosted", {}).get("date") or {}).get("start", ""),
                "status":     status,
                "status_log": _text(p.get("StatusLog", {})),
                "docs_done":  p.get("DocsGenerated", {}).get("checkbox", False),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return sorted(jobs, key=lambda j: j["score"], reverse=True)


def _patch(page_id: str, props: dict) -> None:
    httpx.patch(f"https://api.notion.com/v1/pages/{page_id}",
                headers=HEADERS, json={"properties": props}, timeout=30)


def update_status(job: dict, new_status: str) -> None:
    date_str = datetime.now().strftime("%-d %b %Y")
    old_log  = job.get("status_log", "")
    new_log  = (f"{old_log}\n{date_str} — {new_status}".strip())[:2000]
    _patch(job["id"], {
        "Status":    {"select": {"name": new_status}},
        "StatusLog": {"rich_text": [{"text": {"content": new_log}}]},
    })


def ignore_job(job: dict) -> None:
    date_str = datetime.now().strftime("%-d %b %Y")
    old_log  = job.get("status_log", "")
    new_log  = (f"{old_log}\n{date_str} — Ignored".strip())[:2000]
    _patch(job["id"], {
        "Status":    {"select": {"name": "Ignored"}},
        "StatusLog": {"rich_text": [{"text": {"content": new_log}}]},
    })


def unignore_job(job: dict) -> None:
    date_str = datetime.now().strftime("%-d %b %Y")
    old_log  = job.get("status_log", "")
    new_log  = (f"{old_log}\n{date_str} — Unignored".strip())[:2000]
    _patch(job["id"], {
        "Status":    {"select": {"name": "New"}},
        "StatusLog": {"rich_text": [{"text": {"content": new_log}}]},
    })


def mark_docs(page_id: str) -> None:
    _patch(page_id, {"DocsGenerated": {"checkbox": True}})


# ── Document generation ───────────────────────────────────────────────────────
def _slug(job: dict) -> str:
    co = re.sub(r'[^\w]', '_', job.get("company", ""))[:20]
    ti = re.sub(r'[^\w]', '_', job.get("title", ""))[:30]
    return f"{datetime.now().strftime('%Y%m%d')}_{co}_{ti}"


# ── Detail dialog ─────────────────────────────────────────────────────────────
@st.dialog("Role Details", width="large")
def job_detail(job: dict) -> None:
    is_ignored = job["status"] == "Ignored"
    flag = " 🏆" if job.get("match_flag") == "HIGH MATCH" else ""

    # Header
    st.markdown(f"### {job['title']}{flag}")
    st.markdown(
        f"**{job['company']}** &nbsp;·&nbsp; {job['location']} &nbsp;·&nbsp; "
        f"via {job['source']} &nbsp;·&nbsp; posted {job['date_posted']}"
    )

    score = job["score"]
    score_color = "#10b981" if score >= 7 else "#f59e0b" if score >= 5 else "#ef4444"
    st.markdown(
        f'<span style="color:{score_color}; font-size:1.1rem; font-weight:700;">▲ Match score: {score}/10</span>',
        unsafe_allow_html=True,
    )

    if job.get("url"):
        st.link_button("🔗 View on job board", job["url"])

    if job.get("keywords"):
        with st.expander("Keywords matched"):
            st.caption(job["keywords"])

    st.divider()

    if not is_ignored:
        # ── Status ──────────────────────────────────────────────────────────
        st.markdown("**Application Status**")
        col_sel, col_btn = st.columns([3, 1])
        with col_sel:
            cur_idx = STATUS_OPTIONS.index(job["status"]) if job["status"] in STATUS_OPTIONS else 0
            new_status = st.selectbox("Status", STATUS_OPTIONS,
                                      index=cur_idx, label_visibility="collapsed",
                                      key=f"sel_{job['id']}")
        with col_btn:
            st.markdown("<div style='margin-top:4px'>", unsafe_allow_html=True)
            if st.button("Save", key=f"save_{job['id']}", use_container_width=True):
                update_status(job, new_status)
                st.cache_data.clear()
                st.rerun()

        if job.get("status_log"):
            with st.expander("Status history"):
                for line in reversed(job["status_log"].strip().split("\n")):
                    if line.strip():
                        st.caption(f"• {line.strip()}")

        st.divider()

        # ── Document generation ──────────────────────────────────────────────
        st.markdown("**Generate Documents**")
        st.markdown(
            '<div class="tip-box">Documents are tailored by AI to this specific role. '
            'Download as Word — edit if needed before sending.</div>',
            unsafe_allow_html=True,
        )

        col_cl, col_cv = st.columns(2)

        with col_cl:
            if st.button("📝 Generate Cover Letter", key=f"cl_{job['id']}",
                         use_container_width=True):
                with st.spinner("Writing cover letter..."):
                    try:
                        from cover_letter import generate
                        from document_builder import build_cover_letter_docx
                        cl_text = generate(job)
                        cl_docx = build_cover_letter_docx(cl_text)
                        st.session_state[f"cl_{job['id']}"] = (cl_text, cl_docx)
                        mark_docs(job["id"])
                    except Exception as e:
                        st.error(f"Error: {e}")

        with col_cv:
            if st.button("📄 Generate Resume", key=f"cv_{job['id']}",
                         use_container_width=True):
                with st.spinner("Tailoring resume..."):
                    try:
                        from document_builder import build_resume_docx
                        cv_docx = build_resume_docx(job)
                        st.session_state[f"cv_{job['id']}"] = cv_docx
                        mark_docs(job["id"])
                    except Exception as e:
                        st.error(f"Error: {e}")

        slug = _slug(job)

        # Cover letter downloads
        if f"cl_{job['id']}" in st.session_state:
            cl_text, cl_docx = st.session_state[f"cl_{job['id']}"]
            st.markdown("**Cover Letter Preview**")
            st.text_area("", cl_text, height=220, label_visibility="collapsed",
                         key=f"clprev_{job['id']}")
            st.download_button(
                "⬇️ Download Cover Letter (.docx)",
                data=cl_docx,
                file_name=f"{slug}_cover_letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dlcl_{job['id']}", use_container_width=True,
            )

        # Resume download
        if f"cv_{job['id']}" in st.session_state:
            st.download_button(
                "⬇️ Download Resume (.docx)",
                data=st.session_state[f"cv_{job['id']}"],
                file_name=f"{slug}_resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dlcv_{job['id']}", use_container_width=True,
            )

        st.divider()

        # ── Ignore ───────────────────────────────────────────────────────────
        if st.button("🚫 Ignore this opportunity", key=f"ign_{job['id']}",
                     use_container_width=True):
            ignore_job(job)
            st.cache_data.clear()
            st.rerun()

    else:
        # Archived view
        st.info("This opportunity has been ignored.")
        if job.get("status_log"):
            with st.expander("History"):
                for line in reversed(job["status_log"].strip().split("\n")):
                    if line.strip():
                        st.caption(f"• {line.strip()}")
        if st.button("↩️ Unignore — move back to active", key=f"unign_{job['id']}",
                     use_container_width=True):
            unignore_job(job)
            st.cache_data.clear()
            st.rerun()


# ── Build table dataframe ─────────────────────────────────────────────────────
def to_df(jobs: list) -> pd.DataFrame:
    rows = []
    for j in jobs:
        score = j["score"]
        score_str = ("🟢 " if score >= 7 else "🟡 " if score >= 5 else "🔴 ") + str(score)
        flag  = "🏆" if j.get("match_flag") == "HIGH MATCH" else ""
        rows.append({
            "Score":   score_str,
            "":        flag,
            "Role":    j["title"],
            "Company": j["company"],
            "Source":  j["source"],
            "Posted":  j["date_posted"],
            "Status":  STATUS_EMOJI.get(j["status"], j["status"]),
            "Docs":    "✅" if j["docs_done"] else "",
            "_score":  score,   # hidden sort key
        })
    return pd.DataFrame(rows)


# ── Main app ──────────────────────────────────────────────────────────────────
# Header
st.markdown("# 💼 Yang's Job Board")
st.markdown('<p class="subtitle">AI-qualified banking opportunities · refreshed every 24 hours</p>',
            unsafe_allow_html=True)

# Load jobs
with st.spinner("Loading opportunities..."):
    try:
        all_jobs = fetch_jobs()
    except Exception as e:
        st.error(f"Could not connect to Notion: {e}")
        st.stop()

active  = [j for j in all_jobs if j["status"] != "Ignored"]
ignored = [j for j in all_jobs if j["status"] == "Ignored"]

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Filters")
    sources = sorted({j["source"] for j in active if j["source"]})
    sel_sources = st.multiselect("Source", sources, default=sources, label_visibility="visible")

    statuses = STATUS_OPTIONS
    sel_statuses = st.multiselect("Status", statuses, default=statuses)

    score_min, score_max = st.slider("Min score", 0, 10, (3, 10))

    st.divider()
    if st.button("🔄 Refresh jobs", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("## About")
    st.caption("Jobs are scraped from SEEK and Adzuna every 24 hours and scored by AI against your profile. "
               "Click any row in the table to view details, generate documents, or update your application status.")

# Apply filters
filtered = [
    j for j in active
    if j["source"] in sel_sources
    and j["status"] in sel_statuses
    and score_min <= j["score"] <= score_max
]

# ── Summary metrics ───────────────────────────────────────────────────────────
high_match = sum(1 for j in filtered if j.get("match_flag") == "HIGH MATCH")
applied    = sum(1 for j in active  if j["status"] == "Applied")
interviews = sum(1 for j in active  if j["status"] == "Interview")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Active roles",   len(active))
m2.metric("Showing",        len(filtered))
m3.metric("🏆 High match",  high_match)
m4.metric("📨 Applied",     applied)
m5.metric("🗣 Interviews",  interviews)

st.markdown("<div style='margin-top:1rem'/>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_active, tab_ignored = st.tabs([
    f"Active opportunities  ({len(filtered)})",
    f"Ignored  ({len(ignored)})",
])

with tab_active:
    if not filtered:
        st.info("No opportunities match your current filters.")
    else:
        st.markdown(
            '<div class="tip-box">👆 Click any row to open details, update status, '
            'or generate a tailored cover letter and resume.</div>',
            unsafe_allow_html=True,
        )

        df = to_df(filtered)
        display_cols = ["Score", "", "Role", "Company", "Source", "Posted", "Status", "Docs"]

        event = st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Score":   st.column_config.TextColumn("Score", width="small"),
                "":        st.column_config.TextColumn("",      width="small"),
                "Role":    st.column_config.TextColumn("Role",    width="large"),
                "Company": st.column_config.TextColumn("Company", width="medium"),
                "Source":  st.column_config.TextColumn("Source",  width="small"),
                "Posted":  st.column_config.TextColumn("Posted",  width="small"),
                "Status":  st.column_config.TextColumn("Status",  width="medium"),
                "Docs":    st.column_config.TextColumn("Docs",    width="small"),
            },
            height=min(80 + len(filtered) * 35, 600),
        )

        sel = event.selection.rows
        if sel:
            job_detail(filtered[sel[0]])

with tab_ignored:
    if not ignored:
        st.info("Nothing ignored yet. Use the Ignore button in a role's detail view to hide it.")
    else:
        df_ign = to_df(ignored)
        display_cols = ["Score", "", "Role", "Company", "Source", "Posted", "Docs"]

        event_ign = st.dataframe(
            df_ign[display_cols],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Score":   st.column_config.TextColumn("Score",   width="small"),
                "":        st.column_config.TextColumn("",        width="small"),
                "Role":    st.column_config.TextColumn("Role",    width="large"),
                "Company": st.column_config.TextColumn("Company", width="medium"),
                "Source":  st.column_config.TextColumn("Source",  width="small"),
                "Posted":  st.column_config.TextColumn("Posted",  width="small"),
                "Docs":    st.column_config.TextColumn("Docs",    width="small"),
            },
            height=min(80 + len(ignored) * 35, 400),
        )

        sel_ign = event_ign.selection.rows
        if sel_ign:
            job_detail(ignored[sel_ign[0]])
