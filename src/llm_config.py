"""
LLM Configuration Module

Loads and provides access to LLM provider/model configuration from config/llm_providers.yaml.
Single source of truth for model specs, pricing, rate limits, and feature flags.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml

from src.paths import get_config_dir


def _get_config_path() -> Path:
    """Get path to LLM config file (works for both dev and packaged modes)."""
    return get_config_dir() / "llm_providers.yaml"


# Config path (computed dynamically to support packaged mode)
CONFIG_PATH = _get_config_path()

# Cached config (loaded once)
_config: Optional[Dict] = None


def _load_config() -> Dict:
    """Load config from YAML file, with caching."""
    global _config
    if _config is None:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"LLM config not found: {CONFIG_PATH}")
        with open(CONFIG_PATH, 'r') as f:
            _config = yaml.safe_load(f)
    return _config


def reload_config() -> Dict:
    """Force reload of config (useful for testing or after config changes)."""
    global _config
    _config = None
    return _load_config()


def get_config() -> Dict:
    """Get the full config dictionary."""
    return _load_config()


# =============================================================================
# Provider Functions
# =============================================================================

def get_providers() -> List[str]:
    """Get list of available provider IDs (e.g., ['openai', 'ollama'])."""
    config = _load_config()
    return list(config.get('providers', {}).keys())


def get_provider_config(provider: str) -> Optional[Dict]:
    """Get full config for a provider."""
    config = _load_config()
    return config.get('providers', {}).get(provider)


def get_provider_name(provider: str) -> str:
    """Get display name for a provider (e.g., 'OpenAI', 'Ollama (Local)')."""
    provider_config = get_provider_config(provider)
    if provider_config:
        return provider_config.get('name', provider)
    return provider


def requires_api_key(provider: str) -> bool:
    """Check if a provider requires an API key."""
    provider_config = get_provider_config(provider)
    if provider_config:
        return provider_config.get('requires_api_key', False)
    return False


# =============================================================================
# Model Functions
# =============================================================================

def get_models(provider: str) -> List[str]:
    """Get list of model IDs for a provider."""
    provider_config = get_provider_config(provider)
    if provider_config:
        return list(provider_config.get('models', {}).keys())
    return []


def get_model_config(provider: str, model: str) -> Optional[Dict]:
    """Get full config for a specific model."""
    provider_config = get_provider_config(provider)
    if provider_config:
        return provider_config.get('models', {}).get(model)
    return None


def get_model_name(provider: str, model: str) -> str:
    """Get display name for a model (e.g., 'GPT-5 Mini')."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('name', model)
    return model


def get_model_description(provider: str, model: str) -> str:
    """Get description for a model."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('description', '')
    return ''


def get_default_model(provider: str) -> str:
    """Get the default model for a provider."""
    provider_config = get_provider_config(provider)
    if provider_config:
        return provider_config.get('default_model', '')
    return ''


# =============================================================================
# Context Window & Limits
# =============================================================================

def get_context_window(provider: str, model: str) -> int:
    """Get context window size for a model (in tokens)."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('context_window', 8192)
    
    # For Ollama, use defaults if model not in config
    if provider == 'ollama':
        provider_config = get_provider_config(provider)
        if provider_config:
            defaults = provider_config.get('model_defaults', {})
            return defaults.get('context_window', 8192)
    
    return 8192  # Safe fallback


def get_max_output(provider: str, model: str) -> int:
    """Get maximum output tokens for a model."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('max_output', 4096)
    
    # For Ollama, use defaults if model not in config
    if provider == 'ollama':
        provider_config = get_provider_config(provider)
        if provider_config:
            defaults = provider_config.get('model_defaults', {})
            return defaults.get('max_output', 4096)
    
    return 4096  # Safe fallback


# =============================================================================
# Feature Support
# =============================================================================

def supports_json(provider: str, model: str) -> bool:
    """Check if a model supports JSON/structured output."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('supports_json', False)
    
    # For Ollama, use defaults
    if provider == 'ollama':
        provider_config = get_provider_config(provider)
        if provider_config:
            defaults = provider_config.get('model_defaults', {})
            return defaults.get('supports_json', True)
    
    return False


def supports_vision(provider: str, model: str) -> bool:
    """Check if a model supports vision/image input."""
    model_config = get_model_config(provider, model)
    if model_config:
        return model_config.get('supports_vision', False)
    
    # For Ollama, use defaults
    if provider == 'ollama':
        provider_config = get_provider_config(provider)
        if provider_config:
            defaults = provider_config.get('model_defaults', {})
            return defaults.get('supports_vision', False)
    
    return False


