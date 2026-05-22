"""
Yang's Job Board — Streamlit web app.
Outlook-style layout: collapsible sidebar | scrollable table | right detail pane.
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

_d = NOTION_DB.replace("-", "")
DB_UUID = (f"{_d[:8]}-{_d[8:12]}-{_d[12:16]}-{_d[16:20]}-{_d[20:]}"
           if len(_d) == 32 else NOTION_DB)

HEADERS = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

STATUS_OPTIONS = ["New", "Applied", "Interview", "Offer", "Rejected"]
STATUS_BADGE   = {
    "New": "🔵 New", "Applied": "🟡 Applied", "Interview": "🟠 Interview",
    "Offer": "🟢 Offer", "Rejected": "🔴 Rejected", "Ignored": "⚫ Ignored",
}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Tighter container — let the split pane breathe */
.main .block-container { padding: 1.2rem 1.5rem 2rem; max-width: none; }
h1 { font-size: 1.8rem !important; font-weight: 800 !important; }
.sub  { color: #94a3b8; font-size: 0.82rem; margin-bottom: 1rem; }

[data-testid="metric-container"] {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 10px; padding: 0.8rem 1rem;
}
[data-testid="stMetricLabel"] p {
    font-size: 0.68rem !important; color: #94a3b8 !important;
    text-transform: uppercase; letter-spacing: 0.06em;
}
[data-testid="stMetricValue"] { font-size: 1.7rem !important; font-weight: 800 !important; }

.stTabs [data-baseweb="tab-list"] { border-bottom: 2px solid #334155; gap: 0; }
.stTabs [data-baseweb="tab"] {
    padding: 0.5rem 1.2rem; font-weight: 500;
    color: #64748b; background: transparent; border: none;
}
.stTabs [aria-selected="true"] {
    color: #f1f5f9 !important;
    border-bottom: 2px solid #3b82f6 !important;
}

[data-testid="stDataFrame"] {
    border-radius: 10px; border: 1px solid #334155; overflow: hidden;
}

/* Right detail pane */
.detail-panel {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
}
.detail-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 0.2rem; }
.detail-meta  { color: #94a3b8; font-size: 0.82rem; margin-bottom: 0.7rem; }
.score-badge  { font-weight: 700; font-size: 0.95rem; }
.doc-note {
    background: #064e3b; border-radius: 6px;
    padding: 0.4rem 0.8rem; font-size: 0.8rem; color: #6ee7b7;
    display: inline-block; margin-bottom: 0.6rem;
}
.section-label {
    font-size: 0.72rem; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 0.4rem;
}
.pane-placeholder {
    height: 260px;
    display: flex; align-items: center; justify-content: center;
    color: #475569; font-size: 0.88rem;
    border: 1px dashed #334155; border-radius: 12px;
}

.stButton > button {
    border-radius: 7px; font-weight: 600; font-size: 0.83rem;
    padding: 0.35rem 0.9rem;
}
.stDownloadButton > button {
    border-radius: 7px; font-weight: 600; font-size: 0.83rem;
    background: #059669 !important; border-color: #059669 !important;
    color: white !important;
}

[data-testid="stSidebar"] { background: #0f172a; border-right: 1px solid #1e293b; }
[data-testid="stSidebar"] .stMarkdown p { font-size: 0.8rem; color: #94a3b8; }
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
            score  = int(p.get("Score", {}).get("number") or 0)
            jobs.append({
                "id":         page["id"],
                "title":      _text(p.get("Title", {})),
                "company":    _text(p.get("Company", {})),
                "location":   _text(p.get("Location", {})),
                "url":        p.get("URL", {}).get("url", ""),
                "score":      score,
                "source":     (p.get("Source", {}).get("select") or {}).get("name", ""),
                "match_flag": (p.get("MatchFlag", {}).get("select") or {}).get("name", ""),
                "keywords":   _text(p.get("KeywordsMatched", {})),
                "date_posted":(p.get("DatePosted", {}).get("date") or {}).get("start", ""),
                "status":     status,
                "status_log": _text(p.get("StatusLog", {})),
                "docs_done":  p.get("DocsGenerated", {}).get("checkbox", False),
                "favorite":   p.get("Favorite", {}).get("checkbox", False),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return sorted(jobs, key=lambda j: (j["favorite"], j["score"]), reverse=True)


def _patch(page_id: str, props: dict) -> None:
    httpx.patch(f"https://api.notion.com/v1/pages/{page_id}",
                headers=HEADERS, json={"properties": props}, timeout=30)


def _log_status(job: dict, label: str) -> str:
    date = datetime.now().strftime("%-d %b %Y")
    old  = job.get("status_log", "")
    return (f"{old}\n{date} — {label}".strip())[:2000]


def update_status(job: dict, new_status: str) -> None:
    _patch(job["id"], {
        "Status":    {"select": {"name": new_status}},
        "StatusLog": {"rich_text": [{"text": {"content": _log_status(job, new_status)}}]},
    })


def toggle_favorite(job: dict) -> None:
    _patch(job["id"], {"Favorite": {"checkbox": not job["favorite"]}})


def ignore_job(job: dict) -> None:
    _patch(job["id"], {
        "Status":    {"select": {"name": "Ignored"}},
        "StatusLog": {"rich_text": [{"text": {"content": _log_status(job, "Ignored")}}]},
    })


def unignore_job(job: dict) -> None:
    _patch(job["id"], {
        "Status":    {"select": {"name": "New"}},
        "StatusLog": {"rich_text": [{"text": {"content": _log_status(job, "Unignored")}}]},
    })


def mark_docs(page_id: str) -> None:
    _patch(page_id, {"DocsGenerated": {"checkbox": True}})


# ── Document helpers ──────────────────────────────────────────────────────────
def _slug(job: dict) -> str:
    co = re.sub(r'[^\w]', '_', job.get("company", ""))[:20]
    ti = re.sub(r'[^\w]', '_', job.get("title",   ""))[:28]
    return f"{datetime.now().strftime('%Y%m%d')}_{co}_{ti}"


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME  = "application/pdf"


# ── Build display dataframe ───────────────────────────────────────────────────
def to_df(jobs: list) -> pd.DataFrame:
    rows = []
    for j in jobs:
        s = j["score"]
        rows.append({
            "⭐":      "⭐" if j["favorite"] else "☆",
            "Score":   ("🟢 " if s >= 7 else "🟡 " if s >= 5 else "🔴 ") + str(s),
            "🏆":      "🏆" if j.get("match_flag") == "HIGH MATCH" else "",
            "Role":    j["title"],
            "Company": j["company"],
            "Posted":  j["date_posted"],
            "Status":  STATUS_BADGE.get(j["status"], j["status"]),
        })
    return pd.DataFrame(rows)


# ── Right detail pane ─────────────────────────────────────────────────────────
def detail_panel(job: dict, is_ignored: bool = False) -> None:
    flag = " 🏆" if job.get("match_flag") == "HIGH MATCH" else ""
    s    = job["score"]
    score_color = "#10b981" if s >= 7 else "#f59e0b" if s >= 5 else "#ef4444"

    st.markdown(f"""
    <div class="detail-panel">
        <div class="detail-title">{job['title']}{flag}</div>
        <div class="detail-meta">
            {job['company']} &nbsp;·&nbsp; {job['location']} &nbsp;·&nbsp; Posted {job['date_posted']}
        </div>
        <span class="score-badge" style="color:{score_color};">▲ Match score: {s}/10</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:0.5rem'/>", unsafe_allow_html=True)

    # Action row
    col_link, col_fav, col_ign = st.columns([2, 1, 1])
    with col_link:
        if job.get("url"):
            st.link_button("🔗 View posting", job["url"], use_container_width=True)
    with col_fav:
        fav_label = "⭐ Unfav" if job["favorite"] else "☆ Fav"
        if st.button(fav_label, key=f"fav_{job['id']}", use_container_width=True):
            toggle_favorite(job)
            st.cache_data.clear()
            st.rerun()
    with col_ign:
        if not is_ignored:
            if st.button("🚫 Ignore", key=f"ign_{job['id']}", use_container_width=True):
                ignore_job(job)
                st.cache_data.clear()
                st.rerun()
        else:
            if st.button("↩️ Unignore", key=f"unign_{job['id']}", use_container_width=True):
                unignore_job(job)
                st.cache_data.clear()
                st.rerun()

    if job.get("keywords"):
        with st.expander("Keywords matched"):
            st.caption(job["keywords"])

    st.divider()

    if not is_ignored:
        # ── Status ──────────────────────────────────────────────────────────
        st.markdown('<div class="section-label">Application status</div>', unsafe_allow_html=True)
        cur = STATUS_OPTIONS.index(job["status"]) if job["status"] in STATUS_OPTIONS else 0
        new_s = st.selectbox("Status", STATUS_OPTIONS, index=cur,
                             label_visibility="collapsed", key=f"sel_{job['id']}")
        if st.button("Save status", key=f"save_{job['id']}", use_container_width=True):
            update_status(job, new_s)
            st.cache_data.clear()
            st.rerun()

        if job.get("status_log"):
            with st.expander("Status history"):
                for line in reversed(job["status_log"].strip().split("\n")):
                    if line.strip():
                        st.caption(f"• {line.strip()}")

        st.divider()

        # ── Documents ───────────────────────────────────────────────────────
        st.markdown('<div class="section-label">Generate documents</div>', unsafe_allow_html=True)

        if job.get("docs_done"):
            st.markdown('<div class="doc-note">✅ Documents previously generated</div>',
                        unsafe_allow_html=True)

        slug = _slug(job)

        # Cover letter
        if st.button("📝 Generate Cover Letter", key=f"btn_cl_{job['id']}",
                     use_container_width=True):
            with st.spinner("Writing cover letter..."):
                try:
                    from cover_letter import generate
                    from document_builder import build_cover_letter_docx, build_cover_letter_pdf
                    text = generate(job)
                    st.session_state[f"cl_data_{job['id']}"] = {
                        "text": text,
                        "docx": build_cover_letter_docx(text),
                        "pdf":  build_cover_letter_pdf(text),
                    }
                    mark_docs(job["id"])
                except Exception as e:
                    st.error(f"Error: {e}")

        if f"cl_data_{job['id']}" in st.session_state:
            cl = st.session_state[f"cl_data_{job['id']}"]
            with st.expander("Preview cover letter"):
                st.text(cl["text"])
            c1, c2 = st.columns(2)
            c1.download_button("⬇️ Word", data=cl["docx"],
                file_name=f"{slug}_cover_letter.docx", mime=DOCX_MIME,
                key=f"dlcl_w_{job['id']}", use_container_width=True)
            c2.download_button("⬇️ PDF", data=cl["pdf"],
                file_name=f"{slug}_cover_letter.pdf", mime=PDF_MIME,
                key=f"dlcl_p_{job['id']}", use_container_width=True)

        st.markdown("<div style='height:0.4rem'/>", unsafe_allow_html=True)

        # Resume
        if st.button("📄 Generate Resume", key=f"btn_cv_{job['id']}",
                     use_container_width=True):
            with st.spinner("Tailoring resume..."):
                try:
                    from document_builder import build_resume_docx, build_resume_pdf
                    st.session_state[f"cv_data_{job['id']}"] = {
                        "docx": build_resume_docx(job),
                        "pdf":  build_resume_pdf(job),
                    }
                    mark_docs(job["id"])
                except Exception as e:
                    st.error(f"Error: {e}")

        if f"cv_data_{job['id']}" in st.session_state:
            cv = st.session_state[f"cv_data_{job['id']}"]
            c3, c4 = st.columns(2)
            c3.download_button("⬇️ Word", data=cv["docx"],
                file_name=f"{slug}_resume.docx", mime=DOCX_MIME,
                key=f"dlcv_w_{job['id']}", use_container_width=True)
            c4.download_button("⬇️ PDF", data=cv["pdf"],
                file_name=f"{slug}_resume.pdf", mime=PDF_MIME,
                key=f"dlcv_p_{job['id']}", use_container_width=True)


