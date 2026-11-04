"""
FinGen v2 — Page 2: Configure Report
Pick report type, audience, tone, privacy masking, citation format.
"""

import streamlit as st

st.set_page_config(page_title="Configure | FinGen", layout="wide")
st.title("2. Configure Report")

REPORT_TYPES = [
    ("company_analysis", "Company Analysis", "Growth, margins, ratios, DuPont, segment mix"),
    ("equity_research", "Equity Research", "Summary, rating, thesis, valuation, risks, catalysts"),
    ("investment_research", "Investment Research", "Thesis, bull/base/bear, risk/reward"),
    ("valuation", "Valuation", "DCF, multiples, football field, sensitivity"),
    ("financial_forecast", "Financial Forecast / Projection", "3-5yr projected IS/BS/CF, scenario table"),
    ("credit_analysis", "Credit Analysis", "Leverage, ICR/DSCR, liquidity, Altman Z, internal rating"),
    ("risk_analysis", "Risk Analysis", "Financial/operational/market risk flags, volatility, sensitivity"),
    ("due_diligence", "Due Diligence", "Red-flag checklist: related-party, contingent liabilities, auditor notes, litigation"),
    ("industry_analysis", "Industry Analysis", "Market size/growth, peer benchmarking, concentration"),
]

st.markdown("### Report Type")
report_choice = st.radio(
    "Select report",
    [f"{name} — {desc}" for _, name, desc in REPORT_TYPES],
    index=0,
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

st.markdown("---")
if st.button("Continue to Data Review →", type="primary"):
    if not st.session_state.get("current_company_id"):
        st.error("No company in session. Upload documents first.")
    else:
        st.switch_page("pages/3_Review_Data.py")
