"""
FinGen v2 — LLM Router

Unified interface for all LLM calls with:
- Task-based model routing (extract, longdoc, write, verify)
- KeyPool integration (automatic key rotation, paid fallback)
- Response caching (Supabase llm_cache table)
- Structured output / JSON mode support
- Pydantic validation with retry
- Usage logging (Supabase llm_calls table)
"""

import json
import time
import hashlib
import logging
from typing import Optional, Type, TypeVar, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

import yaml
import requests
from pydantic import BaseModel, ValidationError

from core.llm.keypool import KeyPool, KeyPoolExhausted, create_key_pool_from_secrets
from core.db.client import get_supabase_client
from core.db.repos.llm_cache_repo import LLMCacheRepo
from core.db.repos.llm_calls_repo import LLMCallsRepo

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MODELS_CONFIG_PATH = "config/models.yaml"


class TaskType(str, Enum):
    EXTRACT = "extract"
    LONGDOC = "longdoc"
    WRITE = "write"
    VERIFY = "verify"


@dataclass
class LLMCallResult:
    content: str
    model_used: str
    key_used_id: str  # Last 8 chars
    tokens_prompt: int
    tokens_completion: int
    latency_ms: int
    cached: bool = False


class LLMExhausted(Exception):
    """All models and keys exhausted."""
    pass


class LLMAPIError(Exception):
    """HTTP error from the LLM API, carries status_code for rotation logic."""
    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(message)


class InMemoryLLMCacheRepo:
    """In-memory fallback cache when Supabase is disconnected."""
    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def get(self, cache_key: str) -> Optional[Any]:
        return self._cache.get(cache_key)

    def set(self, cache_key: str, output: Any, task: str = None, model: str = None, **kwargs) -> dict:
        self._cache[cache_key] = output
        return {"cache_key": cache_key, "output": output}

    def delete_expired(self) -> int:
        return 0

    def clear_task(self, task: str) -> int:
        self._cache.clear()
        return 0


