"""
FinGen v2 — Page 1: Upload Documents
Upload annual reports, results PRs, transcripts, DRHP/RHP, Screener xlsx.
Files persist to Storage; documents rows track status.
Supports both direct in-process extraction and background worker queue.
"""

import os
import uuid
import streamlit as st
from core.db.supabase_client import get_service_client
from core.db.repos.company_repo import CompanyRepo
from core.db.repos.document_repo import DocumentRepo
from core.db.repos.job_repo import JobRepo
from core.db.repos.fact_repo import FactRepo
from core.db.repos.review_queue_repo import ReviewQueueRepo
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


supabase = st.session_state.get("supabase")
if supabase is None:
    st.info("ℹ️ Local Mode: files are processed and stored in your local session.")

service_client = get_service_client()
company_repo = CompanyRepo()
document_repo = DocumentRepo()
job_repo = JobRepo()
fact_repo = FactRepo()
review_repo = ReviewQueueRepo()

user_id = (st.session_state.get("user") or {}).get("id", "local-user")

# ── Demo Quick Load ────────────────────────────────────────────────
with st.expander("⚡ Quick Start: Load Sample Data (Tata Steel FY24)", expanded=False):
    st.write("Load pre-verified financial facts for Tata Steel FY24 directly into the session to test reports immediately.")
    if st.button("Load Tata Steel FY24 Sample Data"):
        sample_company = company_repo.create_company(
            user_id=user_id,
            name="Tata Steel Limited",
            ticker="TATASTEEL",
            exchange="NSE",
        )
        sample_company_id = sample_company["id"]
        st.session_state["current_company_id"] = sample_company_id
        st.session_state["company_name"] = "Tata Steel Limited"
        st.session_state["ticker"] = "TATASTEEL"

        # Load facts from fixture CSV
        fixture_path = os.path.join("tests", "fixtures", "tata_steel", "expected_facts.csv")
        if os.path.exists(fixture_path):
            with open(fixture_path, "rb") as f:
                csv_bytes = f.read()
            from core.ingest.parsers import spreadsheet_to_facts
            s_facts = spreadsheet_to_facts(csv_bytes, "expected_facts.csv", as_facts=True, company_id=sample_company_id)
            fact_repo.bulk_upsert_facts(s_facts, sample_company_id, user_id, "demo-doc-1")
            st.success(f"Loaded {len(s_facts)} financial facts for Tata Steel FY24!")
            st.session_state["fiscal_year"] = "FY24"
            st.session_state["doc_type"] = "annual_report"

# ── Company identity ───────────────────────────────────────────────
st.markdown("### Company Details")
c1, c2, c3 = st.columns(3)
company_name = c1.text_input("Company name *", value=st.session_state.get("company_name", ""))
ticker = c2.text_input("Ticker (e.g., TATASTEEL)", value=st.session_state.get("ticker", ""))
exchange = c3.selectbox("Exchange", ["NSE", "BSE", "NYSE", "NASDAQ", "Other"], index=0)

fiscal_year = st.text_input("Fiscal year of latest report (e.g., FY24)", value=st.session_state.get("fiscal_year", "FY24"))
doc_type = st.selectbox("Document type", DOC_TYPES, index=0)

# ── File upload ────────────────────────────────────────────────────
st.markdown("### Upload Documents")
uploaded_files = st.file_uploader(
    "Upload PDFs, Excel, CSV, or text files",
    type=["pdf", "xlsx", "xls", "csv", "txt", "md"],
    accept_multiple_files=True,
)

if uploaded_files:
    for f in uploaded_files:
        st.caption(f"📄 {f.name} — {f.size / 1024:.1f} KB")

extract_now = st.checkbox(
    "Extract immediately (in-process)",
    value=True,
    help="Extracts facts directly without waiting for a background worker thread.",
)

