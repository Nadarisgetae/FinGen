"""
FinGen v2 — Financial Ratios Analytics
Pure Python calculations from Fact objects.
"""

from typing import List, Dict, Optional
from collections import defaultdict

from core.schema import Fact, AnalyticsResult


def _group_by_period(facts: List[Fact]) -> Dict[str, Dict[str, Fact]]:
    """Group facts by period, then by line_item."""
    grouped = defaultdict(lambda: {})
    for f in facts:
        grouped[f.period][f.line_item] = f
    return dict(grouped)


def _get(facts_by_period: Dict[str, Dict[str, Fact]], period: str, line_item: str) -> Optional[float]:
    """Get value for period+line_item."""
    period_data = facts_by_period.get(period, {})
    f = period_data.get(line_item)
    return f.value if f else None


def profitability_ratios(facts: List[Fact]) -> AnalyticsResult:
    """
    Gross margin, EBITDA margin, PAT margin, ROE, ROCE, ROIC.
    """
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        pd = grouped[period]
        
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        cogs = _get(grouped, period, "cost_of_goods_sold") or _get(grouped, period, "cost_of_materials")
        ebitda = _get(grouped, period, "ebitda")
        pat = _get(grouped, period, "profit_after_tax")
        ebit = _get(grouped, period, "ebit") or _get(grouped, period, "operating_profit")
        total_equity = _get(grouped, period, "total_equity")
        total_assets = _get(grouped, period, "total_assets")
        total_debt = _get(grouped, period, "total_debt")
        current_liabilities = _get(grouped, period, "current_liabilities")
        
        ratios = {}
        
        if revenue and cogs is not None and revenue != 0:
            ratios["gross_margin"] = (revenue - cogs) / revenue
        
        if revenue and ebitda is not None and revenue != 0:
            ratios["ebitda_margin"] = ebitda / revenue
        
        if revenue and pat is not None and revenue != 0:
            ratios["pat_margin"] = pat / revenue
        
        if total_equity and pat is not None and total_equity != 0:
            ratios["roe"] = pat / total_equity
        
        # ROCE = EBIT / (Total Equity + Total Debt)
        if ebit is not None and total_equity and total_debt is not None:
            capital_employed = total_equity + total_debt
            if capital_employed != 0:
                ratios["roce"] = ebit / capital_employed
        
        # ROIC = NOPAT / Invested Capital (approx: EBIT*(1-tax) / (debt+equity-cash))
        if ebit is not None and total_equity and total_debt is not None:
            tax_rate = 0.25  # default assumption
            tax = _get(grouped, period, "tax_expense")
            pbt = _get(grouped, period, "profit_before_tax")
            if tax is not None and pbt and pbt != 0:
                tax_rate = tax / pbt
            invested_capital = total_equity + total_debt
            if invested_capital != 0:
                ratios["roic"] = (ebit * (1 - tax_rate)) / invested_capital
        
        if ratios:
            results[period] = ratios
    
    return AnalyticsResult(metrics=results, metadata={"ratios_calculated": list(results.keys())})


def leverage_ratios(facts: List[Fact]) -> AnalyticsResult:
    """
    Debt/Equity, Net Debt/EBITDA, Debt/Assets, Interest Coverage.
    """
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        total_debt = _get(grouped, period, "total_debt")
        cash = _get(grouped, period, "cash_and_equivalents") or _get(grouped, period, "cash_and_bank_balances")
        total_equity = _get(grouped, period, "total_equity")
        total_assets = _get(grouped, period, "total_assets")
        ebitda = _get(grouped, period, "ebitda")
        finance_costs = _get(grouped, period, "finance_costs") or _get(grouped, period, "interest_expense")
        
        ratios = {}
        
        if total_debt is not None and total_equity and total_equity != 0:
            ratios["debt_equity"] = total_debt / total_equity
        
        if total_debt is not None and cash is not None and ebitda and ebitda != 0:
            net_debt = total_debt - cash
            ratios["net_debt_ebitda"] = net_debt / ebitda
            ratios["net_debt"] = net_debt
        
        if total_debt is not None and total_assets and total_assets != 0:
            ratios["debt_assets"] = total_debt / total_assets
        
        if ebitda is not None and finance_costs and finance_costs != 0:
            ratios["interest_coverage"] = ebitda / finance_costs
        
        if ratios:
            results[period] = ratios
    
    return AnalyticsResult(metrics=results, metadata={})


