"""
FinGen v2 — Growth Analytics
Pure Python, no LLM. Input: Fact objects from FactRepo.
"""

from typing import List, Dict, Optional
from collections import defaultdict

from core.schema import Fact, AnalyticsResult


def _group_by_line_item(facts: List[Fact]) -> Dict[str, List[Fact]]:
    """Group facts by line_item."""
    grouped = defaultdict(list)
    for f in facts:
        grouped[f.line_item].append(f)
    return grouped


def _sort_by_period(facts: List[Fact]) -> List[Fact]:
    """Sort facts by period. Handles FY, Q formats."""
    def period_key(f: Fact):
        p = f.period.upper()
        # FY24 -> 202400, Q1FY25 -> 202501, etc.
        if p.startswith("FY"):
            try:
                return int(p[2:]) * 100
            except:
                return 0
        if p.startswith("Q") and "FY" in p:
            try:
                q = int(p[1])
                fy = int(p.split("FY")[1])
                return fy * 100 + q
            except:
                return 0
        # Try parsing as date
        try:
            from datetime import datetime
            return int(datetime.strptime(p, "%Y-%m-%d").strftime("%Y%m"))
        except:
            return 0
    return sorted(facts, key=period_key)


def yoy_growth(facts: List[Fact], line_items: List[str] = None) -> AnalyticsResult:
    """
    Year-over-year growth rate for specified line items.
    Returns: {line_item: {period: growth_rate_decimal}}
    """
    grouped = _group_by_line_item(facts)
    results = {}
    metadata = {}
    
    for item, item_facts in grouped.items():
        if line_items and item not in line_items:
            continue
        
        sorted_facts = _sort_by_period(item_facts)
        if len(sorted_facts) < 2:
            continue
        
        growth = {}
        for i in range(1, len(sorted_facts)):
            curr = sorted_facts[i]
            prev = sorted_facts[i - 1]
            
            # Only calculate YoY for comparable periods (both FY or both same quarter)
            if _comparable_periods(prev.period, curr.period):
                if prev.value != 0:
                    rate = (curr.value - prev.value) / abs(prev.value)
                    growth[curr.period] = rate
                    metadata.setdefault(item, []).append({
                        "current_period": curr.period,
                        "base_period": prev.period,
                        "current_value": curr.value,
                        "base_value": prev.value,
                        "growth_rate": rate,
                    })
        
        if growth:
            results[item] = growth
    
    return AnalyticsResult(metrics=results, metadata=metadata)


def cagr(facts: List[Fact], line_items: List[str] = None, periods_back: int = 5) -> AnalyticsResult:
    """
    Compound Annual Growth Rate over N periods.
    Returns: {line_item: cagr_decimal}
    """
    grouped = _group_by_line_item(facts)
    results = {}
    metadata = {}
    
    for item, item_facts in grouped.items():
        if line_items and item not in line_items:
            continue
        
        sorted_facts = _sort_by_period(item_facts)
        if len(sorted_facts) < 2:
            continue
        
        # Use last N periods
        relevant = sorted_facts[-periods_back:] if len(sorted_facts) >= periods_back else sorted_facts
        start = relevant[0]
        end = relevant[-1]
        
        if start.value > 0:
            years = _periods_between(start.period, end.period)
            if years > 0:
                cagr_val = (end.value / start.value) ** (1 / years) - 1
                results[item] = cagr_val
                metadata[item] = {
                    "start_period": start.period,
                    "end_period": end.period,
                    "start_value": start.value,
                    "end_value": end.value,
                    "years": years,
                }
    
    return AnalyticsResult(metrics=results, metadata=metadata)


def quarterly_trend(facts: List[Fact], line_items: List[str] = None) -> AnalyticsResult:
    """
    Quarterly trend analysis: QoQ growth, trend direction, seasonality.
    """
    grouped = _group_by_line_item(facts)
    results = {}
    
    for item, item_facts in grouped.items():
        if line_items and item not in line_items:
            continue
        
        # Filter quarterly facts
        q_facts = [f for f in item_facts if _is_quarterly(f.period)]
        if len(q_facts) < 3:
            continue
        
        sorted_facts = _sort_by_period(q_facts)
        
        # QoQ growth
        qoq = {}
        for i in range(1, len(sorted_facts)):
            curr = sorted_facts[i]
            prev = sorted_facts[i - 1]
            if prev.value != 0:
                qoq[curr.period] = (curr.value - prev.value) / abs(prev.value)
        
        # Trend direction (last 4 quarters)
        recent = sorted_facts[-4:] if len(sorted_facts) >= 4 else sorted_facts
        if len(recent) >= 2:
            first_val = recent[0].value
            last_val = recent[-1].value
            if first_val != 0:
                trend_pct = (last_val - first_val) / abs(first_val)
                if trend_pct > 0.05:
                    trend = "improving"
                elif trend_pct < -0.05:
                    trend = "deteriorating"
                else:
                    trend = "stable"
            else:
                trend = "unknown"
        else:
            trend = "insufficient_data"
        
        # Simple seasonality: average QoQ by quarter number
        seasonality = {}
        for f in sorted_facts:
            q_num = _extract_quarter(f.period)
            if q_num:
                seasonality.setdefault(q_num, []).append(f.value)
        
        seasonality_idx = {}
        for q, vals in seasonality.items():
            if len(vals) > 1:
                avg = sum(vals) / len(vals)
                overall_avg = sum(v for vs in seasonality.values() for v in vs) / sum(len(vs) for vs in seasonality.values())
                seasonality_idx[f"Q{q}"] = avg / overall_avg if overall_avg else 1.0
        
        results[item] = {
            "qoq_growth": qoq,
            "trend": trend,
            "seasonality_index": seasonality_idx,
        }
    
    return AnalyticsResult(metrics=results, metadata={})


# Helper functions
def _comparable_periods(p1: str, p2: str) -> bool:
    """Check if two periods are comparable (both FY, both same quarter, etc.)."""
    p1_u, p2_u = p1.upper(), p2.upper()
    
    # Both FY
    if p1_u.startswith("FY") and p2_u.startswith("FY"):
        return True
    
    # Both same quarter format
    if "Q" in p1_u and "Q" in p2_u and "FY" in p1_u and "FY" in p2_u:
        q1 = p1_u.split("FY")[0]
        q2 = p2_u.split("FY")[0]
        return q1 == q2
    
    return False


def _periods_between(p1: str, p2: str) -> float:
    """Estimate years between two periods."""
    def parse_year(p):
        p = p.upper()
        if p.startswith("FY"):
            try:
                return int(p[2:]) + 2000 if int(p[2:]) < 50 else int(p[2:])
            except:
                return 0
        if "FY" in p:
            try:
                return int(p.split("FY")[1]) + 2000 if int(p.split("FY")[1]) < 50 else int(p.split("FY")[1])
            except:
                return 0
        try:
            from datetime import datetime
            return datetime.strptime(p, "%Y-%m-%d").year
        except:
            return 0
    
    y1, y2 = parse_year(p1), parse_year(p2)
    return max(1, abs(y2 - y1))


def _is_quarterly(period: str) -> bool:
    p = period.upper()
    return p.startswith("Q") and "FY" in p


def _extract_quarter(period: str) -> Optional[int]:
    p = period.upper()
    if p.startswith("Q") and "FY" in p:
        try:
            return int(p[1])
        except:
            return None
    return None