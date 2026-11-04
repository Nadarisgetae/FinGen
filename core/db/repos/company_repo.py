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
        result = self.client.table(self.table).select("*").eq("user_id", str(user_id)).eq("ticker", ticker).single().execute()
        return result.data if result.data else None
    
    def get_by_user(self, user_id: UUID, active_only: bool = True) -> List[dict]:
        filters = {"user_id": str(user_id)}
        if active_only:
            filters["is_active"] = True
        return self.list(filters, order_by="created_at", desc=True)
    
    def search(self, user_id: UUID, query: str) -> List[dict]:
        return self.client.table(self.table).select("*").eq("user_id", str(user_id)).ilike("name", f"%{query}%").execute().data or []