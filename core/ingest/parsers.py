"""
FinGen v2 — Document Parsers (adapted from CaseGen)
PDF (Docling deep / PyMuPDF fast), spreadsheet (outputs Fact rows),
web parser, Whisper audio.
"""

import os
import re
import logging
from typing import List, Optional
from core.ingest.storage import parse_storage_path

logger = logging.getLogger(__name__)


# =============================================================================
# PDF Parsing (Docling — deep mode)
# =============================================================================

def parse_pdf_bytes(content: bytes, filename: str = "document.pdf", max_pages: int = None) -> str:
    """Parse PDF bytes using IBM Docling. Returns markdown text."""
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    except ImportError as e:
        raise RuntimeError("PDF parsing needs 'docling'. Install it or use fast mode.") from e

    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", filename)
    with open(temp_path, "wb") as f:
        f.write(content)

    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend,
                )
            }
        )

        convert_kwargs = {"source": temp_path}
        if max_pages is not None:
            convert_kwargs["page_range"] = (1, max_pages)

        result = converter.convert(**convert_kwargs)
        return result.document.export_to_markdown()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def parse_pdf_fast_bytes(content: bytes, filename: str = "document.pdf", max_pages: int = None) -> str:
    """Parse PDF bytes using PyMuPDF (fast mode)."""
    try:
        import pymupdf as fitz
    except ImportError as e:
        raise RuntimeError("Fast PDF parsing needs 'pymupdf'.") from e

    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", filename)
    with open(temp_path, "wb") as f:
        f.write(content)

    try:
        doc = fitz.open(temp_path)
        total_pages = len(doc)
        limit = min(max_pages, total_pages) if max_pages else total_pages

        pages_text = []
        for i in range(limit):
            page = doc[i]
            text = page.get_text("text").strip()
            if text:
                pages_text.append(f"<!-- page {i + 1} -->\n{text}")
        doc.close()
        return "\n\n".join(pages_text)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# =============================================================================
# Spreadsheet → Fact rows (NOT chunked — direct extraction)
# =============================================================================

def spreadsheet_to_facts(
    content: bytes,
    filename: str,
    as_facts: bool = False,
    company_id=None,
    document_id=None,
    taxonomy_path: str = "config/taxonomy.yaml",
) -> List[Any]:
    """
    Convert Excel/CSV to structured fact rows.
    Returns list of dicts (or list of Fact models if as_facts=True).
    This BYPASSES the chunker — financial tables are never chunked.
    """
    import pandas as pd
    import io

    raw_facts = []

    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
        raw_facts.extend(_extract_facts_from_dataframe(df, filename))
    elif filename.lower().endswith((".xls", ".xlsx")):
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
        for sheet_name, df in sheets.items():
            raw_facts.extend(_extract_facts_from_dataframe(df, f"{filename}:{sheet_name}"))
    else:
        raise ValueError(f"Unsupported spreadsheet format: {filename}")

    if not as_facts:
        return raw_facts

    # Convert to typed Fact objects with taxonomy classification
    from core.schema import Fact
    from core.extract.extractor import Extractor

    extractor = Extractor(taxonomy_path=taxonomy_path)
    facts: List[Fact] = []

    for item in raw_facts:
        raw_label = item.get("raw_label", "")
        tax_key = extractor._classify_label(raw_label)
        if not tax_key:
            continue

        stmt = extractor.statement_of_key.get(tax_key, "IS")
        period = item.get("period", "FY24")

        fact = Fact(
            company_id=company_id,
            document_id=document_id,
            statement=stmt,
            line_item=tax_key,
            raw_label=raw_label,
            period=period,
            period_type=extractor._infer_period_type(period),
            value=float(item.get("value", 0.0)),
            unit=item.get("unit", "INR_cr"),
            confidence=1.0,  # Spreadsheet table structured input = 100% confidence
            source_text=f"{item.get('source', '')}: {raw_label}",
        )
        facts.append(fact)

    return facts


