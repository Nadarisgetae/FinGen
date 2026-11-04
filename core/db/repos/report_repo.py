"""
FinGen v2 — Report Repository
"""

from typing import List, Optional, Dict
from uuid import UUID

from core.db.repos.base import BaseRepo


class ReportRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("reports", use_service_key)
    
    def create_version(self, company_id: UUID, user_id: UUID, report_type: str, markdown: str, **kwargs) -> dict:
        # Get latest version number
        existing = self.list({
            "company_id": str(company_id),
            "type": report_type
        }, order_by="version", desc=True, limit=1)
        version = (existing[0]["version"] + 1) if existing else 1
        
        data = {
            "company_id": str(company_id),
            "user_id": str(user_id),
            "type": report_type,
            "version": version,
            "markdown": markdown,
            **kwargs
        }
        return self.create(data)
    
    def get_latest(self, company_id: UUID, report_type: str) -> Optional[dict]:
        result = self.list({
            "company_id": str(company_id),
            "type": report_type
        }, order_by="version", desc=True, limit=1)
        return result[0] if result else None
    
    def list_by_company(self, company_id: UUID, report_type: str = None) -> List[dict]:
        filters = {"company_id": str(company_id)}
        if report_type:
            filters["type"] = report_type
        return self.list(filters, order_by="created_at", desc=True)
    
    def update_storage_paths(self, report_id: UUID, docx_path: str = None, pdf_path: str = None) -> Optional[dict]:
        data = {}
        if docx_path:
            data["storage_path_docx"] = docx_path
        if pdf_path:
            data["storage_path_pdf"] = pdf_path
        return self.update(report_id, data)
    
    def update_status(self, report_id: UUID, status: str, error_message: str = None, **kwargs) -> Optional[dict]:
        data = {"status": status}
        if error_message:
            data["error_message"] = error_message
        data.update(kwargs)
        return self.update(report_id, data)