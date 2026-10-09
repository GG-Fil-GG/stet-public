"""
Token Counter Module

Provides accurate token counting for OpenAI models (using tiktoken)
and approximate counting for other providers.

Used for:
- Displaying prompt size to users
- Enforcing context window limits
- Estimating costs
"""

from typing import Optional
from src import llm_config


def count_tokens(text: str, provider: str = "openai", model: Optional[str] = None) -> int:
    """
    Count tokens in text for a specific provider/model.
    
    Args:
        text: The text to count tokens for
        provider: LLM provider ("openai" or "ollama")
        model: Model name (uses default for provider if not specified)
    
    Returns:
        Token count (exact for OpenAI, approximate for others)
    """
    if not text:
        return 0
    
    if provider == "openai":
        return _count_tokens_openai(text, model)
    else:
        return _count_tokens_approximate(text)


def _count_tokens_openai(text: str, model: Optional[str] = None) -> int:
    """
    Count tokens using tiktoken (accurate for OpenAI models).
    
    Args:
        text: Text to count
        model: OpenAI model name
    
    Returns:
        Exact token count
    """
    try:
        import tiktoken
    except ImportError:
        # Fallback if tiktoken not installed
        return _count_tokens_approximate(text)
    
    # Get encoding from config or use default
    token_config = llm_config.get_token_counting_config()
    encoding_name = token_config.get('openai_encoding', 'cl100k_base')
    
    try:
        # Try to get encoding for specific model first
        if model:
            try:
                encoder = tiktoken.encoding_for_model(model)
            except KeyError:
                # Model not recognized, use default encoding
                encoder = tiktoken.get_encoding(encoding_name)
        else:
            encoder = tiktoken.get_encoding(encoding_name)
        
        return len(encoder.encode(text))
    except Exception as e:
        # Any error, fall back to approximation
        print(f"[TOKEN_COUNTER] tiktoken error: {e}, using approximation")
        return _count_tokens_approximate(text)


def _count_tokens_approximate(text: str) -> int:
    """
    Approximate token count based on character count.
    
    Rule of thumb: ~4 characters per token for English text.
    This is used for:
    - Ollama models (no official tokenizer)
    - Fallback when tiktoken fails
    
    Args:
        text: Text to count
    
    Returns:
        Approximate token count
    """
    token_config = llm_config.get_token_counting_config()
    chars_per_token = token_config.get('fallback_chars_per_token', 4)
    return len(text) // chars_per_token


def get_context_window(provider: str, model: Optional[str] = None) -> int:
    """
    Get the context window size for a model.
    
    Args:
        provider: LLM provider
        model: Model name (uses default if not specified)
    
    Returns:
        Context window size in tokens
    """
    if not model:
        model = llm_config.get_default_model(provider)
    return llm_config.get_context_window(provider, model)


def check_token_limit(
    text: str, 
    provider: str = "openai", 
    model: Optional[str] = None,
    buffer_ratio: float = 0.9
) -> dict:
    """
    Check if text fits within the model's context window.
    
    Args:
        text: Text to check
        provider: LLM provider
        model: Model name
        buffer_ratio: Fraction of context window to allow (default 0.9 = 90%)
    
    Returns:
        Dict with:
            - token_count: Number of tokens
            - context_window: Model's context window
            - max_allowed: Effective limit (context_window * buffer_ratio)
            - is_within_limit: True if token_count <= max_allowed
            - usage_percent: Percentage of limit used
            - status: "ok", "warning", or "error"
    """
    token_count = count_tokens(text, provider, model)
    context_window = get_context_window(provider, model)
    max_allowed = int(context_window * buffer_ratio)
    
    usage_percent = (token_count / context_window * 100) if context_window > 0 else 0
    
    # Determine status
    if token_count > context_window:
        status = "error"
    elif token_count > max_allowed:
        status = "warning"
    else:
        status = "ok"
    
    return {
        "token_count": token_count,
        "context_window": context_window,
        "max_allowed": max_allowed,
        "is_within_limit": token_count <= max_allowed,
        "usage_percent": round(usage_percent, 1),
        "status": status
    }


def format_token_display(token_count: int, context_window: int) -> str:
    """
    Format token count for UI display.
    
    Args:
        token_count: Current token count
        context_window: Model's context window
    
    Returns:
        Formatted string like "~2,450 / 400,000"
    """
    return f"~{token_count:,} / {context_window:,}"


def estimate_cost(
    input_tokens: int, 
    output_tokens: int,
    provider: str = "openai",
    model: Optional[str] = None
) -> Optional[float]:
    """
    Estimate cost for a request.
    
    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens (can be estimated)
        provider: LLM provider
        model: Model name
    
    Returns:
        Estimated cost in USD, or None for free/local models
    """
    if not model:
        model = llm_config.get_default_model(provider)
    return llm_config.estimate_cost(provider, model, input_tokens, output_tokens)
