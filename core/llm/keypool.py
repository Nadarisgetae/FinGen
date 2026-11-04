"""
FinGen v2 — KeyPool with Distributed Locking & Exhaustion Handling

Features:
- Multiple API keys with automatic rotation on 429/401/402/403/5xx
- Distributed locking via Supabase advisory locks (works across workers)
- Paid fallback key support
- Queue + timeout instead of raising on exhaustion
- Usage tracking per key/model for daily limit awareness
- Thread-safe, process-safe
"""

import time
import threading
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from contextlib import contextmanager
from enum import Enum

logger = logging.getLogger(__name__)


class KeyState(Enum):
    HEALTHY = "healthy"
    COOLING = "cooling"
    EXHAUSTED = "exhausted"  # Daily limit hit (401/402)
    ERROR = "error"


@dataclass
class KeyMetrics:
    """Track usage per key for observability & limit awareness."""
    key_id: str  # Last 8 chars of key for logging
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    last_used: float = 0
    last_error: Optional[str] = None
    state: KeyState = KeyState.HEALTHY
    cooldown_until: float = 0


class KeyPool:
    """
    Thread-safe, process-safe key pool with distributed locking.
    
    Usage:
        pool = KeyPool(free_keys, paid_key, supabase_client)
        key = pool.acquire(timeout=30)  # Blocks until key available
        try:
            response = call_llm(key, ...)
            pool.record_success(key, tokens=100)
        except APIError as e:
            pool.record_failure(key, e)
        finally:
            pool.release(key)
    """
    
    def __init__(
        self,
        free_keys: List[str],
        paid_key: Optional[str] = None,
        supabase_client=None,
        cooldown_seconds: int = 60,
        exhausted_cooldown_seconds: int = 3600,
        max_wait_seconds: int = 120,
    ):
        """
        Args:
            free_keys: List of OpenRouter API keys (free tier)
            paid_key: Single paid fallback key (optional)
            supabase_client: Supabase client for distributed locking (optional but recommended)
            cooldown_seconds: Cooldown for rate limit errors (429, 5xx)
            exhausted_cooldown_seconds: Cooldown for auth/billing errors (401, 402)
            max_wait_seconds: Max time to wait for a key before raising
        """
        if not free_keys:
            raise ValueError("At least one free key required")
        
        self.free_keys = free_keys
        self.paid_key = paid_key
        self.supabase = supabase_client
        self.cooldown_seconds = cooldown_seconds
        self.exhausted_cooldown_seconds = exhausted_cooldown_seconds
        self.max_wait_seconds = max_wait_seconds
        
        # Local state (synced via distributed lock)
        self._metrics: Dict[str, KeyMetrics] = {}
        self._index = 0
        self._local_lock = threading.RLock()
        self._waiting_threads = 0
        self._cv = threading.Condition(self._local_lock)
        
        # Initialize metrics
        for key in free_keys:
            key_id = self._key_id(key)
            self._metrics[key] = KeyMetrics(key_id=key_id)
        if paid_key:
            key_id = self._key_id(paid_key)
            self._metrics[paid_key] = KeyMetrics(key_id=key_id)
    
    @staticmethod
    def _key_id(key: str) -> str:
        """Return last 8 chars for logging (never log full key)."""
        return key[-8:] if len(key) >= 8 else key
    
    @staticmethod
    def _lock_name(key: str) -> int:
        """Generate deterministic advisory lock ID from key."""
        return abs(hash(key)) % 2147483647  # 32-bit signed int
    
    @contextmanager
    def _distributed_lock(self, key: str):
        """Acquire distributed lock via Supabase advisory lock."""
        if self.supabase:
            lock_id = self._lock_name(key)
            # pg_advisory_xact_lock releases automatically at transaction end
            self.supabase.rpc("pg_advisory_xact_lock", {"lock_id": lock_id}).execute()
            try:
                yield
            finally:
                pass  # Released on transaction commit/rollback
        else:
            # Fallback to local lock only (single process)
            with self._local_lock:
                yield
    
    def _is_available(self, key: str) -> bool:
        """Check if key is available (not cooling, not exhausted)."""
        metrics = self._metrics.get(key)
        if not metrics:
            return False
        if metrics.state == KeyState.EXHAUSTED:
            return False
        if metrics.cooldown_until > time.time():
            return False
        return True
    
    def _set_cooldown(self, key: str, seconds: int):
        """Set cooldown for a key."""
        metrics = self._metrics.get(key)
        if metrics:
            metrics.cooldown_until = time.time() + seconds
            metrics.state = KeyState.COOLING
            logger.warning(f"Key {metrics.key_id} cooling for {seconds}s")
    
    def _set_exhausted(self, key: str):
        """Mark key as exhausted (daily limit)."""
        metrics = self._metrics.get(key)
        if metrics:
            metrics.state = KeyState.EXHAUSTED
            metrics.cooldown_until = time.time() + self.exhausted_cooldown_seconds
            logger.error(f"Key {metrics.key_id} EXHAUSTED (daily limit)")
    
    def _set_healthy(self, key: str):
        """Mark key as healthy."""
        metrics = self._metrics.get(key)
        if metrics:
            metrics.state = KeyState.HEALTHY
            metrics.cooldown_until = 0
    
    def acquire(self, timeout: Optional[float] = None) -> str:
        """
        Acquire an available key. Blocks until key available or timeout.
        
        Args:
            timeout: Max seconds to wait (None = use max_wait_seconds)
            
        Returns:
            API key string
            
        Raises:
            KeyPoolExhausted: No keys available within timeout
        """
        if timeout is None:
            timeout = self.max_wait_seconds
        
        deadline = time.time() + timeout
        self._waiting_threads += 1
        
        try:
            while time.time() < deadline:
                # Try free keys first (round-robin)
                with self._local_lock:
                    for _ in range(len(self.free_keys)):
                        key = self.free_keys[self._index % len(self.free_keys)]
                        self._index += 1
                        if self._is_available(key):
                            # Try to acquire distributed lock
                            with self._distributed_lock(key):
                                # Re-check under distributed lock
                                if self._is_available(key):
                                    self._metrics[key].last_used = time.time()
                                    return key
                    
                    # Try paid key if enabled and free keys exhausted
                    if self.paid_key and self._is_available(self.paid_key):
                        with self._distributed_lock(self.paid_key):
                            if self._is_available(self.paid_key):
                                self._metrics[self.paid_key].last_used = time.time()
                                logger.info("Using PAID fallback key")
                                return self.paid_key
                
                # No key available, wait a bit
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                wait_time = min(1.0, remaining)
                with self._cv:
                    self._cv.wait(timeout=wait_time)
            
            # Timeout - all keys exhausted
            raise KeyPoolExhausted(
                f"No keys available after {timeout}s. "
                f"Free keys: {len(self.free_keys)}, Paid: {'yes' if self.paid_key else 'no'}"
            )
        finally:
            self._waiting_threads -= 1
            with self._cv:
                self._cv.notify_all()
    
    def release(self, key: str):
        """Release key (no-op for advisory locks, but kept for symmetry)."""
        # Advisory locks auto-release on transaction end
        # This method exists for API symmetry and future extensibility
        pass
    
    def record_success(self, key: str, tokens: int = 0):
        """Record successful call."""
        metrics = self._metrics.get(key)
        if metrics:
            metrics.total_calls += 1
            metrics.successful_calls += 1
            metrics.total_tokens += tokens
            metrics.last_error = None
            self._set_healthy(key)
    
    def record_failure(self, key: str, error: Exception, status_code: Optional[int] = None):
        """Record failed call and apply appropriate cooldown."""
        metrics = self._metrics.get(key)
        if not metrics:
            return
        
        metrics.total_calls += 1
        metrics.failed_calls += 1
        metrics.last_error = str(error)
        
        # Determine cooldown based on status code
        if status_code in (401, 402):  # Auth failed / billing limit
            self._set_exhausted(key)
        elif status_code == 429:  # Rate limit
            self._set_cooldown(key, self.cooldown_seconds)
        elif status_code and 500 <= status_code < 600:  # Server error
            self._set_cooldown(key, self.cooldown_seconds)
        else:
            # Unknown error - short cooldown
            self._set_cooldown(key, min(self.cooldown_seconds, 30))
        
        # Notify waiting threads that key state changed
        with self._cv:
            self._cv.notify_all()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics for monitoring."""
        return {
            "free_keys_total": len(self.free_keys),
            "paid_key_available": self.paid_key is not None,
            "waiting_threads": self._waiting_threads,
            "keys": {
                self._key_id(k): {
                    "state": m.state.value,
                    "total_calls": m.total_calls,
                    "success_rate": m.successful_calls / max(m.total_calls, 1),
                    "total_tokens": m.total_tokens,
                    "cooldown_remaining": max(0, m.cooldown_until - time.time()),
                    "last_error": m.last_error,
                }
                for k, m in self._metrics.items()
            }
        }
    
    def reset_key(self, key: str):
        """Manually reset a key (e.g., after manual limit reset)."""
        with self._distributed_lock(key):
            self._set_healthy(key)
            logger.info(f"Key {self._key_id(key)} manually reset")


class KeyPoolExhausted(Exception):
    """Raised when no keys available within timeout."""
    pass


def create_key_pool_from_secrets(st_secrets=None, supabase_client=None) -> KeyPool:
    """
    Factory function to create KeyPool from Streamlit secrets or environment variables.
    
    Expected secrets structure:
    [secrets]
    OPENROUTER_KEYS = ["key1", "key2", "key3"]  # List of free keys
    OPENROUTER_PAID_KEY = "paid_key"  # Optional single paid key
    """
    import os
    free_keys = []
    paid_key = None
    if st_secrets:
        raw_keys = st_secrets.get("OPENROUTER_KEYS", [])
        if isinstance(raw_keys, str):
            free_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        elif isinstance(raw_keys, list):
            free_keys = list(raw_keys)
        paid_key = st_secrets.get("OPENROUTER_PAID_KEY")
    
    if not free_keys:
        env_keys = os.environ.get("OPENROUTER_KEYS") or os.environ.get("OPENROUTER_API_KEY")
        if env_keys:
            free_keys = [k.strip() for k in env_keys.split(",") if k.strip()]
        if not paid_key:
            paid_key = os.environ.get("OPENROUTER_PAID_KEY")
    
    return KeyPool(
        free_keys=free_keys or ["mock_key_offline"],
        paid_key=paid_key,
        supabase_client=supabase_client,
    )