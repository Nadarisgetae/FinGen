"""
FinGen v2 — Risk Analytics
Financial / operational / market risk flags, volatility, concentration, sensitivity.
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


def financial_risk_flags(facts: List[Fact]) -> AnalyticsResult:
    """
    Automated financial risk flags:
    - Liquidity: current ratio < 1.0
    - Solvency: Debt/Equity > 2.0, Net Debt/EBITDA > 4.0
    - Coverage: ICR < 2.0
    - Profitability: declining revenue 3+ years, negative PAT
    - Cash: negative CFO, closing cash declining
    """
    grouped = _group_by_period(facts)
    periods = sorted(grouped.keys())
    flags = []

    # --- Per-period ratio flags ---
    for period in periods:
        current_assets = _get(grouped, period, "current_assets")
        current_liabilities = _get(grouped, period, "current_liabilities")
        total_debt = _get(grouped, period, "total_debt")
        total_equity = _get(grouped, period, "total_equity")
        cash = _get(grouped, period, "cash_and_equivalents") or _get(grouped, period, "cash_and_bank_balances")
        ebitda = _get(grouped, period, "ebitda")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        pat = _get(grouped, period, "profit_after_tax")
        cfo = _get(grouped, period, "cfo")

        # Liquidity
        if current_assets is not None and current_liabilities and current_liabilities != 0:
            cr = current_assets / current_liabilities
            if cr < 1.0:
                flags.append({
                    "flag_id": "LIQ_CRITICAL",
                    "severity": "error",
                    "category": "liquidity",
                    "description": f"Current ratio {cr:.2f} < 1.0 — potential liquidity stress",
                    "current_value": cr,
                    "threshold": 1.0,
                    "period": period,
                })
            elif cr < 1.25:
                flags.append({
                    "flag_id": "LIQ_WARNING",
                    "severity": "warning",
                    "category": "liquidity",
                    "description": f"Current ratio {cr:.2f} below comfortable 1.25",
                    "current_value": cr,
                    "threshold": 1.25,
                    "period": period,
                })

        # Solvency
        if total_debt is not None and total_equity and total_equity != 0:
            de = total_debt / total_equity
            if de > 2.5:
                flags.append({
                    "flag_id": "SOLV_CRITICAL",
                    "severity": "error",
                    "category": "solvency",
                    "description": f"Debt/Equity {de:.2f} > 2.5 — high leverage",
                    "current_value": de,
                    "threshold": 2.5,
                    "period": period,
                })
            elif de > 1.5:
                flags.append({
                    "flag_id": "SOLV_WARNING",
                    "severity": "warning",
                    "category": "solvency",
                    "description": f"Debt/Equity {de:.2f} elevated",
                    "current_value": de,
                    "threshold": 1.5,
                    "period": period,
                })

        if total_debt is not None and cash is not None and ebitda and ebitda != 0:
            nd = (total_debt - cash) / ebitda
            if nd > 4.0:
                flags.append({
                    "flag_id": "ND_EBITDA_CRITICAL",
                    "severity": "error",
                    "category": "solvency",
                    "description": f"Net Debt/EBITDA {nd:.2f}x > 4.0x",
                    "current_value": nd,
                    "threshold": 4.0,
                    "period": period,
                })

        # Coverage
        if ebitda is not None and finance_costs and finance_costs != 0:
            icr = ebitda / finance_costs
            if icr < 1.5:
                flags.append({
                    "flag_id": "ICR_CRITICAL",
                    "severity": "error",
                    "category": "coverage",
                    "description": f"Interest coverage {icr:.2f}x < 1.5x — debt service risk",
                    "current_value": icr,
                    "threshold": 1.5,
                    "period": period,
                })
            elif icr < 2.5:
                flags.append({
                    "flag_id": "ICR_WARNING",
                    "severity": "warning",
                    "category": "coverage",
                    "description": f"Interest coverage {icr:.2f}x below 2.5x",
                    "current_value": icr,
                    "threshold": 2.5,
                    "period": period,
                })

        # Profitability
        if pat is not None and pat < 0:
            flags.append({
                "flag_id": "PAT_NEGATIVE",
                "severity": "error",
                "category": "profitability",
                "description": "Net loss reported (PAT negative)",
                "current_value": pat,
                "threshold": 0,
                "period": period,
            })

        # Cash flow
        if cfo is not None and cfo < 0:
            flags.append({
                "flag_id": "CFO_NEGATIVE",
                "severity": "warning",
                "category": "cash_flow",
                "description": "Negative operating cash flow",
                "current_value": cfo,
                "threshold": 0,
                "period": period,
            })

    # --- Multi-period trend flags ---
    revenue_series = []
    for period in periods:
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        if revenue:
            revenue_series.append((period, revenue))

    if len(revenue_series) >= 3:
        declining = all(
            revenue_series[i][1] < revenue_series[i - 1][1]
            for i in range(1, len(revenue_series))
        )
        if declining:
            flags.append({
                "flag_id": "REV_DECLINE_3Y",
                "severity": "error",
                "category": "growth",
                "description": f"Revenue declined for {len(revenue_series)} consecutive periods",
                "current_value": None,
                "threshold": None,
                "period": revenue_series[-1][0],
            })

    # Sort by severity
    severity_order = {"error": 0, "warning": 1}
    flags.sort(key=lambda f: severity_order.get(f["severity"], 9))

    return AnalyticsResult(
        metrics={"flags": flags, "flag_count": len(flags)},
        metadata={"periods_analyzed": periods},
    )


def market_risk_metrics(
    price_history: List[Dict] = None,
    benchmark_history: List[Dict] = None,
    risk_free_rate: float = 0.065,
) -> AnalyticsResult:
    """
    Volatility, beta, max drawdown, VaR, Sharpe from price history.
    price_history = [{"date": ..., "close": ...}, ...] sorted ascending
    """
    if not price_history or len(price_history) < 2:
        return AnalyticsResult(metrics={}, metadata={"error": "Insufficient price history"})

    closes = [float(p["close"]) for p in price_history]

    # Daily returns
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    # Volatility (annualized, 252 trading days)
    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
    daily_vol = variance ** 0.5
    annual_vol = daily_vol * (252 ** 0.5)

    # Max drawdown
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak
        if dd > max_dd:
            max_dd = dd

    # VaR 95% (historical)
    sorted_returns = sorted(returns)
    var_95 = sorted_returns[int(0.05 * len(sorted_returns))]

    # Sharpe (annualized)
    excess = mean_ret - risk_free_rate / 252
    sharpe = (excess / daily_vol) * (252 ** 0.5) if daily_vol != 0 else 0

    # Beta vs benchmark
    beta = None
    if benchmark_history and len(benchmark_history) >= 2:
        b_closes = [float(p["close"]) for p in benchmark_history]
        b_returns = [(b_closes[i] - b_closes[i - 1]) / b_closes[i - 1] for i in range(1, len(b_closes))]
        n = min(len(returns), len(b_returns))
        if n > 1:
            r, b = returns[-n:], b_returns[-n:]
            mean_r, mean_b = sum(r) / n, sum(b) / n
            cov = sum((r[i] - mean_r) * (b[i] - mean_b) for i in range(n)) / n
            var_b = sum((x - mean_b) ** 2 for x in b) / n
            beta = cov / var_b if var_b != 0 else None

    results = {
        "volatility_annual": annual_vol,
        "max_drawdown": max_dd,
        "var_95_daily": var_95,
        "sharpe_ratio": sharpe,
    }
    metadata = {"observations": len(returns)}
    if beta is not None:
        results["beta"] = beta

    return AnalyticsResult(metrics=results, metadata=metadata)


def concentration_risk(facts: List[Fact]) -> AnalyticsResult:
    """
    Revenue concentration: HHI, top-N shares from segment facts.
    """
    segment_revenues = defaultdict(float)
    for f in facts:
        if f.statement == "SEGMENT" and f.line_item in ("segment_revenue", "revenue"):
            # Use raw_label or meta as segment identifier
            key = f.raw_label or (f.meta or {}).get("segment_name") or f.period
            segment_revenues[key] += f.value

    if not segment_revenues:
        return AnalyticsResult(metrics={}, metadata={"error": "No segment revenue data"})

    total = sum(segment_revenues.values())
    if total == 0:
        return AnalyticsResult(metrics={}, metadata={"error": "Zero total revenue"})

    shares = {k: v / total for k, v in segment_revenues.items()}
    sorted_shares = sorted(shares.values(), reverse=True)

    hhi = sum(s ** 2 for s in shares.values())  # 0-1 scale (1 = monopoly)
    hhi_scaled = hhi * 10000  # DOJ scale

    results = {
        "hhi": hhi,
        "hhi_doj_scale": hhi_scaled,
        "top1_share": sorted_shares[0],
        "top3_share": sum(sorted_shares[:3]),
        "top5_share": sum(sorted_shares[:5]),
        "segment_count": len(shares),
    }

    if hhi_scaled > 2500:
        results["concentration_level"] = "high"
    elif hhi_scaled > 1500:
        results["concentration_level"] = "moderate"
    else:
        results["concentration_level"] = "low"

    return AnalyticsResult(
        metrics=results,
        metadata={"segment_shares": shares},
    )


def sensitivity_analysis(
    base_metric: float,
    drivers: Dict[str, Dict[str, float]],
) -> AnalyticsResult:
    """
    Tornado chart data: impact of ±X% change in each driver on a metric.
    drivers = {"revenue_growth": {"low": -0.02, "high": 0.02, "impact_per_unit": 0.8}, ...}
    """
    tornado = []
    for driver, spec in drivers.items():
        low_impact = base_metric * spec.get("impact_per_unit", 1.0) * spec["low"]
        high_impact = base_metric * spec.get("impact_per_unit", 1.0) * spec["high"]
        tornado.append({
            "driver": driver,
            "low_case": base_metric + low_impact,
            "high_case": base_metric + high_impact,
            "swing": abs(high_impact - low_impact),
        })

    tornado.sort(key=lambda x: x["swing"], reverse=True)

    return AnalyticsResult(
        metrics={"base_metric": base_metric, "tornado": tornado},
        metadata={},
    )