"""
FinGen v2 — Model Discovery & Validation

Runs at startup to:
1. Fetch live model list from OpenRouter API
2. Filter for :free models
3. Validate against configured task lists
4. Update config/models.yaml with discovered IDs
5. Cache results (TTL 24h) to avoid repeated API calls

Also provides model capability detection (context window, JSON mode support).
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

import requests
import yaml

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "openrouter_models.json"
CACHE_TTL_SECONDS = 24 * 3600  # 24 hours

MODELS_CONFIG_PATH = Path("config/models.yaml")


@dataclass
class ModelInfo:
    id: str
    name: str
    context_length: int
    pricing: Dict
    architecture: Dict
    supported_parameters: List[str]


def fetch_models_from_openrouter(api_key: Optional[str] = None) -> List[ModelInfo]:
    """Fetch live model list from OpenRouter."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    try:
        resp = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        models = []
        for m in data.get("data", []):
            models.append(ModelInfo(
                id=m["id"],
                name=m.get("name", m["id"]),
                context_length=m.get("context_length", 4096),
                pricing=m.get("pricing", {}),
                architecture=m.get("architecture", {}),
                supported_parameters=m.get("supported_parameters", []),
            ))
        return models
    except Exception as e:
        logger.error(f"Failed to fetch models from OpenRouter: {e}")
        raise


def load_cached_models(ignore_ttl: bool = False) -> Optional[List[ModelInfo]]:
    """Load cached models if still valid (or if ignore_ttl=True for offline fallback)."""
    if not CACHE_FILE.exists():
        return None
    
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        
        if not ignore_ttl and time.time() - cache.get("timestamp", 0) > CACHE_TTL_SECONDS:
            logger.info("Model cache expired")
            return None
        
        models = []
        for m in cache.get("models", []):
            models.append(ModelInfo(**m))
        logger.info(f"Loaded {len(models)} models from cache")
        return models
    except Exception as e:
        logger.warning(f"Failed to load model cache: {e}")
        return None