def _extract_facts_from_dataframe(df, source: str) -> List[dict]:
    """
    Extract facts from a dataframe.
    Heuristic: first column = label, remaining columns = periods.
    Detects year columns and extracts per-period values.
    """
    import pandas as pd
    from datetime import datetime

    facts = []
    current_year = datetime.now().year

    # Normalize headers
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Detect year columns (e.g., "FY24", "2024", "Mar-24")
    year_cols = {}
    for col in df.columns:
        col_str = str(col)
        # FY24 pattern
        m = re.match(r"^(?:FY|fy)(\d{2})$", col_str)
        if m:
            year_cols[col] = f"FY{m.group(1)}"
            continue
        # Quarterly pattern e.g. Q1FY24, Q2 2024, Q3-24
        m = re.match(r"^Q([1-4])[-\s]?(?:FY|fy)?(\d{2,4})$", col_str, re.IGNORECASE)
        if m:
            q_num, yr = m.groups()
            yr_suffix = yr[-2:] if len(yr) == 4 else yr
            year_cols[col] = f"Q{q_num}FY{yr_suffix}"
            continue
        # TTM pattern
        if col_str.upper() in ("TTM", "LTM"):
            year_cols[col] = "TTM"
            continue
        # 2024 pattern
        m = re.match(r"^(19|20)\d{2}$", col_str)
        if m:
            y = int(col_str)
            if y <= current_year + 1:
                year_cols[col] = str(y)
            continue
        # Mar-24 / Mar 2024 pattern
        m = re.match(r"^([A-Za-z]{3})[-\s](\d{2,4})$", col_str)
        if m:
            month, year = m.groups()
            if len(year) == 2:
                year = "20" + year
            year = int(year)
            if year <= current_year + 1:
                # Indian FY: Apr-Mar. Mar = FY end.
                if month.lower() in ("mar", "march"):
                    year_cols[col] = f"FY{str(year)[2:]}"
                else:
                    year_cols[col] = f"FY{str(year - 1)[2:]}"
            continue

    if not year_cols:
        logger.warning(f"No year columns detected in {source}")
        return facts

    # Detect unit from any cell/column containing "crore"/"lakh"
    unit = "INR_cr"
    df_text = " ".join(str(c) for c in df.columns) + " " + " ".join(str(v) for v in df.iloc[:2].values.flatten() if pd.notna(v))
    if "lakh" in df_text.lower():
        unit = "INR_lakh"
    elif "crore" in df_text.lower() or "₹" in df_text:
        unit = "INR_cr"

    # Extract rows
    label_col = df.columns[0]
    for _, row in df.iterrows():
        label = str(row.get(label_col, "")).strip()
        if not label or label.lower() in ("nan", "none", "total", ""):
            continue
        if label.lower().startswith(("note", "source", "figure")):
            continue

        for col, period in year_cols.items():
            value = row.get(col)
            if pd.isna(value):
                continue
            try:
                numeric = float(str(value).replace(",", "").replace("₹", "").replace("(", "-").replace(")", ""))
            except (ValueError, TypeError):
                continue

            facts.append({
                "raw_label": label,
                "period": period,
                "value": numeric,
                "unit": unit,
                "source": source,
            })

    return facts


# =============================================================================
# Web parser (adapted from CaseGen)
# =============================================================================

def parse_url(url: str) -> tuple:
    """Fetch URL, extract clean text. Returns (text, warning)."""
    import requests
    from bs4 import BeautifulSoup

    url = url.strip()
    if not url:
        return "", None

    headers = {"User-Agent": "Mozilla/5.0 (compatible; FinGen/1.0)"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise Exception(f"Failed to fetch {url}: {e}")

    content_type = response.headers.get("Content-Type", "").lower()
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return parse_pdf_bytes(response.content), None

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    text = _extract_main_text(soup)
    warning = _detect_homepage_junk(text)
    return text, warning


def _extract_main_text(soup) -> str:
    for selector in [{"name": "main"}, {"name": "article"}, {"attrs": {"role": "main"}},
                     {"name": "div", "attrs": {"id": "content"}}]:
        el = soup.find(**selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 300:
                return text
    body = soup.find("body")
    return body.get_text(separator="\n", strip=True) if body else ""


def _detect_homepage_junk(text: str) -> Optional[str]:
    if not text or len(text) < 200:
        return None
    lower = text.lower()
    nav_keywords = ["cookie", "privacy policy", "sign in", "subscribe", "accept all"]
    nav_hits = sum(1 for kw in nav_keywords if kw in lower)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    short_ratio = sum(1 for ln in lines if len(ln) < 40) / max(len(lines), 1)
    if nav_hits >= 2 and short_ratio > 0.45:
        return "Content looks like a homepage (nav/cookie banners). Link to a PDF or article instead."
    return None


# =============================================================================
# Whisper audio (adapted from CaseGen)
# =============================================================================

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
_model_cache: dict = {}


def get_whisper_model(model_size: Optional[str] = None):
    """Load Whisper model once (singleton cache)."""
    try:
        import whisper
    except ImportError as e:
        raise RuntimeError("Audio needs 'openai-whisper' + torch.") from e

    size = model_size or WHISPER_MODEL
    if size not in _model_cache:
        _model_cache[size] = whisper.load_model(size)
    return _model_cache[size]


def transcribe_audio_bytes(content: bytes, filename: str = "audio.mp3", model_size: str = None) -> str:
    """Transcribe audio bytes with Whisper."""
    os.makedirs("uploads", exist_ok=True)
    temp_path = os.path.join("uploads", filename)
    with open(temp_path, "wb") as f:
        f.write(content)
    try:
        model = get_whisper_model(model_size)
        result = model.transcribe(temp_path)
        return result.get("text", "").strip()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# =============================================================================
# Narrative text chunker (ONLY for narrative text — never tables)
# =============================================================================

def chunk_narrative_text(text: str, chunk_size: int = 2000, chunk_overlap: int = 300) -> List[str]:
    """
    Chunk NARRATIVE text only (MD&A, risk factors, transcripts).
    Financial tables must NEVER go through this — they are extracted
    structurally by spreadsheet_to_facts / Extractor.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)