class InMemoryLLMCallsRepo:
    """In-memory fallback call logger when Supabase is disconnected."""
    def __init__(self):
        self.calls: List[dict] = []

    def log_call(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return kwargs

    def update_status(self, model: str, key_id: str, status: str) -> dict:
        return {"model": model, "key_id": key_id, "status": status}


class Router:
    """
    Main LLM router. Initialize once at app startup.
    
    Usage:
        router = Router(st_secrets, supabase_client)
        result = router.call(TaskType.EXTRACT, messages, schema=FactList)
    """
    
    def __init__(
        self,
        st_secrets=None,
        supabase_client=None,
        max_retries: int = 3,
        default_timeout: int = 120,
    ):
        if supabase_client is not None:
            self.supabase = supabase_client
        else:
            try:
                self.supabase = get_supabase_client()
            except Exception as e:
                logger.info(f"Supabase client not available ({e}); using in-memory cache/call log")
                self.supabase = None

        self.max_retries = max_retries
        self.default_timeout = default_timeout
        
        # Load model config
        with open(MODELS_CONFIG_PATH, encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        
        # Initialize KeyPool
        self.key_pool = create_key_pool_from_secrets(st_secrets, self.supabase)
        
        # Initialize repos with in-memory fallback
        if self.supabase is not None:
            try:
                self.cache_repo = LLMCacheRepo(client=self.supabase)
                self.calls_repo = LLMCallsRepo(client=self.supabase)
            except Exception as e:
                logger.warning(f"Failed to initialize Supabase repos ({e}), falling back to in-memory")
                self.cache_repo = InMemoryLLMCacheRepo()
                self.calls_repo = InMemoryLLMCallsRepo()
        else:
            self.cache_repo = InMemoryLLMCacheRepo()
            self.calls_repo = InMemoryLLMCallsRepo()
        
        # OpenRouter endpoint
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        
        logger.info("Router initialized")
    
    def _get_models_for_task(self, task: TaskType) -> List[str]:
        """Get model list for task from config."""
        tasks_cfg = self.config.get("tasks", self.config)
        return tasks_cfg.get(task.value, [])
    
    def _make_cache_key(self, task: TaskType, messages: List[Dict], schema: Optional[Type[T]] = None) -> str:
        """Generate deterministic cache key from task + messages + schema."""
        content = {
            "task": task.value,
            "messages": messages,
            "schema": schema.model_json_schema() if schema else None,
        }
        # Sort keys for determinism
        serialized = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()[:32]
    
    def _call_openrouter(
        self,
        model: str,
        key: str,
        messages: List[Dict],
        schema: Optional[Type[T]] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMCallResult:
        """Make raw API call to OpenRouter."""
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://fingen.local",
            "X-Title": "FinGen",
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # Enable JSON mode if schema provided and model supports it
        if schema:
            payload["response_format"] = {"type": "json_object"}
        
        start = time.time()
        resp = requests.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=self.default_timeout,
        )
        latency_ms = int((time.time() - start) * 1000)
        
        # Log call
        self.calls_repo.log_call(
            model=model,
            key_id=key[-8:],
            task="unknown",  # Will be updated by caller
            status_code=resp.status_code,
            latency_ms=latency_ms,
        )
        
        if resp.status_code in (401, 402, 403, 429):
            # Raise so the rotation wrapper can handle it
            raise LLMAPIError(
                f"OpenRouter returned {resp.status_code}",
                status_code=resp.status_code,
            )

        if resp.status_code >= 500:
            raise LLMAPIError(
                f"OpenRouter server error {resp.status_code}",
                status_code=resp.status_code,
            )

        resp.raise_for_status()
        data = resp.json()
        
        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        
        usage = data.get("usage", {})
        tokens_prompt = usage.get("prompt_tokens", 0)
        tokens_completion = usage.get("completion_tokens", 0)
        
        return LLMCallResult(
            content=content,
            model_used=model,
            key_used_id=key[-8:],
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            latency_ms=latency_ms,
        )
    
    def _validate_and_retry(
        self,
        content: str,
        schema: Type[T],
        attempt: int,
    ) -> T:
        """Validate response against schema, retry on failure."""
        try:
            # Extract JSON from content (handle markdown fences)
            json_str = self._extract_json(content)
            data = json.loads(json_str)
            return schema(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt >= self.max_retries:
                raise
            logger.warning(f"Validation failed (attempt {attempt + 1}): {e}")
            # Re-prompt with error - handled by caller
            raise ValidationRetryError(str(e), content)
    
    def _extract_json(self, content: str) -> str:
        """Extract JSON from response (handles markdown fences)."""
        content = content.strip()
        if content.startswith("```"):
            # Find first { and last }
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return content[start:end+1]
        return content
    
    def call(
        self,
        task: TaskType,
        messages: List[Dict],
        schema: Optional[Type[T]] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        use_cache: bool = True,
    ) -> T | str:
        """
        Main entry point for LLM calls.

        Flow: cache check → for each model → for each key:
        acquire key → call API → on 401/402/429/5xx record_failure +
        rotate to next key → on 400/404/422 fail fast to next model →
        on success validate schema (with retry re-prompts) → return.

        Returns:
            Parsed Pydantic model (if schema provided) or raw string

        Raises:
            LLMExhausted: All models/keys exhausted
        """
        models = self._get_models_for_task(task)
        if not models:
            raise ValueError(f"No models configured for task: {task.value}")

        cache_key = self._make_cache_key(task, messages, schema) if use_cache else None

        # Check cache
        if cache_key:
            cached = self.cache_repo.get(cache_key)
            if cached:
                logger.info(f"Cache hit for {task.value} (key: {cache_key[:8]})")
                if schema:
                    return schema(**cached)
                return cached

        last_error = None
        total_key_attempts = len(self.key_pool.free_keys) + (1 if self.key_pool.paid_key else 0)

        for model in models:
            for _key_attempt in range(total_key_attempts):
                try:
                    key = self.key_pool.acquire(timeout=30)
                except KeyPoolExhausted as e:
                    logger.error(f"Key pool exhausted for model {model}: {e}")
                    break  # Try next model

                try:
                    result = self._call_openrouter(
                        model=model,
                        key=key,
                        messages=messages,
                        schema=schema,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except LLMAPIError as e:
                    last_error = e
                    logger.warning(f"API error {e.status_code} on {model} (key {key[-8:]}): {e}")
                    self.key_pool.record_failure(key, e, status_code=e.status_code)
                    if e.status_code in (400, 404, 422):
                        # Client error — key rotation won't help; next model
                        logger.warning(f"Client error {e.status_code} on {model}, trying next model")
                        break
                    # 401/402/403/429/5xx → rotate to next key
                    continue
                except Exception as e:
                    last_error = e
                    logger.warning(f"Call failed: {model} (key: {key[-8:]}) - {e}")
                    self.key_pool.record_failure(key, e)
                    continue

                # Success — validate if schema provided
                if schema:
                    current_messages = list(messages)
                    for retry in range(self.max_retries):
                        try:
                            validated = self._validate_and_retry(result.content, schema, retry)
                            if cache_key:
                                self.cache_repo.set(cache_key, validated.model_dump(), task=task.value, model=model)
                            self.key_pool.record_success(key, result.tokens_prompt + result.tokens_completion)
                            self.calls_repo.update_status(model, key[-8:], "success")
                            logger.info(f"Success: {task.value} via {model} (key: {result.key_used_id})")
                            return validated
                        except ValidationRetryError as e:
                            last_error = e
                            # Re-prompt with validation error (same key, new request)
                            current_messages = messages + [{
                                "role": "user",
                                "content": f"Previous response failed validation: {e.error}. "
                                           f"Your response: {e.bad_response}. "
                                           f"Return ONLY valid JSON matching the schema."
                            }]
                            try:
                                result = self._call_openrouter(
                                    model=model,
                                    key=key,
                                    messages=current_messages,
                                    schema=schema,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                )
                            except LLMAPIError as api_err:
                                self.key_pool.record_failure(key, api_err, status_code=api_err.status_code)
                                if api_err.status_code in (400, 404, 422):
                                    break
                                continue
                            except Exception as api_err:
                                self.key_pool.record_failure(key, api_err)
                                break
                    # All retries exhausted
                    self.key_pool.record_failure(key, last_error, status_code=400)
                    continue
                else:
                    # No schema — return raw content
                    if cache_key:
                        self.cache_repo.set(cache_key, result.content, task=task.value, model=model)
                    self.key_pool.record_success(key, result.tokens_prompt + result.tokens_completion)
                    self.calls_repo.update_status(model, key[-8:], "success")
                    logger.info(f"Success: {task.value} via {model} (key: {result.key_used_id})")
                    return result.content

            # All keys exhausted for this model, try next model
            logger.warning(f"All keys exhausted for {model}, trying next model")
            continue

        # All models and keys exhausted
        raise LLMExhausted(f"All models/keys exhausted for task {task.value}. Last error: {last_error}")
    
    def call_with_fallback(
        self,
        task: TaskType,
        messages: List[Dict],
        schema: Optional[Type[T]] = None,
        **kwargs,
    ) -> T | str:
        """
        Wrapper that catches LLMExhausted and tries paid fallback or secondary provider (Gemini).
        """
        try:
            return self.call(task, messages, schema, **kwargs)
        except LLMExhausted as e:
            if self.config.get("paid_fallback_enabled") and self.key_pool.paid_key:
                logger.warning("Free tier exhausted, attempting paid fallback...")
                original_free = self.key_pool.free_keys
                self.key_pool.free_keys = []
                try:
                    return self.call(task, messages, schema, **kwargs)
                except LLMExhausted:
                    pass
                finally:
                    self.key_pool.free_keys = original_free

            if self.config.get("fallback_provider") == "gemini":
                logger.warning("All OpenRouter options exhausted, attempting Gemini fallback provider...")
                return self._call_gemini_fallback(task, messages, schema, **kwargs)
            raise

    def _call_gemini_fallback(
        self,
        task: TaskType,
        messages: List[Dict],
        schema: Optional[Type[T]] = None,
        **kwargs,
    ) -> T | str:
        """Fallback to Google Gemini API when OpenRouter is exhausted."""
        import os
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            raise LLMExhausted("Gemini fallback requested but GEMINI_API_KEY is not set.")
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            prompt_text = "\n".join(f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in messages)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt_text,
            )
            content = response.text or ""
            if schema:
                return self._validate_and_retry(content, schema, attempt=0)
            return content
        except Exception as err:
            logger.error(f"Gemini fallback failed: {err}")
            raise LLMExhausted(f"Both OpenRouter and Gemini fallback failed: {err}")


class ValidationRetryError(Exception):
    """Internal exception for validation retry loop."""
    def __init__(self, error: str, bad_response: str):
        self.error = error
        self.bad_response = bad_response
        super().__init__(error)


# Convenience functions for common patterns
def build_extraction_prompt(system: str, user: str, schema: Type[T]) -> List[Dict]:
    """Build messages for extraction task with schema instruction."""
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{user}\n\nReturn ONLY valid JSON matching this schema:\n{schema_json}"},
    ]


def build_writing_prompt(system: str, user: str, context: Dict[str, Any]) -> List[Dict]:
    """Build messages for writing task with context."""
    context_str = json.dumps(context, indent=2, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{user}\n\nCONTEXT DATA:\n{context_str}"},
    ]


def build_verification_prompt(text: str, facts: List[Dict]) -> List[Dict]:
    """Build messages for verification task."""
    facts_str = json.dumps(facts, indent=2, ensure_ascii=False)
    return [
        {"role": "system", "content": "You are a financial fact-checker. Verify every number in the text against the provided facts."},
        {"role": "user", "content": f"TEXT TO VERIFY:\n{text}\n\nFACTS (source of truth):\n{facts_str}\n\nReturn JSON with 'flags' array: each flag has 'type' (MISSING_SOURCE|MISMATCH|UNSUPPORTED_CLAIM|PROMOTIONAL), 'location' (text snippet), 'expected' (correct value), 'severity' (error|warning)."},
    ]


# Singleton instance (initialized in app.py)
_router: Optional[Router] = None


def get_router() -> Router:
    global _router
    if _router is None:
        raise RuntimeError("Router not initialized. Call init_router() first.")
    return _router


def init_router(st_secrets=None, supabase_client=None) -> Router:
    global _router
    _router = Router(st_secrets, supabase_client)
    return _router