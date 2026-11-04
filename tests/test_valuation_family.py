"""
FinGen v2 — Valuation Family Reports Tests (Phase 3)
Tests:
- Valuation Report (valuation.json): DCF, Relative Multiples, Football Field, Sensitivity Grid
- Financial Forecast Report (financial_forecast.json): 5-Year IS/BS/CF projections, Bull/Base/Bear scenarios
- Investment Research Report (investment_research.json): Thesis, Scenarios, Valuation, Risk/Reward
- Dynamic Assumption Propagation: WACC and Terminal Growth rate sensitivity
"""

import csv
import pytest
from pathlib import Path
from typing import List

from core.schema import Fact
from core.generate.runner import load_template
from core.analytics.valuation import dcf_fcff, sensitivity_grid, multiples_valuation, football_field
from core.analytics.forecast import project_is_bs_cf


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
            "Tata Steel (TATASTEEL.NS) financial projections indicate sustained cash generation. "
            "In FY24, reported revenue from operations was 229171.0 INR_cr, "
            "EBITDA reached 23402.0 INR_cr, with total debt of 87082.0 INR_cr "
            "and cash of 9530.0 INR_cr."
        )


class TestValuationReport:
    def test_valuation_report_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("valuation", router=router)

        assumptions = {
            "wacc": 0.115,
            "terminal_growth_rate": 0.04,
            "exit_multiple": 7.5,
            "projection_years": 5,
            "shares_outstanding": 1222.0,
        }

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
            "market_price": 150.0,
            "shares_outstanding": 1222.0,
            "52_week_low": 115.0,
            "52_week_high": 180.0,
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            assumptions=assumptions,
            context=context,
            ui_config={"currency": "INR", "unit": "INR_cr", "horizon": "5Y"},
        )

        # 1. Check sections
        expected_sections = ["methodology", "dcf", "multiples", "football_field"]
        for sec in expected_sections:
            assert sec in res["sections"]
            assert len(res["sections"][sec]) > 0

        # 2. Check analytics
        ar = res["analytics_results"]
        dcf_res = ar["dcf"]["dcf_fcff"]
        assert dcf_res["enterprise_value"] > 0
        assert dcf_res["equity_value"] > 0
        assert dcf_res["wacc"] == 0.115

        grid_res = ar["dcf"]["sensitivity_grid"]
        assert len(grid_res["grid"]) == 5  # 5x5 sensitivity table
        assert len(grid_res["grid"][0]) == 5

        mult_res = ar["multiples"]["multiples_valuation"]
        assert len(mult_res) > 0

        ff_res = ar["football_field"]["football_field"]
        assert "ranges" in ff_res
        assert len(ff_res["ranges"]) >= 2

        # 3. Check Verifier
        ver = res["verification"]
        assert ver.numbers_checked > 0
        assert ver.error_count == 0


class TestFinancialForecastReport:
    def test_forecast_report_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("financial_forecast", router=router)

        assumptions = {
            "projection_years": 5,
            "revenue_growth": [0.09, 0.08, 0.07, 0.06, 0.05],
            "ebitda_margin": [0.12, 0.13, 0.13, 0.14, 0.14],
            "tax_rate": 0.25,
            "capex_pct_revenue": 0.06,
            "scenario": "base",
        }

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            assumptions=assumptions,
            context=context,
            ui_config={"currency": "INR", "unit": "INR_cr", "horizon": "5Y"},
        )

        expected_sections = ["assumptions", "income_statement", "balance_sheet", "cash_flow", "scenarios"]
        for sec in expected_sections:
            assert sec in res["sections"]

        # Check IS projection
        is_analytics = res["analytics_results"]["income_statement"]["project_is_bs_cf"]
        assert len(is_analytics["is_projected"]) == 5
        assert is_analytics["is_projected"][0]["revenue"] > 229171.0  # FY24 base + growth
        assert is_analytics["is_projected"][0]["ebitda"] > 0
        assert is_analytics["is_projected"][0]["pat"] > 0

        # Check BS projection
        bs_analytics = res["analytics_results"]["balance_sheet"]["project_is_bs_cf"]
        assert len(bs_analytics["bs_projected"]) == 5
        assert bs_analytics["bs_projected"][0]["total_assets"] > 0
        assert bs_analytics["bs_projected"][0]["total_equity"] > 0

        # Check CF projection
        cf_analytics = res["analytics_results"]["cash_flow"]["project_is_bs_cf"]
        assert len(cf_analytics["cf_projected"]) == 5
        assert cf_analytics["cf_projected"][0]["cfo"] > 0

        # Check verification
        ver = res["verification"]
        assert ver.error_count == 0


