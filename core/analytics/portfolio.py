"""
FinGen v2 — Portfolio Analytics (Report #10)
XIRR, allocation, attribution, drawdown, benchmark comparison.
Input: holdings + transactions + price history (NOT company facts).
"""

from typing import List, Dict, Optional
from datetime import date, datetime
from collections import defaultdict
import statistics

from core.schema import AnalyticsResult


def _xirr(cash_flows: List[Dict]) -> float:
    """
    Extended Internal Rate of Return for irregular cash flows.
    cash_flows = [{"date": date, "amount": float}, ...]
    Negative = outflow (investment), positive = inflow (redemption/dividend).
    Uses Newton-Raphson iteration.
    """
    if not cash_flows:
        return 0.0

    # Sort by date
    flows = sorted(cash_flows, key=lambda x: x["date"])
    d0 = flows[0]["date"]

    def npv(rate: float) -> float:
        total = 0.0
        for cf in flows:
            days = (cf["date"] - d0).days
            years = days / 365.25
            if years == 0:
                total += cf["amount"]
            else:
                try:
                    total += cf["amount"] / ((1 + rate) ** years)
                except OverflowError:
                    return float("inf") if cf["amount"] > 0 else float("-inf")
        return total

    # Newton-Raphson
    rate = 0.1
    for _ in range(100):
        npv_val = npv(rate)
        # Numerical derivative
        h = 0.0001
        deriv = (npv(rate + h) - npv(rate - h)) / (2 * h)
        if abs(deriv) < 1e-12:
            break
        new_rate = rate - npv_val / deriv
        if abs(new_rate - rate) < 1e-7:
            return new_rate
        rate = new_rate
        # Keep rate in sane bounds
        if rate < -0.99:
            rate = -0.99
        if rate > 10:
            rate = 10
    return rate


def xirr(
    transactions: List[Dict],
    current_holdings_value: float,
    valuation_date: date = None,
) -> AnalyticsResult:
    """
    XIRR from transactions + current portfolio value.
    transactions = [{"date": date, "amount": float, "type": "buy"/"sell"/"dividend"}, ...]
    """
    if valuation_date is None:
        valuation_date = date.today()

    cash_flows = []
    for tx in transactions:
        tx_date = tx["date"]
        if isinstance(tx_date, str):
            tx_date = datetime.strptime(tx_date, "%Y-%m-%d").date()
        amount = float(tx["amount"])
        tx_type = tx.get("type", "buy")
        # Outflows negative, inflows positive
        if tx_type in ("buy", "transfer_in"):
            cash_flows.append({"date": tx_date, "amount": -abs(amount)})
        elif tx_type in ("sell", "dividend", "transfer_out"):
            cash_flows.append({"date": tx_date, "amount": abs(amount)})

    # Terminal value (current holdings)
    cash_flows.append({"date": valuation_date, "amount": float(current_holdings_value)})

    total_invested = sum(-cf["amount"] for cf in cash_flows if cf["amount"] < 0)
    total_returned = sum(cf["amount"] for cf in cash_flows if cf["amount"] > 0)

    rate = _xirr(cash_flows)

    results = {
        "xirr": rate,
        "total_invested": total_invested,
        "total_returned": total_returned,
        "current_value": current_holdings_value,
        "absolute_return": current_holdings_value + sum(cf["amount"] for cf in cash_flows),
        "absolute_return_pct": (
            (current_holdings_value + sum(cf["amount"] for cf in cash_flows)) / total_invested
            if total_invested else 0
        ),
    }

    return AnalyticsResult(
        metrics=results,
        metadata={"cash_flow_count": len(cash_flows)},
    )


