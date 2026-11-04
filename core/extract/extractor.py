"""
FinGen v2 — Extractor Agent
Replaces CaseGen Agent 1. Section-based extraction (not chunked).
Maps raw labels -> taxonomy keys. Outputs Fact rows + narrative snippets.
"""

import re
import json
import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from core.schema import Fact, NarrativeSnippet, Company
from core.llm.router import TaskType, Router, get_router, build_extraction_prompt

logger = logging.getLogger(__name__)


# =============================================================================
# Response Schemas for Structured Output
# =============================================================================

class FactItem(BaseModel):
    raw_label: str
    line_item: Optional[str] = None
    period: str
    value: float
    unit: str = "INR_cr"
    page: Optional[int] = None


class UnmappedItem(BaseModel):
    raw_label: str
    period: str
    value: float
    unit: str = "INR_cr"
    page: Optional[int] = None


class FactListResponse(BaseModel):
    facts: List[FactItem] = Field(default_factory=list)
    unmapped: List[UnmappedItem] = Field(default_factory=list)


class ExtractionResult:
    def __init__(
        self,
        facts: List[Fact],
        snippets: List[NarrativeSnippet],
        unmapped: List[Dict],
        stats: Dict[str, Any],
    ):
        self.facts = facts
        self.snippets = snippets
        self.unmapped = unmapped
        self.stats = stats


# =============================================================================
# Extractor Engine
# =============================================================================

