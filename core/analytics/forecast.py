"""
FinGen v2 — Forecast Analytics
5-year projected IS/BS/CF from historicals + assumptions.
"""

from typing import List, Dict, Optional
from collections import defaultdict

from core.schema import Fact, AnalyticsResult


def _group_by_period(facts: List[Fact]) -> Dict[str, Dict[str, Fact]]:
    grouped = defaultdict(lambda: {})
    for f in facts:
        grouped[f.period][f.line_item] = f
    return dict(grouped)


def _get(grouped, period: str, line_item: str) -> Optional[float]:
    period_data = grouped.get(period, {})
    f = period_data.get(line_item)
    return f.value if f else None


def project_is_bs_cf(
    facts: List[Fact],
    assumptions: Dict = None,
) -> AnalyticsResult:
    """
    Build 5-year projected Income Statement, Balance Sheet, Cash Flow.
    
    assumptions = {
        "scenario": "base",
        "projection_years": 5,
        "revenue_growth": [0.10, 0.09, 0.08, 0.07, 0.06],
        "ebitda_margin": [0.20, 0.21, 0.22, 0.22, 0.23],
        "da_pct_revenue": 0.03,
        "finance_costs_pct_debt": 0.08,
        "tax_rate": 0.25,
        "capex_pct_revenue": 0.05,
        "inventory_pct_revenue": 0.08,
        "receivables_pct_revenue": 0.10,
        "payables_pct_revenue": 0.06,
        "debt_repayment": [100, 100, 100, 100, 100],  # INR_cr
        "new_debt": [0, 0, 0, 0, 0],
        "dividend_payout": 0.30,
        "equity_issuance": 0,
    }
    """
    grouped = _group_by_period(facts)
    periods = sorted(grouped.keys())
    
    if not periods:
        return AnalyticsResult(metrics={}, metadata={"error": "No historical data"})
    
    latest = periods[-1]
    
    # Historical base
    revenue_base = _get(grouped, latest, "revenue_from_operations") or _get(grouped, latest, "total_income")
    cogs_base = _get(grouped, latest, "cost_of_goods_sold") or _get(grouped, latest, "cost_of_materials")
    employee_base = _get(grouped, latest, "employee_benefits_expense")
    other_exp_base = _get(grouped, latest, "other_expenses")
    da_base = _get(grouped, latest, "depreciation_amortisation") or _get(grouped, latest, "depreciation")
    finance_costs_base = _get(grouped, latest, "finance_costs") or _get(grouped, latest, "interest_expense")
    tax_base = _get(grouped, latest, "tax_expense")
    pbt_base = _get(grouped, latest, "profit_before_tax")
    pat_base = _get(grouped, latest, "profit_after_tax")
    
    total_assets_base = _get(grouped, latest, "total_assets") or 0
    total_equity_base = _get(grouped, latest, "total_equity") or 0
    total_debt_base = _get(grouped, latest, "total_debt") or 0
    cash_base = _get(grouped, latest, "cash_and_equivalents") or _get(grouped, latest, "cash_and_bank_balances") or 0
    inventory_base = _get(grouped, latest, "inventory") or 0
    receivables_base = _get(grouped, latest, "trade_receivables") or 0
    payables_base = _get(grouped, latest, "trade_payables") or 0
    retained_earnings_base = _get(grouped, latest, "retained_earnings") or _get(grouped, latest, "reserves_and_surplus") or total_equity_base
    
    a = assumptions or {}
    n_years = a.get("projection_years", 5)
    rev_growth = a.get("revenue_growth", [0.10] * n_years)
    ebitda_margin = a.get("ebitda_margin", [0.20] * n_years)
    da_pct = a.get("da_pct_revenue", 0.03)
    finance_pct_debt = a.get("finance_costs_pct_debt", 0.08)
    tax_rate = a.get("tax_rate", 0.25)
    capex_pct = a.get("capex_pct_revenue", 0.05)
    inventory_pct = a.get("inventory_pct_revenue", 0.08)
    receivables_pct = a.get("receivables_pct_revenue", 0.10)
    payables_pct = a.get("payables_pct_revenue", 0.06)
    debt_repayment = a.get("debt_repayment", [0] * n_years)
    new_debt = a.get("new_debt", [0] * n_years)
    dividend_payout = a.get("dividend_payout", 0.30)
    equity_issuance = a.get("equity_issuance", 0)
    
    if not revenue_base:
        return AnalyticsResult(metrics={}, metadata={"error": "No revenue base"})
    
    # Base ratios for items without explicit assumptions
    cogs_pct = (cogs_base / revenue_base) if cogs_base and revenue_base else 0.5
    employee_pct = (employee_base / revenue_base) if employee_base and revenue_base else 0.10
    other_exp_pct = (other_exp_base / revenue_base) if other_exp_base and revenue_base else 0.05
    
    # Initialize projection
    projected_is = []
    projected_bs = []
    projected_cf = []
    
    prev_revenue = revenue_base
    prev_cash = cash_base
    prev_debt = total_debt_base
    prev_equity = total_equity_base
    prev_retained = retained_earnings_base
    prev_inventory = inventory_base
    prev_receivables = receivables_base
    prev_payables = payables_base
    prev_da = da_base or 0
    
    for t in range(1, n_years + 1):
        growth = rev_growth[t - 1] if t - 1 < len(rev_growth) else rev_growth[-1]
        margin = ebitda_margin[t - 1] if t - 1 < len(ebitda_margin) else ebitda_margin[-1]
        
        # --- Income Statement ---
        revenue_t = prev_revenue * (1 + growth)
        cogs_t = revenue_t * cogs_pct
        employee_t = revenue_t * employee_pct
        other_exp_t = revenue_t * other_exp_pct
        ebitda_t = revenue_t * margin
        da_t = revenue_t * da_pct
        ebit_t = ebitda_t - da_t
        debt_avg = (prev_debt + (prev_debt - debt_repayment[t-1] + new_debt[t-1])) / 2
        finance_costs_t = debt_avg * finance_pct_debt
        pbt_t = ebit_t - finance_costs_t
        tax_t = max(0, pbt_t * tax_rate)
        pat_t = pbt_t - tax_t
        
        # --- Cash Flow ---
        capex_t = revenue_t * capex_pct
        delta_inventory = (revenue_t * inventory_pct) - prev_inventory
        delta_receivables = (revenue_t * receivables_pct) - prev_receivables
        delta_payables = (revenue_t * payables_pct) - prev_payables
        delta_wc = delta_inventory + delta_receivables - delta_payables
        
        cfo_t = pat_t + da_t - delta_wc
        cfi_t = -capex_t
        dividends_t = pat_t * dividend_payout
        debt_net = new_debt[t-1] - debt_repayment[t-1]
        cff_t = debt_net + equity_issuance - dividends_t
        
        net_change_cash = cfo_t + cfi_t + cff_t
        cash_t = prev_cash + net_change_cash
        
        # --- Balance Sheet ---
        inventory_t = revenue_t * inventory_pct
        receivables_t = revenue_t * receivables_pct
        payables_t = revenue_t * payables_pct
        
        debt_t = prev_debt + debt_net
        dividends_paid = dividends_t
        retained_t = prev_retained + pat_t - dividends_paid
        equity_t = prev_equity + pat_t - dividends_paid + equity_issuance
        
        # Fixed assets: prev + capex - D&A
        fixed_assets_t = (prev_da * 0) + capex_t - da_t  # simplified
        total_assets_t = inventory_t + receivables_t + cash_t + max(0, fixed_assets_t)
        total_liabilities_t = payables_t + debt_t
        
        projected_is.append({
            "period": f"FY{25 + t}",
            "revenue": revenue_t,
            "cogs": cogs_t,
            "employee_benefits": employee_t,
            "other_expenses": other_exp_t,
            "ebitda": ebitda_t,
            "da": da_t,
            "ebit": ebit_t,
            "finance_costs": finance_costs_t,
            "pbt": pbt_t,
            "tax": tax_t,
            "pat": pat_t,
        })
        
        projected_bs.append({
            "period": f"FY{25 + t}",
            "inventory": inventory_t,
            "receivables": receivables_t,
            "cash": cash_t,
            "total_assets": total_assets_t,
            "payables": payables_t,
            "total_debt": debt_t,
            "total_equity": equity_t,
            "retained_earnings": retained_t,
        })
        
        projected_cf.append({
            "period": f"FY{25 + t}",
            "cfo": cfo_t,
            "capex": capex_t,
            "cfi": cfi_t,
            "dividends": dividends_t,
            "net_debt_change": debt_net,
            "cff": cff_t,
            "net_change_cash": net_change_cash,
            "closing_cash": cash_t,
        })
        
        prev_revenue = revenue_t
        prev_cash = cash_t
        prev_debt = debt_t
        prev_equity = equity_t
        prev_retained = retained_t
        prev_inventory = inventory_t
        prev_receivables = receivables_t
        prev_payables = payables_t
        prev_da = da_t
    
    results = {
        "projected_periods": [f"FY{25 + t}" for t in range(1, n_years + 1)],
        "is_projected": projected_is,
        "bs_projected": projected_bs,
        "cf_projected": projected_cf,
        "scenario": a.get("scenario", "base"),
    }
    
    metadata = {
        "revenue_growth_assumptions": rev_growth,
        "ebitda_margin_assumptions": ebitda_margin,
        "capex_assumptions": [revenue_base * (1 + sum(rev_growth[:t+1])) * capex_pct for t in range(n_years)],
        "wc_assumptions": {
            "inventory_pct": inventory_pct,
            "receivables_pct": receivables_pct,
            "payables_pct": payables_pct,
        },
        "debt_assumptions": {
            "repayment": debt_repayment,
            "new_debt": new_debt,
        },
        "equity_assumptions": {
            "dividend_payout": dividend_payout,
            "equity_issuance": equity_issuance,
        },
        "latest_period": latest,
        "base_revenue": revenue_base,
    }
    
    return AnalyticsResult(metrics=results, metadata=metadata)