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

user_id = (st.session_state.get("user") or {}).get("id", "local-user")
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

DEFAULT_DRIVER_VALUES = {
    "base": {
        "revenue_growth": 0.10,
        "ebitda_margin": 0.18,
        "da_pct_revenue": 0.04,
        "capex_pct_revenue": 0.05,
        "tax_rate": 0.25,
        "finance_costs_pct_debt": 0.08,
        "wc_pct_revenue_change": 0.10,
        "wacc": 0.11,
        "terminal_growth_rate": 0.04,
        "exit_multiple": 10.0,
    },
    "bull": {
        "revenue_growth": 0.15,
        "ebitda_margin": 0.22,
        "da_pct_revenue": 0.04,
        "capex_pct_revenue": 0.06,
        "tax_rate": 0.25,
        "finance_costs_pct_debt": 0.07,
        "wc_pct_revenue_change": 0.08,
        "wacc": 0.10,
        "terminal_growth_rate": 0.05,
        "exit_multiple": 12.0,
    },
    "bear": {
        "revenue_growth": 0.05,
        "ebitda_margin": 0.12,
        "da_pct_revenue": 0.05,
        "capex_pct_revenue": 0.04,
        "tax_rate": 0.25,
        "finance_costs_pct_debt": 0.09,
        "wc_pct_revenue_change": 0.12,
        "wacc": 0.12,
        "terminal_growth_rate": 0.03,
        "exit_multiple": 8.0,
    },
}

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
            if default is None:
                default = DEFAULT_DRIVER_VALUES.get(scenario, {}).get(driver, 0.0)

            value = cols[1].number_input(
                f"{label} ({scenario})",
                value=float(default),
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


def _save_current_assumptions():
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
    return len(by_scenario)


st.markdown("---")
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("← Back to Review Data"):
        st.switch_page("pages/3_Review_Data.py")
with col2:
    if st.button("Save Assumptions"):
        n = _save_current_assumptions()
        st.success(f"Saved assumptions for {n} scenario(s).")
with col3:
    if st.button("Generate Report →", type="primary", use_container_width=True):
        _save_current_assumptions()
        st.switch_page("pages/5_Generate.py")
