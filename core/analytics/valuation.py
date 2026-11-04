"""
FinGen v2 — Valuation Analytics
DCF (FCFF), multiples, football field, sensitivity grid.
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


def _sort_periods_desc(grouped: Dict) -> List[str]:
    return sorted(grouped.keys(), reverse=True)


def dcf_fcff(
    facts: List[Fact],
    assumptions: Dict = None,
) -> AnalyticsResult:
    """
    DCF using Free Cash Flow to Firm:
    FCFF = EBIT*(1-tax) + D&A - Capex - ΔWC
    PV = sum(FCFF_t / (1+WACC)^t) + TV / (1+WACC)^n
    TV (Gordon) = FCFF_n * (1+g) / (WACC - g)
    TV (Exit Multiple) = EBITDA_n * exit_multiple
    Enterprise Value = PV(explicit) + PV(TV)
    Equity Value = EV - Net Debt
    
    assumptions = {
        "wacc": 0.12,
        "terminal_growth_rate": 0.04,
        "exit_multiple": 8.0,
        "projection_years": 5,
        "revenue_growth": [0.10, 0.09, 0.08, 0.07, 0.06],
        "ebitda_margin": [0.20, 0.21, 0.22, 0.22, 0.23],
        "tax_rate": 0.25,
        "capex_pct_revenue": 0.05,
        "da_pct_revenue": 0.03,
        "wc_pct_revenue_change": 0.15,
    }
    """
    grouped = _group_by_period(facts)
    periods_desc = _sort_periods_desc(grouped)
    
    if not periods_desc:
        return AnalyticsResult(metrics={}, metadata={"error": "No historical data"})
    
    latest = periods_desc[0]
    
    # Historical base values
    revenue_base = _get(grouped, latest, "revenue_from_operations") or _get(grouped, latest, "total_income")
    ebitda_base = _get(grouped, latest, "ebitda")
    da_base = _get(grouped, latest, "depreciation_amortisation") or _get(grouped, latest, "depreciation")
    capex_base = _get(grouped, latest, "capex") or _get(grouped, latest, "capital_expenditure")
    ebit_base = _get(grouped, latest, "ebit") or _get(grouped, latest, "operating_profit")
    
    total_debt = _get(grouped, latest, "total_debt") or 0.0
    cash = _get(grouped, latest, "cash_and_equivalents") or _get(grouped, latest, "cash_and_bank_balances") or 0.0
    net_debt = total_debt - cash
    
    total_equity = _get(grouped, latest, "total_equity")
    shares_outstanding = _get(grouped, latest, "shares_outstanding")
    
    # Assumptions with defaults
    a = assumptions or {}
    wacc = a.get("wacc", 0.12)
    g = a.get("terminal_growth_rate", 0.04)
    exit_multiple = a.get("exit_multiple", 8.0)
    n_years = a.get("projection_years", 5)
    tax_rate = a.get("tax_rate", 0.25)
    
    rev_growth = a.get("revenue_growth", [0.10] * n_years)
    ebitda_margin = a.get("ebitda_margin", [0.20] * n_years)
    capex_pct = a.get("capex_pct_revenue", 0.05)
    da_pct = a.get("da_pct_revenue", 0.03)
    wc_pct = a.get("wc_pct_revenue_change", 0.15)
    
    if not revenue_base or revenue_base == 0:
        return AnalyticsResult(metrics={}, metadata={"error": "No revenue base"})
    
    # Project FCFF
    projected = []
    prev_revenue = revenue_base
    pv_explicit = 0.0
    
    for t in range(1, n_years + 1):
        growth = rev_growth[t - 1] if t - 1 < len(rev_growth) else rev_growth[-1]
        margin = ebitda_margin[t - 1] if t - 1 < len(ebitda_margin) else ebitda_margin[-1]
        
        revenue_t = prev_revenue * (1 + growth)
        ebitda_t = revenue_t * margin
        da_t = revenue_t * da_pct
        ebit_t = ebitda_t - da_t
        nopat_t = ebit_t * (1 - tax_rate)
        capex_t = revenue_t * capex_pct
        delta_wc_t = (revenue_t - prev_revenue) * wc_pct
        
        fcff_t = nopat_t + da_t - capex_t - delta_wc_t
        
        discount_factor = (1 + wacc) ** t
        pv_t = fcff_t / discount_factor
        pv_explicit += pv_t
        
        projected.append({
            "year": t,
            "revenue": revenue_t,
            "ebitda": ebitda_t,
            "ebit": ebit_t,
            "nopat": nopat_t,
            "da": da_t,
            "capex": capex_t,
            "delta_wc": delta_wc_t,
            "fcff": fcff_t,
            "discount_factor": discount_factor,
            "pv_fcff": pv_t,
        })
        
        prev_revenue = revenue_t
    
    # Terminal values
    fcff_final = projected[-1]["fcff"]
    ebitda_final = projected[-1]["ebitda"]
    
    tv_gordon = fcff_final * (1 + g) / (wacc - g) if wacc > g else 0
    tv_exit = ebitda_final * exit_multiple
    
    pv_tv_gordon = tv_gordon / ((1 + wacc) ** n_years)
    pv_tv_exit = tv_exit / ((1 + wacc) ** n_years)
    
    ev_gordon = pv_explicit + pv_tv_gordon
    ev_exit = pv_explicit + pv_tv_exit
    
    equity_gordon = ev_gordon - net_debt
    equity_exit = ev_exit - net_debt
    
    # Implied share price
    share_price_gordon = equity_gordon / shares_outstanding if shares_outstanding else None
    share_price_exit = equity_exit / shares_outstanding if shares_outstanding else None
    
    results = {
        "enterprise_value": (ev_gordon + ev_exit) / 2,
        "enterprise_value_gordon": ev_gordon,
        "enterprise_value_exit": ev_exit,
        "equity_value": (equity_gordon + equity_exit) / 2,
        "equity_value_gordon": equity_gordon,
        "equity_value_exit": equity_exit,
        "pv_explicit_fcf": pv_explicit,
        "terminal_value_gordon": tv_gordon,
        "terminal_value_exit_multiple": tv_exit,
        "pv_terminal_gordon": pv_tv_gordon,
        "pv_terminal_exit": pv_tv_exit,
        "wacc": wacc,
        "terminal_growth_rate": g,
        "exit_multiple": exit_multiple,
        "net_debt": net_debt,
        "share_price_implied_gordon": share_price_gordon,
        "share_price_implied_exit": share_price_exit,
    }
    
    metadata = {
        "projected_periods": projected,
        "assumptions_used": {
            "wacc": wacc,
            "terminal_growth_rate": g,
            "exit_multiple": exit_multiple,
            "projection_years": n_years,
            "tax_rate": tax_rate,
            "revenue_growth": rev_growth,
            "ebitda_margin": ebitda_margin,
            "capex_pct_revenue": capex_pct,
            "da_pct_revenue": da_pct,
            "wc_pct_revenue_change": wc_pct,
        },
        "latest_period": latest,
        "revenue_base": revenue_base,
        "ebitda_base": ebitda_base,
    }
    
    return AnalyticsResult(metrics=results, metadata=metadata)


def multiples_valuation(
    facts: List[Fact],
    context: Dict = None,
) -> AnalyticsResult:
    """
    Relative valuation using peer multiples.
    context = {
        "peer_multiples": {
            "ev_ebitda": [8.5, 9.2, 7.8, ...],
            "pe": [22.0, 25.5, 19.0, ...],
            "pb": [3.2, 4.1, 2.8, ...],
            "ev_sales": [2.5, 3.0, 2.2, ...],
        },
        "market_price": 1250.0,
        "shares_outstanding": 100000000,
    }
    """
    grouped = _group_by_period(facts)
    periods_desc = _sort_periods_desc(grouped)
    
    if not periods_desc:
        return AnalyticsResult(metrics={}, metadata={"error": "No data"})
    
    latest = periods_desc[0]
    
    ebitda = _get(grouped, latest, "ebitda")
    pat = _get(grouped, latest, "profit_after_tax")
    revenue = _get(grouped, latest, "revenue_from_operations") or _get(grouped, latest, "total_income")
    total_equity = _get(grouped, latest, "total_equity")
    total_debt = _get(grouped, latest, "total_debt") or 0.0
    cash = _get(grouped, latest, "cash_and_equivalents") or _get(grouped, latest, "cash_and_bank_balances") or 0.0
    net_debt = total_debt - cash
    
    ctx = context or {}
    peer_multiples = ctx.get("peer_multiples", {})
    
    import statistics
    
    results = {}
    metadata = {}
    
    # EV/EBITDA
    if ebitda and ebitda != 0 and peer_multiples.get("ev_ebitda"):
        median = statistics.median(peer_multiples["ev_ebitda"])
        implied_ev = median * ebitda
        implied_equity = implied_ev - net_debt
        results["implied_equity_value_ev_ebitda"] = implied_equity
        metadata["peer_median_ev_ebitda"] = median
        metadata["peer_ev_ebitda_range"] = {
            "min": min(peer_multiples["ev_ebitda"]),
            "max": max(peer_multiples["ev_ebitda"]),
        }
    
    # P/E
    if pat and pat != 0 and peer_multiples.get("pe"):
        median = statistics.median(peer_multiples["pe"])
        implied_equity = median * pat
        results["implied_equity_value_pe"] = implied_equity
        metadata["peer_median_pe"] = median
        metadata["peer_pe_range"] = {
            "min": min(peer_multiples["pe"]),
            "max": max(peer_multiples["pe"]),
        }
    
    # P/B
    if total_equity and total_equity != 0 and peer_multiples.get("pb"):
        median = statistics.median(peer_multiples["pb"])
        implied_equity = median * total_equity
        results["implied_equity_value_pb"] = implied_equity
        metadata["peer_median_pb"] = median
    
    # EV/Sales
    if revenue and revenue != 0 and peer_multiples.get("ev_sales"):
        median = statistics.median(peer_multiples["ev_sales"])
        implied_ev = median * revenue
        implied_equity = implied_ev - net_debt
        results["implied_equity_value_ev_sales"] = implied_equity
        metadata["peer_median_ev_sales"] = median
    
    # Company's own multiples (for comparison)
    market_price = ctx.get("market_price")
    shares = ctx.get("shares_outstanding")
    if market_price and shares:
        market_cap = market_price * shares
        results["market_cap"] = market_cap
        if ebitda and ebitda != 0:
            results["ev_ebitda_current"] = (market_cap + net_debt) / ebitda
        if pat and pat != 0:
            results["pe_current"] = market_cap / pat
        if total_equity and total_equity != 0:
            results["pb_current"] = market_cap / total_equity
        if revenue and revenue != 0:
            results["ev_sales_current"] = (market_cap + net_debt) / revenue
    
    return AnalyticsResult(metrics=results, metadata=metadata)


def football_field(
    dcf_result: Dict = None,
    multiples_result: Dict = None,
    context: Dict = None,
    facts: List[Fact] = None,
    assumptions: Dict = None,
) -> AnalyticsResult:
    """
    Football field chart data: valuation ranges from multiple methods.
    """
    if dcf_result is None and facts:
        res = dcf_fcff(facts, assumptions)
        dcf_result = res.metrics if hasattr(res, "metrics") else res
    if multiples_result is None and facts:
        res = multiples_valuation(facts, assumptions)
        multiples_result = res.metrics if hasattr(res, "metrics") else res

    ranges = []
    
    # DCF range (WACC sensitivity ±2%)
    if dcf_result and "equity_value" in dcf_result:
        base = dcf_result["equity_value"]
        ranges.append({
            "label": "DCF (WACC ±2%)",
            "low": base * 0.85,
            "high": base * 1.15,
            "color": "#2563EB",
        })
    
    # Multiples range
    if multiples_result:
        implied_values = [
            v for k, v in multiples_result.items()
            if k.startswith("implied_equity_value_")
        ]
        if implied_values:
            ranges.append({
                "label": "Multiples (Peer Range)",
                "low": min(implied_values),
                "high": max(implied_values),
                "color": "#16A34A",
            })
    
    # Market range
    ctx = context or {}
    if ctx.get("market_price") and ctx.get("shares_outstanding"):
        market_cap = ctx["market_price"] * ctx["shares_outstanding"]
        ranges.append({
            "label": "Market Price",
            "low": market_cap * 0.9,
            "high": market_cap * 1.1,
            "color": "#94A3B8",
        })
    
    # 52-week range
    if ctx.get("52_week_low") and ctx.get("52_week_high") and ctx.get("shares_outstanding"):
        ranges.append({
            "label": "52-Week Range",
            "low": ctx["52_week_low"] * ctx["shares_outstanding"],
            "high": ctx["52_week_high"] * ctx["shares_outstanding"],
            "color": "#F59E0B",
        })
    
    return AnalyticsResult(
        metrics={"ranges": ranges},
        metadata={"market_cap": ctx.get("market_price", 0) * ctx.get("shares_outstanding", 1) if ctx.get("market_price") and ctx.get("shares_outstanding") else None},
    )


def sensitivity_grid(
    dcf_result: Dict = None,
    facts: List[Fact] = None,
    assumptions: Dict = None,
    wacc_range: List[float] = None,
    growth_range: List[float] = None,
) -> AnalyticsResult:
    """
    2D sensitivity: Equity value vs (WACC × Terminal Growth).
    """
    if wacc_range is None:
        base_wacc = (assumptions or {}).get("wacc", 0.12)
        wacc_range = [base_wacc - 0.02, base_wacc - 0.01, base_wacc, base_wacc + 0.01, base_wacc + 0.02]
    
    if growth_range is None:
        base_g = (assumptions or {}).get("terminal_growth_rate", 0.04)
        growth_range = [base_g - 0.01, base_g - 0.005, base_g, base_g + 0.005, base_g + 0.01]
    
    grid = []
    for wacc in wacc_range:
        row = []
        mod_assumptions = dict(assumptions or {})
        mod_assumptions["wacc"] = wacc
        for g in growth_range:
            mod_assumptions["terminal_growth_rate"] = g
            result = dcf_fcff(facts, mod_assumptions)
            row.append(result.metrics.get("equity_value", 0))
        grid.append(row)
    
    return AnalyticsResult(
        metrics={
            "wacc_range": wacc_range,
            "growth_range": growth_range,
            "grid": grid,
        },
        metadata={},
    )