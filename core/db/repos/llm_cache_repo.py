"""
FinGen v2 — LLM Cache Repository
"""

from typing import Optional, Any
from uuid import UUID

from core.db.repos.base import BaseRepo


class LLMCacheRepo(BaseRepo):
    def __init__(self, client=None, use_service_key: bool = True):  # Always service key for cache
        super().__init__("llm_cache", use_service_key=use_service_key, client=client)
    
    def get(self, cache_key: str) -> Optional[Any]:
        result = self.client.table(self.table).select("output").eq("cache_key", cache_key).single().execute()
        if result.data:
            return result.data["output"]
        return None
    
    def set(self, cache_key: str, output: Any, task: str = None, model: str = None, tokens_prompt: int = 0, tokens_completion: int = 0) -> dict:
        data = {
            "cache_key": cache_key,
            "output": output,
        }
        if task:
            data["task"] = task
        if model:
            data["model"] = model
        if tokens_prompt:
            data["tokens_prompt"] = tokens_prompt
        if tokens_completion:
            data["tokens_completion"] = tokens_completion
        # Upsert to handle collisions
        result = self.client.table(self.table).upsert(data, on_conflict="cache_key").execute()
        return result.data[0] if result.data else {}
    
    def delete_expired(self) -> int:
        """Delete expired cache entries. Call periodically."""
        result = self.client.table(self.table).delete().lt("expires_at", "now()").execute()
        return len(result.data) if result.data else 0
    
    def clear_task(self, task: str) -> int:
        """Clear all cache for a specific task (e.g., after model update)."""
        result = self.client.table(self.table).delete().eq("task", task).execute()
        return len(result.data) if result.data else 0