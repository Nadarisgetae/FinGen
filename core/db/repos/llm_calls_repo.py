"""
FinGen v2 — LLM Calls Log Repository
"""

from typing import List, Optional, Dict
from uuid import UUID

from core.db.repos.base import BaseRepo


class LLMCallsRepo(BaseRepo):
    def __init__(self, client=None, use_service_key: bool = True):
        super().__init__("llm_calls", use_service_key=use_service_key, client=client)
    
    def log_call(self, model: str, key_id: str, task: str, status_code: int = None, latency_ms: int = None, tokens_prompt: int = 0, tokens_completion: int = 0, error_message: str = None) -> dict:
        data = {
            "model": model,
            "key_id": key_id,
            "task": task,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "error_message": error_message,
        }
        return self.create(data)
    
    def update_status(self, model: str, key_id: str, status: str) -> dict:
        # Update the most recent call for this model/key
        result = self.client.table(self.table).select("id").eq("model", model).eq("key_id", key_id).order("created_at", desc=True).limit(1).execute()
        if result.data:
            return self.update(result.data[0]["id"], {"error_message": status if status != "success" else None})
        return {}
    
    def get_usage_stats(self, user_id: UUID = None, days: int = 7) -> Dict:
        """Get usage statistics for monitoring."""
        from datetime import datetime, timedelta
        since = (datetime.now() - timedelta(days=days)).isoformat()
        
        query = self.client.table(self.table).select("*").gte("created_at", since)
        if user_id:
            query = query.eq("user_id", str(user_id))
        
        result = query.execute()
        calls = result.data or []
        
        stats = {
            "total_calls": len(calls),
            "successful": len([c for c in calls if c.get("status_code") == 200]),
            "failed": len([c for c in calls if c.get("status_code") and c["status_code"] >= 400]),
            "total_tokens_prompt": sum(c.get("tokens_prompt", 0) for c in calls),
            "total_tokens_completion": sum(c.get("tokens_completion", 0) for c in calls),
            "avg_latency_ms": sum(c.get("latency_ms", 0) for c in calls) / max(len(calls), 1),
            "by_model": {},
            "by_task": {},
            "by_status": {},
        }
        
        for c in calls:
            model = c.get("model", "unknown")
            task = c.get("task", "unknown")
            status = c.get("status_code", 0)
            
            stats["by_model"][model] = stats["by_model"].get(model, 0) + 1
            stats["by_task"][task] = stats["by_task"].get(task, 0) + 1
            stats["by_status"][str(status)] = stats["by_status"].get(str(status), 0) + 1
        
        return stats