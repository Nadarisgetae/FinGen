"""
FinGen v2 — Page 4: Thesis & Assumptions
Bull/base/bear driver grid with rationale and source.
Saves to the assumptions table.
"""

import streamlit as st
from core.db.repos.assumption_repo import AssumptionRepo

st.set_page_config(page_title="Thesis & Assumptions | FinGen", layout="wide")
st.title("4. Thesis & Assumptions")

company_id = st.session_state.get("current_company_id")
if not company_id:
    st.error("No company in session. Upload documents first.")
    st.stop()

user_id = st.session_state["user"]["id"]
repo = AssumptionRepo()

DRIVERS = [
    ("revenue_growth", "Revenue growth", "percentage"),
    ("ebitda_margin", "EBITDA margin", "percentage"),
    ("da_pct_revenue", "D&A (% of revenue)", "percentage"),
    ("capex_pct_revenue", "Capex (% of revenue)", "percentage"),
    ("tax_rate", "Tax rate", "percentage"),
    ("finance_costs_pct_debt", "Finance costs (% of debt)", "percentage"),
    ("wc_pct_revenue_change", "WC change (% of Δrevenue)", "percentage"),
    ("wacc", "WACC", "percentage"),
    ("terminal_growth_rate", "Terminal growth rate", "percentage"),
    ("exit_multiple", "Exit multiple (EV/EBITDA)", "times"),
]

SCENARIOS = ["bull", "base", "bear"]
PROJECTION_YEARS = ["FY26", "FY27", "FY28", "FY29", "FY30"]

st.markdown("### Driver Assumptions")
st.caption("Enter per-scenario values. Every assumption is stored with your rationale and source.")

# Load existing assumptions
existing = repo.get_for_forecast(company_id, SCENARIOS)

for scenario in SCENARIOS:
    with st.expander(f"**{scenario.upper()} case**", expanded=(scenario == "base")):
        for driver, label, unit in DRIVERS:
            cols = st.columns([2, 1, 1, 3])
            cols[0].markdown(f"**{label}**")
            default = existing.get(scenario, {}).get(driver, {}).get(PROJECTION_YEARS[0], {}).get("value", None)
            value = cols[1].number_input(
                f"{label} ({scenario})",
                value=default if default is not None else 0.0,
                format="%.4f",
                key=f"{scenario}_{driver}_val",
                label_visibility="collapsed",
            )
            source = cols[2].selectbox(
                "Source",
                ["analyst_estimate", "historical_avg", "management_guidance", "document", "model_default"],
                index=0,
                key=f"{scenario}_{driver}_src",
                label_visibility="collapsed",
            )
            rationale = cols[3].text_input(
                "Rationale",
                value="",
                key=f"{scenario}_{driver}_rat",
                label_visibility="collapsed",
                placeholder="Why this value?",
            )
            # Store in session state for save
            st.session_state.setdefault("assumption_buffer", {})
            st.session_state["assumption_buffer"][f"{scenario}|{driver}"] = {
                "value": value,
                "unit": unit,
                "source": source,
                "rationale": rationale,
            }

# Projection horizon
st.markdown("### Projection Horizon")
projection_years = st.number_input("Years to project", min_value=1, max_value=10, value=5)

st.markdown("---")
col1, col2 = st.columns([1, 3])
with col1:
    if st.button("← Back to Review Data"):
        st.switch_page("pages/3_Review_Data.py")
with col2:
    if st.button("Save Assumptions", type="primary"):
        buffer = st.session_state.get("assumption_buffer", {})
        by_scenario = {}
        for key, val in buffer.items():
            scenario, driver = key.split("|")
            by_scenario.setdefault(scenario, []).append({
                "driver": driver,
                "period": "projection",
                "value": val["value"],
                "unit": val["unit"],
                "rationale": val["rationale"],
                "is_manual": True,
            })
        for scenario, assumptions in by_scenario.items():
            repo.upsert_scenario(company_id, user_id, scenario, assumptions)
        st.success(f"Saved assumptions for {len(by_scenario)} scenario(s).")

    if st.button("Generate Report →", type="primary"):
        st.switch_page("pages/5_Generate.py")
