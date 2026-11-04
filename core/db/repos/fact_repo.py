"""
FinGen v2 — Fact Repository (Core for Analytics)
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from dataclasses import dataclass

from core.db.repos.base import BaseRepo
from core.schema import Fact


class FactRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("facts", use_service_key)
    
    def bulk_upsert_facts(self, facts: List[Fact], company_id: UUID, user_id: UUID, document_id: UUID = None) -> List[dict]:
        """Bulk insert facts with upsert on unique constraint."""
        if not facts:
            return []
        
        payload = []
        for f in facts:
            data = {
                "company_id": str(company_id),
                "user_id": str(user_id),
                "statement": f.statement,
                "line_item": f.line_item,
                "period": f.period,
                "period_type": f.period_type,
                "value": float(f.value),
                "unit": f.unit,
                "scaling_factor": float(f.scaling_factor) if f.scaling_factor else 1.0,
                "page": f.page,
                "confidence": float(f.confidence) if f.confidence else 1.0,
                "edited_by_user": f.edited_by_user,
                "source_text": f.source_text,
            }
            if document_id:
                data["document_id"] = str(document_id)
            if f.raw_label:
                data["raw_label"] = f.raw_label
            if f.meta:
                data["meta"] = f.meta
            payload.append(data)
        
        # Use upsert (on conflict do update)
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            import uuid
            res = []
            for p in payload:
                existing_idx = next(
                    (i for i, r in enumerate(_in_memory_db["facts"])
                     if str(r.get("company_id")) == str(p.get("company_id"))
                     and r.get("statement") == p.get("statement")
                     and r.get("line_item") == p.get("line_item")
                     and r.get("period") == p.get("period")),
                    None
                )
                if existing_idx is not None:
                    _in_memory_db["facts"][existing_idx].update(p)
                    res.append(_in_memory_db["facts"][existing_idx])
                else:
                    if "id" not in p:
                        p["id"] = str(uuid.uuid4())
                    _in_memory_db["facts"].append(p)
                    res.append(p)
            return res

        try:
            result = self.client.table(self.table).upsert(
                payload,
                on_conflict="company_id,statement,line_item,period,unit,document_id"
            ).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Bulk upsert facts failed: {e}")
            raise
    
    def get_by_company_period(
        self, 
        company_id: UUID, 
        periods: List[str] = None,
        statements: List[str] = None,
        line_items: List[str] = None,
        edited_only: bool = False,
        min_confidence: float = 0.0
    ) -> List[dict]:
        """Get facts for a company with flexible filters."""
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            results = []
            for r in _in_memory_db["facts"]:
                if str(r.get("company_id")) != str(company_id):
                    continue
                if periods and r.get("period") not in periods:
                    continue
                if statements and r.get("statement") not in statements:
                    continue
                if line_items and r.get("line_item") not in line_items:
                    continue
                if edited_only and not r.get("edited_by_user"):
                    continue
                if min_confidence > 0 and float(r.get("confidence", 1.0)) < min_confidence:
                    continue
                results.append(dict(r))
            return results

        query = self.client.table(self.table).select("*").eq("company_id", str(company_id))
        
        if periods:
            query = query.in_("period", periods)
        if statements:
            query = query.in_("statement", statements)
        if line_items:
            query = query.in_("line_item", line_items)
        if edited_only:
            query = query.eq("edited_by_user", True)
        if min_confidence > 0:
            query = query.gte("confidence", min_confidence)
        
        # Order by statement, line_item, period
        query = query.order("statement").order("line_item").order("period")
        
        result = query.execute()
        return result.data or []
    
    def get_for_report(
        self, 
        company_id: UUID, 
        required_facts: Dict[str, List[str]]  # {section_key: [fact_keys]}
    ) -> Dict[str, List[dict]]:
        """
        Get all facts needed for a report template.
        required_facts = {"leverage": ["BS.total_debt", "BS.total_equity", ...], ...}
        """
        # Flatten all required fact keys
        all_keys = set()
        for keys in required_facts.values():
            all_keys.update(keys)
        
        # Parse statement.line_item
        statement_line_items = {}
        for key in all_keys:
            if "." in key:
                stmt, item = key.split(".", 1)
                statement_line_items.setdefault(stmt, set()).add(item)
        
        # Fetch by statement
        all_facts = []
        for stmt, items in statement_line_items.items():
            facts = self.get_by_company_period(
                company_id=company_id,
                statements=[stmt],
                line_items=list(items),
            )
            all_facts.extend(facts)
        
        # Group by section
        result = {}
        for section, keys in required_facts.items():
            section_facts = [f for f in all_facts if f"{f['statement']}.{f['line_item']}" in keys]
            result[section] = section_facts
        
        return result
    
    def get_latest_period_values(self, company_id: UUID, line_items: List[str], statement: str) -> Dict[str, dict]:
        """Get the most recent period value for each line item."""
        facts = self.get_by_company_period(
            company_id=company_id,
            statements=[statement],
            line_items=line_items,
        )
        
        # Group by line_item, take latest period
        latest = {}
        for f in facts:
            key = f["line_item"]
            if key not in latest or f["period"] > latest[key]["period"]:
                latest[key] = f
        
        return latest
    
    def get_time_series(self, company_id: UUID, line_item: str, statement: str, periods: int = 10) -> List[dict]:
        """Get time series for a single line item (most recent N periods)."""
        facts = self.get_by_company_period(
            company_id=company_id,
            statements=[statement],
            line_items=[line_item],
        )
        # Sort by period desc, take N
        facts.sort(key=lambda x: x["period"], reverse=True)
        return facts[:periods]
    
    def update_fact(self, fact_id: UUID, value: float = None, unit: str = None, edited_by_user: bool = True, **kwargs) -> Optional[dict]:
        """Update a fact (typically user edit in Review Grid)."""
        data = {"edited_by_user": edited_by_user}
        if value is not None:
            data["value"] = value
        if unit is not None:
            data["unit"] = unit
        data.update(kwargs)
        return self.update(fact_id, data)
    
    def get_validation_data(self, company_id: UUID) -> Dict[str, List[dict]]:
        """Get all facts needed for validation, grouped by statement."""
        statements = ["IS", "BS", "CF", "SEGMENT", "KPI", "GUIDANCE"]
        result = {}
        for stmt in statements:
            facts = self.get_by_company_period(company_id=company_id, statements=[stmt])
            result[stmt] = facts
        return result


# Import logger at bottom to avoid circular import
import logging
logger = logging.getLogger(__name__)