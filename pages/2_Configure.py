"""
FinGen v2 — Page 2: Configure Report
Pick report type, audience, tone, privacy masking, citation format.
Supports all 10 FinGen report templates.
"""

import streamlit as st

st.set_page_config(page_title="Configure | FinGen", layout="wide")
st.title("2. Configure Report")

REPORT_TYPES = [
    ("company_analysis", "Company Analysis", "Growth, margins, ratios, DuPont, segment mix"),
    ("equity_research", "Equity Research", "Summary, rating, thesis, valuation, risks, catalysts"),
    ("valuation", "Valuation", "DCF, multiples, football field, sensitivity"),
    ("financial_forecast", "Financial Forecast / Projection", "3-5yr projected IS/BS/CF, scenario table"),
    ("investment_research", "Investment Research", "Thesis, bull/base/bear, risk/reward"),
    ("credit_analysis", "Credit Analysis", "Leverage, ICR/DSCR, liquidity, Altman Z, internal rating"),
    ("risk_analysis", "Risk Analysis", "Financial/operational/market risk flags, volatility, sensitivity"),
    ("due_diligence", "Due Diligence", "Red-flag checklist: related-party, contingent liabilities, auditor notes, litigation"),
    ("industry_analysis", "Industry Analysis", "Market size/growth, peer benchmarking, concentration"),
    ("portfolio_performance", "Portfolio Performance", "XIRR, sector allocation, Brinson attribution, drawdown analysis"),
]

st.markdown("### Report Type")
current_report = st.session_state.get("current_report_type") or (st.session_state.get("ui_config") or {}).get("report_type", "company_analysis")
default_idx = next((i for i, (code, _, _) in enumerate(REPORT_TYPES) if code == current_report), 0)

report_choice = st.radio(
    "Select report",
    [f"{name} — {desc}" for _, name, desc in REPORT_TYPES],
    index=default_idx,
)
report_type = REPORT_TYPES[[f"{n} — {d}" for _, n, d in REPORT_TYPES].index(report_choice)][0]

st.markdown("### Output Settings")
col1, col2 = st.columns(2)
with col1:
    audience = st.selectbox(
        "Audience",
        ["Investment Analyst (MBA-level)", "C-Suite Executive", "Credit Officer", "Equity Research Associate", "General (accessible)"],
        index=0,
    )
    tone = st.selectbox(
        "Tone",
        ["Objective and analytical", "Concise and bullet-heavy", "Critical and diagnostic", "Persuasive and forward-looking"],
        index=0,
    )
with col2:
    citation = st.selectbox(
        "Citation format",
        ["Financial (Source: Company AR FY24, p.42)", "Inline numeric references", "None"],
        index=0,
    )
    privacy_masking = st.toggle(
        "Data privacy masking",
        value=False,
        help="Replace exact figures with directional language in the output.",
    )

ui_config = {
    "report_type": report_type,
    "audience": audience,
    "tone": tone,
    "citation_format": citation,
    "privacy_masking": privacy_masking,
}
st.session_state["ui_config"] = ui_config
st.session_state["current_report_type"] = report_type

st.markdown("---")
c_back, c_next = st.columns([1, 3])
with c_back:
    if st.button("← Back to Upload"):
        st.switch_page("pages/1_Upload.py")
with c_next:
    if st.button("Continue to Data Review →", type="primary"):
        if not st.session_state.get("current_company_id"):
            st.error("No company in session. Upload documents first.")
        else:
            st.switch_page("pages/3_Review_Data.py")
