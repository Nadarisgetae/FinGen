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
        
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            import uuid
            res = []
            for p in payload:
                match_idx = next(
                    (i for i, r in enumerate(_in_memory_db["assumptions"])
                     if str(r.get("company_id")) == str(p.get("company_id"))
                     and r.get("scenario") == p.get("scenario")
                     and r.get("driver") == p.get("driver")
                     and r.get("period") == p.get("period")),
                    None
                )
                if match_idx is not None:
                    _in_memory_db["assumptions"][match_idx].update(p)
                    res.append(_in_memory_db["assumptions"][match_idx])
                else:
                    if "id" not in p:
                        p["id"] = str(uuid.uuid4())
                    _in_memory_db["assumptions"].append(p)
                    res.append(p)
            return res

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
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            output = {}
            for row in _in_memory_db["assumptions"]:
                if str(row.get("company_id")) != str(company_id):
                    continue
                if scenarios and row.get("scenario") not in scenarios:
                    continue
                sc = row["scenario"]
                dr = row["driver"]
                pd = row["period"]
                if sc not in output:
                    output[sc] = {}
                if dr not in output[sc]:
                    output[sc][dr] = {}
                output[sc][dr][pd] = {"value": row["value"], "unit": row.get("unit")}
            return output

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
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            _in_memory_db["assumptions"] = [
                r for r in _in_memory_db["assumptions"]
                if not (str(r.get("company_id")) == str(company_id) and r.get("scenario") == scenario)
            ]
            return True

        self.client.table(self.table).delete().eq("company_id", str(company_id)).eq("scenario", scenario).execute()
        return True


import logging
logger = logging.getLogger(__name__)