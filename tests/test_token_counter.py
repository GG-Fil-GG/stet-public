"""Unit tests for src/token_counter.py."""

from src.token_counter import (
    check_token_limit,
    count_tokens,
    format_token_display,
    get_context_window,
)


class TestCountTokens:
    def test_empty_text_returns_zero(self):
        assert count_tokens("") == 0
        assert count_tokens("", provider="ollama") == 0

    def test_openai_returns_positive_count(self):
        text = "Hello, this is a test sentence for token counting."
        assert count_tokens(text, provider="openai") > 0

    def test_ollama_uses_approximate_counting(self):
        text = "abcd" * 10  # 40 chars -> ~10 tokens at 4 chars/token
        assert count_tokens(text, provider="ollama") == 10


class TestCheckTokenLimit:
    def test_short_text_is_within_limit(self):
        result = check_token_limit("Short prompt.", provider="openai")
        assert result["status"] == "ok"
        assert result["is_within_limit"] is True
        assert result["token_count"] >= 0
        assert result["context_window"] > 0

    def test_returns_expected_keys(self):
        result = check_token_limit("Sample text", provider="openai")
        assert set(result.keys()) == {
            "token_count",
            "context_window",
            "max_allowed",
            "is_within_limit",
            "usage_percent",
            "status",
        }


class TestFormatTokenDisplay:
    def test_formats_with_commas(self):
        display = format_token_display(2450, 400000)
        assert display == "~2,450 / 400,000"


class TestGetContextWindow:
    def test_openai_default_model_has_context_window(self):
        window = get_context_window("openai")
        assert window > 0
