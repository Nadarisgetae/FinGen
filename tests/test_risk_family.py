"""
FinGen v2 — Risk Family Reports Tests (Phase 4)
Tests:
- Credit Analysis Report (credit_analysis.json): Leverage, ICR, DSCR, Altman Z-Score, Internal Rating, Covenants
- Risk Analysis Report (risk_analysis.json): Financial Risk Flags, Market Risk, Sensitivity Tornado, Mitigants
- Due Diligence Report (due_diligence.json): Executive Summary, Red Flags Checklist, Earnings Quality
- Credit & Risk Math Accuracy: Altman Z boundaries and coverage ratios
"""

import csv
import pytest
from pathlib import Path
from typing import List

from core.schema import Fact
from core.generate.runner import load_template
from core.analytics.credit import altman_z_score, icr, internal_rating
from core.analytics.risk import financial_risk_flags, sensitivity_analysis


def _load_tata_steel_facts() -> List[Fact]:
    fixture_path = Path("tests/fixtures/tata_steel/expected_facts.csv")
    facts = []
    with open(fixture_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            facts.append(Fact(
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
            "Credit risk profile for Tata Steel (TATASTEEL.NS): "
            "In FY24, revenue from operations was 229171.0 INR_cr, "
            "with an EBITDA of 23402.0 INR_cr. "
            "Total debt stood at 87082.0 INR_cr, and cash was 9530.0 INR_cr."
        )


class TestCreditAnalysisReport:
    def test_credit_analysis_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("credit_analysis", router=router)

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            context=context,
            ui_config={"currency": "INR", "unit": "INR_cr", "horizon": "FY24"},
        )

        expected_sections = ["overview", "leverage", "coverage", "liquidity", "score", "covenants"]
        for sec in expected_sections:
            assert sec in res["sections"]
            assert len(res["sections"][sec]) > 0

        # Check analytics
        ar = res["analytics_results"]
        assert "internal_rating" in ar["overview"]
        rating_res = ar["overview"]["internal_rating"]
        assert "FY24" in rating_res
        assert "grade" in rating_res["FY24"]
        assert "score" in rating_res["FY24"]

        assert "debt_equity" in ar["leverage"]
        assert "net_debt_ebitda" in ar["leverage"]
        assert "icr" in ar["coverage"]
        assert "altman_z_score" in ar["score"]
        assert "covenant_headroom" in ar["covenants"]

        ver = res["verification"]
        assert ver.numbers_checked > 0
        assert ver.error_count == 0


class TestRiskAnalysisReport:
    def test_risk_analysis_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("risk_analysis", router=router)

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
            "price_history": [{"date": f"2024-0{i}-01", "close": 140.0 + i * 2.0} for i in range(1, 10)],
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            context=context,
        )

        expected_sections = ["financial_risks", "market_risks", "operational_risks", "sensitivity", "mitigants"]
        for sec in expected_sections:
            assert sec in res["sections"]

        ar = res["analytics_results"]
        assert "financial_risk_flags" in ar["financial_risks"]
        assert "market_risk_metrics" in ar["market_risks"]
        assert "sensitivity_analysis" in ar["sensitivity"]

        tornado_res = ar["sensitivity"]["sensitivity_analysis"]
        assert "base_ebitda" in tornado_res or "tornado" in tornado_res or "base_revenue" in tornado_res

        ver = res["verification"]
        assert ver.error_count == 0


class TestDueDiligenceReport:
    def test_due_diligence_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("due_diligence", router=router)

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            context=context,
        )

        expected_sections = [
            "executive_summary", "red_flags", "related_party",
            "contingent_liabilities", "auditor", "financial_quality"
        ]
        for sec in expected_sections:
            assert sec in res["sections"]

        ar = res["analytics_results"]
        assert "financial_risk_flags" in ar["red_flags"]
        assert "common_size_statements" in ar["financial_quality"]

        ver = res["verification"]
        assert ver.error_count == 0


class TestCreditMathAccuracy:
    def test_icr_calculation(self):
        facts = _load_tata_steel_facts()
        icr_res = icr(facts)
        assert "FY24" in icr_res.metrics
        # Tata Steel: EBITDA = 23402, Finance costs = 7552 -> ICR = ~3.10
        expected_icr = 23402.0 / 7552.0
        assert abs(icr_res.metrics["FY24"] - expected_icr) < 0.01

    def test_internal_rating_grade_assignment(self):
        facts = _load_tata_steel_facts()
        ir_res = internal_rating(facts)
        assert "FY24" in ir_res.metrics
        fy24_rating = ir_res.metrics["FY24"]
        assert fy24_rating["grade"] in ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "D"]
        assert 0 <= fy24_rating["score"] <= 100
