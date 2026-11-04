"""
FinGen v2 — Test Suite
Run: pytest tests/ -v
"""

import pytest
import json
from datetime import date, timedelta

# =============================================================================
# Analytics tests (pure code, no LLM/DB)
# =============================================================================

class TestGrowth:
    def test_yoy_growth(self):
        from core.schema import Fact
        from core.analytics.growth import yoy_growth

        facts = [
            Fact(statement="IS", line_item="revenue_from_operations", period="FY23", value=1000.0, unit="INR_cr"),
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=1200.0, unit="INR_cr"),
        ]
        result = yoy_growth(facts)
        assert abs(result.metrics["revenue_from_operations"]["FY24"] - 0.20) < 1e-9

    def test_cagr(self):
        from core.schema import Fact
        from core.analytics.growth import cagr

        facts = [
            Fact(statement="IS", line_item="revenue_from_operations", period="FY20", value=1000.0, unit="INR_cr"),
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=2000.0, unit="INR_cr"),
        ]
        result = cagr(facts)
        cagr_val = result.metrics["revenue_from_operations"]
        # 2x over 4 years = 2^(1/4) - 1 ≈ 0.189
        assert abs(cagr_val - (2 ** 0.25 - 1)) < 1e-3


class TestRatios:
    def test_dupont(self):
        from core.schema import Fact
        from core.analytics.ratios import dupont_analysis

        facts = [
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=1000.0, unit="INR_cr"),
            Fact(statement="IS", line_item="profit_after_tax", period="FY24", value=100.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_assets", period="FY24", value=2000.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_equity", period="FY24", value=500.0, unit="INR_cr"),
        ]
        result = dupont_analysis(facts)
        m = result.metrics["FY24"]
        assert abs(m["net_margin"] - 0.10) < 1e-9
        assert abs(m["asset_turnover"] - 0.50) < 1e-9
        assert abs(m["financial_leverage"] - 4.0) < 1e-9
        assert abs(m["roe"] - 0.20) < 1e-9  # 0.10 * 0.50 * 4.0


class TestCredit:
    def test_altman_z(self):
        from core.schema import Fact
        from core.analytics.credit import altman_z_score

        # Working capital 200, RE 300, EBIT 400, equity 500, liab 1000, sales 2000, assets 1500
        facts = [
            Fact(statement="BS", line_item="current_assets", period="FY24", value=700.0, unit="INR_cr"),
            Fact(statement="BS", line_item="current_liabilities", period="FY24", value=500.0, unit="INR_cr"),
            Fact(statement="BS", line_item="retained_earnings", period="FY24", value=300.0, unit="INR_cr"),
            Fact(statement="IS", line_item="ebit", period="FY24", value=400.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_equity", period="FY24", value=500.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_liabilities", period="FY24", value=1000.0, unit="INR_cr"),
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=2000.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_assets", period="FY24", value=1500.0, unit="INR_cr"),
        ]
        result = altman_z_score(facts)
        z = result.metrics["FY24"]
        # X1=200/1500=0.133, X2=300/1500=0.2, X3=400/1500=0.267, X4=500/1000=0.5, X5=2000/1500=1.333
        # Z = 1.2*0.133 + 1.4*0.2 + 3.3*0.267 + 0.6*0.5 + 1.0*1.333 = 0.16+0.28+0.88+0.30+1.33 = 2.95
        assert abs(z - 2.95) < 0.05
        assert result.metadata["FY24"]["zone"] == "grey"


class TestPortfolio:
    def test_xirr_single_period(self):
        from core.analytics.portfolio import xirr

        # Invest 100 today, get 110 in 1 year → 10% return
        flows = [
            {"date": date(2024, 1, 1), "amount": -100.0, "type": "buy"},
            {"date": date(2025, 1, 1), "amount": 110.0, "type": "sell"},
        ]
        result = xirr(flows, current_holdings_value=0.0, valuation_date=date(2025, 1, 1))
        # Terminal value 0, so XIRR is undefined with these flows;
        # instead test with holdings value
        result2 = xirr(
            [{"date": date(2024, 1, 1), "amount": -100.0, "type": "buy"}],
            current_holdings_value=110.0,
            valuation_date=date(2025, 1, 1),
        )
        assert abs(result2.metrics["xirr"] - 0.10) < 0.01

    def test_drawdown(self):
        from core.analytics.portfolio import drawdown_analysis

        values = [
            {"date": date(2024, 1, 1), "value": 100.0},
            {"date": date(2024, 1, 2), "value": 90.0},
            {"date": date(2024, 1, 3), "value": 80.0},
            {"date": date(2024, 1, 4), "value": 95.0},
        ]
        result = drawdown_analysis(values)
        assert abs(result.metrics["max_drawdown"] - 0.20) < 1e-9  # 100→80