class TestInvestmentResearchReport:
    def test_investment_research_generation(self):
        facts = _load_tata_steel_facts()
        router = MockRouter()
        generator = load_template("investment_research", router=router)

        assumptions = {
            "wacc": 0.115,
            "terminal_growth_rate": 0.04,
            "exit_multiple": 7.5,
            "projection_years": 5,
            "revenue_growth": [0.08, 0.08, 0.07, 0.06, 0.05],
            "ebitda_margin": [0.12, 0.13, 0.13, 0.14, 0.14],
        }

        context = {
            "company_name": "Tata Steel Limited",
            "ticker": "TATASTEEL.NS",
            "fiscal_year": "FY24",
            "price_history": [{"date": f"2024-0{i}-01", "close": 140.0 + i * 2.5} for i in range(1, 10)],
        }

        res = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            assumptions=assumptions,
            context=context,
        )

        expected_sections = ["thesis", "scenarios", "valuation", "risk_reward"]
        for sec in expected_sections:
            assert sec in res["sections"]

        # Check risk reward metrics
        rr_analytics = res["analytics_results"]["risk_reward"]
        assert "financial_risk_flags" in rr_analytics
        assert "market_risk_metrics" in rr_analytics
        market_metrics = rr_analytics["market_risk_metrics"]
        assert "volatility_annual" in market_metrics
        assert market_metrics["volatility_annual"] > 0

        ver = res["verification"]
        assert ver.error_count == 0


class TestAssumptionPropagation:
    def test_wacc_increase_lowers_dcf_equity_value(self):
        facts = _load_tata_steel_facts()
        
        low_wacc = dcf_fcff(facts, {"wacc": 0.10, "terminal_growth_rate": 0.04, "shares_outstanding": 1222.0})
        high_wacc = dcf_fcff(facts, {"wacc": 0.14, "terminal_growth_rate": 0.04, "shares_outstanding": 1222.0})

        ev_low = low_wacc.metrics["enterprise_value"]
        ev_high = high_wacc.metrics["enterprise_value"]
        assert ev_low > ev_high, f"Expected EV at 10% WACC ({ev_low}) > EV at 14% WACC ({ev_high})"

    def test_growth_increase_raises_dcf_equity_value(self):
        facts = _load_tata_steel_facts()
        
        low_g = dcf_fcff(facts, {"wacc": 0.12, "terminal_growth_rate": 0.02, "shares_outstanding": 1222.0})
        high_g = dcf_fcff(facts, {"wacc": 0.12, "terminal_growth_rate": 0.05, "shares_outstanding": 1222.0})

        ev_low = low_g.metrics["enterprise_value"]
        ev_high = high_g.metrics["enterprise_value"]
        assert ev_high > ev_low, f"Expected EV at 5% g ({ev_high}) > EV at 2% g ({ev_low})"

    def test_bull_base_bear_forecast_divergence(self):
        facts = _load_tata_steel_facts()

        base_res = project_is_bs_cf(facts, {"revenue_growth": [0.08] * 5, "ebitda_margin": [0.15] * 5})
        bull_res = project_is_bs_cf(facts, {"revenue_growth": [0.16] * 5, "ebitda_margin": [0.22] * 5})
        bear_res = project_is_bs_cf(facts, {"revenue_growth": [0.01] * 5, "ebitda_margin": [0.08] * 5})

        rev_base_y5 = base_res.metrics["is_projected"][-1]["revenue"]
        rev_bull_y5 = bull_res.metrics["is_projected"][-1]["revenue"]
        rev_bear_y5 = bear_res.metrics["is_projected"][-1]["revenue"]

        assert rev_bull_y5 > rev_base_y5 > rev_bear_y5

