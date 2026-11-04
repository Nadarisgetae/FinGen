"""
FinGen v2 — Review Queue Repository (unmapped line items)
"""

from typing import List, Optional
from uuid import UUID

from core.db.repos.base import BaseRepo


class ReviewQueueRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("review_queue", use_service_key)

    def get_pending(self, company_id: UUID = None, limit: int = 100) -> List[dict]:
        filters = {"status": "pending"}
        if company_id:
            filters["company_id"] = str(company_id)
        return self.list(filters, order_by="created_at", limit=limit)

    def resolve(self, item_id: UUID, mapped_taxonomy_key: str, reviewer_notes: str = None) -> Optional[dict]:
        data = {
            "status": "mapped",
            "mapped_taxonomy_key": mapped_taxonomy_key,
            "reviewer_notes": reviewer_notes,
            "resolved_at": "now()",
        }
        return self.update(item_id, data)

    def reject(self, item_id: UUID, reviewer_notes: str = None) -> Optional[dict]:
        data = {
            "status": "rejected",
            "reviewer_notes": reviewer_notes,
            "resolved_at": "now()",
        }
        return self.update(item_id, data)
