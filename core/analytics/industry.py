"""
FinGen v2 — Industry Analytics
Peer benchmarking, market size/growth, concentration.
"""

from typing import List, Dict, Optional
from collections import defaultdict
import statistics

from core.schema import Fact, AnalyticsResult


def _group_by_company_period(facts: List[Fact]) -> Dict[str, Dict[str, Dict[str, Fact]]]:
    """Group facts by company_id, then period, then line_item."""
    grouped = defaultdict(lambda: defaultdict(dict))
    for f in facts:
        grouped[str(f.company_id)][f.period][f.line_item] = f
    return dict(grouped)


def _get(grouped, company: str, period: str, line_item: str) -> Optional[float]:
    period_data = grouped.get(company, {}).get(period, {})
    f = period_data.get(line_item)
    return f.value if f else None


def peer_benchmark(
    facts: List[Fact],
    target_company_id: str = None,
    peer_company_ids: List[str] = None,
    context: Dict = None,
) -> AnalyticsResult:
    """
    Peer comparison table: key metrics vs selected peers.
    facts include the target company + peers.
    """
    grouped = _group_by_company_period(facts)
    all_companies = list(grouped.keys())

    if not target_company_id:
        if context and context.get("company_id"):
            target_company_id = str(context["company_id"])
        elif all_companies:
            target_company_id = all_companies[0]
        else:
            target_company_id = "target"

    if peer_company_ids:
        peers = [c for c in all_companies if c in peer_company_ids]
    else:
        peers = [c for c in all_companies if c != target_company_id]

    # Use latest period common to most companies
    period_counts = defaultdict(int)
    for company, periods in grouped.items():
        for period in periods:
            period_counts[period] += 1
    if not period_counts:
        return AnalyticsResult(metrics={}, metadata={"error": "No data"})
    latest_period = max(period_counts, key=period_counts.get)

    # Metrics to compare
    metric_map = {
        "revenue": ("revenue_from_operations", "IS"),
        "ebitda": ("ebitda", "IS"),
        "ebitda_margin": None,  # derived
        "pat": ("profit_after_tax", "IS"),
        "pat_margin": None,  # derived
        "total_assets": ("total_assets", "BS"),
        "total_equity": ("total_equity", "BS"),
        "total_debt": ("total_debt", "BS"),
        "roe": None,  # derived
        "debt_equity": None,  # derived
    }

    def compute_metrics(company: str) -> Dict[str, Optional[float]]:
        m = {}
        for metric, mapping in metric_map.items():
            if mapping is None:
                # Derived
                if metric == "ebitda_margin":
                    rev = _get(grouped, company, latest_period, "revenue_from_operations")
                    ebitda = _get(grouped, company, latest_period, "ebitda")
                    m[metric] = ebitda / rev if rev and ebitda is not None and rev != 0 else None
                elif metric == "pat_margin":
                    rev = _get(grouped, company, latest_period, "revenue_from_operations")
                    pat = _get(grouped, company, latest_period, "profit_after_tax")
                    m[metric] = pat / rev if rev and pat is not None and rev != 0 else None
                elif metric == "roe":
                    pat = _get(grouped, company, latest_period, "profit_after_tax")
                    equity = _get(grouped, company, latest_period, "total_equity")
                    m[metric] = pat / equity if pat is not None and equity and equity != 0 else None
                elif metric == "debt_equity":
                    debt = _get(grouped, company, latest_period, "total_debt")
                    equity = _get(grouped, company, latest_period, "total_equity")
                    m[metric] = debt / equity if debt is not None and equity and equity != 0 else None
            else:
                line_item, _stmt = mapping
                m[metric] = _get(grouped, company, latest_period, line_item)
        return m

    target_metrics = compute_metrics(target_company_id)
    peer_metrics = {p: compute_metrics(p) for p in peers}

    # Percentiles for target
    percentiles = {}
    for metric in metric_map.keys():
        peer_values = [peer_metrics[p][metric] for p in peers if peer_metrics[p].get(metric) is not None]
        target_value = target_metrics.get(metric)
        if peer_values and target_value is not None:
            below = sum(1 for v in peer_values if v < target_value)
            percentiles[metric] = below / len(peer_values) * 100

    results = {
        "target": {"company_id": target_company_id, **target_metrics},
        "peers": [{"company_id": p, **peer_metrics[p]} for p in peers],
        "target_percentile": percentiles,
        "period": latest_period,
    }

    return AnalyticsResult(metrics=results, metadata={"peer_count": len(peers)})


def market_size_growth(
    market_data: Dict = None,
    company_revenue: float = None,
    context: Dict = None,
    facts: List[Fact] = None,
) -> AnalyticsResult:
    """
    Market size, growth, share, TAM/SAM/SOM.
    """
    ctx = context or {}
    if not market_data:
        market_data = ctx.get("market_data") or ctx.get("industry_data") or {}

    if not company_revenue and facts:
        for f in facts:
            if f.line_item in ("revenue_from_operations", "total_income"):
                company_revenue = f.value
                break

    if not market_data:
        return AnalyticsResult(metrics={}, metadata={"error": "No market data provided"})

    tam = market_data.get("total_addressable_market")
    sam = market_data.get("serviceable_addressable_market")
    growth = market_data.get("market_growth_rate")
    historical = market_data.get("historical_market_size", {})

    results = {
        "tam": tam,
        "sam": sam,
        "market_growth_rate": growth,
    }

    # Market share
    if company_revenue and tam:
        results["market_share"] = company_revenue / tam
        results["som"] = company_revenue  # Serviceable obtainable market = current revenue

    # Historical CAGR
    if historical and len(historical) >= 2:
        years = sorted(historical.keys())
        start_val = historical[years[0]]
        end_val = historical[years[-1]]
        n_years = years[-1] - years[0]
        if start_val > 0 and n_years > 0:
            results["market_cagr"] = (end_val / start_val) ** (1 / n_years) - 1

    return AnalyticsResult(metrics=results, metadata=market_data)


def industry_concentration(
    peer_market_shares: Dict[str, float] = None,
    context: Dict = None,
) -> AnalyticsResult:
    """
    Industry concentration via HHI and CR4/CR8.
    peer_market_shares = {"Company A": 0.25, "Company B": 0.20, ...}
    """
    ctx = context or {}
    if not peer_market_shares:
        peer_market_shares = ctx.get("peer_market_shares") or ctx.get("market_shares") or {}

    if not peer_market_shares:
        return AnalyticsResult(metrics={}, metadata={"error": "No share data"})
        return AnalyticsResult(metrics={}, metadata={"error": "No share data"})

    shares = sorted(peer_market_shares.values(), reverse=True)
    total = sum(shares)
    normalized = [s / total for s in shares] if total > 0 else shares

    hhi = sum(s ** 2 for s in normalized) * 10000
    cr4 = sum(normalized[:4])
    cr8 = sum(normalized[:8])

    if hhi > 2500:
        structure = "highly_concentrated"
    elif hhi > 1500:
        structure = "moderately_concentrated"
    else:
        structure = "fragmented"

    results = {
        "hhi": hhi,
        "cr4": cr4,
        "cr8": cr8,
        "market_structure": structure,
        "competitor_count": len(shares),
        "leader_share": normalized[0] if normalized else 0,
    }

    return AnalyticsResult(metrics=results, metadata={"shares": peer_market_shares})