class Extractor:
    """
    Extracts structured financial facts from document sections.

    Design:
    - Each document section (IS, BS, CF) is fed WHOLE to the LLM (never chunked).
    - Section-based splitter prevents disclosure notes and schedules from bleeding in.
    - LLM maps raw labels to taxonomy keys using taxonomy.yaml aliases.
    - Unmapped labels go to review_queue.
    - Narrative sections (risk factors, MD&A, auditor report) -> NarrativeSnippet rows.
    """

    @staticmethod
    def _clean_label(label: str) -> str:
        """Strip punctuation, normalize whitespace, and convert to lowercase."""
        if not label:
            return ""
        return re.sub(r"[^\w\s]", "", str(label)).strip().lower()

    def __init__(
        self,
        taxonomy_path: str = "config/taxonomy.yaml",
        router: Optional[Router] = None,
    ):
        with open(taxonomy_path, encoding="utf-8") as f:
            self.taxonomy = yaml.safe_load(f) or {}

        # Build alias -> key lookup and statement lookup
        self.alias_map: Dict[str, str] = {}
        self.statement_of_key: Dict[str, str] = {}
        for statement, items in self.taxonomy.items():
            if not isinstance(items, dict):
                continue
            for key, spec in items.items():
                if not isinstance(spec, dict):
                    continue
                stmt_code = {"income_statement": "IS", "balance_sheet": "BS", "cash_flow": "CF", "segment": "SEGMENT"}.get(statement, statement.upper())
                self.statement_of_key[key] = stmt_code
                
                # Register aliases
                for alias in spec.get("aliases", []):
                    clean_alias = self._clean_label(alias)
                    self.alias_map[clean_alias] = key
                # Register exact key
                self.alias_map[self._clean_label(key)] = key
                # Register human readable version of key
                self.alias_map[self._clean_label(key.replace("_", " "))] = key

        # Router injection with fallback
        if router is not None:
            self.router = router
        else:
            try:
                self.router = get_router()
            except Exception:
                self.router = Router()

    def _classify_label(self, raw_label: str) -> Optional[str]:
        """Exact and token-overlap match of a raw label to a taxonomy key."""
        if not raw_label:
            return None
        clean = self._clean_label(raw_label)
        if not clean:
            return None

        # 1. Exact alias match
        if clean in self.alias_map:
            return self.alias_map[clean]

        # 2. Token overlap match (require all words of alias in raw_label or high overlap)
        tokens = set(clean.split())
        best_match = None
        best_score = 0.0

        for alias, tax_key in self.alias_map.items():
            alias_tokens = set(alias.split())
            if not alias_tokens:
                continue
            if alias_tokens.issubset(tokens):
                score = len(alias_tokens) / len(tokens)
                if score > best_score and len(alias_tokens) >= 2:
                    best_score = score
                    best_match = tax_key

        return best_match

    def extract_from_text(
        self,
        company_id=None,
        user_id=None,
        document_id=None,
        document_type: str = "annual_report",
        text: str = "",
        fiscal_year: str = None,
    ) -> ExtractionResult:
        """
        Synchronous extraction of facts from document text.
        """
        sections = self._split_sections(text)

        all_facts: List[Fact] = []
        all_snippets: List[NarrativeSnippet] = []
        unmapped: List[Dict] = []
        stats = {"sections": {}, "llm_calls": 0}

        for section_name, section_text in sections.items():
            if not section_text or len(section_text.strip()) < 50:
                continue

            if section_name.upper() in ("IS", "BS", "CF", "SEGMENT"):
                facts, section_unmapped, calls = self._extract_financial_section(
                    company_id=company_id,
                    user_id=user_id,
                    document_id=document_id,
                    section=section_name.upper(),
                    section_text=section_text,
                    fiscal_year=fiscal_year,
                )
                all_facts.extend(facts)
                unmapped.extend(section_unmapped)
                stats["llm_calls"] += calls
                stats["sections"][section_name] = {"facts": len(facts), "unmapped": len(section_unmapped)}
            else:
                snippets = self._extract_narrative(
                    company_id=company_id,
                    user_id=user_id,
                    document_id=document_id,
                    section=section_name,
                    section_text=section_text,
                )
                all_snippets.extend(snippets)
                stats["sections"][section_name] = {"snippets": len(snippets)}

        return ExtractionResult(
            facts=all_facts,
            snippets=all_snippets,
            unmapped=unmapped,
            stats=stats,
        )

    async def extract_from_text_async(
        self,
        company_id=None,
        user_id=None,
        document_id=None,
        document_type: str = "annual_report",
        text: str = "",
        fiscal_year: str = None,
    ) -> ExtractionResult:
        """Asynchronous wrapper for extract_from_text."""
        return self.extract_from_text(
            company_id=company_id,
            user_id=user_id,
            document_id=document_id,
            document_type=document_type,
            text=text,
            fiscal_year=fiscal_year,
        )

    def _split_sections(self, text: str) -> Dict[str, str]:
        """
        Split document text into financial and narrative sections.
        Detects section boundaries and isolates statement tables from disclosure notes.
        """
        raw_sections: Dict[str, List[str]] = {}
        lines = text.split("\n")
        current_section = "OTHER"
        statement_line_count = 0
        MAX_STATEMENT_LINES = 350  # Cap statement pages (~4-5 pages max)

        is_keywords = [
            "statement of profit and loss", "profit and loss statement",
            "statement of profit & loss", "statement of operations",
            "income statement", "consolidated statement of profit",
        ]
        bs_keywords = [
            "balance sheet", "statement of financial position",
        ]
        cf_keywords = [
            "cash flow statement", "statement of cash flows",
            "consolidated cash flow", "cash flows statement",
        ]
        segment_keywords = [
            "segment reporting", "segment information", "segment revenue",
        ]
        narrative_keywords = {
            "risk_factors": ["risk factor", "risk management", "principal risks"],
            "mda": ["management discussion", "operating and financial review", "md&a", "managements discussion"],
            "auditor_report": ["auditors report", "auditor's report", "independent auditor"],
            "corporate_governance": ["corporate governance", "governance report"],
        }
        termination_keywords = [
            "notes forming part of", "notes to the financial", "notes to financial",
            "notes to the consolidated", "significant accounting policies",
            "notes to accounts", "note 1 :", "note 1:", "note 1 -",
        ]

        def classify_heading(heading: str) -> Optional[str]:
            h = heading.lower().replace("’", "'").replace("&", "and")
            h_clean = re.sub(r"[^\w\s]", " ", h)

            # Check termination first (notes / policies exit statements)
            for kw in termination_keywords:
                if kw in h_clean:
                    return "NOTES"

            is_consolidated = "consolidated" in h_clean

            # Segment
            for kw in segment_keywords:
                if kw in h_clean:
                    return "SEGMENT"

            # Financial statements
            for kw in is_keywords:
                if kw in h_clean:
                    return "CONSOLIDATED_IS" if is_consolidated else "STANDALONE_IS"

            for kw in bs_keywords:
                if kw in h_clean:
                    return "CONSOLIDATED_BS" if is_consolidated else "STANDALONE_BS"

            for kw in cf_keywords:
                if kw in h_clean:
                    return "CONSOLIDATED_CF" if is_consolidated else "STANDALONE_CF"

            # Narrative
            for section, kws in narrative_keywords.items():
                if any(kw in h_clean for kw in kws):
                    return section

            return None

        for line in lines:
            stripped = line.strip()
            # Detect headings (#, all-caps short line, or markdown bold title)
            is_heading = (
                stripped.startswith("#") or
                stripped.startswith("**") and stripped.endswith("**") and len(stripped) < 80 or
                (len(stripped) < 80 and stripped.isupper() and any(c.isalpha() for c in stripped))
            )

            if is_heading:
                clean_heading = stripped.lstrip("#* ").rstrip("* ")
                classified = classify_heading(clean_heading)
                if classified:
                    current_section = classified
                    statement_line_count = 0
                elif current_section in ("CONSOLIDATED_IS", "CONSOLIDATED_BS", "CONSOLIDATED_CF",
                                         "STANDALONE_IS", "STANDALONE_BS", "STANDALONE_CF"):
                    # Check if line looks like a note boundary
                    if any(term in clean_heading.lower() for term in ["note", "schedule", "annexure"]):
                        current_section = "NOTES"
            else:
                if current_section in ("CONSOLIDATED_IS", "CONSOLIDATED_BS", "CONSOLIDATED_CF",
                                       "STANDALONE_IS", "STANDALONE_BS", "STANDALONE_CF"):
                    statement_line_count += 1
                    if statement_line_count > MAX_STATEMENT_LINES:
                        current_section = "OTHER"

            if current_section not in raw_sections:
                raw_sections[current_section] = []
            raw_sections[current_section].append(line)

        # Assemble joined sections
        sections: Dict[str, str] = {k: "\n".join(v) for k, v in raw_sections.items()}

        # Consolidate prioritization: Consolidated > Standalone
        final_sections: Dict[str, str] = {}

        for stmt in ["IS", "BS", "CF"]:
            cons_key = f"CONSOLIDATED_{stmt}"
            stand_key = f"STANDALONE_{stmt}"
            if cons_key in sections and len(sections[cons_key].strip()) > 50:
                final_sections[stmt] = sections[cons_key]
            elif stand_key in sections and len(sections[stand_key].strip()) > 50:
                final_sections[stmt] = sections[stand_key]
            elif stmt in sections:
                final_sections[stmt] = sections[stmt]

        # Copy non-statement sections
        for k, v in sections.items():
            if not k.startswith("CONSOLIDATED_") and not k.startswith("STANDALONE_") and k not in ("IS", "BS", "CF"):
                final_sections[k] = v

        return final_sections

    def _extract_financial_section(
        self,
        company_id,
        user_id,
        document_id,
        section: str,
        section_text: str,
        fiscal_year: str = None,
    ) -> tuple:
        """Extraction of a financial statement section using the LLM Router."""
        statement_key = {
            "IS": "income_statement",
            "BS": "balance_sheet",
            "CF": "cash_flow",
            "SEGMENT": "segment",
        }.get(section, "income_statement")

        tax_subset = self.taxonomy.get(statement_key, {})
        tax_json = json.dumps(tax_subset, indent=2, ensure_ascii=False)

        system = (
            "You are a financial document extraction engine for corporate reporting. "
            "Extract EVERY numerical financial line item from the provided document section. "
            "Map each raw line item to its corresponding canonical taxonomy key.\n"
            "Rules:\n"
            "1. Copy numbers EXACTLY as printed. Never calculate, invent, round, or extrapolate.\n"
            "2. Preserve units: if the section header says '₹ in crore', '(₹ in lakhs)', or 'USD in millions', "
            "assign the appropriate unit ('INR_cr', 'INR_lakh', 'USD_mn') to each value.\n"
            "3. Multi-period extraction: if columns show values for multiple periods (e.g., FY24 and FY23), "
            "extract each period as a distinct fact.\n"
            "4. Negative numbers: parentheses like (1,234.50) mean negative numbers (-1234.50).\n"
            "5. If a line item has no matching taxonomy key, set line_item to null and add it to 'unmapped'.\n"
            "6. Output must strictly conform to the FactListResponse schema.\n"
        )

        user = (
            f"TAXONOMY FOR {section}:\n{tax_json}\n\n"
            f"DOCUMENT SECTION ({section}, target fiscal year: {fiscal_year or 'Latest'}):\n"
            f"{section_text}\n\n"
            "Extract all facts and unmapped line items into valid JSON."
        )

        messages = build_extraction_prompt(system, user, FactListResponse)

        try:
            parsed = self.router.call(TaskType.EXTRACT, messages, schema=FactListResponse)
            result = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
        except Exception as e:
            logger.error(f"Extraction LLM call failed for {section}: {e}")
            return [], [], 0

        facts = []
        for item in (result.get("facts") or []):
            line_item = item.get("line_item")
            raw_label = item.get("raw_label", "")
            if not line_item:
                line_item = self._classify_label(raw_label)
            if not line_item:
                continue

            try:
                period_val = item.get("period") or fiscal_year or "FY24"
                fact = Fact(
                    company_id=company_id,
                    document_id=document_id,
                    statement=section,
                    line_item=line_item,
                    raw_label=raw_label,
                    period=period_val,
                    period_type=self._infer_period_type(period_val),
                    value=float(item.get("value", 0.0)),
                    unit=item.get("unit", "INR_cr"),
                    page=item.get("page"),
                    confidence=0.9,
                    source_text=raw_label,
                )
                facts.append(fact)
            except Exception as e:
                logger.warning(f"Failed to build Fact from item {item}: {e}")

        unmapped = result.get("unmapped") or []
        return facts, unmapped, 1

    def _extract_narrative(
        self,
        company_id,
        user_id,
        document_id,
        section: str,
        section_text: str,
    ) -> List[NarrativeSnippet]:
        """Extract narrative snippets (risk factors, MD&A, auditor notes)."""
        paragraphs = [p.strip() for p in section_text.split("\n\n") if len(p.strip()) > 80]
        snippets = []
        for para in paragraphs:
            snippet = NarrativeSnippet(
                company_id=company_id,
                document_id=document_id,
                section=section,
                text=para,
                themes=[],
            )
            snippets.append(snippet)
        return snippets

    @staticmethod
    def _infer_period_type(period: str) -> Optional[str]:
        p = (period or "").upper().strip()
        if p.startswith("FY") and "Q" not in p:
            return "FY"
        if p.startswith("Q") and "FY" in p:
            return "Q"
        if "TTM" in p:
            return "TTM"
        if p.endswith("H1") or "H1" in p:
            return "H1"
        if p.endswith("H2") or "H2" in p:
            return "H2"
        # Match 4-digit year like 2024
        if re.match(r"^(19|20)\d{2}$", p):
            return "FY"
        return "FY"
