"""
FinGen v2 — Assumption Repository
"""

from typing import List, Optional, Dict
from uuid import UUID

from core.db.repos.base import BaseRepo


class AssumptionRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("assumptions", use_service_key)
    
    def upsert_scenario(self, company_id: UUID, user_id: UUID, scenario: str, assumptions: List[Dict]) -> List[dict]:
        """Bulk upsert assumptions for a scenario."""
        if not assumptions:
            return []
        
        payload = []
        for a in assumptions:
            payload.append({
                "company_id": str(company_id),
                "user_id": str(user_id),
                "scenario": scenario,
                "driver": a["driver"],
                "period": a["period"],
                "value": float(a["value"]),
                "unit": a.get("unit"),
                "rationale": a.get("rationale"),
                "source_document_id": str(a["source_document_id"]) if a.get("source_document_id") else None,
                "source_page": a.get("source_page"),
                "is_manual": a.get("is_manual", True),
            })
        
        try:
            result = self.client.table(self.table).upsert(
                payload,
                on_conflict="company_id,scenario,driver,period"
            ).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Upsert scenario failed: {e}")
            raise
    
    def get_by_company(self, company_id: UUID, scenario: str = None) -> List[dict]:
        filters = {"company_id": str(company_id)}
        if scenario:
            filters["scenario"] = scenario
        return self.list(filters, order_by="driver,period")
    
    def get_for_forecast(self, company_id: UUID, scenarios: List[str] = None) -> Dict[str, Dict[str, Dict]]:
        """
        Get assumptions formatted for forecast engine.
        Returns: {scenario: {driver: {period: value}}}
        """
        filters = {"company_id": str(company_id)}
        if scenarios:
            filters["scenario"] = scenarios  # This won't work directly, need in_
        
        query = self.client.table(self.table).select("*").eq("company_id", str(company_id))
        if scenarios:
            query = query.in_("scenario", scenarios)
        
        result = query.execute()
        data = result.data or []
        
        output = {}
        for row in data:
            sc = row["scenario"]
            dr = row["driver"]
            pd = row["period"]
            if sc not in output:
                output[sc] = {}
            if dr not in output[sc]:
                output[sc][dr] = {}
            output[sc][dr][pd] = {"value": row["value"], "unit": row["unit"]}
        
        return output
    
    def delete_scenario(self, company_id: UUID, scenario: str) -> bool:
        self.client.table(self.table).delete().eq("company_id", str(company_id)).eq("scenario", scenario).execute()
        return True


import logging
logger = logging.getLogger(__name__)