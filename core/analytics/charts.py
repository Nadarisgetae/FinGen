"""
FinGen v2 — Chart Registry
Matplotlib charts for embedding in docx/pdf exports.
Each chart function returns a PNG bytes buffer.
"""

import io
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Brand palette
COLORS = {
    "primary": "#2563EB",
    "success": "#16A34A",
    "warning": "#F59E0B",
    "danger": "#DC2626",
    "muted": "#94A3B8",
    "dark": "#0F172A",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": "#E2E8F0",
    "axes.grid": True,
    "grid.color": "#E2E8F0",
    "grid.linewidth": 0.5,
    "figure.facecolor": "white",
})


def _to_png(fig, dpi: int = 150) -> bytes:
    """Render figure to PNG bytes."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# =============================================================================
# Chart functions — each returns PNG bytes
# =============================================================================

def leverage_trend(periods: List[str], debt_equity: List[float], net_debt_ebitda: List[float]) -> bytes:
    """Dual-axis leverage trend chart."""
    fig, ax1 = plt.subplots(figsize=(8, 4))

    x = range(len(periods))
    ax1.bar([i - 0.2 for i in x], debt_equity, width=0.4, color=COLORS["primary"], label="Debt/Equity", alpha=0.85)
    ax1.set_ylabel("Debt/Equity (x)", color=COLORS["primary"])
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(periods, rotation=45, ha="right")

    ax2 = ax1.twinx()
    ax2.plot([i + 0.2 for i in x], net_debt_ebitda, color=COLORS["warning"], marker="o", label="Net Debt/EBITDA", linewidth=2)
    ax2.set_ylabel("Net Debt/EBITDA (x)", color=COLORS["warning"])
    ax2.grid(False)

    fig.suptitle("Leverage Trend", fontsize=12, fontweight="bold", color=COLORS["dark"])
    fig.tight_layout()
    return _to_png(fig)


def coverage_trend(periods: List[str], icr: List[float], dscr: Optional[List[float]] = None) -> bytes:
    """Interest coverage trend with 2.0x threshold line."""
    fig, ax = plt.subplots(figsize=(8, 4))

    ax.plot(periods, icr, color=COLORS["primary"], marker="o", linewidth=2, label="Interest Coverage")
    if dscr:
        ax.plot(periods, dscr, color=COLORS["success"], marker="s", linewidth=2, label="DSCR")

    ax.axhline(y=2.0, color=COLORS["danger"], linestyle="--", alpha=0.7, label="2.0x threshold")
    ax.set_ylabel("Coverage (x)")
    ax.set_title("Coverage Ratios Trend", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.legend()
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    return _to_png(fig)


def dupont_decomposition(periods: List[str], net_margin: List[float], asset_turnover: List[float], financial_leverage: List[float]) -> bytes:
    """Stacked/grouped DuPont components."""
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(periods))
    width = 0.25

    ax.bar([i - width for i in x], net_margin, width, color=COLORS["primary"], label="Net Margin")
    ax.bar(x, asset_turnover, width, color=COLORS["success"], label="Asset Turnover")
    ax.bar([i + width for i in x], financial_leverage, width, color=COLORS["warning"], label="Financial Leverage")

    ax.set_xticks(list(x))
    ax.set_xticklabels(periods, rotation=45, ha="right")
    ax.set_title("DuPont Decomposition", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.legend()
    fig.tight_layout()
    return _to_png(fig)


def football_field(ranges: List[Dict]) -> bytes:
    """
    Football field valuation chart.
    ranges = [{"label": "DCF", "low": 100, "high": 150, "color": "#2563EB"}, ...]
    """
    fig, ax = plt.subplots(figsize=(8, max(3, len(ranges) * 0.7)))

    for i, r in enumerate(ranges):
        ax.barh(i, r["high"] - r["low"], left=r["low"], color=r.get("color", COLORS["primary"]), alpha=0.85, height=0.5)
        ax.text(r["low"], i, f"  {r['low']:,.0f}", va="center", fontsize=9)
        ax.text(r["high"], i, f"{r['high']:,.0f}  ", va="center", ha="right", fontsize=9)

    ax.set_yticks(range(len(ranges)))
    ax.set_yticklabels([r["label"] for r in ranges])
    ax.set_xlabel("Equity Value (INR cr)")
    ax.set_title("Valuation Football Field", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _to_png(fig)


def sensitivity_tornado(tornado: List[Dict], base_metric: float) -> bytes:
    """
    Tornado chart for sensitivity analysis.
    tornado = [{"driver": ..., "low_case": ..., "high_case": ..., "swing": ...}, ...]
    """
    fig, ax = plt.subplots(figsize=(8, max(3, len(tornado) * 0.6)))

    drivers = [t["driver"] for t in tornado]
    lows = [t["low_case"] for t in tornado]
    highs = [t["high_case"] for t in tornado]

    y = range(len(drivers))
    ax.barh(y, [h - l for h, l in zip(highs, lows)], left=lows, color=COLORS["primary"], alpha=0.85, height=0.5)
    ax.axvline(base_metric, color=COLORS["dark"], linestyle="--", linewidth=1.5, label="Base case")

    ax.set_yticks(list(y))
    ax.set_yticklabels(drivers)
    ax.set_title("Sensitivity Analysis", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.legend()
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return _to_png(fig)


def xirr_curve(values: List[Dict]) -> bytes:
    """Portfolio value over time with drawdown shading."""
    dates = [v["date"] for v in values]
    vals = [v["value"] for v in values]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, vals, color=COLORS["primary"], linewidth=2)
    ax.fill_between(dates, vals, alpha=0.15, color=COLORS["primary"])

    ax.set_ylabel("Portfolio Value (INR)")
    ax.set_title("Portfolio Value Over Time", fontsize=12, fontweight="bold", color=COLORS["dark"])
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    return _to_png(fig)


def allocation_pie(by_sector: Dict[str, float]) -> bytes:
    """Portfolio allocation pie chart."""
    labels = list(by_sector.keys())
    sizes = list(by_sector.values())

    fig, ax = plt.subplots(figsize=(6, 6))
    palette = [COLORS["primary"], COLORS["success"], COLORS["warning"], COLORS["danger"], COLORS["muted"], "#8B5CF6", "#EC4899", "#14B8A6"]
    ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=palette[:len(labels)], startangle=90)
    ax.set_title("Allocation by Sector", fontsize=12, fontweight="bold", color=COLORS["dark"])
    fig.tight_layout()
    return _to_png(fig)


def margin_trend(periods: List[str], gross: List[float], ebitda: List[float], pat: List[float]) -> bytes:
    """Margin trend lines."""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(periods, [g * 100 for g in gross], marker="o", label="Gross Margin", color=COLORS["primary"], linewidth=2)
    ax.plot(periods, [e * 100 for e in ebitda], marker="s", label="EBITDA Margin", color=COLORS["success"], linewidth=2)
    ax.plot(periods, [p * 100 for p in pat], marker="^", label="PAT Margin", color=COLORS["warning"], linewidth=2)

    ax.set_ylabel("Margin (%)")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(decimals=0))
    ax.set_title("Margin Trends", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.legend()
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    return _to_png(fig)


def growth_bars(periods: List[str], revenue: List[float], pat: List[float]) -> bytes:
    """Revenue and PAT growth bars."""
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(periods))
    width = 0.35
    ax.bar([i - width / 2 for i in x], revenue, width, color=COLORS["primary"], label="Revenue", alpha=0.85)
    ax.bar([i + width / 2 for i in x], pat, width, color=COLORS["success"], label="PAT", alpha=0.85)
    ax.set_xticks(list(x))
    ax.set_xticklabels(periods, rotation=45, ha="right")
    ax.set_ylabel("INR cr")
    ax.set_title("Revenue & PAT", fontsize=12, fontweight="bold", color=COLORS["dark"])
    ax.legend()
    fig.tight_layout()
    return _to_png(fig)


# =============================================================================
# Chart Registry
# =============================================================================

CHART_REGISTRY = {
    "leverage_trend": leverage_trend,
    "coverage_trend": coverage_trend,
    "dupont_decomposition": dupont_decomposition,
    "football_field": football_field,
    "sensitivity_tornado": sensitivity_tornado,
    "xirr_curve": xirr_curve,
    "allocation_pie": allocation_pie,
    "margin_trend": margin_trend,
    "growth_bars": growth_bars,
}


def get_chart(chart_name: str, **kwargs) -> Optional[bytes]:
    """Get chart PNG bytes by registry name."""
    fn = CHART_REGISTRY.get(chart_name)
    if not fn:
        return None
    return fn(**kwargs)


def list_charts() -> List[str]:
    return list(CHART_REGISTRY.keys())