def efficiency_ratios(facts: List[Fact]) -> AnalyticsResult:
    """
    Asset turnover, inventory days, receivable days, payable days, WC cycle.
    """
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        cogs = _get(grouped, period, "cost_of_goods_sold") or _get(grouped, period, "cost_of_materials")
        total_assets = _get(grouped, period, "total_assets")
        inventory = _get(grouped, period, "inventory")
        receivables = _get(grouped, period, "trade_receivables")
        payables = _get(grouped, period, "trade_payables")
        
        ratios = {}
        
        if revenue and total_assets and total_assets != 0:
            ratios["asset_turnover"] = revenue / total_assets
        
        # Days calculations (assume 365 days)
        if inventory and cogs and cogs != 0:
            ratios["inventory_days"] = (inventory / cogs) * 365
        
        if receivables and revenue and revenue != 0:
            ratios["receivable_days"] = (receivables / revenue) * 365
        
        if payables and cogs and cogs != 0:
            ratios["payable_days"] = (payables / cogs) * 365
        
        # Working capital cycle
        if all(k in ratios for k in ["inventory_days", "receivable_days", "payable_days"]):
            ratios["wc_cycle_days"] = (
                ratios["inventory_days"] + ratios["receivable_days"] - ratios["payable_days"]
            )
        
        if ratios:
            results[period] = ratios
    
    return AnalyticsResult(metrics=results, metadata={})


def dupont_analysis(facts: List[Fact]) -> AnalyticsResult:
    """
    ROE decomposition: Net Margin × Asset Turnover × Financial Leverage.
    """
    grouped = _group_by_period(facts)
    results = {}
    
    for period in sorted(grouped.keys()):
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        pat = _get(grouped, period, "profit_after_tax")
        total_assets = _get(grouped, period, "total_assets")
        total_equity = _get(grouped, period, "total_equity")
        
        ratios = {}
        
        if revenue and pat is not None and revenue != 0:
            ratios["net_margin"] = pat / revenue
        
        if revenue and total_assets and total_assets != 0:
            ratios["asset_turnover"] = revenue / total_assets
        
        if total_assets and total_equity and total_equity != 0:
            ratios["financial_leverage"] = total_assets / total_equity
        
        if all(k in ratios for k in ["net_margin", "asset_turnover", "financial_leverage"]):
            ratios["roe"] = (
                ratios["net_margin"] *
                ratios["asset_turnover"] *
                ratios["financial_leverage"]
            )
        
        if ratios:
            results[period] = ratios
    
    return AnalyticsResult(metrics=results, metadata={})


def common_size_statements(facts: List[Fact]) -> AnalyticsResult:
    """
    IS and BS as percentage of revenue / total assets.
    """
    grouped = _group_by_period(facts)
    results = {}
    
    is_items = [
        "cost_of_goods_sold", "cost_of_materials", "employee_benefits_expense",
        "other_expenses", "ebitda", "depreciation_amortisation", "finance_costs",
        "profit_before_tax", "tax_expense", "profit_after_tax", "operating_profit",
        "other_income", "total_income",
    ]
    bs_items = [
        "current_assets", "non_current_assets", "inventory", "trade_receivables",
        "cash_and_equivalents", "current_liabilities", "non_current_liabilities",
        "total_debt", "total_equity", "trade_payables", "borrowings",
    ]
    
    for period in sorted(grouped.keys()):
        period_result = {"is_common_size": {}, "bs_common_size": {}}
        
        revenue = _get(grouped, period, "revenue_from_operations") or _get(grouped, period, "total_income")
        total_assets = _get(grouped, period, "total_assets")
        
        if revenue and revenue != 0:
            for item in is_items:
                val = _get(grouped, period, item)
                if val is not None:
                    period_result["is_common_size"][item] = val / revenue
        
        if total_assets and total_assets != 0:
            for item in bs_items:
                val = _get(grouped, period, item)
                if val is not None:
                    period_result["bs_common_size"][item] = val / total_assets
        
        if period_result["is_common_size"] or period_result["bs_common_size"]:
            results[period] = period_result
    
    return AnalyticsResult(metrics=results, metadata={})