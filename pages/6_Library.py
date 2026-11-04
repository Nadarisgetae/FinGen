"""
FinGen v2 — Page 6: Library
Past reports with version history, view/download/regenerate/delete.
"""

import streamlit as st
from core.db.repos.report_repo import ReportRepo
from core.db.supabase_client import get_service_client
from core.export.markdown_to_docx import markdown_to_docx
from core.export.markdown_to_pdf import markdown_to_pdf

st.set_page_config(page_title="Library | FinGen", layout="wide")
st.title("6. Report Library")

company_id = st.session_state.get("current_company_id")
user_id = st.session_state["user"]["id"]
report_repo = ReportRepo()
supabase = get_service_client()

# ── Filter ─────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    report_filter = st.selectbox(
        "Report type",
        ["all", "company_analysis", "equity_research", "investment_research", "valuation",
         "financial_forecast", "credit_analysis", "risk_analysis", "due_diligence", "industry_analysis"],
        index=0,
    )
with col2:
    refresh = st.button("↻ Refresh")

if refresh:
    st.rerun()

# ── List reports ───────────────────────────────────────────────────
if company_id:
    reports = report_repo.list_by_company(company_id, report_filter if report_filter != "all" else None)
else:
    reports = []

if not reports:
    st.info("No reports yet. Generate one from the wizard.")
    st.stop()

for report in reports:
    with st.expander(f"📄 **{report['title'] or report['type']}** — v{report['version']} — {str(report['created_at'])[:16].replace('T', ' ')}"):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])

        # View
        if c1.button("View", key=f"view_{report['id']}"):
            st.session_state["view_report"] = report["id"]
            st.rerun()

        # Download docx
        if c2.button("Download DOCX", key=f"docx_{report['id']}"):
            docx_bytes = markdown_to_docx(report["markdown"], title=report["title"])
            st.download_button(
                "Click to download",
                data=docx_bytes,
                file_name=f"{report['type']}_v{report['version']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"dl_docx_{report['id']}",
            )

        # Download PDF
        if c3.button("Download PDF", key=f"pdf_{report['id']}"):
            try:
                pdf_bytes = markdown_to_pdf(report["markdown"])
                st.download_button(
                    "Click to download",
                    data=pdf_bytes,
                    file_name=f"{report['type']}_v{report['version']}.pdf",
                    mime="application/pdf",
                    key=f"dl_pdf_{report['id']}",
                )
            except Exception as e:
                st.error(f"PDF export unavailable: {e}")

        # Delete
        if c4.button("Delete", key=f"del_{report['id']}"):
            report_repo.delete(report["id"])
            st.rerun()

        # Verification summary
        st.caption(f"Status: {report['status']} | Type: {report['type']}")

# ── Inline view ────────────────────────────────────────────────────
if st.session_state.get("view_report"):
    report = report_repo.get_by_id(st.session_state["view_report"])
    if report:
        st.markdown("---")
        st.markdown(report["markdown"])
        if st.button("Close view"):
            st.session_state["view_report"] = None
            st.rerun()

st.markdown("---")
if st.button("← Back to Generate"):
    st.switch_page("pages/5_Generate.py")
