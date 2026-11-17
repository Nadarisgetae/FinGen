"""
FinGen v2 — Company Repository
"""

from typing import List, Optional
from uuid import UUID

from core.db.repos.base import BaseRepo


class CompanyRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("companies", use_service_key)
    
    def create_company(self, user_id: UUID, name: str, ticker: str = None, **kwargs) -> dict:
        data = {
            "user_id": str(user_id),
            "name": name,
            "ticker": ticker,
            **kwargs
        }
        return self.create(data)
    
    def get_by_ticker(self, user_id: UUID, ticker: str) -> Optional[dict]:
        if not ticker:
            return None
        rows = self.list({"user_id": str(user_id), "ticker": ticker}, limit=1)
        return rows[0] if rows else None
    
    def get_by_user(self, user_id: UUID, active_only: bool = True) -> List[dict]:
        filters = {"user_id": str(user_id)}
        if active_only:
            filters["is_active"] = True
        return self.list(filters, order_by="created_at", desc=True)
    
    def search(self, user_id: UUID, query: str) -> List[dict]:
        if not query:
            return self.get_by_user(user_id)
        if self.client is None:
            q = query.lower()
            return [r for r in self.get_by_user(user_id) if q in (r.get("name") or "").lower()]
        try:
            return self.client.table(self.table).select("*").eq("user_id", str(user_id)).ilike("name", f"%{query}%").execute().data or []
        except Exception as e:
            return [r for r in self.get_by_user(user_id) if query.lower() in (r.get("name") or "").lower()]