class TestVerifier:
    def test_verifies_known_number(self):
        from core.schema import Fact
        from core.verify.verifier import Verifier

        facts = [
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=1234.0, unit="INR_cr"),
        ]
        v = Verifier(facts=facts)
        result = v.verify("Revenue was ₹1,234 cr in FY24.")
        assert result.numbers_verified >= 1
        assert result.error_count == 0

    def test_flags_unknown_number(self):
        from core.schema import Fact
        from core.verify.verifier import Verifier

        facts = [
            Fact(statement="IS", line_item="revenue_from_operations", period="FY24", value=1234.0, unit="INR_cr"),
        ]
        v = Verifier(facts=facts)
        result = v.verify("Revenue was ₹9,999 cr in FY24.")
        assert result.numbers_verified == 0
        assert len(result.flags) >= 1

    def test_flags_promotional_language(self):
        from core.verify.verifier import Verifier

        v = Verifier(facts=[])
        result = v.verify("This is a revolutionary, world-class company.")
        promotional = [f for f in result.flags if f.flag_type.value == "PROMOTIONAL_LANGUAGE"]
        assert len(promotional) >= 1


class TestValidator:
    def test_balance_sheet_balance(self):
        from core.schema import Fact
        from core.validate import Validator

        facts = [
            Fact(statement="BS", line_item="total_assets", period="FY24", value=1500.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_liabilities", period="FY24", value=1000.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_equity", period="FY24", value=500.0, unit="INR_cr"),
        ]
        result = Validator(facts).validate()
        assert result.blocking == []

    def test_balance_sheet_imbalance(self):
        from core.schema import Fact
        from core.validate import Validator

        facts = [
            Fact(statement="BS", line_item="total_assets", period="FY24", value=1500.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_liabilities", period="FY24", value=900.0, unit="INR_cr"),
            Fact(statement="BS", line_item="total_equity", period="FY24", value=500.0, unit="INR_cr"),
        ]
        result = Validator(facts).validate()
        assert len(result.blocking) >= 1
        assert any("BS.balance" in b for b in result.blocking)


class TestRegistry:
    def test_all_analytics_registered(self):
        from core.analytics.registry import ANALYTICS_REGISTRY, get_spec

        required = [
            "yoy_growth", "cagr", "quarterly_trend",
            "profitability_ratios", "leverage_ratios", "efficiency_ratios",
            "dupont_analysis", "common_size_statements",
            "debt_equity", "net_debt_ebitda", "icr", "dscr",
            "altman_z_score", "internal_rating", "covenant_headroom",
            "dcf_fcff", "multiples_valuation", "football_field", "sensitivity_grid",
            "project_is_bs_cf",
            "financial_risk_flags", "market_risk_metrics", "concentration_risk",
            "peer_benchmark", "market_size_growth",
            "xirr", "portfolio_allocation", "portfolio_attribution",
            "drawdown_analysis", "benchmark_comparison",
        ]
        for name in required:
            spec = get_spec(name)
            assert spec.requires is not None
            assert spec.returns

    def test_template_analytics_valid(self):
        import json
        from pathlib import Path
        from core.analytics.registry import validate_template_analytics

        templates_dir = Path("templates/reports")
        for template_file in templates_dir.glob("*.json"):
            with open(template_file) as f:
                template = json.load(f)
            errors = validate_template_analytics(template.get("sections", []))
            assert errors == [], f"{template_file.name}: {errors}"


# =============================================================================
# KeyPool tests (issue #6 fix)
# =============================================================================

class TestKeyPool:
    def test_rotation_on_exhaustion(self):
        from core.llm.keypool import KeyPool

        pool = KeyPool(
            free_keys=["key1", "key2", "key3"],
            paid_key="paid1",
            cooldown_seconds=0.01,
        )

        # Acquire all three keys
        acquired = set()
        for _ in range(3):
            key = pool.acquire(timeout=1)
            acquired.add(key)
            pool.record_failure(key, Exception("429"), status_code=429)

        assert acquired == {"key1", "key2", "key3"}

        # All cooling → falls back to paid key
        paid = pool.acquire(timeout=1)
        assert paid == "paid1"

    def test_paid_fallback_after_free_exhausted(self):
        from core.llm.keypool import KeyPool, KeyPoolExhausted

        pool = KeyPool(
            free_keys=["key1"],
            paid_key="paid1",
            cooldown_seconds=60,
        )

        key = pool.acquire(timeout=1)
        assert key == "key1"
        pool.record_failure(key, Exception("402"), status_code=402)

        # Free key exhausted (1h cooldown) → paid key
        paid = pool.acquire(timeout=1)
        assert paid == "paid1"


# =============================================================================
# Schema / unit conversion tests
# =============================================================================

class TestSchema:
    def test_unit_conversion(self):
        from core.schema import convert_to_base_unit

        # 100 crore = 100 crore (base)
        assert convert_to_base_unit(100, "INR_cr") == 100
        # 1000 lakh = 10 crore
        assert abs(convert_to_base_unit(1000, "INR_lakh") - 10) < 1e-9
        # 1 billion = 100 crore
        assert abs(convert_to_base_unit(1, "INR_bn") - 100) < 1e-9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])