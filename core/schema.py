"""
FinGen v2 — Core Schema (Canonical Fact Model)
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from uuid import UUID
from datetime import date


class Fact(BaseModel):
    """Canonical financial fact - every number in the system maps to this."""
    
    # Identity
    company_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    
    # Classification (must match taxonomy.yaml)
    statement: Literal["IS", "BS", "CF", "SEGMENT", "KPI", "GUIDANCE"] = Field(
        description="Financial statement type"
    )
    line_item: str = Field(
        description="Normalized taxonomy key, e.g., revenue_from_operations"
    )
    raw_label: Optional[str] = Field(
        default=None,
        description="Original label from source document"
    )
    
    # Period
    period: str = Field(description="Period identifier: FY24, Q1FY25, 2024-03-31, TTM")
    period_type: Optional[Literal["FY", "Q", "TTM", "YTD", "H1", "H2"]] = None
    
    # Value
    value: float = Field(description="Numeric value")
    unit: Literal[
        "INR_cr", "INR_lakh", "INR", "INR_mn", "INR_bn",
        "USD_mn", "USD_bn", "EUR_mn", "EUR_bn",
        "percentage", "ratio", "times", "days", "shares"
    ] = Field(description="Unit of the value")
    scaling_factor: float = Field(
        default=1.0,
        description="Multiplier to convert to base unit (e.g., 100 for crore->lakh)"
    )
    
    # Source & Quality
    page: Optional[int] = Field(default=None, description="Source page number")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Extraction confidence 0-1"
    )
    edited_by_user: bool = Field(
        default=False,
        description="True if user manually edited in Review Grid"
    )
    source_text: Optional[str] = Field(
        default=None,
        description="Surrounding text for context"
    )
    meta: dict = Field(default_factory=dict)


class Company(BaseModel):
    id: Optional[UUID] = None
    user_id: UUID
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    currency: str = "INR"
    unit: str = "crore"
    sector: Optional[str] = None
    industry: Optional[str] = None
    is_active: bool = True


class Assumption(BaseModel):
    company_id: UUID
    scenario: str  # bull, base, bear, custom
    driver: str    # revenue_growth, ebitda_margin, etc.
    period: str
    value: float
    unit: Optional[str] = None
    rationale: Optional[str] = None
    source_document_id: Optional[UUID] = None
    source_page: Optional[int] = None
    is_manual: bool = True


class NarrativeSnippet(BaseModel):
    company_id: UUID
    document_id: Optional[UUID] = None
    section: Optional[str] = None  # risk_factors, mda, auditor_report, etc.
    text: str
    page: Optional[int] = None
    themes: List[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    blocking: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    edited_facts: List[dict] = Field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        return len(self.blocking) == 0


class AnalyticsResult(BaseModel):
    metrics: dict
    metadata: dict = Field(default_factory=dict)


# Unit conversion helpers
UNIT_CONVERSIONS = {
    # To INR_cr (base)
    "INR_cr": 1.0,
    "INR_lakh": 0.01,
    "INR": 0.0000001,
    "INR_mn": 0.1,
    "INR_bn": 100.0,
    "USD_mn": 8.3,      # Approx, should use FX rate
    "USD_bn": 8300.0,
    "EUR_mn": 9.0,
    "EUR_bn": 9000.0,
}

def convert_to_base_unit(value: float, from_unit: str, to_unit: str = "INR_cr") -> float:
    """Convert value from one unit to another via base unit (INR_cr)."""
    from_factor = UNIT_CONVERSIONS.get(from_unit)
    to_factor = UNIT_CONVERSIONS.get(to_unit)
    if not from_factor or not to_factor:
        raise ValueError(f"Unknown unit: {from_unit} or {to_unit}")
    # Convert to base, then to target
    base_value = value * from_factor
    return base_value / to_factor

def normalize_fact_unit(fact: Fact, target_unit: str = "INR_cr") -> Fact:
    """Return a copy of fact with value converted to target_unit."""
    if fact.unit == target_unit:
        return fact
    new_value = convert_to_base_unit(fact.value, fact.unit, target_unit)
    return fact.model_copy(update={"value": new_value, "unit": target_unit})