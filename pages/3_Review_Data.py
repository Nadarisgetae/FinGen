"""
FinGen v2 — Page 3: Review Data
Validation results + editable fact grid (st.data_editor).
Pipeline is BLOCKED until zero blocking errors.
"""

import streamlit as st
from core.db.repos.fact_repo import FactRepo
from core.db.repos.review_queue_repo import ReviewQueueRepo
from core.db.repos.job_repo import JobRepo
from core.db.repos.document_repo import DocumentRepo
from core.validate import Validator
from core.schema import Fact

st.set_page_config(page_title="Review Data | FinGen", layout="wide")
st.title("3. Review Data")

company_id = st.session_state.get("current_company_id")
if not company_id:
    st.error("No company in session. Upload documents first.")
    st.stop()

user_id = st.session_state["user"]["id"]
fact_repo = FactRepo()
review_repo = ReviewQueueRepo()
job_repo = JobRepo()
document_repo = DocumentRepo()

# ── Job status ─────────────────────────────────────────────────────
jobs = job_repo.get_by_user(user_id, status=None, limit=10)
active_jobs = [j for j in jobs if j["status"] in ("pending", "running")]
if active_jobs:
    st.warning(f"⏳ {len(active_jobs)} extraction job(s) still processing. Refresh to update.")
    if st.button("Refresh status"):
        st.rerun()

# ── Load facts ─────────────────────────────────────────────────────
facts_data = fact_repo.get_by_company_period(company_id=company_id)

if not facts_data:
    st.info("No facts extracted yet. Wait for extraction jobs to complete, then refresh.")
    st.stop()

# ── Validation ─────────────────────────────────────────────────────
facts = _facts_from_rows(facts_data)
validation = Validator(facts).validate()

if validation.blocking:
    st.error(f"🚫 {len(validation.blocking)} blocking validation error(s) — generation is blocked until fixed:")
    for b in validation.blocking:
        st.markdown(f"- **{b}**")
else:
    st.success("✅ All validation checks passed. You can proceed to generation.")

if validation.warnings:
    with st.expander(f"⚠️ {len(validation.warnings)} warnings", expanded=False):
        for w in validation.warnings:
            st.markdown(f"- {w}")

# ── Editable fact grid ─────────────────────────────────────────────
st.markdown("### Fact Grid (editable)")
st.caption("Edit values directly. Changes are saved with edited_by_user=true and confidence=1.0.")

periods = sorted({f["period"] for f in facts_data})
statements = ["IS", "BS", "CF"]

for statement in statements:
    stmt_facts = [f for f in facts_data if f["statement"] == statement]
    if not stmt_facts:
        continue

    line_items = sorted({f["line_item"] for f in stmt_facts})
    if not line_items:
        continue

    st.markdown(f"#### {statement}")

    # Build grid: rows = line items, cols = periods
    grid = []
    for li in line_items:
        row = {"line_item": li}
        for period in periods:
            match = next(
                (f for f in stmt_facts if f["line_item"] == li and f["period"] == period),
                None,
            )
            row[period] = match["value"] if match else None
        grid.append(row)

    edited_grid = st.data_editor(
        grid,
        key=f"grid_{statement}",
        column_config={
            "line_item": st.column_config.TextColumn("Line Item", width="medium"),
            **{p: st.column_config.NumberColumn(p, format="%.2f") for p in periods},
        },
        use_container_width=True,
        hide_index=True,
    )

    # Persist edits
    for row in edited_grid:
        li = row["line_item"]
        for period in periods:
            new_value = row.get(period)
            if new_value is None:
                continue
            match = next(
                (f for f in stmt_facts if f["line_item"] == li and f["period"] == period),
                None,
            )
            if match is None:
                continue
            if abs(float(new_value) - float(match["value"])) > 1e-9:
                fact_repo.update_fact(
                    match["id"],
                    value=float(new_value),
                    edited_by_user=True,
                )

# ── Unmapped line items (review queue) ─────────────────────────────
unmapped = review_repo.get_pending(company_id=company_id, limit=50)
if unmapped:
    st.markdown("### Unmapped Line Items")
    st.caption("Label extraction could not map these to the taxonomy. Map or reject them.")
    for item in unmapped:
        c1, c2, c3, c4 = st.columns([3, 1, 1, 2])
        c1.markdown(f"**{item['raw_label']}** — {item.get('period', '')}: {item.get('value', '')} {item.get('unit', '')}")
        mapped_key = c2.text_input("Taxonomy key", key=f"map_{item['id']}", placeholder="e.g., revenue_from_operations")
        if c3.button("Map", key=f"btn_{item['id']}"):
            if mapped_key:
                review_repo.resolve(item["id"], mapped_key)
                st.rerun()
        if c4.button("Reject", key=f"rej_{item['id']}"):
            review_repo.reject(item["id"])
            st.rerun()

st.markdown("---")
col1, col2 = st.columns([1, 3])
with col1:
    if st.button("← Back to Configure"):
        st.switch_page("pages/2_Configure.py")
with col2:
    proceed = st.button(
        "Continue to Thesis & Assumptions →",
        type="primary",
        disabled=bool(validation.blocking),
    )
    if proceed:
        st.switch_page("pages/4_Thesis_Assumptions.py")


def _facts_from_rows(rows):
    facts = []
    for r in rows:
        try:
            facts.append(Fact(
                company_id=r.get("company_id"),
                document_id=r.get("document_id"),
                statement=r.get("statement"),
                line_item=r.get("line_item"),
                raw_label=r.get("raw_label"),
                period=r.get("period"),
                period_type=r.get("period_type"),
                value=float(r.get("value", 0)),
                unit=r.get("unit", "INR_cr"),
                scaling_factor=float(r.get("scaling_factor", 1.0)),
                page=r.get("page"),
                confidence=float(r.get("confidence", 1.0)),
                edited_by_user=bool(r.get("edited_by_user", False)),
                source_text=r.get("source_text"),
                meta=r.get("meta") or {},
            ))
        except Exception:
            continue
    return facts