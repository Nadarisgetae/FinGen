"""
FinGen v2 — Job Worker
Background thread that processes jobs from the Supabase `jobs` table.
Streamlit-safe: runs in a daemon thread, updates job progress in DB.
"""

import time
import logging
import threading
from typing import Optional, Callable

from core.db.repos.job_repo import JobRepo
from core.db.repos.report_repo import ReportRepo
from core.db.repos.fact_repo import FactRepo
from core.db.repos.assumption_repo import AssumptionRepo
from core.generate.runner import load_template
from core.export.markdown_to_docx import markdown_to_docx
from core.export.markdown_to_pdf import markdown_to_pdf
from core.analytics.charts import get_chart

logger = logging.getLogger(__name__)


class JobWorker:
    """
    Polls the jobs table and processes pending/running jobs.

    Usage:
        worker = JobWorker(user_id, supabase_client)
        worker.start()          # daemon thread
        ...
        worker.stop()
    """

    def __init__(self, user_id, supabase_client=None, poll_interval: float = 2.0):
        self.user_id = user_id
        self.poll_interval = poll_interval
        self.job_repo = JobRepo()
        self.report_repo = ReportRepo()
        self.fact_repo = FactRepo()
        self.assumption_repo = AssumptionRepo()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current_job_id = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("JobWorker started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop_event.is_set():
            try:
                job = self._claim_next_job()
                if job:
                    self._process_job(job)
                else:
                    time.sleep(self.poll_interval)
            except Exception as e:
                logger.exception(f"JobWorker loop error: {e}")
                time.sleep(self.poll_interval)

    def _claim_next_job(self) -> Optional[dict]:
        jobs = self.job_repo.list(
            {"user_id": str(self.user_id), "status": "pending"},
            order_by="created_at",
            desc=False,
            limit=1,
        )
        if not jobs:
            return None
        job = jobs[0]
        self.job_repo.update(job["id"], {"status": "running", "started_at": "now()"})
        self._current_job_id = job["id"]
        return job

    def _process_job(self, job: dict):
        job_id = job["id"]
        kind = job["kind"]
        payload = job.get("payload") or {}

        try:
            if kind == "generate_report":
                self._run_generate_report(job_id, payload)
            elif kind == "extract":
                self._run_extract(job_id, payload)
            elif kind == "transcribe":
                self._run_transcribe(job_id, payload)
            elif kind == "price_fetch":
                self._run_price_fetch(job_id, payload)
            else:
                self.job_repo.fail(job_id, f"Unknown job kind: {kind}")
        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            self.job_repo.fail(job_id, str(e))
        finally:
            self._current_job_id = None

    def _update_progress(self, job_id: str, progress: int, status: str = "running"):
        self.job_repo.update_progress(job_id, progress)

    # =============================================================================
    # Job handlers
    # =============================================================================

    def _run_generate_report(self, job_id: str, payload: dict):
        company_id = payload["company_id"]
        report_type = payload["report_type"]
        ui_config = payload.get("ui_config", {})

        # 1. Load facts
        facts_data = self.fact_repo.get_by_company_period(company_id=company_id)
        from core.schema import Fact
        facts = [Fact(**{k: v for k, v in f.items() if k in Fact.model_fields}) for f in facts_data]

        # 2. Load assumptions
        assumptions_data = self.assumption_repo.get_for_forecast(company_id, None)

        # 3. Generate
        generator = load_template(report_type)

        def on_progress(current, total, section):
            pct = int((current / max(total, 1)) * 100)
            self._update_progress(job_id, pct)
            logger.info(f"Job {job_id}: {pct}% — {section}")

        result = generator.generate(
            company_id=company_id,
            user_id=self.user_id,
            facts=facts,
            assumptions=assumptions_data,
            ui_config=ui_config,
            on_progress=on_progress,
        )

        markdown = result["markdown"]

        # 4. Generate charts for markers in markdown
        charts = self._render_charts(markdown, result.get("analytics_results", {}))

        # 5. Export docx/pdf
        disclaimers = self._disclaimers_for(report_type)
        docx_bytes = markdown_to_docx(markdown, charts=charts, disclaimers=disclaimers)
        pdf_bytes = markdown_to_pdf(markdown, charts=charts, disclaimers=disclaimers)

        # 6. Upload to Storage + save report row
        from core.db.client import get_supabase_client
        supabase = get_supabase_client(use_service_key=True)

        docx_path = f"reports/{self.user_id}/{company_id}/{report_type}/report.docx"
        pdf_path = f"reports/{self.user_id}/{company_id}/{report_type}/report.pdf"

        try:
            supabase.storage.from_("reports").upload(docx_path, docx_bytes, {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"})
            supabase.storage.from_("reports").upload(pdf_path, pdf_bytes, {"content-type": "application/pdf"})
        except Exception as e:
            logger.warning(f"Storage upload failed: {e}")

        report = self.report_repo.create_version(
            company_id=company_id,
            user_id=self.user_id,
            report_type=report_type,
            markdown=markdown,
            title=generator.template.get("title", report_type),
            ui_config=ui_config,
            generation_time_ms=payload.get("generation_time_ms"),
        )
        self.report_repo.update_storage_paths(report["id"], docx_path, pdf_path)

        # 7. Complete job
        self.job_repo.complete(job_id, {
            "report_id": report["id"],
            "docx_path": docx_path,
            "pdf_path": pdf_path,
            "verification": result["verification"].to_dict() if hasattr(result["verification"], "to_dict") else {},
        })
        logger.info(f"Job {job_id} complete: report {report['id']}")

    def _run_extract(self, job_id: str, payload: dict):
        """Extract facts from a document (async)."""
        from core.extract.extractor import Extractor
        from core.db.repos.document_repo import DocumentRepo
        from core.db.repos.review_queue_repo import ReviewQueueRepo

        document_id = payload["document_id"]
        company_id = payload["company_id"]

        doc_repo = DocumentRepo()
        doc = doc_repo.get_by_id(document_id)
        if not doc:
            self.job_repo.fail(job_id, f"Document {document_id} not found")
            return

        self.job_repo.update_progress(job_id, 10)
        doc_repo.update_status(document_id, "processing")

        # Fetch text from Storage
        from core.db.client import get_supabase_client
        supabase = get_supabase_client(use_service_key=True)
        try:
            text_response = supabase.storage.from_("uploads").download(doc["storage_path"])
            text = text_response.decode("utf-8") if isinstance(text_response, bytes) else str(text_response)
        except Exception:
            # If binary PDF, parse with Docling / PyMuPDF
            from core.ingest.parsers import parse_pdf_bytes, parse_pdf_fast_bytes
            try:
                text = parse_pdf_bytes(text_response)
            except Exception:
                text = parse_pdf_fast_bytes(text_response)

        self.job_repo.update_progress(job_id, 30)

        extractor = Extractor()
        extraction = extractor.extract_from_text(
            company_id=company_id,
            user_id=self.user_id,
            document_id=document_id,
            document_type=doc["type"],
            text=text,
            fiscal_year=doc.get("fiscal_year"),
        )

        self.job_repo.update_progress(job_id, 70)

        # Save facts
        self.fact_repo.bulk_upsert_facts(extraction.facts, company_id, self.user_id, document_id)

        # Save unmapped to review queue
        for um in extraction.unmapped:
            ReviewQueueRepo().create({
                "company_id": str(company_id),
                "user_id": str(self.user_id),
                "document_id": str(document_id),
                "raw_label": um.get("raw_label"),
                "period": um.get("period"),
                "value": um.get("value"),
                "unit": um.get("unit"),
                "page": um.get("page"),
            })

        # Save narrative snippets
        from core.db.repos.narrative_repo import NarrativeRepo
        NarrativeRepo().bulk_create_snippets(extraction.snippets)

        doc_repo.update_status(document_id, "completed", page_count=0)
        self.job_repo.complete(job_id, {
            "facts_extracted": len(extraction.facts),
            "snippets": len(extraction.snippets),
            "unmapped": len(extraction.unmapped),
            "stats": extraction.stats,
        })

    def _run_transcribe(self, job_id: str, payload: dict):
        """Transcribe audio (Whisper) as a job."""
        from core.ingest.parsers import get_whisper_model
        from core.db.client import get_supabase_client

        document_id = payload["document_id"]
        supabase = get_supabase_client(use_service_key=True)

        self.job_repo.update_progress(job_id, 5)
        # Download audio
        audio_bytes = supabase.storage.from_("uploads").download(payload["storage_path"])

        self.job_repo.update_progress(job_id, 10)
        # Whisper transcription (blocking, but in worker thread)
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name

        try:
            from core.ingest.parsers import get_whisper_model
            model = get_whisper_model(payload.get("model_size"))
            result = model.transcribe(temp_path)
            transcript = result.get("text", "")
        finally:
            os.unlink(temp_path)

        self.job_repo.update_progress(job_id, 90)

        # Save transcript as document
        from core.db.repos.document_repo import DocumentRepo
        doc_repo = DocumentRepo()
        transcript_path = f"uploads/{self.user_id}/{document_id}/transcript.txt"
        supabase.storage.from_("uploads").upload(transcript_path, transcript.encode("utf-8"))

        self.job_repo.complete(job_id, {"transcript_path": transcript_path, "chars": len(transcript)})

    def _run_price_fetch(self, job_id: str, payload: dict):
        """Fetch prices for portfolio tickers."""
        import pandas as pd
        import yfinance as yf
        from core.db.repos.portfolio_repo import HoldingRepo, PriceRepo

        holding_repo = HoldingRepo()
        price_repo = PriceRepo()
        holdings = holding_repo.get_by_portfolio(payload["portfolio_id"])

        total = len(holdings)
        for i, holding in enumerate(holdings):
            try:
                ticker = holding["ticker"]
                data = yf.Ticker(ticker).history(period="1mo")
                if not data.empty:
                    latest = data.iloc[-1]
                    price_repo.upsert_holding_price(holding["id"], float(latest["Close"]))
                    # Store price history
                    price_rows = [
                        {
                            "ticker": ticker,
                            "date": str(idx.date()),
                            "close": float(row["Close"]),
                            "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                        }
                        for idx, row in data.iterrows()
                    ]
                    price_repo.bulk_upsert_prices(price_rows)
            except Exception as e:
                logger.warning(f"Price fetch failed for {holding['ticker']}: {e}")

            self.job_repo.update_progress(job_id, int((i + 1) / max(total, 1) * 100))

        self.job_repo.complete(job_id, {"prices_fetched": total})

    def _render_charts(self, markdown: str, analytics_results: dict) -> dict:
        """Render <!--chart:name--> markers found in markdown."""
        import re
        charts = {}
        for m in re.finditer(r"<!--\s*chart:(\S+)\s*-->", markdown):
            chart_name = m.group(1)
            # Try to render with analytics data heuristics
            try:
                charts[chart_name] = self._render_single_chart(chart_name, analytics_results)
            except Exception as e:
                logger.warning(f"Chart {chart_name} render failed: {e}")
        return charts

    def _render_single_chart(self, chart_name: str, analytics_results: dict):
        """Best-effort chart render from analytics results."""
        from core.analytics.charts import get_chart

        # Find matching analytics data
        for section, analytics in analytics_results.items():
            for aname, result in analytics.items():
                metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
                if chart_name == "leverage_trend" and "debt_equity" in str(metrics):
                    # Heuristic render
                    periods = list(metrics.keys())
                    de = [m.get("debt_equity", 0) for m in metrics.values() if isinstance(m, dict)]
                    nde = [m.get("net_debt_ebitda", 0) for m in metrics.values() if isinstance(m, dict)]
                    if de and nde:
                        return get_chart("leverage_trend", periods=periods, debt_equity=de, net_debt_ebitda=nde)
        return None

    def _disclaimers_for(self, report_type: str) -> list:
        """Regulatory disclaimers per report type."""
        base = [
            "This report was generated by FinGen, an automated financial analysis tool.",
            "All figures are extracted from user-provided source documents and have not been independently audited.",
        ]
        if report_type in ("equity_research", "investment_research", "valuation"):
            base.insert(0, "IMPORTANT: This is not investment advice. Ratings, target prices, and valuations are model outputs based on user-supplied assumptions and require analyst review before use.")
            base.append("Subject to SEBI Research Analyst Regulations, 2014. Analyst certification: views expressed accurately reflect the model's output based on the stated assumptions.")
        if report_type == "credit_analysis":
            base.append("Credit ratings are internal model estimates and do not constitute a formal credit rating from a registered agency.")
        return base


# Convenience
def run_job(user_id, job_id, payload, kind):
    """Synchronous job execution (for testing)."""
    worker = JobWorker(user_id)
    job = {"id": job_id, "kind": kind, "payload": payload}
    worker._process_job(job)