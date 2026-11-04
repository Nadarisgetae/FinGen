"""
FinGen v2 — Report Generator & Verification Tests (Phase 2)
Tests:
- All 10 report templates load and validate against analytics registry
- Section prompt resolution
- Company Analysis report generation end-to-end
- Equity Research report generation end-to-end (with DCF & multiples)
- Anti-hallucination verification integration (clean vs injected errors)
- Progress callback streaming and error resilience
"""

import csv
import pytest
from pathlib import Path
from typing import List

from core.schema import Fact
from core.generate.runner import list_templates, load_template, ReportGenerator
from core.verify.verifier import Verifier, FlagType, Severity


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

    def __init__(self, mode="accurate"):
        self.mode = mode
        self.calls = []

    def call(self, task, messages, schema=None):
        self.calls.append({"task": task, "messages": messages})
        
        if self.mode == "accurate":
            return (
                "Tata Steel reported FY24 revenue from operations of 229171.0 INR_cr, "
                "with an EBITDA of 23402.0 INR_cr and total debt of 87082.0 INR_cr. "
                "Cash and equivalents stood at 9530.0 INR_cr."
            )
        elif self.mode == "injected_errors":
            return (
                "Tata Steel is a world-class revolutionary market-leader that achieved "
                "unprecedented revenue of 999999.0 INR_cr in FY24."
            )
        elif self.mode == "failing":
            raise RuntimeError("Simulated LLM API rate limit or outage")
        return "Generic section content."


class TestTemplateValidation:
    def test_all_10_templates_load_and_validate(self):
        templates = list_templates()
        assert len(templates) == 10
        expected = [
            "company_analysis", "credit_analysis", "due_diligence",
            "equity_research", "financial_forecast", "industry_analysis",
            "investment_research", "portfolio_performance", "risk_analysis",
            "valuation"
        ]
        for name in expected:
            assert name in templates
            gen = load_template(name)
            assert gen.template["id"] == name
            assert len(gen.template.get("sections", [])) > 0

    def test_prompts_exist_for_all_template_sections(self):
        templates = list_templates()
        for name in templates:
            gen = load_template(name)
            for sec in gen.template.get("sections", []):
                prompt_file = sec.get("prompt")
                if prompt_file:
                    ppath = Path("prompts") / prompt_file
                    assert ppath.exists(), f"Missing prompt file {ppath} for template {name}"


class TestCompanyAnalysisReport:
    def test_company_analysis_end_to_end(self):
        facts = _load_tata_steel_facts()
        router = MockRouter(mode="accurate")
        generator = load_template("company_analysis", router=router)

        progress_log = []
        def on_progress(cur, total, msg):
            progress_log.append((cur, total, msg))

        result = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            context={
                "company_name": "Tata Steel Limited",
                "ticker": "TATASTEEL.NS",
                "fiscal_year": "FY24"
            },
            ui_config={
                "currency": "INR",
                "unit": "INR_cr",
                "horizon": "FY24",
                "include_disclaimer": True,
            },
            on_progress=on_progress,
        )

        # 1. Output structure
        assert "markdown" in result
        assert "sections" in result
        assert "analytics_results" in result
        assert "verification" in result

        # 2. Sections
        sections = result["sections"]
        expected_sections = ["overview", "growth", "profitability", "leverage", "efficiency", "cash_flow"]
        for s in expected_sections:
            assert s in sections
            assert len(sections[s]) > 0

        # 3. Analytics computed
        ar = result["analytics_results"]
        assert "profitability_ratios" in ar["profitability"]
        assert "dupont_analysis" in ar["profitability"]
        assert "leverage_ratios" in ar["leverage"]
        assert "efficiency_ratios" in ar["efficiency"]

        # 4. Markdown header and disclaimers
        md = result["markdown"]
        assert "Company Analysis: Tata Steel Limited (TATASTEEL.NS)" in md
        assert "Disclaimers & Regulatory Notes" in md

        # 5. Verification
        ver = result["verification"]
        assert ver.numbers_checked > 0
        assert ver.numbers_verified > 0
        assert ver.error_count == 0

        # 6. Progress calls
        assert len(progress_log) == len(expected_sections) + 1  # 6 sections + completion


class TestEquityResearchReport:
    def test_equity_research_end_to_end(self):
        facts = _load_tata_steel_facts()
        router = MockRouter(mode="accurate")
        generator = load_template("equity_research", router=router)

        assumptions = {
            "wacc": 0.12,
            "terminal_growth_rate": 0.04,
            "exit_multiple": 7.5,
            "projection_years": 5,
            "shares_outstanding": 1222.0,
        }

        result = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            assumptions=assumptions,
            context={
                "company_name": "Tata Steel Limited",
                "ticker": "TATASTEEL.NS",
                "fiscal_year": "FY24"
            },
            ui_config={
                "currency": "INR",
                "unit": "INR_cr",
                "horizon": "5Y",
                "include_disclaimer": True,
            },
        )

        expected_sections = ["summary", "business", "financials", "valuation", "risks", "catalysts"]
        for s in expected_sections:
            assert s in result["sections"]

        # Check valuation analytics
        val_analytics = result["analytics_results"]["valuation"]
        assert "dcf_fcff" in val_analytics
        assert "football_field" in val_analytics
        assert val_analytics["dcf_fcff"]["enterprise_value"] > 0
        assert val_analytics["dcf_fcff"]["equity_value"] > 0

        # Verification passes cleanly
        ver = result["verification"]
        assert ver.error_count == 0
        assert ver.numbers_verified > 0


class TestVerificationIntegration:
    def test_verifier_catches_hallucinations_and_promotional_language(self):
        facts = _load_tata_steel_facts()
        router = MockRouter(mode="injected_errors")
        generator = load_template("company_analysis", router=router)

        result = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
            context={"company_name": "Tata Steel Limited"},
        )

        ver = result["verification"]
        # Injected number 999999.0 should be flagged
        flag_types = [f.flag_type for f in ver.flags]
        assert FlagType.MISSING_SOURCE in flag_types or FlagType.MISMATCH in flag_types
        # Injected words 'world-class', 'revolutionary', 'market-leader' should be flagged
        assert FlagType.PROMOTIONAL_LANGUAGE in flag_types


class TestResilienceAndFallbacks:
    def test_section_failure_handled_gracefully(self):
        facts = _load_tata_steel_facts()
        failing_router = MockRouter(mode="failing")
        generator = load_template("company_analysis", router=failing_router)

        # Should not raise exception; section output should contain failure note
        result = generator.generate(
            company_id="tata_steel",
            user_id="test_user",
            facts=facts,
        )

        for sec_content in result["sections"].values():
            assert "Section generation failed" in sec_content
        assert "# Company Analysis" in result["markdown"]