def portfolio_allocation(holdings: List[Dict]) -> AnalyticsResult:
    """
    Current allocation by sector, market cap, geography.
    holdings = [{"ticker": ..., "current_value": ..., "sector": ..., "market_cap": ..., "geography": ...}, ...]
    """
    if not holdings:
        return AnalyticsResult(metrics={}, metadata={"error": "No holdings"})

    total_value = sum(float(h.get("current_value", 0)) for h in holdings)
    if total_value == 0:
        return AnalyticsResult(metrics={}, metadata={"error": "Zero portfolio value"})

    by_sector = defaultdict(float)
    by_market_cap = defaultdict(float)
    by_geography = defaultdict(float)
    by_holding = {}

    for h in holdings:
        value = float(h.get("current_value", 0))
        weight = value / total_value
        by_sector[h.get("sector", "Unknown")] += weight
        by_market_cap[h.get("market_cap", "Unknown")] += weight
        by_geography[h.get("geography", h.get("country", "Unknown"))] += weight
        by_holding[h["ticker"]] = weight

    results = {
        "total_value": total_value,
        "by_sector": dict(by_sector),
        "by_market_cap": dict(by_market_cap),
        "by_geography": dict(by_geography),
        "by_holding": dict(sorted(by_holding.items(), key=lambda x: x[1], reverse=True)),
        "holding_count": len(holdings),
    }

    # Concentration: top holding weight
    if by_holding:
        results["top_holding_weight"] = max(by_holding.values())

    return AnalyticsResult(metrics=results, metadata={})


def portfolio_attribution(
    portfolio_returns: Dict[str, float],
    benchmark_returns: Dict[str, float],
    portfolio_weights: Dict[str, float],
    benchmark_weights: Dict[str, float],
) -> AnalyticsResult:
    """
    Brinson attribution: allocation + selection + interaction effects.
    All dicts: {sector: value} for a single period.
    """
    sectors = set(portfolio_returns.keys()) | set(benchmark_returns.keys())

    allocation_effect = 0.0
    selection_effect = 0.0
    interaction_effect = 0.0
    details = []

    benchmark_total = sum(benchmark_returns.get(s, 0) * benchmark_weights.get(s, 0) for s in sectors)

    for sector in sectors:
        rp = portfolio_returns.get(sector, 0)
        rb = benchmark_returns.get(sector, 0)
        wp = portfolio_weights.get(sector, 0)
        wb = benchmark_weights.get(sector, 0)

        alloc = (wp - wb) * rb
        sel = wb * (rp - rb)
        inter = (wp - wb) * (rp - rb)

        allocation_effect += alloc
        selection_effect += sel
        interaction_effect += inter

        details.append({
            "sector": sector,
            "allocation_effect": alloc,
            "selection_effect": sel,
            "interaction_effect": inter,
            "total_effect": alloc + sel + inter,
        })

    portfolio_total = sum(portfolio_returns.get(s, 0) * portfolio_weights.get(s, 0) for s in sectors)
    total_active = portfolio_total - benchmark_total

    results = {
        "allocation_effect": allocation_effect,
        "selection_effect": selection_effect,
        "interaction_effect": interaction_effect,
        "total_active_return": total_active,
        "portfolio_return": portfolio_total,
        "benchmark_return": benchmark_total,
        "attribution_details": details,
    }

    return AnalyticsResult(metrics=results, metadata={})


