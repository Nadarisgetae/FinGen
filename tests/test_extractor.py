"""
FinGen v2 — Extractor & Parser Test Suite (Phase 1 Benchmarking)
Run: pytest tests/test_extractor.py -v
"""

import io
import csv
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.schema import Fact
from core.extract.extractor import Extractor, ExtractionResult, FactListResponse
from core.ingest.parsers import spreadsheet_to_facts
from core.validate import Validator


FIXTURES_DIR = Path("tests/fixtures")


# =============================================================================
# Section Splitting & Boundary Detection Tests
# =============================================================================

class TestSectionSplitting:
    @pytest.fixture
    def extractor(self):
        return Extractor()

    def test_section_splitting_isolates_statements(self, extractor):
        sample_doc = """
# Management Discussion and Analysis
The company recorded strong performance in FY24 driven by steel demand...

# Consolidated Statement of Profit and Loss
Revenue from operations: 229,171 cr
Total Income: 231,151 cr
Profit before tax: 6,010 cr
Profit after tax: -4,910 cr

# Consolidated Balance Sheet
Property, Plant and Equipment: 142,500 cr
Total Assets: 284,383 cr
Total Equity: 89,835 cr
Total Liabilities: 194,548 cr

# Notes to Consolidated Financial Statements
Note 1: Company Information
The company is engaged in the manufacturing and distribution of steel products.
Note 2: Long term debt details...

# Consolidated Statement of Cash Flows
Cash from operating activities: 20,270 cr
Net cash flow: 330 cr
Closing cash: 9,530 cr

# Independent Auditor's Report
To the Members of the Company...
"""
        sections = extractor._split_sections(sample_doc)
        
        # Verify key sections exist
        assert "IS" in sections
        assert "BS" in sections
        assert "CF" in sections
        assert "mda" in sections
        assert "auditor_report" in sections

        # Verify Notes did NOT bleed into Balance Sheet
        assert "Property, Plant and Equipment" in sections["BS"]
        assert "Note 1: Company Information" not in sections["BS"]
        assert "Note 2: Long term debt details" not in sections["BS"]

    def test_consolidated_prioritized_over_standalone(self, extractor):
        sample_doc = """
# Standalone Balance Sheet
Total Assets: 150,000 cr

# Consolidated Balance Sheet
Total Assets: 284,383 cr
Total Liabilities: 194,548 cr
"""
        sections = extractor._split_sections(sample_doc)
        assert "BS" in sections
        assert "284,383" in sections["BS"]


# =============================================================================
# Label Classification Tests
# =============================================================================

class TestLabelClassification:
    @pytest.fixture
    def extractor(self):
        return Extractor()

    def test_exact_and_fuzzy_aliases(self, extractor):
        cases = [
            ("Revenue from operations", "revenue_from_operations"),
            ("Net Sales", "revenue_from_operations"),
            ("Turnover", "revenue_from_operations"),
            ("Profit After Tax", "profit_after_tax"),
            ("Net Profit for the year", "profit_after_tax"),
            ("Total Equity", "total_equity"),
            ("Shareholders' Funds", "total_equity"),
            ("Net Worth", "total_equity"),
            ("Borrowings", "total_debt"),
            ("Cash and cash equivalents", "cash_and_equivalents"),
        ]
        for raw, expected_key in cases:
            matched = extractor._classify_label(raw)
            assert matched == expected_key, f"Failed for raw label '{raw}': got '{matched}', expected '{expected_key}'"


# =============================================================================
# Spreadsheet Ingestion Tests
# =============================================================================

class TestSpreadsheetIngestion:
    def test_csv_to_facts_direct(self):
        csv_content = b"""Line Item,FY22,FY23,FY24
Revenue from operations,1000,1200,1500
EBITDA,200,250,300
Profit After Tax,100,120,150
Total Assets,2000,2400,3000
Total Liabilities,1200,1400,1800
Total Equity,800,1000,1200
"""
        facts = spreadsheet_to_facts(csv_content, "screener_export.csv", as_facts=True)
        assert len(facts) >= 15
        
        # Verify FY24 Revenue fact
        rev_fy24 = [f for f in facts if f.line_item == "revenue_from_operations" and f.period == "FY24"]
        assert len(rev_fy24) == 1
        assert rev_fy24[0].value == 1500.0
        assert rev_fy24[0].statement == "IS"

    def test_quarterly_and_negative_number_parsing(self):
        csv_content = b"""Line Item,Q1FY24,Q2FY24
Profit After Tax,(50.50),120.00
"""
        facts = spreadsheet_to_facts(csv_content, "quarterly.csv", as_facts=True)
        assert len(facts) == 2
        q1_pat = [f for f in facts if f.period == "Q1FY24"][0]
        assert q1_pat.value == -50.50
        assert q1_pat.period_type == "Q"


