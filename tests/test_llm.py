"""
FinGen v2 — LLM Layer Test Suite (Task F0-04)
Run: pytest tests/test_llm.py -v
"""

import time
import json
import pytest
from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from core.llm.keypool import KeyPool, KeyState, KeyPoolExhausted
from core.llm.router import Router, TaskType, LLMExhausted
from core.llm.discover_models import (
    ModelInfo,
    is_free_model,
    categorize_models,
    validate_and_update_config,
    discover_models,
)


# =============================================================================
# KeyPool Tests
# =============================================================================

class TestKeyPoolRotation:
    def test_round_robin_rotation(self):
        pool = KeyPool(free_keys=["key_a", "key_b", "key_c"], cooldown_seconds=10)
        k1 = pool.acquire(timeout=1)
        k2 = pool.acquire(timeout=1)
        k3 = pool.acquire(timeout=1)
        k4 = pool.acquire(timeout=1)

        assert [k1, k2, k3, k4] == ["key_a", "key_b", "key_c", "key_a"]

    def test_cooldown_on_429(self):
        pool = KeyPool(free_keys=["key1", "key2"], cooldown_seconds=60)
        
        # Acquire first key and report 429
        k1 = pool.acquire(timeout=1)
        assert k1 == "key1"
        pool.record_failure(k1, Exception("Rate limited"), status_code=429)

        # Immediate next acquire should skip key1 and return key2
        k2 = pool.acquire(timeout=1)
        assert k2 == "key2"
        assert pool._metrics["key1"].state == KeyState.COOLING

    def test_exhaustion_on_401_402(self):
        pool = KeyPool(
            free_keys=["free_key"],
            paid_key="paid_key",
            exhausted_cooldown_seconds=3600,
        )
        k = pool.acquire(timeout=1)
        assert k == "free_key"
        
        # Simulate payment required / quota exhausted
        pool.record_failure(k, Exception("Insufficient quota"), status_code=402)
        assert pool._metrics["free_key"].state == KeyState.EXHAUSTED
        
        # Free key is exhausted -> should automatically fall back to paid key
        fallback = pool.acquire(timeout=1)
        assert fallback == "paid_key"

    def test_paid_fallback_when_all_free_cooling(self):
        pool = KeyPool(
            free_keys=["k1", "k2"],
            paid_key="paid_backup",
            cooldown_seconds=30,
        )
        pool.record_failure("k1", Exception("429"), status_code=429)
        pool.record_failure("k2", Exception("429"), status_code=429)

        # Free keys are both cooling -> should acquire paid key immediately
        acquired = pool.acquire(timeout=1)
        assert acquired == "paid_backup"

    def test_pool_exhausted_raises(self):
        pool = KeyPool(free_keys=["only_key"], cooldown_seconds=30)
        pool.record_failure("only_key", Exception("429"), status_code=429)

        with pytest.raises(KeyPoolExhausted):
            pool.acquire(timeout=0.05)

    def test_manual_key_reset(self):
        pool = KeyPool(free_keys=["key1"], cooldown_seconds=60)
        pool.record_failure("key1", Exception("429"), status_code=429)
        assert not pool._is_available("key1")

        pool.reset_key("key1")
        assert pool._is_available("key1")
        assert pool._metrics["key1"].state == KeyState.HEALTHY


# =============================================================================
# Router & Model Resolution Tests
# =============================================================================

class MockFact(BaseModel):
    metric: str
    value: float


