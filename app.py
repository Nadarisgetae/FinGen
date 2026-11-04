"""
FinGen v2 — Streamlit Entry Point

Run: streamlit run app.py
"""

import streamlit as st

from core.db.supabase_client import client_from_secrets


def main():
    st.set_page_config(
        page_title="FinGen — Financial Research Engine",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Supabase connection ──────────────────────────────────────────
    if "supabase" not in st.session_state:
        try:
            st.session_state["supabase"] = client_from_secrets(getattr(st, "secrets", None))
        except Exception:
            st.session_state["supabase"] = None

    if st.session_state["supabase"] is None:
        st.sidebar.info("💡 Local Demo Mode (Offline In-Memory)")

    # ── Sidebar nav ──────────────────────────────────────────────────
    st.sidebar.title("📊 FinGen")
    st.sidebar.caption("Financial Research Engine")
    st.sidebar.divider()

    pages = {
        "1. Upload Documents": "pages/1_Upload.py",
        "2. Configure": "pages/2_Configure.py",
        "3. Review Data": "pages/3_Review_Data.py",
        "4. Thesis & Assumptions": "pages/4_Thesis_Assumptions.py",
        "5. Generate Report": "pages/5_Generate.py",
        "6. Library": "pages/6_Library.py",
    }

    choice = st.sidebar.radio("Navigate", list(pages.keys()))

    # ── Session state init ───────────────────────────────────────────
    if "user" not in st.session_state or st.session_state["user"] is None:
        st.session_state["user"] = {"id": "local-user", "email": "local@dev"}
    if "ui_config" not in st.session_state or st.session_state["ui_config"] is None:
        st.session_state["ui_config"] = {"report_type": "company_analysis"}
    for key in ("current_company_id", "current_report_type"):
        if key not in st.session_state:
            st.session_state[key] = None

    # ── Page router ──────────────────────────────────────────────────
    st.switch_page(pages[choice])


if __name__ == "__main__":
    main()