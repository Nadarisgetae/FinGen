"""
FinGen v2 — Page 5: Generate Report
Runs report generation directly or as a background job.
Displays real-time verification metrics and downloadable outputs.
"""

import time
import streamlit as st
from core.db.repos.job_repo import JobRepo
from core.db.repos.report_repo import ReportRepo
from core.export.markdown_to_docx import markdown_to_docx

st.set_page_config(page_title="Generate | FinGen", layout="wide")
st.title("5. Generate Report")

company_id = st.session_state.get("current_company_id")
ui_config = st.session_state.get("ui_config") or {}
report_type = ui_config.get("report_type") or st.session_state.get("current_report_type", "company_analysis")

if not company_id:
    st.error("No company in session. Upload documents first.")
    if st.button("← Go to Upload Page"):
        st.switch_page("pages/1_Upload.py")
    st.stop()

user_id = st.session_state.get("user", {}).get("id", "local-user")
job_repo = JobRepo()
report_repo = ReportRepo()

st.markdown(f"### Active Report: **{report_type.replace('_', ' ').title()}**")
company_name = st.session_state.get("company_name", "Selected Company")
st.caption(f"Target: **{company_name}** | Audience: {ui_config.get('audience', 'Investment Analyst')} | Tone: {ui_config.get('tone', 'Objective and analytical')}")

def _generate_report_now(job_repo, user_id, company_id, report_type, ui_config):
    job = job_repo.create_job(
        user_id=user_id,
        kind="generate_report",
        payload={
            "company_id": company_id,
            "report_type": report_type,
            "ui_config": ui_config,
        },
        company_id=company_id,
    )
    job_repo.update(job["id"], {"status": "running", "started_at": "now()"})
    from core.jobs.worker import JobWorker
    worker = JobWorker(user_id)
    worker._process_job(job)
    return job["id"]

def _queue_generation(job_repo, user_id, company_id, report_type, ui_config):
    return job_repo.create_job(
        user_id=user_id,
        kind="generate_report",
        payload={
            "company_id": company_id,
            "report_type": report_type,
            "ui_config": ui_config,
        },
        company_id=company_id,
    )

# ── Check for existing jobs ────────────────────────────────────────
jobs = job_repo.get_by_user(user_id, status=None, limit=20)
generate_jobs = [j for j in jobs if j.get("kind") == "generate_report"]

if generate_jobs:
    latest_job = generate_jobs[0]
    status = latest_job.get("status")

    if status in ("pending", "running"):
        st.markdown("### ⏳ Generating Report...")
        progress = latest_job.get("progress") or 0
        pbar = st.progress(progress / 100, text=f"{progress}%")

        # Poll loop (client-side)
        for _ in range(15):
            time.sleep(1)
            updated_job = job_repo.get_by_id(latest_job["id"])
            if updated_job:
                progress = updated_job.get("progress") or 0
                pbar.progress(progress / 100, text=f"{progress}%")
                if updated_job["status"] in ("completed", "failed"):
                    break
        st.rerun()

    elif status == "completed":
        result = latest_job.get("result") or {}
        report_id = result.get("report_id")
        st.success("✅ Report generated successfully!")

        if report_id:
            report = report_repo.get_by_id(report_id)
            if report:
                st.session_state["latest_report_id"] = report["id"]
                markdown_content = report.get("markdown", "")

                # Export action bar
                e1, e2, e3 = st.columns([1, 1, 2])
                with e1:
                    try:
                        docx_bytes = markdown_to_docx(markdown_content, title=report.get("title", report_type))
                        st.download_button(
                            "📥 Download DOCX",
                            data=docx_bytes,
                            file_name=f"{report_type}_report.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True,
                        )
                    except Exception as e:
                        st.warning(f"DOCX export: {e}")
                with e2:
                    st.download_button(
                        "📄 Download Markdown",
                        data=markdown_content.encode("utf-8"),
                        file_name=f"{report_type}_report.md",
                        mime="text/markdown",
                        use_container_width=True,
                    )
                with e3:
                    if st.button("📚 View in Report Library →", use_container_width=True):
                        st.switch_page("pages/6_Library.py")

                # Verification flags drawer
                verification = result.get("verification") or {}
                if verification:
                    err_cnt = verification.get("error_count", 0)
                    warn_cnt = verification.get("warning_count", 0)
                    shield_icon = "🟢" if err_cnt == 0 else "🔴"
                    with st.expander(f"{shield_icon} Verifier Results: {err_cnt} errors, {warn_cnt} warnings", expanded=(err_cnt > 0)):
                        if err_cnt == 0 and warn_cnt == 0:
                            st.write("✅ All facts, calculations, and citations verified against source data.")
                        for flag in verification.get("flags", []):
                            severity = "🔴" if flag.get("severity") == "error" else "🟡"
                            st.markdown(
                                f"{severity} **{flag.get('flag_type')}** — `{flag.get('text_value')}`  \n"
                                f"{flag.get('message')}  \n"
                                f"*Location:* ...{str(flag.get('location'))[:120]}..."
                            )

                # Report Preview
                with st.expander("📄 Report Preview", expanded=True):
                    st.markdown(markdown_content)

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        if c1.button("← Back to Assumptions"):
            st.switch_page("pages/4_Thesis_Assumptions.py")
        if c2.button("🔄 Regenerate Report", type="primary"):
            with st.spinner("Generating financial report..."):
                _generate_report_now(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
        if c3.button("Go to Library →"):
            st.switch_page("pages/6_Library.py")

    else:  # failed
        st.error(f"❌ Generation failed: {latest_job.get('error_message', 'Unknown error')}")
        if st.button("Retry Generation", type="primary"):
            with st.spinner("Retrying report generation..."):
                _generate_report_now(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
else:
    st.markdown("Ready to generate your report with deterministic financial analytics.")
    sync_mode = st.checkbox("Run directly in this session", value=True, help="Executes report generation immediately in-process.")
    
    st.markdown("---")
    if st.button("🚀 Generate Report", type="primary", use_container_width=True):
        if sync_mode:
            with st.spinner("Calculating deterministic analytics, synthesizing narrative, and verifying numbers..."):
                _generate_report_now(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
        else:
            _queue_generation(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