# =============================================================================
# Ground-Truth Fixtures & Benchmark Verification
# =============================================================================

def load_fixture_facts(company: str) -> list[Fact]:
    path = FIXTURES_DIR / company / "expected_facts.csv"
    facts = []
    with open(path, "r", encoding="utf-8") as f:
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


class TestExtractionBenchmarking:
    def test_tata_steel_fixtures_validation_passes(self):
        facts = load_fixture_facts("tata_steel")
        assert len(facts) >= 20
        result = Validator(facts).validate()
        assert result.blocking == [], f"Tata Steel benchmark has blocking errors: {result.blocking}"

    def test_toyota_fixtures_validation_passes(self):
        facts = load_fixture_facts("toyota")
        assert len(facts) >= 15
        result = Validator(facts).validate()
        assert result.blocking == [], f"Toyota benchmark has blocking errors: {result.blocking}"

    def test_reliance_fixtures_validation_passes(self):
        facts = load_fixture_facts("reliance")
        assert len(facts) >= 15
        result = Validator(facts).validate()
        assert result.blocking == [], f"Reliance benchmark has blocking errors: {result.blocking}"

    @patch("core.llm.router.requests.post")
    def test_end_to_end_extractor_benchmark_accuracy(self, mock_post):
        """Simulate section extraction on Tata Steel and compute accuracy vs expected facts."""
        expected_facts = load_fixture_facts("tata_steel")
        expected_dict = {(f.line_item, f.period): f.value for f in expected_facts}

        # Mock LLM output returning all key items
        llm_response_payload = {
            "facts": [
                {"raw_label": "Revenue from Operations", "line_item": "revenue_from_operations", "period": "FY24", "value": 229171.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "Other Income", "line_item": "other_income", "period": "FY24", "value": 1980.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "Total Income", "line_item": "total_income", "period": "FY24", "value": 231151.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "EBITDA", "line_item": "ebitda", "period": "FY24", "value": 23402.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "Finance Costs", "line_item": "finance_costs", "period": "FY24", "value": 7552.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "Profit After Tax", "line_item": "profit_after_tax", "period": "FY24", "value": -4910.0, "unit": "INR_cr", "page": 124},
                {"raw_label": "Total Assets", "line_item": "total_assets", "period": "FY24", "value": 284383.0, "unit": "INR_cr", "page": 126},
                {"raw_label": "Total Equity", "line_item": "total_equity", "period": "FY24", "value": 89835.0, "unit": "INR_cr", "page": 127},
                {"raw_label": "Total Liabilities", "line_item": "total_liabilities", "period": "FY24", "value": 194548.0, "unit": "INR_cr", "page": 127},
                {"raw_label": "Cash and Cash Equivalents", "line_item": "cash_and_equivalents", "period": "FY24", "value": 9530.0, "unit": "INR_cr", "page": 126},
                {"raw_label": "Cash from Operations", "line_item": "cfo", "period": "FY24", "value": 20270.0, "unit": "INR_cr", "page": 129},
            ],
            "unmapped": [],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(llm_response_payload)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 150},
        }
        mock_post.return_value = mock_resp

        extractor = Extractor()
        sample_text = """
# Consolidated Statement of Profit and Loss
Revenue from Operations: 229171
EBITDA: 23402
Profit After Tax: -4910
"""
        result = extractor.extract_from_text(text=sample_text, fiscal_year="FY24")
        
        # Check that extracted facts match expected ground truth
        matched_count = 0
        for fact in result.facts:
            key = (fact.line_item, fact.period)
            if key in expected_dict and abs(fact.value - expected_dict[key]) < 1e-3:
                matched_count += 1

        accuracy = matched_count / len(result.facts)
        assert accuracy >= 0.95, f"Extraction accuracy {accuracy:.2%} is below required 95%"

