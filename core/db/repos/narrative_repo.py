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
        try:
            result = self.client.table(self.table).insert(payload).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Bulk create snippets failed: {e}")
            raise

    def get_by_company(self, company_id: UUID, section: str = None) -> List[dict]:
        filters = {"company_id": str(company_id)}
        if section:
            filters["section"] = section
        return self.list(filters, order_by="created_at")

    def get_by_theme(self, company_id: UUID, theme: str) -> List[dict]:
        """Get snippets tagged with a specific theme (e.g., 'litigation')."""
        result = self.client.table(self.table).select("*").eq(
            "company_id", str(company_id)
        ).contains("themes", [theme]).execute()
        return result.data or []


import logging
logger = logging.getLogger(__name__)