def drawdown_analysis(
    portfolio_values: List[Dict],
) -> AnalyticsResult:
    """
    Max drawdown, duration, recovery, underwater curve.
    portfolio_values = [{"date": date, "value": float}, ...] sorted ascending
    """
    if not portfolio_values or len(portfolio_values) < 2:
        return AnalyticsResult(metrics={}, metadata={"error": "Insufficient data"})

    values = [(p["date"], float(p["value"])) for p in portfolio_values]

    peak = values[0][1]
    peak_date = values[0][0]
    max_dd = 0.0
    max_dd_date = values[0][0]
    max_dd_peak_date = values[0][0]
    recovery_date = None

    underwater = []
    current_dd_start = None
    current_dd = 0.0

    for d, v in values:
        if v > peak:
            # New peak - check recovery
            if current_dd_start is not None and current_dd > 0:
                recovery_date = d
            peak = v
            peak_date = d
            current_dd = 0.0
            current_dd_start = None
        else:
            dd = (peak - v) / peak
            underwater.append({"date": d, "drawdown": dd})
            if dd > current_dd:
                current_dd = dd
                if current_dd_start is None:
                    current_dd_start = d
            if dd > max_dd:
                max_dd = dd
                max_dd_date = d
                max_dd_peak_date = peak_date

    # Duration in days
    duration_days = (max_dd_date - max_dd_peak_date).days if hasattr(max_dd_date, "days") else 0

    results = {
        "max_drawdown": max_dd,
        "max_drawdown_date": str(max_dd_date),
        "max_drawdown_peak_date": str(max_dd_peak_date),
        "recovery_date": str(recovery_date) if recovery_date else None,
        "duration_days": duration_days,
        "current_drawdown": underwater[-1]["drawdown"] if underwater else 0,
    }

    return AnalyticsResult(
        metrics=results,
        metadata={"underwater_curve": underwater[::max(1, len(underwater) // 100)]},  # sample for chart
    )


def benchmark_comparison(
    portfolio_returns: List[float],
    benchmark_returns: List[float],
    risk_free_rate: float = 0.065,
) -> AnalyticsResult:
    """
    Portfolio vs benchmark: excess return, tracking error, information ratio, beta, alpha.
    Returns series (periodic, e.g., daily).
    """
    if not portfolio_returns or not benchmark_returns:
        return AnalyticsResult(metrics={}, metadata={"error": "No return data"})

    n = min(len(portfolio_returns), len(benchmark_returns))
    p = portfolio_returns[-n:]
    b = benchmark_returns[-n:]

    # Returns
    port_total = 1.0
    bench_total = 1.0
    for i in range(n):
        port_total *= (1 + p[i])
        bench_total *= (1 + b[i])

    excess_return = port_total - bench_total

    # Tracking error (annualized, assume daily, 252 days)
    diffs = [p[i] - b[i] for i in range(n)]
    mean_diff = sum(diffs) / n
    te_daily = (sum((d - mean_diff) ** 2 for d in diffs) / n) ** 0.5
    tracking_error = te_daily * (252 ** 0.5)

    # Information ratio
    mean_excess_annual = mean_diff * 252
    info_ratio = mean_excess_annual / tracking_error if tracking_error != 0 else 0

    # Beta and alpha
    mean_p = sum(p) / n
    mean_b = sum(b) / n
    cov = sum((p[i] - mean_p) * (b[i] - mean_b) for i in range(n)) / n
    var_b = sum((x - mean_b) ** 2 for x in b) / n
    beta = cov / var_b if var_b != 0 else 0

    # Alpha (annualized)
    port_annual = mean_p * 252
    bench_annual = mean_b * 252
    alpha = port_annual - (risk_free_rate + beta * (bench_annual - risk_free_rate))

    results = {
        "portfolio_return": port_total - 1,
        "benchmark_return": bench_total - 1,
        "excess_return": excess_return,
        "tracking_error": tracking_error,
        "information_ratio": info_ratio,
        "beta": beta,
        "alpha": alpha,
        "sharpe_portfolio": (port_annual - risk_free_rate) / (te_daily * (252 ** 0.5)) if te_daily else 0,
    }

    return AnalyticsResult(metrics=results, metadata={"observations": n})


def xnpv(rate: float, cash_flows: List[Dict]) -> float:
    """XNPV helper for XIRR validation."""
    if not cash_flows:
        return 0.0
    d0 = min(cf["date"] for cf in cash_flows)
    total = 0.0
    for cf in cash_flows:
        days = (cf["date"] - d0).days
        years = days / 365.25
        total += cf["amount"] / ((1 + rate) ** years)
    return total