# ── Process ────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns([1, 2])

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
    st.session_state["ticker"] = ticker
    st.session_state["doc_type"] = doc_type
    st.session_state["fiscal_year"] = fiscal_year

    total_facts_extracted = 0

    with st.spinner("Processing documents..."):
        for f in uploaded_files:
            doc_id = str(uuid.uuid4())
            storage_path = parse_storage_path(user_id, doc_id, f.name)
            content_type = _content_type(f.name)
            file_bytes = f.getvalue()

            # Save local copy
            try:
                os.makedirs(os.path.dirname(storage_path), exist_ok=True)
                with open(storage_path, "wb") as out_f:
                    out_f.write(file_bytes)
            except Exception as e:
                st.warning(f"Local file write warning: {e}")

            # Upload to Supabase Storage if service_client available
            if service_client:
                try:
                    service_client.storage.from_("uploads").upload(
                        storage_path, file_bytes, {"content-type": content_type}
                    )
                except Exception as e:
                    st.warning(f"Remote storage upload skipped: {e}")

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

            if extract_now:
                # Direct in-process extraction
                ext = f.name.rsplit(".", 1)[-1].lower()
                extracted_facts = []
                if ext in ("csv", "xlsx", "xls"):
                    from core.ingest.parsers import spreadsheet_to_facts
                    extracted_facts = spreadsheet_to_facts(
                        file_bytes, f.name, as_facts=True, company_id=company_id, document_id=doc["id"]
                    )
                elif ext == "pdf":
                    from core.ingest.parsers import parse_pdf_fast_bytes
                    from core.extract.extractor import Extractor
                    text = parse_pdf_fast_bytes(file_bytes, f.name)
                    ext_result = Extractor().extract_from_text(
                        company_id=company_id,
                        user_id=user_id,
                        document_id=doc["id"],
                        document_type=doc_type,
                        text=text,
                        fiscal_year=fiscal_year,
                    )
                    extracted_facts = ext_result.facts
                    for um in ext_result.unmapped:
                        review_repo.create({
                            "company_id": str(company_id),
                            "user_id": str(user_id),
                            "document_id": str(doc["id"]),
                            "raw_label": um.get("raw_label"),
                            "period": um.get("period"),
                            "value": um.get("value"),
                            "unit": um.get("unit"),
                        })
                else:  # txt, md
                    from core.extract.extractor import Extractor
                    text = file_bytes.decode("utf-8", errors="replace")
                    ext_result = Extractor().extract_from_text(
                        company_id=company_id,
                        user_id=user_id,
                        document_id=doc["id"],
                        document_type=doc_type,
                        text=text,
                        fiscal_year=fiscal_year,
                    )
                    extracted_facts = ext_result.facts

                if extracted_facts:
                    fact_repo.bulk_upsert_facts(extracted_facts, company_id, user_id, doc["id"])
                    total_facts_extracted += len(extracted_facts)

                # Record completed job
                job_repo.create_job(
                    user_id=user_id,
                    kind="extract",
                    payload={"document_id": doc["id"], "company_id": company_id},
                    company_id=company_id,
                )
            else:
                # Queue extraction job for background worker
                job_repo.create_job(
                    user_id=user_id,
                    kind="extract",
                    payload={"document_id": doc["id"], "company_id": company_id},
                    company_id=company_id,
                )

    if extract_now:
        st.success(f"✅ Processed {len(uploaded_files)} file(s). Extracted {total_facts_extracted} facts!")
    else:
        st.success(f"Uploaded {len(uploaded_files)} file(s). Extraction jobs queued.")
        st.info("Jobs are processed by the background worker.")

st.markdown("---")
if st.session_state.get("current_company_id"):
    c_left, c_right = st.columns([2, 1])
    c_left.write(f"Active Company: **{st.session_state.get('company_name', 'Selected')}** (`{st.session_state.get('current_company_id')}`)")
    if c_right.button("Continue to Configure Report →", type="primary"):
        st.switch_page("pages/2_Configure.py")