# ── Outlook-style split pane table ───────────────────────────────────────────
def render_table(jobs: list, tab_key: str, is_ignored: bool = False) -> None:
    if not jobs:
        st.info("Nothing here yet.")
        return

    df = to_df(jobs)

    # Use a rotating instance key so the close button can reset the table's
    # selection state by forcing Streamlit to remount the dataframe widget.
    inst_key = f"tbl_inst_{tab_key}"
    tbl_instance = st.session_state.get(inst_key, 0)
    tbl_key = f"tbl_{tab_key}_{tbl_instance}"

    # Outlook split: left = table, right = detail pane (always visible)
    col_table, col_detail = st.columns([3, 2], gap="medium")

    with col_table:
        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                # No explicit widths → Streamlit auto-sizes every column
                "⭐":      st.column_config.TextColumn("⭐"),
                "Score":   st.column_config.TextColumn("Score"),
                "🏆":      st.column_config.TextColumn("🏆"),
                "Role":    st.column_config.TextColumn("Role"),
                "Company": st.column_config.TextColumn("Company"),
                "Posted":  st.column_config.TextColumn("Posted"),
                "Status":  st.column_config.TextColumn("Status"),
            },
            key=tbl_key,
            height=600,
        )
        sel = event.selection.rows

    with col_detail:
        if sel:
            # Close button — rotates the table key so its selection clears
            if st.button("✕ Close", key=f"close_{tab_key}"):
                st.session_state[inst_key] = tbl_instance + 1
                st.rerun()
            detail_panel(jobs[sel[0]], is_ignored=is_ignored)
        else:
            st.markdown(
                '<div class="pane-placeholder">← Select a role to view details</div>',
                unsafe_allow_html=True,
            )


