"""
FinGen v2 — Job Repository (Async Processing)
"""

from typing import List, Optional, Dict, Any
from uuid import UUID

from core.db.repos.base import BaseRepo


class JobRepo(BaseRepo):
    def __init__(self, use_service_key: bool = False):
        super().__init__("jobs", use_service_key)
    
    def create_job(self, user_id: UUID, kind: str, payload: Dict, company_id: UUID = None) -> dict:
        data = {
            "user_id": str(user_id),
            "kind": kind,
            "payload": payload,
            "status": "pending",
            "progress": 0,
        }
        if company_id:
            data["company_id"] = str(company_id)
        return self.create(data)
    
    def claim_next(self, kinds: List[str], worker_id: str) -> Optional[dict]:
        """Atomically claim the next pending job (for worker process)."""
        # Use RPC for atomic claim
        try:
            result = self.client.rpc("claim_job", {
                "p_kinds": kinds,
                "p_worker_id": worker_id
            }).execute()
            return result.data[0] if result.data else None
        except Exception:
            # Fallback: simple select + update (race condition possible)
            jobs = self.list({
                "status": "pending",
                "kind": kinds
            }, order_by="created_at", limit=1)
            if jobs:
                job = jobs[0]
                self.update(job["id"], {"status": "running", "started_at": "now()"})
                return job
            return None
    
    def update_progress(self, job_id: UUID, progress: int, result: Dict = None) -> Optional[dict]:
        data = {"progress": progress}
        if result:
            data["result"] = result
        return self.update(job_id, data)
    
    def complete(self, job_id: UUID, result: Dict = None) -> Optional[dict]:
        data = {"status": "completed", "progress": 100, "completed_at": "now()"}
        if result:
            data["result"] = result
        return self.update(job_id, data)
    
    def fail(self, job_id: UUID, error_message: str) -> Optional[dict]:
        data = {
            "status": "failed",
            "error_message": error_message,
            "completed_at": "now()"
        }
        return self.update(job_id, data)
    
    def get_by_user(self, user_id: UUID, status: str = None, limit: int = 50) -> List[dict]:
        filters = {"user_id": str(user_id)}
        if status:
            filters["status"] = status
        return self.list(filters, order_by="created_at", desc=True, limit=limit)
    
    def get_active_for_company(self, company_id: UUID) -> List[dict]:
        return self.list({
            "company_id": str(company_id),
            "status": ["pending", "running"]
        })