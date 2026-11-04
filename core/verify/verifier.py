"""
FinGen v2 — Verifier (Code-First, LLM Second)

Code-first: regex-extract every number from the markdown,
normalize to canonical unit, match against fact store + analytics.
Flags: MISSING_SOURCE, MISMATCH, UNSUPPORTED_CLAIM, PROMOTIONAL_LANGUAGE.

LLM second pass: only on flagged segments, for rewrite suggestions.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from core.schema import Fact
from core.schema import convert_to_base_unit

logger = logging.getLogger(__name__)


class FlagType(str, Enum):
    MISSING_SOURCE = "MISSING_SOURCE"
    MISMATCH = "MISMATCH"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    PROMOTIONAL_LANGUAGE = "PROMOTIONAL_LANGUAGE"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Flag:
    flag_type: FlagType
    severity: Severity
    location: str          # text snippet where flagged
    text_value: str        # the number as written in text
    expected_value: Optional[float] = None
    expected_unit: Optional[str] = None
    source: Optional[str] = None  # fact line_item or analytics name
    message: str = ""


@dataclass
class VerificationResult:
    flags: List[Flag] = field(default_factory=list)
    numbers_checked: int = 0
    numbers_verified: int = 0
    unsupported_claims: List[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.flags if f.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.flags if f.severity == Severity.WARNING)

    @property
    def is_clean(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> Dict:
        return {
            "flags": [
                {
                    "flag_type": f.flag_type.value,
                    "severity": f.severity.value,
                    "location": f.location,
                    "text_value": f.text_value,
                    "expected_value": f.expected_value,
                    "expected_unit": f.expected_unit,
                    "source": f.source,
                    "message": f.message,
                }
                for f in self.flags
            ],
            "numbers_checked": self.numbers_checked,
            "numbers_verified": self.numbers_verified,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


# Regex to find numbers with optional currency/unit context
# Matches: 1,234.56 / ₹1,234 cr / 15.5% / 2.5x / $4.5 bn
NUMBER_PATTERN = re.compile(
    r"(?P<number>[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)"
    r"(?P<unit>\s*(?:%|percent|crore|cr|lakh|mn|bn|billion|million|x|times|₹|Rs\.?|INR|USD|\$)?)",
    re.IGNORECASE,
)

PROMOTIONAL_PATTERNS = [
    r"\b(best[- ]in[- ]class|world[- ]class|revolutionary|unparalleled|outstanding|exceptional|market[- ]leader|leading|premium|superior|excellent)\b",
    r"\b(unprecedented|game[- ]changing|groundbreaking|pioneering)\b",
]
PROMOTIONAL_RE = re.compile("|".join(PROMOTIONAL_PATTERNS), re.IGNORECASE)

UNSUPPORTED_CLAIM_PATTERNS = [
    r"\b(expect[s]? to|is expected to|will likely|we believe|management expects|guidance suggests)\b",
]
UNSUPPORTED_RE = re.compile("|".join(UNSUPPORTED_CLAIM_PATTERNS), re.IGNORECASE)


class Verifier:
    """
    Code-first verification of generated report text.
    """

    def __init__(
        self,
        facts: List[Fact],
        analytics_results: Dict[str, Dict[str, Any]] = None,
        tolerance_reported: float = 0.01,   # 1% for reported figures
        tolerance_derived: float = 0.05,    # 5% for analytics-derived
    ):
        self.facts = facts
        self.analytics_results = analytics_results or {}
        self.tolerance_reported = tolerance_reported
        self.tolerance_derived = tolerance_derived

        # Build lookup of all known numeric values (normalized to INR_cr where possible)
        self.known_values: List[Dict] = []  # {value_inr_cr, unit, line_item, period, source_type}
        for f in facts:
            try:
                base = convert_to_base_unit(f.value, f.unit)
            except Exception:
                base = f.value
            self.known_values.append({
                "value_inr_cr": base,
                "original_value": f.value,
                "unit": f.unit,
                "line_item": f.line_item,
                "period": f.period,
                "source_type": "fact",
                "source": f"{f.line_item} ({f.period})",
            })

        # Add analytics-derived values
        for section, analytics in self.analytics_results.items():
            for aname, aresult in analytics.items():
                metrics = aresult.get("metrics", {}) if isinstance(aresult, dict) else {}
                flat = self._flatten_metrics(metrics)
                for key, val in flat.items():
                    if isinstance(val, (int, float)):
                        self.known_values.append({
                            "value_inr_cr": float(val),
                            "original_value": float(val),
                            "unit": "mixed",
                            "line_item": f"{aname}.{key}",
                            "period": "computed",
                            "source_type": "analytics",
                            "source": f"{aname}.{key}",
                        })

    def _flatten_metrics(self, metrics: Any, prefix: str = "") -> Dict[str, Any]:
        """Flatten nested analytics metrics dict."""
        flat = {}
        if isinstance(metrics, dict):
            for k, v in metrics.items():
                full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
                if isinstance(v, (int, float)):
                    flat[full_key] = v
                elif isinstance(v, dict):
                    flat.update(self._flatten_metrics(v, full_key))
                elif isinstance(v, list):
                    # Sum lists of numbers (e.g., projected values)
                    if v and all(isinstance(x, (int, float)) for x in v):
                        flat[full_key] = sum(v)
        return flat

    def verify(self, markdown: str) -> VerificationResult:
        """Verify all numbers in the markdown."""
        result = VerificationResult()

        # Strip markdown formatting for analysis
        text = re.sub(r"[*_`#|]", " ", markdown)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # links

        # 1. Extract all numbers with context
        matches = list(NUMBER_PATTERN.finditer(text))
        result.numbers_checked = len(matches)

        for m in matches:
            number_str = m.group("number")
            unit_str = (m.group("unit") or "").strip().lower()
            value = self._parse_number(number_str)
            if value is None:
                continue

            # Context window (sentence around the number)
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 100)
            context = text[start:end]

            # Normalize value to INR_cr if unit detected
            normalized_unit = self._detect_unit(unit_str, context)
            try:
                normalized_value = convert_to_base_unit(value, normalized_unit)
            except Exception:
                normalized_value = value
                normalized_unit = None

            # Try to match against known values
            matched = self._match_value(normalized_value, normalized_unit, value, unit_str)

            if matched:
                result.numbers_verified += 1
            else:
                # Check if it might be a derived/calculated value (e.g., simple arithmetic)
                if self._is_likely_derived(value, normalized_value, context):
                    result.numbers_verified += 1
                else:
                    flag = Flag(
                        flag_type=FlagType.MISMATCH,
                        severity=Severity.WARNING,  # MISMATCH is warning; hard errors reserved
                        location=context.strip()[:200],
                        text_value=f"{number_str} {unit_str}".strip(),
                        message=f"Number '{number_str} {unit_str}' not found in fact store or analytics",
                    )
                    result.flags.append(flag)

        # 2. Promotional language scan
        for m in PROMOTIONAL_RE.finditer(text):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            flag = Flag(
                flag_type=FlagType.PROMOTIONAL_LANGUAGE,
                severity=Severity.WARNING,
                location=text[start:end].strip()[:200],
                text_value=m.group(0),
                message=f"Promotional language '{m.group(0)}' — neutralize unless backed by fact store data",
            )
            result.flags.append(flag)

        # 3. Unsupported claim scan (forward-looking statements without source)
        for m in UNSUPPORTED_RE.finditer(text):
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            snippet = text[start:end].strip()[:200]
            # Check if "estimate" or "assumption" nearby (allowed)
            if not re.search(r"\b(estimate|assumption|scenario|projection)\b", snippet, re.IGNORECASE):
                flag = Flag(
                    flag_type=FlagType.UNSUPPORTED_CLAIM,
                    severity=Severity.WARNING,
                    location=snippet,
                    text_value=m.group(0),
                    message="Forward-looking claim without estimate/assumption label",
                )
                result.flags.append(flag)
                result.unsupported_claims.append(snippet)

        return result

    def _parse_number(self, number_str: str) -> Optional[float]:
        """Parse '1,234.56' -> 1234.56."""
        try:
            return float(number_str.replace(",", ""))
        except ValueError:
            return None

    def _detect_unit(self, unit_str: str, context: str) -> str:
        """Detect unit from explicit unit string or context."""
        unit_map = {
            "%": "percentage", "percent": "percentage",
            "crore": "INR_cr", "cr": "INR_cr",
            "lakh": "INR_lakh",
            "mn": "INR_mn", "million": "INR_mn",
            "bn": "INR_bn", "billion": "INR_bn",
            "x": "times", "times": "times",
        }
        if unit_str in unit_map:
            return unit_map[unit_str]

        # Context hints
        ctx_lower = context.lower()
        if "crore" in ctx_lower or " cr" in ctx_lower or "₹" in ctx_lower or "inr" in ctx_lower:
            return "INR_cr"
        if "lakh" in ctx_lower:
            return "INR_lakh"
        if "billion" in ctx_lower or "$" in ctx_lower:
            return "USD_bn"
        if "million" in ctx_lower:
            return "USD_mn"
        return "INR_cr"  # default for Indian financial reports

    def _match_value(
        self,
        normalized_value: float,
        normalized_unit: Optional[str],
        original_value: float,
        unit_str: str,
    ) -> bool:
        """Check if value matches any known value within tolerance."""
        for known in self.known_values:
            kv = known["value_inr_cr"]

            # If both are INR_cr-normalized, compare directly
            if normalized_unit and known["unit"] in ("INR_cr", "INR_lakh", "INR", "INR_mn", "INR_bn", "USD_mn", "USD_bn"):
                tolerance = (
                    self.tolerance_reported
                    if known["source_type"] == "fact"
                    else self.tolerance_derived
                )
                if kv != 0 and abs(normalized_value - kv) / abs(kv) <= tolerance:
                    return True
                if kv == 0 and abs(normalized_value) < 0.01:
                    return True

            # Fallback: compare raw values (for ratios, percentages, times)
            if known["unit"] in ("percentage", "ratio", "times", "days", "score", "grade", "mixed"):
                if kv != 0 and abs(original_value - known["original_value"]) / abs(kv) <= self.tolerance_derived:
                    return True

        return False

    def _is_likely_derived(self, value: float, normalized_value: float, context: str) -> bool:
        """
        Check if a number is likely a simple derived value
        (e.g., sum/difference/percentage of known values).
        """
        known_vals = [k["value_inr_cr"] for k in self.known_values if k["source_type"] == "fact"]

        # Check pairwise sums and differences
        for i, a in enumerate(known_vals):
            for b in known_vals[i + 1:]:
                for derived in (a + b, a - b, b - a):
                    if derived != 0 and abs(normalized_value - derived) / abs(derived) <= self.tolerance_derived:
                        return True

        # Check percentage of a known value
        for a in known_vals:
            if a != 0:
                pct = normalized_value / a * 100
                if 0.1 < pct < 100 and abs(pct - round(pct)) < 0.01:
                    return True

        return False

    def generate_flags_report(self, result: VerificationResult) -> str:
        """Human-readable flags summary."""
        lines = ["# Verification Report\n"]
        lines.append(f"Numbers checked: {result.numbers_checked}")
        lines.append(f"Numbers verified: {result.numbers_verified}")
        lines.append(f"Errors: {result.error_count} | Warnings: {result.warning_count}\n")

        for flag in result.flags:
            lines.append(
                f"- **[{flag.flag_type.value}]** ({flag.severity.value}) "
                f"`{flag.text_value}` — {flag.message}\n"
                f"  Location: ...{flag.location}..."
            )
        return "\n".join(lines)