# ── Main ──────────────────────────────────────────────────────────────────────
st.markdown("# 💼 Yang's Job Board")
st.markdown('<p class="sub">AI-qualified banking opportunities · refreshed every 24 hours · '
            'click any row to open the detail pane</p>', unsafe_allow_html=True)

with st.spinner("Loading..."):
    try:
        all_jobs = fetch_jobs()
    except Exception as e:
        st.error(f"Could not connect to Notion: {e}")
        st.stop()

active  = [j for j in all_jobs if j["status"] != "Ignored"]
ignored = [j for j in all_jobs if j["status"] == "Ignored"]

# ── Sidebar (collapsible via the built-in › arrow) ────────────────────────────
with st.sidebar:
    st.markdown("## Filters")

    show_favs = st.toggle("⭐ Favourites only", value=False)

    sel_statuses = st.multiselect(
        "Application status", STATUS_OPTIONS, default=STATUS_OPTIONS,
    )

    score_range = st.slider("Score range", 0, 10, (3, 10))

    st.divider()
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("**How to use**")
    st.markdown(
        "Click any row to open the detail pane on the right. "
        "Click **✕ Close** to dismiss it. "
        "Use the **›** arrow at the top-left of this sidebar to hide it."
    )

# Apply filters
filtered = [
    j for j in active
    if j["status"] in sel_statuses
    and score_range[0] <= j["score"] <= score_range[1]
    and (not show_favs or j["favorite"])
]

# ── Metrics ───────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Active roles",  len(active))
m2.metric("Showing",       len(filtered))
m3.metric("🏆 High match", sum(1 for j in filtered if j.get("match_flag") == "HIGH MATCH"))
m4.metric("📨 Applied",    sum(1 for j in active  if j["status"] == "Applied"))
m5.metric("🗣 Interviews", sum(1 for j in active  if j["status"] == "Interview"))

st.markdown("<div style='margin-top:0.8rem'/>", unsafe_allow_html=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_active, tab_ignored = st.tabs([
    f"Active  ({len(filtered)})",
    f"Ignored  ({len(ignored)})",
])

with tab_active:
    render_table(filtered, "active")

with tab_ignored:
    render_table(ignored, "ignored", is_ignored=True)
