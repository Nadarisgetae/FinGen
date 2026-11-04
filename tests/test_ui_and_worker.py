"""
FinGen v2 — Test Suite for UI Flow and JobWorker
Tests offline end-to-end generation, in-memory repository persistence, and page module validity.
"""

import os
import io
import py_compile
import pytest
from uuid import uuid4

from core.schema import Fact
from core.db.repos.company_repo import CompanyRepo
from core.db.repos.document_repo import DocumentRepo
from core.db.repos.fact_repo import FactRepo
from core.db.repos.job_repo import JobRepo
from core.db.repos.report_repo import ReportRepo
from core.db.repos.assumption_repo import AssumptionRepo
from core.jobs.worker import JobWorker, run_job
from core.validate import Validator
from core.ingest.parsers import spreadsheet_to_facts
from core.export.markdown_to_docx import markdown_to_docx


@pytest.fixture
def sample_user_and_company():
    user_id = f"test-user-{uuid4().hex[:8]}"
    company_repo = CompanyRepo()
    company = company_repo.create_company(
        user_id=user_id,
        name="Tata Steel Test",
        ticker="TATASTEEL",
        exchange="NSE",
    )
    return user_id, company["id"]


def test_page_syntax_and_compilation():
    """Verify that all Streamlit page scripts compile without syntax errors."""
    page_files = [
        "app.py",
        "pages/1_Upload.py",
        "pages/2_Configure.py",
        "pages/3_Review_Data.py",
        "pages/4_Thesis_Assumptions.py",
        "pages/5_Generate.py",
        "pages/6_Library.py",
    ]
    for file_path in page_files:
        assert os.path.exists(file_path), f"File {file_path} does not exist"
        py_compile.compile(file_path, doraise=True)


def test_offline_fixture_extraction_and_validation(sample_user_and_company):
    """Test importing facts from fixture CSV, saving to FactRepo, and validating."""
    user_id, company_id = sample_user_and_company
    fixture_path = os.path.join("tests", "fixtures", "tata_steel", "expected_facts.csv")
    assert os.path.exists(fixture_path)

    with open(fixture_path, "rb") as f:
        csv_bytes = f.read()

    facts = spreadsheet_to_facts(csv_bytes, "expected_facts.csv", as_facts=True, company_id=company_id)
    assert len(facts) >= 20

    fact_repo = FactRepo()
    fact_repo.bulk_upsert_facts(facts, company_id, user_id, "doc-test-1")

    saved = fact_repo.get_by_company_period(company_id=company_id)
    assert len(saved) >= 20

    # Test validation
    typed_facts = [Fact(**{k: v for k, v in row.items() if k in Fact.model_fields}) for row in saved]
    validation = Validator(typed_facts).validate()
    # Stored facts must have 0 blocking errors
    assert len(validation.blocking) == 0


def test_assumption_repo_persistence(sample_user_and_company):
    """Test storing and retrieving scenario driver assumptions in in-memory mode."""
    user_id, company_id = sample_user_and_company
    repo = AssumptionRepo()

    assumptions = [
        {"driver": "revenue_growth", "period": "projection", "value": 0.12, "unit": "percentage", "rationale": "Strong demand", "is_manual": True},
        {"driver": "ebitda_margin", "period": "projection", "value": 0.20, "unit": "percentage", "rationale": "Cost efficiencies", "is_manual": True},
        {"driver": "wacc", "period": "projection", "value": 0.10, "unit": "percentage", "rationale": "Market rate", "is_manual": True},
    ]

    repo.upsert_scenario(company_id, user_id, "base", assumptions)
    retrieved = repo.get_for_forecast(company_id, ["base"])
    assert "base" in retrieved
    assert "revenue_growth" in retrieved["base"]


def test_job_worker_end_to_end_generation(sample_user_and_company):
    """Test running JobWorker synchronously to generate a report, render docx, and record report."""
    user_id, company_id = sample_user_and_company
    
    # 1. Seed facts
    fixture_path = os.path.join("tests", "fixtures", "tata_steel", "expected_facts.csv")
    with open(fixture_path, "rb") as f:
        csv_bytes = f.read()
    facts = spreadsheet_to_facts(csv_bytes, "expected_facts.csv", as_facts=True, company_id=company_id)
    FactRepo().bulk_upsert_facts(facts, company_id, user_id, "doc-worker-1")

    # 2. Seed assumptions
    AssumptionRepo().upsert_scenario(company_id, user_id, "base", [
        {"driver": "revenue_growth", "period": "projection", "value": 0.10, "unit": "percentage", "rationale": "Base", "is_manual": True},
        {"driver": "ebitda_margin", "period": "projection", "value": 0.18, "unit": "percentage", "rationale": "Base", "is_manual": True},
        {"driver": "wacc", "period": "projection", "value": 0.11, "unit": "percentage", "rationale": "Base", "is_manual": True},
    ])

    job_repo = JobRepo()
    report_repo = ReportRepo()

    payload = {
        "company_id": company_id,
        "report_type": "company_analysis",
        "ui_config": {
            "report_type": "company_analysis",
            "audience": "Investment Analyst",
            "tone": "Objective and analytical",
            "citation_format": "Financial",
            "privacy_masking": False,
        },
    }
    created_job = job_repo.create_job(user_id, "generate_report", payload, company_id=company_id)
    job_id = created_job["id"]

    # Execute job synchronously via worker
    run_job(user_id, job_id, payload, "generate_report")

    # Verify job completion
    completed_job = job_repo.get_by_id(job_id)
    assert completed_job is not None
    assert completed_job["status"] == "completed"
    assert "report_id" in completed_job["result"]

    # Verify report in ReportRepo
    report_id = completed_job["result"]["report_id"]
    report = report_repo.get_by_id(report_id)
    assert report is not None
    assert report["report_type"] == "company_analysis"
    assert len(report["markdown"]) > 100

    # Verify DOCX conversion
    docx_bytes = markdown_to_docx(report["markdown"], title=report["title"])
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 1000

    # Test library listing & filtering
    listed = report_repo.list_by_company(company_id, "company_analysis")
    assert len(listed) >= 1

    # Test deletion
    report_repo.delete(report_id)
    assert report_repo.get_by_id(report_id) is None