def save_models_cache(models: List[ModelInfo]):
    """Save models to cache."""
    try:
        cache = {
            "timestamp": time.time(),
            "models": [
                {
                    "id": m.id,
                    "name": m.name,
                    "context_length": m.context_length,
                    "pricing": m.pricing,
                    "architecture": m.architecture,
                    "supported_parameters": m.supported_parameters,
                }
                for m in models
            ]
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        logger.info(f"Cached {len(models)} models")
    except Exception as e:
        logger.warning(f"Failed to save model cache: {e}")


def is_free_model(model: ModelInfo) -> bool:
    """Check if model is free (prompt + completion pricing = 0)."""
    pricing = model.pricing
    prompt_price = float(pricing.get("prompt", "0"))
    completion_price = float(pricing.get("completion", "0"))
    return prompt_price == 0 and completion_price == 0


def discover_models(api_key: Optional[str] = None, force_refresh: bool = False) -> Dict[str, List[str]]:
    """
    Discover available free models and categorize by capability.
    
    Returns:
        Dict mapping task -> list of model IDs (best first)
    """
    # Try cache first
    if not force_refresh:
        cached = load_cached_models()
        if cached:
            return categorize_models(cached)
    
    # Fetch live with graceful fallback
    try:
        models = fetch_models_from_openrouter(api_key)
        save_models_cache(models)
        return categorize_models(models)
    except Exception as e:
        logger.warning(f"Live model fetch failed ({e}); falling back to cache/config")
        stale_cached = load_cached_models(ignore_ttl=True)
        if stale_cached:
            logger.info("Using stale cached models as fallback")
            return categorize_models(stale_cached)
        
        if MODELS_CONFIG_PATH.exists():
            try:
                with open(MODELS_CONFIG_PATH, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                tasks_cfg = cfg.get("tasks", cfg)
                return {
                    task: tasks_cfg.get(task, ["openrouter/auto"])
                    for task in ["extract", "longdoc", "write", "verify"]
                }
            except Exception:
                pass
        
        return {
            "extract": ["nvidia/nemotron-3-ultra:free", "openrouter/auto"],
            "longdoc": ["nvidia/nemotron-3-ultra:free", "openrouter/auto"],
            "write": ["qwen/qwen-2.5-72b-instruct:free", "openrouter/auto"],
            "verify": ["google/gemma-2-27b-it:free", "openrouter/auto"],
        }


def categorize_models(models: List[ModelInfo]) -> Dict[str, List[str]]:
    """
    Categorize models by task suitability based on:
    - Free tier availability
    - Context window (longdoc needs 100k+)
    - Instruction following quality (heuristic by provider)
    - JSON mode / structured output support
    """
    free_models = [m for m in models if is_free_model(m)]
    logger.info(f"Found {len(free_models)} free models out of {len(models)} total")
    
    # Sort by context length (descending) then by provider preference
    provider_priority = {
        "nvidia": 1,      # Nemotron - good reasoning
        "qwen": 2,        # Qwen - strong instruction following
        "meta-llama": 3,  # Llama - solid general purpose
        "google": 4,      # Gemma - good for verification
        "mistral": 5,
        "cohere": 6,
        "openrouter": 99, # Auto router
    }
    
    def sort_key(m: ModelInfo):
        provider = m.id.split("/")[0].lower()
        return (provider_priority.get(provider, 50), -m.context_length)
    
    free_models.sort(key=sort_key)
    
    # Long-context models (100k+ context) for longdoc task
    longdoc_models = [m.id for m in free_models if m.context_length >= 100000]
    
    # Models with JSON mode / structured output support
    json_models = [m.id for m in free_models if "json" in m.supported_parameters or "structured_output" in m.supported_parameters]
    
    # All free models by priority
    all_free = [m.id for m in free_models]
    
    # Add auto-router as fallback
    all_free.append("openrouter/auto")
    longdoc_models.append("openrouter/auto")
    json_models.append("openrouter/auto")
    
    return {
        "extract": all_free,           # Extraction needs accuracy, not huge context
        "longdoc": longdoc_models,     # Long context for full reports/transcripts
        "write": json_models or all_free,  # Writing benefits from JSON mode
        "verify": json_models or all_free, # Verification needs structured output
    }


def validate_and_update_config(
    discovered: Dict[str, List[str]],
    config_path: Path = MODELS_CONFIG_PATH,
) -> Dict[str, List[str]]:
    """
    Validate discovered models against config, update config with discovered IDs.
    Preserves paid_fallback_enabled and other config settings.
    """
    # Load existing config
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    
    # Support both nested 'tasks:' and flat config structures
    if "tasks" in config and isinstance(config["tasks"], dict):
        tasks_section = config["tasks"]
    else:
        tasks_section = config
    
    # Update with discovered models (preserve order, deduplicate)
    for task in ["extract", "longdoc", "write", "verify"]:
        existing = tasks_section.get(task, [])
        new_models = discovered.get(task, [])
        
        # Merge: discovered first, then existing (for any pinned models)
        seen = set()
        merged = []
        for m in new_models + existing:
            if m not in seen:
                merged.append(m)
                seen.add(m)
        tasks_section[task] = merged
    
    # Ensure fallback_provider exists
    if "fallback_provider" not in config:
        config["fallback_provider"] = "gemini"
    if "paid_fallback_enabled" not in config:
        config["paid_fallback_enabled"] = True
    
    # Write back
    with open(config_path, "w") as f:
        yaml.dump(config, f, sort_keys=False)
    
    logger.info(f"Updated {config_path} with discovered models")
    return config


def get_model_capabilities(model_id: str, api_key: Optional[str] = None) -> Optional[ModelInfo]:
    """Get detailed capabilities for a specific model."""
    models = load_cached_models()
    if not models:
        models = fetch_models_from_openrouter(api_key)
        save_models_cache(models)
    
    for m in models:
        if m.id == model_id:
            return m
    return None


def run_discovery_at_startup(st_secrets=None) -> Dict[str, List[str]]:
    """
    Main entry point for app startup.
    Call once in Home.py or app.py before any LLM calls.
    """
    api_key = None
    if st_secrets:
        keys = st_secrets.get("OPENROUTER_KEYS", [])
        if keys:
            api_key = keys[0] if isinstance(keys, list) else keys
    if not api_key:
        import os
        api_key = os.environ.get("OPENROUTER_API_KEY")
    
    discovered = discover_models(api_key=api_key)
    validated = validate_and_update_config(discovered)
    
    logger.info("Model discovery complete:")
    for task, models in validated.items():
        if task in ["extract", "longdoc", "write", "verify"]:
            logger.info(f"  {task}: {models[:3]}... ({len(models)} total)")
    
    return validated


if __name__ == "__main__":
    # CLI for manual testing
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        discovered = discover_models(force_refresh=True)
    else:
        discovered = discover_models()
    
    validate_and_update_config(discovered)
    print("Done.")