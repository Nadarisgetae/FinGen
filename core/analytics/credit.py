"""
FinGen v2 — Credit Analytics
Leverage, coverage, liquidity, Altman Z-score, internal rating.
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


def debt_equity(facts: List[Fact]) -> AnalyticsResult:
    """Total debt / Total equity per period."""
    grouped = _group_by_period(facts)
    results = {}
    for period in sorted(grouped.keys()):
        debt = _get(grouped, period, "total_debt")
        equity = _get(grouped, period, "total_equity")
        if debt is not None and equity and equity != 0:
            results[period] = debt / equity
    return AnalyticsResult(metrics=results, metadata={})


def net_debt_ebitda(facts: List[Fact]) -> AnalyticsResult:
    """(Total debt - Cash) / EBITDA per period."""
    grouped = _group_by_period(facts)
    results = {}
    metadata = {}
    for period in sorted(grouped.keys()):
        debt = _get(grouped, period, "total_debt")
        cash = _get(grouped, period, "cash_and_equivalents") or _get(grouped, period, "cash_and_bank_balances")
        ebitda = _get(grouped, period, "ebitda")
        if debt is not None and cash is not None and ebitda and ebitda != 0:
            net_debt = debt - cash
            results[period] = net_debt / ebitda
            metadata[period] = {"net_debt": net_debt, "ebitda": ebitda}
    return AnalyticsResult(metrics=results, metadata=metadata)


def icr(facts: List[Fact]) -> AnalyticsResult:
    """Interest Coverage Ratio: EBITDA / Finance Costs."""
    grouped = _group_by_period(facts)
    results = {}
    for period in sorted(grouped.keys()):
        ebitda = _get(grouped, period, "ebitda")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        if ebitda is not None and finance_costs and finance_costs != 0:
            results[period] = ebitda / finance_costs
    return AnalyticsResult(metrics=results, metadata={})


def dscr(facts: List[Fact]) -> AnalyticsResult:
    """Debt Service Coverage Ratio: (EBITDA - Capex) / (Interest + Principal)."""
    grouped = _group_by_period(facts)
    results = {}
    metadata = {}
    for period in sorted(grouped.keys()):
        ebitda = _get(grouped, period, "ebitda")
        capex = _get(grouped, period, "capex") or _get(grouped, period, "capital_expenditure")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        principal = _get(grouped, period, "principal_repayment") or _get(grouped, period, "repayment_of_borrowings")
        
        if ebitda is not None and finance_costs and principal is not None:
            debt_service = finance_costs + principal
            if debt_service != 0:
                cash_available = ebitda - (capex or 0)
                results[period] = cash_available / debt_service
                metadata[period] = {
                    "cash_available_for_debt_service": cash_available,
                    "debt_service": debt_service,
                }
    return AnalyticsResult(metrics=results, metadata=metadata)


def altman_z_score(facts: List[Fact]) -> AnalyticsResult:
    """
    Altman Z-Score (original manufacturing model):
    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
    X1 = Working Capital / Total Assets
    X2 = Retained Earnings / Total Assets
    X3 = EBIT / Total Assets
    X4 = Market Value Equity / Total Liabilities (use book equity if no market)
    X5 = Sales / Total Assets
    """
    grouped = _group_by_period(facts)
    results = {}
    metadata = {}
    
    for period in sorted(grouped.keys()):
        current_assets = _get(grouped, period, "current_assets")
        current_liabilities = _get(grouped, period, "current_liabilities")
        retained_earnings = _get(grouped, period, "retained_earnings") or _get(grouped, period, "reserves_and_surplus")
        ebit = _get(grouped, period, "ebit") or _get(grouped, period, "operating_profit")
        total_equity = _get(grouped, period, "total_equity")
        total_liabilities = _get(grouped, period, "total_liabilities")
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        total_assets = _get(grouped, period, "total_assets")
        
        if not total_assets or total_assets == 0:
            continue
        
        x1 = (current_assets - current_liabilities) / total_assets if current_assets is not None and current_liabilities is not None else None
        x2 = retained_earnings / total_assets if retained_earnings is not None else None
        x3 = ebit / total_assets if ebit is not None else None
        x4 = total_equity / total_liabilities if total_equity is not None and total_liabilities and total_liabilities != 0 else None
        x5 = revenue / total_assets if revenue is not None else None
        
        # Only compute if we have all components
        if all(v is not None for v in [x1, x2, x3, x4, x5]):
            z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
            if z > 2.99:
                zone = "safe"
            elif z < 1.81:
                zone = "distress"
            else:
                zone = "grey"
            results[period] = z
            metadata[period] = {
                "zone": zone,
                "x1_working_capital_ta": x1,
                "x2_retained_earnings_ta": x2,
                "x3_ebit_ta": x3,
                "x4_equity_liabilities": x4,
                "x5_sales_ta": x5,
            }
    
    return AnalyticsResult(metrics=results, metadata=metadata)


def internal_rating(facts: List[Fact]) -> AnalyticsResult:
    """
    Internal credit rating based on 4 pillars (0-100 each):
    - Leverage (40%): Debt/Equity, Net Debt/EBITDA
    - Coverage (30%): ICR, DSCR
    - Liquidity (15%): Current ratio, Cash/Debt
    - Profitability (15%): EBITDA margin, ROE
    
    Returns: {period: {grade: str, score: float, ...}}
    """
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        # Leverage
        debt = _get(grouped, period, "total_debt")
        equity = _get(grouped, period, "total_equity")
        cash = _get(grouped, period, "cash_and_equivalents") or _get(grouped, period, "cash_and_bank_balances")
        ebitda = _get(grouped, period, "ebitda")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        principal = _get(grouped, period, "principal_repayment") or _get(grouped, period, "repayment_of_borrowings")
        current_assets = _get(grouped, period, "current_assets")
        current_liabilities = _get(grouped, period, "current_liabilities")
        pat = _get(grouped, period, "profit_after_tax")
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        total_assets = _get(grouped, period, "total_assets")
        
        leverage_score = 50  # neutral default
        coverage_score = 50
        liquidity_score = 50
        profitability_score = 50
        
        # Leverage scoring
        if debt is not None and equity and equity != 0:
            de = debt / equity
            if de < 0.5:
                leverage_score = 90
            elif de < 1.0:
                leverage_score = 75
            elif de < 2.0:
                leverage_score = 50
            elif de < 3.0:
                leverage_score = 30
            else:
                leverage_score = 15
        elif debt is not None and ebitda and ebitda != 0:
            nd = (debt - (cash or 0)) / ebitda
            if nd < 1.0:
                leverage_score = 90
            elif nd < 2.0:
                leverage_score = 75
            elif nd < 3.5:
                leverage_score = 50
            elif nd < 5.0:
                leverage_score = 30
            else:
                leverage_score = 15
        
        # Coverage scoring
        if ebitda is not None and finance_costs and finance_costs != 0:
            icr_val = ebitda / finance_costs
            if icr_val > 6:
                coverage_score = 90
            elif icr_val > 4:
                coverage_score = 75
            elif icr_val > 2.5:
                coverage_score = 50
            elif icr_val > 1.5:
                coverage_score = 30
            else:
                coverage_score = 15
        
        # Liquidity scoring
        if current_assets is not None and current_liabilities and current_liabilities != 0:
            cr = current_assets / current_liabilities
            if cr > 2.0:
                liquidity_score = 90
            elif cr > 1.5:
                liquidity_score = 75
            elif cr > 1.0:
                liquidity_score = 50
            elif cr > 0.75:
                liquidity_score = 30
            else:
                liquidity_score = 15
        
        # Profitability scoring
        if revenue and ebitda is not None and revenue != 0:
            margin = ebitda / revenue
            if margin > 0.25:
                profitability_score = 90
            elif margin > 0.15:
                profitability_score = 75
            elif margin > 0.08:
                profitability_score = 50
            elif margin > 0.03:
                profitability_score = 30
            else:
                profitability_score = 15
        
        # Weighted total
        total = (
            leverage_score * 0.40 +
            coverage_score * 0.30 +
            liquidity_score * 0.15 +
            profitability_score * 0.15
        )
        
        # Grade mapping
        if total >= 80:
            grade = "AAA"
        elif total >= 70:
            grade = "AA"
        elif total >= 60:
            grade = "A"
        elif total >= 50:
            grade = "BBB"
        elif total >= 40:
            grade = "BB"
        elif total >= 30:
            grade = "B"
        else:
            grade = "C"
        
        results[period] = {
            "grade": grade,
            "score": total,
            "leverage_score": leverage_score,
            "coverage_score": coverage_score,
            "liquidity_score": liquidity_score,
            "profitability_score": profitability_score,
        }
    
    return AnalyticsResult(metrics=results, metadata={})


def covenant_headroom(facts: List[Fact], covenants: Dict = None) -> AnalyticsResult:
    """
    Headroom vs covenant thresholds.
    covenants = {"net_debt_ebitda_max": 3.5, "icr_min": 2.0}
    """
    if not covenants:
        covenants = {"net_debt_ebitda_max": 3.5, "icr_min": 2.0}
    
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        period_data = {}
        
        debt = _get(grouped, period, "total_debt")
        cash = _get(grouped, period, "cash_and_equivalents") or _get(grouped, period, "cash_and_bank_balances")
        ebitda = _get(grouped, period, "ebitda")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        
        if "net_debt_ebitda_max" in covenants and debt is not None and cash is not None and ebitda and ebitda != 0:
            actual = (debt - cash) / ebitda
            limit = covenants["net_debt_ebitda_max"]
            period_data["net_debt_ebitda_covenant"] = {
                "actual": actual,
                "limit": limit,
                "headroom_pct": (limit - actual) / limit * 100,
                "breach": actual > limit,
            }
        
        if "icr_min" in covenants and ebitda is not None and finance_costs and finance_costs != 0:
            actual = ebitda / finance_costs
            limit = covenants["icr_min"]
            period_data["icr_covenant"] = {
                "actual": actual,
                "limit": limit,
                "headroom_pct": (actual - limit) / limit * 100,
                "breach": actual < limit,
            }
        
        if period_data:
            results[period] = period_data
    
    return AnalyticsResult(metrics=results, metadata={"covenants": covenants})