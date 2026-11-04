"""
FinGen v2 — Base Repository Class
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, TypeVar, Generic
from uuid import UUID
from dataclasses import dataclass
from collections import defaultdict

from core.db.client import get_supabase_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

# In-memory storage fallback when Supabase is not configured
_in_memory_db: Dict[str, List[Dict]] = defaultdict(list)


@dataclass
class PaginatedResult(Generic[T]):
    data: List[T]
    count: int
    page: int
    page_size: int
    has_more: bool


class BaseRepo:
    """Base repository with common CRUD operations and offline in-memory fallback."""
    
    def __init__(self, table: str, use_service_key: bool = False, client=None):
        self.table = table
        if client is not None:
            self.client = client
        else:
            try:
                self.client = get_supabase_client(use_service_key=use_service_key)
            except Exception as e:
                logger.debug(f"Running {table} in offline in-memory mode: {e}")
                self.client = None
    
    def _to_dict(self, obj: Any) -> Dict:
        """Convert dataclass/Pydantic model to dict."""
        if hasattr(obj, "model_dump"):
            return obj.model_dump(exclude_none=True)
        elif hasattr(obj, "__dataclass_fields__"):
            import dataclasses
            return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj) if getattr(obj, f.name) is not None}
        elif isinstance(obj, dict):
            return dict(obj)
        else:
            raise ValueError(f"Cannot convert {type(obj)} to dict")
    
    def create(self, data: Any, returning: bool = True) -> Optional[Dict]:
        """Insert a single record."""
        payload = self._to_dict(data)
        if self.client is None:
            if "id" not in payload:
                payload["id"] = str(uuid.uuid4())
            _in_memory_db[self.table].append(payload)
            return payload

        try:
            query = self.client.table(self.table).insert(payload)
            if returning:
                query = query.select()
            result = query.execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Create failed for {self.table}: {e}")
            raise
    
    def bulk_create(self, data: List[Any], returning: bool = False) -> List[Dict]:
        """Insert multiple records."""
        if not data:
            return []
        payloads = [self._to_dict(d) for d in data]

        if self.client is None:
            created = []
            for p in payloads:
                if "id" not in p:
                    p["id"] = str(uuid.uuid4())
                _in_memory_db[self.table].append(p)
                created.append(p)
            return created

        try:
            query = self.client.table(self.table).insert(payloads)
            if returning:
                query = query.select()
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Bulk create failed for {self.table}: {e}")
            raise
    
    def get_by_id(self, id: UUID | str) -> Optional[Dict]:
        """Get single record by ID."""
        if self.client is None:
            for row in _in_memory_db[self.table]:
                if str(row.get("id")) == str(id):
                    return dict(row)
            return None

        try:
            result = self.client.table(self.table).select("*").eq("id", str(id)).single().execute()
            return result.data
        except Exception as e:
            if "PGRST116" in str(e):  # No rows returned
                return None
            logger.error(f"Get by ID failed for {self.table}: {e}")
            raise
    
    def update(self, id: UUID | str, data: Any) -> Optional[Dict]:
        """Update a record by ID."""
        payload = self._to_dict(data)

        if self.client is None:
            for i, row in enumerate(_in_memory_db[self.table]):
                if str(row.get("id")) == str(id):
                    _in_memory_db[self.table][i].update(payload)
                    return dict(_in_memory_db[self.table][i])
            return None

        try:
            result = self.client.table(self.table).update(payload).eq("id", str(id)).select().execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Update failed for {self.table}: {e}")
            raise
    
    def delete(self, id: UUID | str) -> bool:
        """Delete a record by ID."""
        if self.client is None:
            before_len = len(_in_memory_db[self.table])
            _in_memory_db[self.table] = [r for r in _in_memory_db[self.table] if str(r.get("id")) != str(id)]
            return len(_in_memory_db[self.table]) < before_len

        try:
            result = self.client.table(self.table).delete().eq("id", str(id)).execute()
            return True
        except Exception as e:
            logger.error(f"Delete failed for {self.table}: {e}")
            raise
    
    def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        desc: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict]:
        """List records with optional filters."""
        if self.client is None:
            rows = list(_in_memory_db[self.table])
            if filters:
                filtered = []
                for r in rows:
                    match = True
                    for k, v in filters.items():
                        if isinstance(v, list):
                            if r.get(k) not in v:
                                match = False
                                break
                        elif str(r.get(k)) != str(v):
                            match = False
                            break
                    if match:
                        filtered.append(r)
                rows = filtered
            if order_by:
                rows.sort(key=lambda x: str(x.get(order_by, "")), reverse=desc)
            if offset:
                rows = rows[offset:]
            if limit:
                rows = rows[:limit]
            return rows

        try:
            query = self.client.table(self.table).select("*")
            
            if filters:
                for key, value in filters.items():
                    if isinstance(value, list):
                        query = query.in_(key, value)
                    else:
                        query = query.eq(key, value)
            
            if order_by:
                query = query.order(order_by, desc=desc)
            
            if limit:
                query = query.limit(limit)
            if offset:
                query = query.offset(offset)
            
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"List failed for {self.table}: {e}")
            raise
    
    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count records matching filters."""
        if self.client is None:
            return len(self.list(filters))

        try:
            query = self.client.table(self.table).select("*", count="exact", head=True)
            
            if filters:
                for key, value in filters.items():
                    if isinstance(value, list):
                        query = query.in_(key, value)
                    else:
                        query = query.eq(key, value)
            
            result = query.execute()
            return result.count or 0
        except Exception as e:
            logger.error(f"Count failed for {self.table}: {e}")
            raise
    
    def paginate(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        desc: bool = True,
    ) -> PaginatedResult:
        """Paginated list."""
        offset = (page - 1) * page_size
        data = self.list(filters, order_by, desc, limit=page_size + 1, offset=offset)
        has_more = len(data) > page_size
        if has_more:
            data = data[:page_size]
        total = self.count(filters)
        return PaginatedResult(
            data=data,
            count=total,
            page=page,
            page_size=page_size,
            has_more=has_more,
        )
    
    def execute_rpc(self, fn: str, params: Dict) -> Any:
        """Execute a stored procedure."""
        if self.client is None:
            return None

        try:
            result = self.client.rpc(fn, params).execute()
            return result.data
        except Exception as e:
            logger.error(f"RPC {fn} failed: {e}")
            raise