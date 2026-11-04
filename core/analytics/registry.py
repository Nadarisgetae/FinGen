"""
FinGen v2 — Analytics Registry

DEFINITIVE CONTRACT between report templates and analytics functions.

This file is the SINGLE SOURCE OF TRUTH for:
- Which analytics functions exist
- What fact keys they require (must match taxonomy.yaml)
- What they return (type, structure, period alignment)
- Which report sections can use them

Templates reference analytics by name. Runner validates at load time.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, get_type_hints
from enum import Enum
import inspect

from core.schema import Fact


class StatementType(str, Enum):
    IS = "IS"          # Income Statement
    BS = "BS"          # Balance Sheet
    CF = "CF"          # Cash Flow
    SEGMENT = "SEGMENT"
    KPI = "KPI"
    GUIDANCE = "GUIDANCE"


class PeriodAlignment(str, Enum):
    """How the output aligns with input periods."""
    SAME = "same"              # One output per input period (e.g., YoY growth)
    AGGREGATE = "aggregate"    # Single value from multiple periods (e.g., CAGR)
    PROJECTED = "projected"    # Future periods (forecast)
    CROSS_SECTIONAL = "cross_sectional"  # Peer comparison (single period)


@dataclass(frozen=True)
class AnalyticsSpec:
    """
    Immutable specification for an analytics function.
    
    Attributes:
        name: Unique identifier (used in templates)
        description: Human-readable description
        requires: List of fact keys required (must exist in taxonomy.yaml)
                  Format: "STATEMENT.line_item" e.g., "IS.revenue_from_operations"
        returns: Python type annotation of return value
        period_alignment: How output periods relate to input periods
        output_unit: Unit of output (e.g., "ratio", "percentage", "INR_cr", "times")
        metadata_keys: Additional keys in returned dict beyond the main metric
    """
    name: str
    description: str
    requires: List[str]
    returns: str  # String representation of type (for serialization)
    period_alignment: PeriodAlignment
    output_unit: str
    metadata_keys: List[str] = field(default_factory=list)
    
    def validate_facts_available(self, available_facts: List[Fact]) -> List[str]:
        """Check which required facts are missing. Returns list of missing keys."""
        available_qualified = {f"{f.statement}.{f.line_item}" for f in available_facts}
        available_items = {f.line_item for f in available_facts}
        missing = []
        for req in self.requires:
            req_item = req.split(".")[-1]
            if req not in available_qualified and req_item not in available_items:
                missing.append(req)
        return missing


# =============================================================================
# ANALYTICS REGISTRY — Add new functions here
# =============================================================================

ANALYTICS_REGISTRY: Dict[str, AnalyticsSpec] = {
    # -----------------------------------------------------------------------------
    # GROWTH ANALYTICS (core/analytics/growth.py)
    # -----------------------------------------------------------------------------
    "yoy_growth": AnalyticsSpec(
        name="yoy_growth",
        description="Year-over-year growth rate for a line item across consecutive periods",
        requires=["IS.revenue_from_operations"],  # Example - actual requires set per call
        returns="Dict[str, float]",  # period -> growth_rate (decimal, e.g., 0.15 for 15%)
        period_alignment=PeriodAlignment.SAME,
        output_unit="percentage",
        metadata_keys=["base_period", "current_period", "base_value", "current_value"],
    ),
    "cagr": AnalyticsSpec(
        name="cagr",
        description="Compound annual growth rate over a period range",
        requires=["IS.revenue_from_operations"],
        returns="float",  # Single CAGR value (decimal)
        period_alignment=PeriodAlignment.AGGREGATE,
        output_unit="percentage",
        metadata_keys=["start_period", "end_period", "start_value", "end_value", "years"],
    ),
    "quarterly_trend": AnalyticsSpec(
        name="quarterly_trend",
        description="Quarterly trend analysis (sequential growth, seasonality)",
        requires=["IS.revenue_from_operations"],
        returns="Dict[str, Any]",  # Contains qoq_growth, trend_direction, seasonality_index
        period_alignment=PeriodAlignment.SAME,
        output_unit="mixed",
        metadata_keys=["qoq_growth", "trend", "seasonality"],
    ),
    
    # -----------------------------------------------------------------------------
    # RATIOS (core/analytics/ratios.py)
    # -----------------------------------------------------------------------------
    "profitability_ratios": AnalyticsSpec(
        name="profitability_ratios",
        description="Gross margin, EBITDA margin, PAT margin, ROE, ROCE, ROIC",
        requires=[
            "IS.revenue_from_operations",
        ],
        returns="Dict[str, Dict[str, float]]",  # period -> {ratio_name: value}
        period_alignment=PeriodAlignment.SAME,
        output_unit="ratio",
        metadata_keys=["gross_margin", "ebitda_margin", "pat_margin", "roe", "roce", "roic"],
    ),
    "leverage_ratios": AnalyticsSpec(
        name="leverage_ratios",
        description="Debt/Equity, Net Debt/EBITDA, Debt/Assets, Interest Coverage",
        requires=[
            "BS.total_debt",
            "BS.total_equity",
        ],
        returns="Dict[str, Dict[str, float]]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="ratio",
        metadata_keys=["debt_equity", "net_debt_ebitda", "debt_assets", "interest_coverage"],
    ),
    "efficiency_ratios": AnalyticsSpec(
        name="efficiency_ratios",
        description="Asset turnover, inventory days, receivable days, payable days, WC cycle",
        requires=[
            "IS.revenue_from_operations",
        ],
        returns="Dict[str, Dict[str, float]]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="mixed",  # times, days
        metadata_keys=["asset_turnover", "inventory_days", "receivable_days", "payable_days", "wc_cycle_days"],
    ),
    "dupont_analysis": AnalyticsSpec(
        name="dupont_analysis",
        description="ROE decomposition: Net Margin × Asset Turnover × Leverage",
        requires=[
            "IS.profit_after_tax",
            "IS.revenue_from_operations",
            "BS.total_assets",
            "BS.total_equity",
        ],
        returns="Dict[str, Dict[str, float]]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="ratio",
        metadata_keys=["net_margin", "asset_turnover", "financial_leverage", "roe"],
    ),
    "common_size_statements": AnalyticsSpec(
        name="common_size_statements",
        description="IS and BS as percentage of revenue / total assets",
        requires=[
            "IS.revenue_from_operations",
            "BS.total_assets",
        ],
        returns="Dict[str, Dict[str, float]]",  # period -> {line_item: pct}
        period_alignment=PeriodAlignment.SAME,
        output_unit="percentage",
        metadata_keys=["is_common_size", "bs_common_size"],
    ),
    
    # -----------------------------------------------------------------------------
    # CREDIT ANALYTICS (core/analytics/credit.py)
    # -----------------------------------------------------------------------------
    "debt_equity": AnalyticsSpec(
        name="debt_equity",
        description="Total debt / Total equity",
        requires=["BS.total_debt", "BS.total_equity"],
        returns="Dict[str, float]",  # period -> ratio
        period_alignment=PeriodAlignment.SAME,
        output_unit="ratio",
        metadata_keys=[],
    ),
    "net_debt_ebitda": AnalyticsSpec(
        name="net_debt_ebitda",
        description="(Total debt - Cash) / EBITDA",
        requires=["BS.total_debt", "BS.cash_and_equivalents", "IS.ebitda"],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="times",
        metadata_keys=["net_debt", "ebitda"],
    ),
    "icr": AnalyticsSpec(
        name="icr",
        description="Interest Coverage Ratio: EBITDA / Finance Costs",
        requires=["IS.ebitda", "IS.finance_costs"],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="times",
        metadata_keys=[],
    ),
    "dscr": AnalyticsSpec(
        name="dscr",
        description="Debt Service Coverage Ratio: (EBITDA - Capex) / (Interest + Principal Repayment)",
        requires=["IS.ebitda", "IS.finance_costs", "CF.principal_repayment", "CF.capex"],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="times",
        metadata_keys=["debt_service", "cash_available_for_debt_service"],
    ),
    "altman_z_score": AnalyticsSpec(
        name="altman_z_score",
        description="Altman Z-Score for bankruptcy prediction (manufacturing version)",
        requires=[
            "BS.total_assets",
            "BS.total_liabilities",
            "BS.current_assets",
            "BS.current_liabilities",
            "BS.retained_earnings",
            "IS.ebit",
            "IS.revenue_from_operations",
            "BS.total_equity",
        ],
        returns="Dict[str, float]",  # period -> z_score
        period_alignment=PeriodAlignment.SAME,
        output_unit="score",
        metadata_keys=["zone"],  # "safe", "grey", "distress"
    ),
    "internal_rating": AnalyticsSpec(
        name="internal_rating",
        description="Internal credit rating based on leverage, coverage, liquidity, profitability",
        requires=[
            "BS.total_debt", "BS.total_equity", "BS.cash_and_equivalents",
            "IS.ebitda", "IS.finance_costs", "IS.profit_after_tax",
            "BS.current_assets", "BS.current_liabilities",
        ],
        returns="Dict[str, Dict[str, Any]]",  # period -> {grade: str, score: float, factors: dict}
        period_alignment=PeriodAlignment.SAME,
        output_unit="grade",
        metadata_keys=["grade", "score", "leverage_score", "coverage_score", "liquidity_score", "profitability_score"],
    ),
    "covenant_headroom": AnalyticsSpec(
        name="covenant_headroom",
        description="Headroom vs. covenant thresholds (if covenants extracted from docs)",
        requires=["BS.total_debt", "IS.ebitda", "IS.finance_costs"],
        returns="Dict[str, Dict[str, float]]",  # period -> {covenant_name: headroom_pct}
        period_alignment=PeriodAlignment.SAME,
        output_unit="percentage",
        metadata_keys=["net_debt_ebitda_covenant", "icr_covenant"],
    ),
    
    # -----------------------------------------------------------------------------
    # VALUATION ANALYTICS (core/analytics/valuation.py)
    # -----------------------------------------------------------------------------
    "dcf_fcff": AnalyticsSpec(
        name="dcf_fcff",
        description="DCF valuation using FCFF: PV of projected FCFF + Terminal Value",
        requires=[
            "IS.revenue_from_operations",
        ],
        returns="Dict[str, Any]",  # {enterprise_value, equity_value, pv_fcf, tv_gordon, tv_exit_multiple, wacc, assumptions}
        period_alignment=PeriodAlignment.PROJECTED,
        output_unit="INR_cr",
        metadata_keys=[
            "enterprise_value", "equity_value", "pv_explicit_fcf", 
            "terminal_value_gordon", "terminal_value_exit_multiple",
            "wacc", "terminal_growth_rate", "exit_multiple",
            "share_price_implied", "upside_downside_pct"
        ],
    ),
    "multiples_valuation": AnalyticsSpec(
        name="multiples_valuation",
        description="Relative valuation using peer multiples (EV/EBITDA, P/E, P/B, EV/Sales)",
        requires=[
            "IS.revenue_from_operations",
        ],
        returns="Dict[str, Any]",  # {implied_ev_ebitda, implied_pe, implied_pb, implied_ev_sales, peer_median_*}
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="INR_cr",
        metadata_keys=[
            "peer_median_ev_ebitda", "peer_median_pe", "peer_median_pb", "peer_median_ev_sales",
            "implied_equity_value_ev_ebitda", "implied_equity_value_pe", "implied_equity_value_pb",
        ],
    ),
    "football_field": AnalyticsSpec(
        name="football_field",
        description="Football field chart data: DCF range, multiples range, 52-week range, analyst targets",
        requires=[],
        returns="Dict[str, List[Dict]]",  # {ranges: [{label, low, high, color}]}
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="INR_cr",
        metadata_keys=["dcf_range", "multiples_range", "market_range", "analyst_range"],
    ),
    "sensitivity_grid": AnalyticsSpec(
        name="sensitivity_grid",
        description="2D sensitivity table: Equity value vs (WACC x Terminal Growth) or (WACC x Exit Multiple)",
        requires=[],
        returns="Dict[str, Any]",  # {wacc_range, growth_range, grid: [[values]]}
        period_alignment=PeriodAlignment.PROJECTED,
        output_unit="INR_cr",
        metadata_keys=["wacc_range", "growth_range", "grid"],
    ),
    
    # -----------------------------------------------------------------------------
    # FORECAST ANALYTICS (core/analytics/forecast.py)
    # -----------------------------------------------------------------------------
    "project_is_bs_cf": AnalyticsSpec(
        name="project_is_bs_cf",
        description="5-year projected Income Statement, Balance Sheet, Cash Flow from assumptions",
        requires=[
            "IS.revenue_from_operations",
        ],
        returns="Dict[str, Any]",  # {is_projected, bs_projected, cf_projected, assumptions_used}
        period_alignment=PeriodAlignment.PROJECTED,
        output_unit="INR_cr",
        metadata_keys=[
            "projected_periods", "revenue_growth_assumptions", "ebitda_margin_assumptions",
            "capex_assumptions", "wc_assumptions", "debt_assumptions", "equity_assumptions"
        ],
    ),
    
    # -----------------------------------------------------------------------------
    # RISK ANALYTICS (core/analytics/risk.py)
    # -----------------------------------------------------------------------------
    "financial_risk_flags": AnalyticsSpec(
        name="financial_risk_flags",
        description="Automated financial risk flags: liquidity, solvency, profitability deterioration",
        requires=[
            "BS.current_assets", "BS.current_liabilities",
            "BS.total_debt", "BS.total_equity", "BS.cash_and_equivalents",
            "IS.ebitda", "IS.finance_costs", "IS.profit_after_tax",
            "IS.revenue_from_operations",
        ],
        returns="List[Dict]",  # [{flag_id, severity, description, current_value, threshold, period}]
        period_alignment=PeriodAlignment.SAME,
        output_unit="flag",
        metadata_keys=["flag_id", "severity", "category", "current_value", "threshold"],
    ),
    "market_risk_metrics": AnalyticsSpec(
        name="market_risk_metrics",
        description="Volatility, beta, max drawdown, VaR from price history",
        requires=[],  # Uses external price data, not facts
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="mixed",
        metadata_keys=["volatility_annual", "beta", "max_drawdown", "var_95", "sharpe"],
    ),
    "concentration_risk": AnalyticsSpec(
        name="concentration_risk",
        description="Revenue/segment/customer/geography concentration (HHI, top-N share)",
        requires=["SEGMENT.segment_revenue"],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="ratio",
        metadata_keys=["hhi", "top1_share", "top3_share", "top5_share"],
    ),
    "sensitivity_analysis": AnalyticsSpec(
        name="sensitivity_analysis",
        description="Tornado chart data: impact of ±X% change in drivers on a target metric",
        requires=["IS.revenue_from_operations", "IS.ebitda"],
        returns="Dict[str, Any]",
        period_alignment=PeriodAlignment.SAME,
        output_unit="mixed",
        metadata_keys=["base_metric", "tornado"],
    ),
    
    # -----------------------------------------------------------------------------
    # INDUSTRY ANALYTICS (core/analytics/industry.py)
    # -----------------------------------------------------------------------------
    "peer_benchmark": AnalyticsSpec(
        name="peer_benchmark",
        description="Peer comparison table: key metrics vs. selected peers",
        requires=[
            "IS.revenue_from_operations", "IS.ebitda", "IS.profit_after_tax",
            "BS.total_assets", "BS.total_equity", "BS.total_debt",
        ],
        returns="Dict[str, Any]",  # {peers: [{name, metrics}], target: {metrics}, percentiles}
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="mixed",
        metadata_keys=["peers", "target_percentile", "metric_comparison"],
    ),
    "market_size_growth": AnalyticsSpec(
        name="market_size_growth",
        description="Market size, growth rate, market share from industry reports",
        requires=[],  # External data
        returns="Dict[str, Any]",
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="INR_cr",
        metadata_keys=["market_size", "market_growth", "market_share", "tam", "sam", "som"],
    ),
    "industry_concentration": AnalyticsSpec(
        name="industry_concentration",
        description="Industry concentration via HHI and CR4/CR8",
        requires=[],  # External peer market share data
        returns="Dict[str, Any]",
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="ratio",
        metadata_keys=["hhi", "cr4", "cr8", "market_structure", "competitor_count", "leader_share"],
    ),
    
    # -----------------------------------------------------------------------------
    # PORTFOLIO ANALYTICS (core/analytics/portfolio.py) — Report #10 only
    # -----------------------------------------------------------------------------
    "xirr": AnalyticsSpec(
        name="xirr",
        description="Extended Internal Rate of Return for irregular cash flows",
        requires=[],  # Uses holdings/transactions, not facts
        returns="float",
        period_alignment=PeriodAlignment.AGGREGATE,
        output_unit="percentage",
        metadata_keys=["cash_flows", "dates"],
    ),
    "portfolio_allocation": AnalyticsSpec(
        name="portfolio_allocation",
        description="Current allocation by sector, market cap, geography",
        requires=[],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.CROSS_SECTIONAL,
        output_unit="percentage",
        metadata_keys=["by_sector", "by_market_cap", "by_geography"],
    ),
    "portfolio_attribution": AnalyticsSpec(
        name="portfolio_attribution",
        description="Brinson attribution: allocation + selection + interaction effects",
        requires=[],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.AGGREGATE,
        output_unit="percentage",
        metadata_keys=["allocation_effect", "selection_effect", "interaction_effect", "total_active_return"],
    ),
    "drawdown_analysis": AnalyticsSpec(
        name="drawdown_analysis",
        description="Max drawdown, drawdown duration, recovery time, underwater chart",
        requires=[],
        returns="Dict[str, Any]",
        period_alignment=PeriodAlignment.AGGREGATE,
        output_unit="mixed",
        metadata_keys=["max_drawdown", "max_drawdown_date", "recovery_date", "duration_days", "underwater_curve"],
    ),
    "benchmark_comparison": AnalyticsSpec(
        name="benchmark_comparison",
        description="Portfolio vs benchmark: excess return, tracking error, information ratio",
        requires=[],
        returns="Dict[str, float]",
        period_alignment=PeriodAlignment.AGGREGATE,
        output_unit="mixed",
        metadata_keys=["excess_return", "tracking_error", "information_ratio", "beta", "alpha"],
    ),
}


# =============================================================================
# REGISTRY HELPERS
# =============================================================================

def get_spec(name: str) -> AnalyticsSpec:
    """Get analytics spec by name. Raises KeyError if not found."""
    if name not in ANALYTICS_REGISTRY:
        raise KeyError(f"Analytics function '{name}' not registered. Available: {list(ANALYTICS_REGISTRY.keys())}")
    return ANALYTICS_REGISTRY[name]


def validate_template_analytics(template_sections: List[Dict]) -> List[str]:
    """
    Validate that all analytics referenced in a template exist in registry.
    Returns list of errors (empty if valid).
    """
    errors = []
    for section in template_sections:
        for analytics_name in section.get("analytics", []):
            if analytics_name not in ANALYTICS_REGISTRY:
                errors.append(f"Section '{section.get('key')}': unknown analytics '{analytics_name}'")
    return errors


def get_required_facts_for_template(template_sections: List[Dict]) -> Dict[str, List[str]]:
    """
    Aggregate all required facts for a template.
    Returns: {section_key: [fact_keys]}
    """
    result = {}
    for section in template_sections:
        section_key = section.get("key")
        required = set()
        for analytics_name in section.get("analytics", []):
            spec = get_spec(analytics_name)
            required.update(spec.requires)
        result[section_key] = sorted(required)
    return result


def get_analytics_by_statement(statement: StatementType) -> List[str]:
    """Get all analytics that require facts from a specific statement."""
    result = []
    for name, spec in ANALYTICS_REGISTRY.items():
        if any(req.startswith(f"{statement.value}.") for req in spec.requires):
            result.append(name)
    return result


def get_analytics_by_output_unit(unit: str) -> List[str]:
    """Get all analytics producing a specific output unit."""
    return [name for name, spec in ANALYTICS_REGISTRY.items() if spec.output_unit == unit]


# =============================================================================
# RUNTIME VALIDATION (called by template runner)
# =============================================================================

class AnalyticsExecutor:
    """
    Executes analytics functions with validated inputs.
    Imports actual implementation from core.analytics.* modules.
    """
    
    def __init__(self):
        self._function_cache: Dict[str, Callable] = {}
    
    def _get_function(self, name: str) -> Callable:
        """Lazy import of analytics function."""
        if name in self._function_cache:
            return self._function_cache[name]
        
        spec = get_spec(name)
        
        # Map analytics name to module
        module_map = {
            # growth
            "yoy_growth": "core.analytics.growth",
            "cagr": "core.analytics.growth",
            "quarterly_trend": "core.analytics.growth",
            # ratios
            "profitability_ratios": "core.analytics.ratios",
            "leverage_ratios": "core.analytics.ratios",
            "efficiency_ratios": "core.analytics.ratios",
            "dupont_analysis": "core.analytics.ratios",
            "common_size_statements": "core.analytics.ratios",
            # credit
            "debt_equity": "core.analytics.credit",
            "net_debt_ebitda": "core.analytics.credit",
            "icr": "core.analytics.credit",
            "dscr": "core.analytics.credit",
            "altman_z_score": "core.analytics.credit",
            "internal_rating": "core.analytics.credit",
            "covenant_headroom": "core.analytics.credit",
            # valuation
            "dcf_fcff": "core.analytics.valuation",
            "multiples_valuation": "core.analytics.valuation",
            "football_field": "core.analytics.valuation",
            "sensitivity_grid": "core.analytics.valuation",
            # forecast
            "project_is_bs_cf": "core.analytics.forecast",
            # risk
            "financial_risk_flags": "core.analytics.risk",
            "market_risk_metrics": "core.analytics.risk",
            "concentration_risk": "core.analytics.risk",
            "sensitivity_analysis": "core.analytics.risk",
            # industry
            "peer_benchmark": "core.analytics.industry",
            "market_size_growth": "core.analytics.industry",
            "industry_concentration": "core.analytics.industry",
            # portfolio
            "xirr": "core.analytics.portfolio",
            "portfolio_allocation": "core.analytics.portfolio",
            "portfolio_attribution": "core.analytics.portfolio",
            "drawdown_analysis": "core.analytics.portfolio",
            "benchmark_comparison": "core.analytics.portfolio",
        }
        
        if name not in module_map:
            raise ValueError(f"No module mapping for analytics: {name}")
        
        module = __import__(module_map[name], fromlist=[name])
        func = getattr(module, name)
        self._function_cache[name] = func
        return func
    
    def execute(
        self,
        name: str,
        facts: List[Fact],
        assumptions: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> Any:
        """
        Execute analytics function with validated inputs.
        
        Args:
            name: Analytics function name
            facts: List of Fact objects (from FactRepo)
            assumptions: Dict of assumption values (for forecast/valuation)
            context: Additional context (peer data, price history, etc.)
            
        Returns:
            Analytics result (type per spec)
            
        Raises:
            ValueError: If required facts missing
        """
        spec = get_spec(name)
        
        # Validate required facts
        missing = spec.validate_facts_available(facts)
        if missing:
            raise ValueError(f"Analytics '{name}' missing required facts: {missing}")
        
        func = self._get_function(name)
        
        # Build kwargs based on function signature
        sig = inspect.signature(func)
        kwargs = {}
        
        if "facts" in sig.parameters:
            kwargs["facts"] = facts
        if "assumptions" in sig.parameters and assumptions:
            kwargs["assumptions"] = assumptions
        if "context" in sig.parameters and context:
            kwargs["context"] = context

        # Unpack matching keys from context if expected as direct parameters
        if context and isinstance(context, dict):
            for param_name in sig.parameters:
                if param_name not in kwargs and param_name in context:
                    kwargs[param_name] = context[param_name]

        # Unpack matching keys from assumptions if expected as direct parameters
        if assumptions and isinstance(assumptions, dict):
            for param_name in sig.parameters:
                if param_name not in kwargs and param_name in assumptions:
                    kwargs[param_name] = assumptions[param_name]

        # For functions that expect specific fact lists, filter
        for param_name in sig.parameters:
            if param_name.endswith("_facts") or param_name in ["revenue_facts", "ebitda_facts", "debt_facts"]:
                line_item = param_name.replace("_facts", "").upper()
                # Find matching facts
                matched = [f for f in facts if f.line_item.lower() == line_item.lower()]
                if matched:
                    kwargs[param_name] = matched

        return func(**kwargs)


# Global executor instance
_executor: Optional[AnalyticsExecutor] = None


def get_executor() -> AnalyticsExecutor:
    global _executor
    if _executor is None:
        _executor = AnalyticsExecutor()
    return _executor


# =============================================================================
# TEMPLATE USAGE EXAMPLE
# =============================================================================

"""
Example template section (templates/reports/credit_analysis.json):

