"""
FinGen v2 — Industry Analysis & Portfolio Performance Tests (Phases 5 & 6)
Tests:
- Industry Analysis Report (industry_analysis.json): TAM/SAM, Market CAGR, HHI Concentration, Peer Benchmarking
- Portfolio Performance Report (portfolio_performance.json): XIRR, Sector Allocation, Brinson Attribution, Drawdown
- Brinson Attribution Math: Allocation + Selection + Interaction = Total Active Return
"""

import csv
import pytest
from datetime import date
from pathlib import Path
from typing import List

from core.schema import Fact
from core.generate.runner import load_template
from core.analytics.industry import market_size_growth, industry_concentration, peer_benchmark
from core.analytics.portfolio import xirr, portfolio_allocation, portfolio_attribution, drawdown_analysis, benchmark_comparison


def _load_facts(company: str) -> List[Fact]:
    fixture_path = Path(f"tests/fixtures/{company}/expected_facts.csv")
    facts = []
    with open(fixture_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            facts.append(Fact(
                company_id=company,
                statement=row["statement"],
                line_item=row["line_item"],
                period=row["period"],
                value=float(row["value"]),
                unit=row["unit"],
                page=int(row["page"]) if row.get("page") else None,
            ))
    return facts


class MockRouter:
    """Mock router that outputs factual, consistent markdown for test verification."""

    def call(self, task, messages, schema=None):
        return (
            "Industry analysis indicates steady expansion with total addressable market of 500000.0 INR_cr. "
            "Reported company revenue stands at 229171.0 INR_cr, while portfolio holdings show total value of 100000.0 INR."
        )


class TestIndustryAnalysisReport:
    def test_industry_analysis_generation(self):
        tata_facts = _load_facts("tata_steel")
        reliance_facts = _load_facts("reliance")
        combined_facts = tata_facts + reliance_facts

        router = MockRouter()
        generator = load_template("industry_analysis", router=router)

        context = {
            "company_name": "Tata Steel Limited",
            "company_id": "tata_steel",
            "ticker": "TATASTEEL.NS",
            "market_data": {
                "total_addressable_market": 500000.0,
                "serviceable_addressable_market": 150000.0,
                "market_growth_rate": 0.08,
                "historical_market_size": {2020: 350000.0, 2024: 500000.0},
            },
            "peer_market_shares": {
                "Tata Steel": 0.28,
                "JSW Steel": 0.26,
                "SAIL": 0.18,
                "Jindal Steel": 0.12,
                "Others": 0.16,
            },
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=combined_facts,
            context=context,
            ui_config={"currency": "INR", "unit": "INR_cr"},
        )

        expected_sections = ["market", "structure", "peers", "drivers"]
        for sec in expected_sections:
            assert sec in res["sections"]
            assert len(res["sections"][sec]) > 0

        ar = res["analytics_results"]
        # Market size & growth
        market_res = ar["market"]["market_size_growth"]
        assert market_res["tam"] == 500000.0
        assert market_res["market_growth_rate"] == 0.08

        # Concentration
        struct_res = ar["structure"]["industry_concentration"]
        assert "hhi" in struct_res
        assert "market_structure" in struct_res

        # Peer benchmarking
        peer_res = ar["peers"]["peer_benchmark"]
        assert "target" in peer_res
        assert "peers" in peer_res

        ver = res["verification"]
        assert ver.error_count == 0


class TestPortfolioPerformanceReport:
    def test_portfolio_performance_generation(self):
        router = MockRouter()
        generator = load_template("portfolio_performance", router=router)

        context = {
            "transactions": [
                {"date": "2023-01-01", "amount": 50000.0, "type": "buy"},
                {"date": "2023-06-01", "amount": 20000.0, "type": "buy"},
                {"date": "2023-12-01", "amount": 5000.0, "type": "dividend"},
            ],
            "current_holdings_value": 100000.0,
            "holdings": [
                {"ticker": "TCS.NS", "current_value": 40000.0, "sector": "Technology", "market_cap": "Large"},
                {"ticker": "HDFCBANK.NS", "current_value": 35000.0, "sector": "Financials", "market_cap": "Large"},
                {"ticker": "TATASTEEL.NS", "current_value": 25000.0, "sector": "Materials", "market_cap": "Large"},
            ],
            "portfolio_values": [
                {"date": date(2023, 1, 1), "value": 50000.0},
                {"date": date(2023, 6, 1), "value": 75000.0},
                {"date": date(2023, 9, 1), "value": 70000.0},
                {"date": date(2023, 12, 31), "value": 100000.0},
            ],
            "portfolio_returns": [0.01, -0.005, 0.02, 0.015, -0.01],
            "benchmark_returns": [0.008, -0.002, 0.012, 0.01, -0.005],
            "portfolio_sector_returns": {"Technology": 0.15, "Financials": 0.10, "Materials": 0.05},
            "benchmark_sector_returns": {"Technology": 0.12, "Financials": 0.08, "Materials": 0.04},
            "portfolio_weights": {"Technology": 0.40, "Financials": 0.35, "Materials": 0.25},
            "benchmark_weights": {"Technology": 0.30, "Financials": 0.40, "Materials": 0.30},
        }

        res = generator.generate(
            user_id="test_user",
            facts=[],
            context=context,
        )

        expected_sections = ["performance", "allocation", "attribution", "drawdown"]
        for sec in expected_sections:
            assert sec in res["sections"]

        ar = res["analytics_results"]
        # XIRR
        xirr_res = ar["performance"]["xirr"]
        assert "xirr" in xirr_res
        assert xirr_res["xirr"] > 0

        # Allocation
        alloc_res = ar["allocation"]["portfolio_allocation"]
        assert alloc_res["total_value"] == 100000.0
        assert abs(sum(alloc_res["by_sector"].values()) - 1.0) < 1e-4

        # Attribution
        attr_res = ar["attribution"]["portfolio_attribution"]
        assert "allocation_effect" in attr_res
        assert "selection_effect" in attr_res
        assert "interaction_effect" in attr_res

        # Drawdown
        dd_res = ar["drawdown"]["drawdown_analysis"]
        assert "max_drawdown" in dd_res

        ver = res["verification"]
        assert ver.error_count == 0


class TestBrinsonAttributionMath:
    def test_brinson_components_sum_to_total_active(self):
        p_ret = {"Tech": 0.15, "Fin": 0.10, "Energy": -0.05}
        b_ret = {"Tech": 0.12, "Fin": 0.08, "Energy": -0.02}
        p_wt = {"Tech": 0.50, "Fin": 0.30, "Energy": 0.20}
        b_wt = {"Tech": 0.30, "Fin": 0.50, "Energy": 0.20}

        res = portfolio_attribution(p_ret, b_ret, p_wt, b_wt)
        m = res.metrics
        alloc = m["allocation_effect"]
        sel = m["selection_effect"]
        inter = m["interaction_effect"]
        total_active = m["total_active_return"]

        # Mathematical identity: Total Active = Allocation + Selection + Interaction
        assert abs((alloc + sel + inter) - total_active) < 1e-7