class TestRouterRouting:
    def test_model_task_resolution(self):
        router = Router(
            st_secrets={"OPENROUTER_KEYS": ["dummy_key"]},
            supabase_client=None,
        )
        for task in [TaskType.EXTRACT, TaskType.WRITE, TaskType.VERIFY, TaskType.LONGDOC]:
            models = router._get_models_for_task(task)
            assert isinstance(models, list)
            assert len(models) >= 1
            assert any(":free" in m or "auto" in m for m in models)

    @patch("core.llm.router.requests.post")
    def test_mock_429_automatic_rotation(self, mock_post):
        # First call on key1 returns 429; second call on key2 returns 200 OK
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.raise_for_status.side_effect = Exception("HTTP 429")

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Report output text"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        mock_post.side_effect = [resp_429, resp_200]

        router = Router(
            st_secrets={"OPENROUTER_KEYS": ["key_first", "key_second"]},
            supabase_client=None,
        )

        result = router.call(TaskType.WRITE, [{"role": "user", "content": "Hello"}], use_cache=False)
        assert result == "Report output text"
        assert mock_post.call_count == 2
        # Key 1 was recorded as failure / cooling
        assert router.key_pool._metrics["key_first"].state == KeyState.COOLING
        assert router.key_pool._metrics["key_second"].state == KeyState.HEALTHY

    @patch("core.llm.router.requests.post")
    def test_pydantic_schema_validation_and_retry(self, mock_post):
        # Attempt 1: Invalid JSON (e.g. malformed or text explanation)
        resp_bad = MagicMock()
        resp_bad.status_code = 200
        resp_bad.json.return_value = {
            "choices": [{"message": {"content": "Here is the data: not valid json"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        # Attempt 2: Valid JSON conforming to MockFact
        resp_good = MagicMock()
        resp_good.status_code = 200
        resp_good.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"metric": "revenue", "value": 1500.0})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        mock_post.side_effect = [resp_bad, resp_good]

        router = Router(
            st_secrets={"OPENROUTER_KEYS": ["valid_key"]},
            supabase_client=None,
        )

        fact = router.call(
            TaskType.EXTRACT,
            [{"role": "user", "content": "Extract fact"}],
            schema=MockFact,
            use_cache=False,
        )

        assert isinstance(fact, MockFact)
        assert fact.metric == "revenue"
        assert fact.value == 1500.0
        assert mock_post.call_count == 2

    @patch("core.llm.router.requests.post")
    def test_in_memory_cache_hit(self, mock_post):
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "Cached analysis"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10},
        }
        mock_post.return_value = resp_200

        router = Router(
            st_secrets={"OPENROUTER_KEYS": ["cache_key"]},
            supabase_client=None,
        )

        # First call hits mock_post
        res1 = router.call(TaskType.WRITE, [{"role": "user", "content": "Repeatable prompt"}], use_cache=True)
        assert res1 == "Cached analysis"
        assert mock_post.call_count == 1

        # Second identical call hits in-memory cache without calling API
        res2 = router.call(TaskType.WRITE, [{"role": "user", "content": "Repeatable prompt"}], use_cache=True)
        assert res2 == "Cached analysis"
        assert mock_post.call_count == 1  # Still 1 call!


# =============================================================================
# Model Discovery Tests
# =============================================================================

class TestModelDiscovery:
    def test_free_model_filter(self):
        m_free = ModelInfo(
            id="test/free-model:free",
            name="Free Model",
            context_length=32000,
            pricing={"prompt": "0", "completion": "0"},
            architecture={},
            supported_parameters=["json"],
        )
        m_paid = ModelInfo(
            id="test/paid-model",
            name="Paid Model",
            context_length=32000,
            pricing={"prompt": "0.001", "completion": "0.002"},
            architecture={},
            supported_parameters=["json"],
        )
        assert is_free_model(m_free) is True
        assert is_free_model(m_paid) is False

    def test_categorize_models_prioritizes_providers_and_context(self):
        models = [
            ModelInfo(
                id="google/gemma:free",
                name="Gemma",
                context_length=8000,
                pricing={"prompt": "0", "completion": "0"},
                architecture={},
                supported_parameters=["json"],
            ),
            ModelInfo(
                id="nvidia/nemotron:free",
                name="Nemotron",
                context_length=128000,
                pricing={"prompt": "0", "completion": "0"},
                architecture={},
                supported_parameters=["json"],
            ),
        ]
        categorized = categorize_models(models)
        assert "extract" in categorized
        assert "longdoc" in categorized
        # Nemotron has >100k context so it qualifies for longdoc
        assert any("nemotron" in m for m in categorized["longdoc"])

    def test_validate_and_update_config_preserves_structure(self, tmp_path):
        cfg_file = tmp_path / "models.yaml"
        initial_cfg = {
            "tasks": {
                "extract": ["pinned/model:free"],
                "write": ["pinned/write:free"],
            },
            "fallback_provider": "gemini",
            "paid_fallback_enabled": True,
        }
        import yaml
        with open(cfg_file, "w") as f:
            yaml.dump(initial_cfg, f)

        discovered = {
            "extract": ["discovered/model:free"],
            "longdoc": ["discovered/longdoc:free"],
            "write": ["discovered/write:free"],
            "verify": ["discovered/verify:free"],
        }
        updated = validate_and_update_config(discovered, config_path=cfg_file)
        
        # Verify structure maintained
        assert "tasks" in updated
        assert "pinned/model:free" in updated["tasks"]["extract"]
        assert "discovered/model:free" in updated["tasks"]["extract"]
        assert updated["fallback_provider"] == "gemini"