# =============================================================================
# Rate Limits
# =============================================================================

def get_openai_tier() -> str:
    """Get the current OpenAI tier from config."""
    config = _load_config()
    return config.get('openai_tier', 'tier_1')


def get_rate_limits(provider: str, model: str, tier: Optional[str] = None) -> Optional[Dict]:
    """
    Get rate limits for a model.
    
    For OpenAI: Returns limits for the specified tier (or config default).
    For Ollama: Returns None (no rate limits for local models).
    
    Returns dict with 'rpm' (requests/min) and 'tpm' (tokens/min), or None.
    """
    if provider == 'ollama':
        return None  # No rate limits for local models
    
    model_config = get_model_config(provider, model)
    if not model_config:
        return None
    
    rate_limits = model_config.get('rate_limits')
    if not rate_limits:
        return None
    
    # For OpenAI, rate limits are per-tier
    if provider == 'openai':
        tier = tier or get_openai_tier()
        return rate_limits.get(tier)
    
    return rate_limits


# =============================================================================
# Pricing
# =============================================================================

def get_pricing(provider: str, model: str) -> Optional[Dict]:
    """
    Get pricing for a model.
    
    Returns dict with:
        - cost_per_1m_input: Cost per 1M input tokens
        - cost_per_1m_cached_input: Cost per 1M cached input tokens
        - cost_per_1m_output: Cost per 1M output tokens
    
    Returns None for local models (Ollama).
    """
    if provider == 'ollama':
        return None  # Free (local)
    
    model_config = get_model_config(provider, model)
    if not model_config:
        return None
    
    pricing = {}
    if 'cost_per_1m_input' in model_config:
        pricing['cost_per_1m_input'] = model_config['cost_per_1m_input']
    if 'cost_per_1m_cached_input' in model_config:
        pricing['cost_per_1m_cached_input'] = model_config['cost_per_1m_cached_input']
    if 'cost_per_1m_output' in model_config:
        pricing['cost_per_1m_output'] = model_config['cost_per_1m_output']
    
    return pricing if pricing else None


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """
    Estimate cost for a request.
    
    Returns estimated cost in USD, or None for local models.
    """
    pricing = get_pricing(provider, model)
    if not pricing:
        return None
    
    input_cost = (input_tokens / 1_000_000) * pricing.get('cost_per_1m_input', 0)
    output_cost = (output_tokens / 1_000_000) * pricing.get('cost_per_1m_output', 0)
    
    return input_cost + output_cost


# =============================================================================
# Token Counting Config
# =============================================================================

def get_token_counting_config() -> Dict:
    """Get token counting configuration."""
    config = _load_config()
    return config.get('token_counting', {
        'openai_encoding': 'cl100k_base',
        'fallback_chars_per_token': 4
    })


# =============================================================================
# Default Settings
# =============================================================================

def get_defaults() -> Dict:
    """Get default LLM settings (temperature, context paragraphs, etc.)."""
    config = _load_config()
    return config.get('defaults', {
        'temperature': 0.3,
        'context_paragraphs_before': 2,
        'context_paragraphs_after': 2
    })


# =============================================================================
# Ollama-specific
# =============================================================================

def get_ollama_default_url() -> str:
    """Get default Ollama server URL."""
    provider_config = get_provider_config('ollama')
    if provider_config:
        return provider_config.get('default_url', 'http://localhost:11434')
    return 'http://localhost:11434'


# =============================================================================
# UI Helpers
# =============================================================================

def get_models_for_dropdown(provider: str) -> List[Dict]:
    """
    Get models formatted for UI dropdown.
    
    Returns list of dicts with 'id', 'name', 'description'.
    """
    provider_config = get_provider_config(provider)
    if not provider_config:
        return []
    
    models = []
    for model_id, model_config in provider_config.get('models', {}).items():
        models.append({
            'id': model_id,
            'name': model_config.get('name', model_id),
            'description': model_config.get('description', '')
        })
    
    return models


def get_providers_for_dropdown() -> List[Dict]:
    """
    Get providers formatted for UI dropdown.
    
    Returns list of dicts with 'id', 'name', 'requires_api_key'.
    """
    config = _load_config()
    providers = []
    
    for provider_id, provider_config in config.get('providers', {}).items():
        providers.append({
            'id': provider_id,
            'name': provider_config.get('name', provider_id),
            'requires_api_key': provider_config.get('requires_api_key', False)
        })
    
    return providers