{
  "key": "leverage",
  "title": "Leverage Profile",
  "analytics": ["debt_equity", "net_debt_ebitda"],
  "needs": ["BS.total_debt", "BS.total_equity", "BS.cash_and_equivalents", "IS.ebitda"],
  "prompt": "credit/leverage.md",
  "max_words": 250,
  "chart": "leverage_trend"
}

Runner flow:
1. Load template
2. validate_template_analytics(template["sections"]) → []
3. get_required_facts_for_template(template["sections"]) → 
   {"leverage": ["BS.total_debt", "BS.total_equity", "BS.cash_and_equivalents", "IS.ebitda"], ...}
4. Fetch facts from FactRepo for company
5. For each section:
   - For each analytics in section["analytics"]:
     - executor.execute(analytics, facts, assumptions, context)
   - Build prompt context with results
   - Call router.call(TaskType.WRITE, ...)
"""

if __name__ == "__main__":
    # Print registry summary
    print(f"Total analytics functions: {len(ANALYTICS_REGISTRY)}")
    print("\nBy category:")
    categories = {}
    for name, spec in ANALYTICS_REGISTRY.items():
        cat = name.split("_")[0] if "_" in name else name
        categories.setdefault(cat, []).append(name)
    
    for cat, names in sorted(categories.items()):
        print(f"  {cat}: {len(names)} functions")
        for n in names:
            spec = ANALYTICS_REGISTRY[n]
            print(f"    - {n}: requires={spec.requires}, returns={spec.returns}")