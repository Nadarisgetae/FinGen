"""
FinGen v2 — Page 1: Upload Documents
Upload annual reports, results PRs, transcripts, DRHP/RHP, Screener xlsx.
Files persist to Supabase Storage; documents rows track status.
"""

import uuid
import streamlit as st
from core.db.supabase_client import get_service_client
from core.db.repos.company_repo import CompanyRepo
from core.db.repos.document_repo import DocumentRepo
from core.db.repos.job_repo import JobRepo
from core.ingest.storage import parse_storage_path

st.set_page_config(page_title="Upload | FinGen", layout="wide")
st.title("1. Upload Documents")

DOC_TYPES = [
    "annual_report",
    "results_pr",
    "earnings_transcript",
    "dhrp_rhp",
    "screener_xlsx",
    "industry_report",
    "other",
]

supabase = st.session_state.get("supabase")
if supabase is None:
    st.error("Supabase not configured. Check st.secrets.")
    st.stop()

service_client = get_service_client()
company_repo = CompanyRepo()
document_repo = DocumentRepo()
job_repo = JobRepo()

user_id = st.session_state["user"]["id"]

# ── Company identity ───────────────────────────────────────────────
st.markdown("### Company")
c1, c2, c3 = st.columns(3)
company_name = c1.text_input("Company name *", value=st.session_state.get("company_name", ""))
ticker = c2.text_input("Ticker (e.g., TATASTEEL)", value=st.session_state.get("ticker", ""))
exchange = c3.selectbox("Exchange", ["NSE", "BSE", "NYSE", "NASDAQ", "Other"], index=0)

fiscal_year = st.text_input("Fiscal year of latest report (e.g., FY24)", value="FY24")
doc_type = st.selectbox("Document type", DOC_TYPES, index=0)

# ── File upload ────────────────────────────────────────────────────
st.markdown("### Files")
uploaded_files = st.file_uploader(
    "Upload PDFs, Excel, or text files",
    type=["pdf", "xlsx", "xls", "csv", "txt", "md"],
    accept_multiple_files=True,
)

if uploaded_files:
    for f in uploaded_files:
        st.caption(f"📄 {f.name} — {f.size / 1024:.0f} KB")

# ── Process ────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns([1, 3])

with col1:
    process = st.button("Extract & Validate", type="primary", use_container_width=True)

if process:
    if not company_name:
        st.error("Company name is required.")
        st.stop()
    if not uploaded_files:
        st.error("Upload at least one document.")
        st.stop()

    # Create or reuse company
    existing = company_repo.get_by_ticker(user_id, ticker) if ticker else None
    if existing:
        company_id = existing["id"]
    else:
        company = company_repo.create_company(
            user_id=user_id,
            name=company_name,
            ticker=ticker or None,
            exchange=exchange if exchange != "Other" else None,
        )
        company_id = company["id"]

    st.session_state["current_company_id"] = company_id
    st.session_state["company_name"] = company_name

    # Upload each file to Storage + create documents rows + queue extraction jobs
    for f in uploaded_files:
        doc_id = str(uuid.uuid4())
        storage_path = parse_storage_path(user_id, doc_id, f.name)
        content_type = _content_type(f.name)

        try:
            service_client.storage.from_("uploads").upload(
                storage_path, f.getvalue(), {"content-type": content_type}
            )
        except Exception as e:
            st.error(f"Upload failed for {f.name}: {e}")
            continue

        doc = document_repo.create_document(
            company_id=company_id,
            user_id=user_id,
            type=doc_type,
            fiscal_year=fiscal_year,
            storage_path=storage_path,
            file_name=f.name,
            file_size=f.size,
            mime_type=content_type,
        )

        # Queue extraction job (processed by JobWorker)
        job_repo.create_job(
            user_id=user_id,
            kind="extract",
            payload={
                "document_id": doc["id"],
                "company_id": company_id,
            },
            company_id=company_id,
        )

    st.success(f"Uploaded {len(uploaded_files)} file(s) to Supabase. Extraction jobs queued.")
    st.info("Jobs are processed by the background worker. Go to **Review Data** to check status.")
    st.session_state["doc_type"] = doc_type
    st.session_state["fiscal_year"] = fiscal_year


def _content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "csv": "text/csv",
        "txt": "text/plain",
        "md": "text/markdown",
    }.get(ext, "application/octet-stream")