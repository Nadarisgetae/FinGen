"""
FinGen v2 — Document Repository
"""

from typing import List, Optional
from uuid import UUID

from core.db.repos.base import BaseRepo


class DocumentRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("documents", use_service_key)
    
    def create_document(self, company_id: UUID, user_id: UUID, **kwargs) -> dict:
        data = {
            "company_id": str(company_id),
            "user_id": str(user_id),
            **kwargs
        }
        return self.create(data)
    
    def get_by_company(self, company_id: UUID, status: str = None) -> List[dict]:
        filters = {"company_id": str(company_id)}
        if status:
            filters["status"] = status
        return self.list(filters, order_by="created_at", desc=True)
    
    def get_by_sha256(self, user_id: UUID, sha256: str) -> Optional[dict]:
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            for r in _in_memory_db["documents"]:
                if str(r.get("user_id")) == str(user_id) and r.get("sha256") == sha256:
                    return dict(r)
            return None
        result = self.client.table(self.table).select("*").eq("user_id", str(user_id)).eq("sha256", sha256).single().execute()
        return result.data if result.data else None
    
    def update_status(self, doc_id: UUID, status: str, error_message: str = None, **kwargs) -> Optional[dict]:
        data = {"status": status}
        if error_message:
            data["error_message"] = error_message
        data.update(kwargs)
        return self.update(doc_id, data)
    
    def get_completed_by_type(self, company_id: UUID, doc_type: str) -> List[dict]:
        return self.list({
            "company_id": str(company_id),
            "type": doc_type,
            "status": "completed"
        }, order_by="created_at", desc=True)