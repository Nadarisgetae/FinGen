"""
FinGen v2 — Page 6: Library
Past reports with version history, view/download/regenerate/delete.
Supports all 10 report types, DOCX, Markdown, and PDF downloads.
"""

import streamlit as st
from core.db.repos.report_repo import ReportRepo
from core.export.markdown_to_docx import markdown_to_docx
from core.export.markdown_to_pdf import markdown_to_pdf

st.set_page_config(page_title="Library | FinGen", layout="wide")
st.title("6. Report Library")

company_id = st.session_state.get("current_company_id")
user_id = st.session_state.get("user", {}).get("id", "local-user")
report_repo = ReportRepo()

REPORT_FILTER_OPTIONS = [
    "all",
    "company_analysis",
    "equity_research",
    "valuation",
    "financial_forecast",
    "investment_research",
    "credit_analysis",
    "risk_analysis",
    "due_diligence",
    "industry_analysis",
    "portfolio_performance",
]

# ── Filter ─────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    report_filter = st.selectbox(
        "Filter by report type",
        REPORT_FILTER_OPTIONS,
        index=0,
    )
with col2:
    if st.button("↻ Refresh Library"):
        st.rerun()

# ── List reports ───────────────────────────────────────────────────
reports = []
if company_id:
    reports = report_repo.list_by_company(company_id, report_filter if report_filter != "all" else None)

# Fallback: if no reports found for this company_id, list by user_id
if not reports:
    filter_dict = {"user_id": str(user_id)}
    if report_filter != "all":
        filter_dict["report_type"] = report_filter
    reports = report_repo.list(filter_dict, order_by="created_at", desc=True, limit=50)

if not reports:
    st.info("No reports found yet. Generate a report from the wizard to see it listed here.")
    if st.button("← Go to Generate Report"):
        st.switch_page("pages/5_Generate.py")
    st.stop()

st.markdown(f"Found **{len(reports)}** report(s):")

for report in reports:
    r_title = report.get("title") or report.get("report_type", "report").replace("_", " ").title()
    r_version = report.get("version", 1)
    r_created = str(report.get("created_at", ""))[:16].replace("T", " ")
    r_markdown = report.get("markdown", "")

    with st.expander(f"📄 **{r_title}** (v{r_version}) — {r_created}"):
        st.caption(f"Status: `{report.get('status', 'completed')}` | Type: `{report.get('report_type')}` | ID: `{report.get('id')}`")

        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])

        # 1. View
        with c1:
            if st.button("View", key=f"view_{report['id']}"):
                st.session_state["view_report"] = report["id"]
                st.rerun()

        # 2. Download DOCX
        with c2:
            try:
                docx_bytes = markdown_to_docx(r_markdown, title=r_title)
                st.download_button(
                    "📥 DOCX",
                    data=docx_bytes,
                    file_name=f"{report.get('report_type', 'report')}_v{r_version}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_docx_{report['id']}",
                    use_container_width=True,
                )
            except Exception as e:
                st.caption(f"DOCX err: {e}")

        # 3. Download Markdown / PDF
        with c3:
            st.download_button(
                "📄 Markdown",
                data=r_markdown.encode("utf-8"),
                file_name=f"{report.get('report_type', 'report')}_v{r_version}.md",
                mime="text/markdown",
                key=f"dl_md_{report['id']}",
                use_container_width=True,
            )

        # 4. Delete
        with c4:
            if st.button("🗑️ Delete", key=f"del_{report['id']}", type="secondary"):
                report_repo.delete(report["id"])
                st.success("Deleted report.")
                st.rerun()

# ── Inline view ────────────────────────────────────────────────────
if st.session_state.get("view_report"):
    viewed = report_repo.get_by_id(st.session_state["view_report"])
    if viewed:
        st.markdown("---")
        st.markdown(f"### 📄 Viewing: {viewed.get('title') or viewed.get('report_type')}")
        st.markdown(viewed.get("markdown", ""))
        if st.button("Close Viewer"):
            st.session_state["view_report"] = None
            st.rerun()

st.markdown("---")
if st.button("← Back to Generate"):
    st.switch_page("pages/5_Generate.py")
