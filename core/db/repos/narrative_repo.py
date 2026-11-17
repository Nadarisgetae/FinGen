"""
FinGen v2 — Narrative Snippets Repository
"""

from typing import List, Optional
from uuid import UUID

from core.db.repos.base import BaseRepo
from core.schema import NarrativeSnippet


class NarrativeRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("narrative_snippets", use_service_key)

    def bulk_create_snippets(self, snippets: List[NarrativeSnippet]) -> List[dict]:
        if not snippets:
            return []
        payload = []
        for s in snippets:
            payload.append({
                "company_id": str(s.company_id),
                "document_id": str(s.document_id) if s.document_id else None,
                "section": s.section,
                "text": s.text,
                "page": s.page,
                "themes": s.themes,
            })
        return self.bulk_create(payload, returning=True)

    def get_by_company(self, company_id: UUID, section: str = None) -> List[dict]:
        filters = {"company_id": str(company_id)}
        if section:
            filters["section"] = section
        return self.list(filters, order_by="created_at")

    def get_by_theme(self, company_id: UUID, theme: str) -> List[dict]:
        """Get snippets tagged with a specific theme (e.g., 'litigation')."""
        if self.client is None:
            from core.db.repos.base import _in_memory_db
            return [
                r for r in _in_memory_db.get(self.table, [])
                if str(r.get("company_id")) == str(company_id) and theme in (r.get("themes") or [])
            ]
        try:
            result = self.client.table(self.table).select("*").eq(
                "company_id", str(company_id)
            ).contains("themes", [theme]).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Get by theme failed: {e}")
            return []


import logging
logger = logging.getLogger(__name__)