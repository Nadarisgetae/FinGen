"""
FinGen v2 — Page 5: Generate Report
Runs generation as a job; polls every 2s for progress.
"""

import time
import streamlit as st
from core.db.repos.job_repo import JobRepo
from core.db.repos.report_repo import ReportRepo
from core.generate.runner import list_templates

st.set_page_config(page_title="Generate | FinGen", layout="wide")
st.title("5. Generate Report")

company_id = st.session_state.get("current_company_id")
ui_config = st.session_state.get("ui_config") or {}
report_type = ui_config.get("report_type", "company_analysis")

if not company_id:
    st.error("No company in session. Upload documents first.")
    st.stop()

user_id = st.session_state["user"]["id"]
job_repo = JobRepo()
report_repo = ReportRepo()

st.markdown(f"### Report type: **{report_type.replace('_', ' ').title()}**")

# ── Check for existing jobs ────────────────────────────────────────
jobs = job_repo.get_by_user(user_id, status=None, limit=20)
generate_jobs = [j for j in jobs if j["kind"] == "generate_report"]

if generate_jobs:
    latest_job = generate_jobs[0]
    status = latest_job["status"]

    if status in ("pending", "running"):
        st.markdown("### ⏳ Generating...")
        progress = latest_job.get("progress") or 0
        st.progress(progress / 100, text=f"{progress}%")

        # Poll loop (client-side)
        placeholder = st.empty()
        for _ in range(150):  # up to 5 min
            time.sleep(2)
            job = job_repo.get_by_id(latest_job["id"])
            if job:
                progress = job.get("progress") or 0
                placeholder.progress(progress / 100, text=f"{progress}%")
                if job["status"] in ("completed", "failed"):
                    break
        st.rerun()

    elif status == "completed":
        result = latest_job.get("result") or {}
        report_id = result.get("report_id")
        st.success("✅ Report generated!")

        if report_id:
            report = report_repo.get_by_id(report_id)
            if report:
                with st.expander("📄 View report", expanded=True):
                    st.markdown(report["markdown"])

                verification = result.get("verification") or {}
                if verification:
                    with st.expander(f"🛡️ Verification ({verification.get('error_count', 0)} errors, {verification.get('warning_count', 0)} warnings)"):
                        for flag in verification.get("flags", []):
                            severity = "🔴" if flag.get("severity") == "error" else "🟡"
                            st.markdown(
                                f"{severity} **{flag.get('flag_type')}** — `{flag.get('text_value')}`  \n"
                                f"{flag.get('message')}  \n"
                                f"*Location:* ...{str(flag.get('location'))[:120]}..."
                            )

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        if c1.button("← Back to Assumptions"):
            st.switch_page("pages/4_Thesis_Assumptions.py")
        if c2.button("Regenerate", type="primary"):
            _queue_generation(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
        if c3.button("Go to Library"):
            st.switch_page("pages/6_Library.py")

    else:  # failed
        st.error(f"❌ Generation failed: {latest_job.get('error_message', 'Unknown error')}")
        if st.button("Retry", type="primary"):
            _queue_generation(job_repo, user_id, company_id, report_type, ui_config)
            st.rerun()
else:
    st.markdown("No generation job yet. Start one below.")

if not generate_jobs or generate_jobs[0]["status"] in ("completed", "failed"):
    st.markdown("---")
    if st.button("🚀 Generate Report", type="primary", use_container_width=True):
        _queue_generation(job_repo, user_id, company_id, report_type, ui_config)
        st.rerun()


def _queue_generation(job_repo, user_id, company_id, report_type, ui_config):
    job_repo.create_job(
        user_id=user_id,
        kind="generate_report",
        payload={
            "company_id": company_id,
            "report_type": report_type,
            "ui_config": ui_config,
        },
        company_id=company_id,
    )
