"""Provider-neutral tool-calling LLM client (Stage 1, Milestone 3).

``AgentLLMClient`` is the transport seam for the agent loop. It:

1. translates the registry's canonical tool schemas (``ToolSpec.json_schema()``)
   into each provider's ``tools`` format,
2. issues a tool-enabled chat completion, and
3. normalizes the provider's reply into a provider-neutral ``LLMToolResponse``
   (free text + parsed ``ToolCall``s).

It deliberately does **not** touch ``LLMHandler`` / ``src/llm_transport.py`` (the
card-UI suggestion/chat path, which stays the regression baseline). It reuses
``src/llm_config`` only for provider/model/url defaults.

Providers: OpenAI (``chat.completions``) and Ollama (``POST /api/chat``). Both use
the same tool-schema shape; the differences the client normalizes are the
argument encoding (OpenAI = JSON string, Ollama = dict) and the tool-result
message key (``tool_call_id`` vs ``tool_name``). Calls are synchronous.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from typing import Any

import requests

from src import llm_config
from . import unicode_protection
from .messages import Message, ToolCall
from .registry import ToolSpec

logger = logging.getLogger(__name__)

# Ollama's /api/chat can be slow on first load (model warm-up); be generous.
_OLLAMA_TIMEOUT_SECONDS = 300

# Bound each OpenAI call so a degenerate request cannot pin a run (and Stop with
# it) for the library default of 600s x retries (M9c-prep).
_OPENAI_TIMEOUT_SECONDS = 120
# Retry transient failures (connection drops, 429, 5xx) so a single network blip
# does not kill a long run. The M9c pilot saw runs die on step 1 with
# "Server disconnected without sending a response"; 0 retries (the original
# M9c-prep value) surfaced that immediately. Retries only fire on failure — a
# normal call is never retried — and the SDK's exponential backoff is short, so
# Stop stays responsive (worst case: a few seconds of backoff on a failing call).
_OPENAI_MAX_RETRIES = 3

# Conversation trim (M9c-prep): when the provider-bound history exceeds the
# budget, the oldest tool results are stubbed out. The stored conversation is
# never mutated — trimming applies to the copy sent to the provider only.
DEFAULT_CONTEXT_TOKEN_BUDGET = 60_000
_TRIM_KEEP_LAST_TOOL_RESULTS = 4
_TRIM_STUB = "[result trimmed to save space — call the tool again if needed]"


def _estimate_tokens(message: Message) -> int:
    """Rough token estimate (chars/4) for one message, including tool-call args."""
    chars = len(message.content or "")
    for tc in message.tool_calls:
        chars += len(json.dumps(tc.arguments))
    return chars // 4


def trim_conversation(
    messages: list[Message], budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET
) -> list[Message]:
    """Return a copy of ``messages`` trimmed to roughly ``budget`` tokens.

    Only tool-result messages are candidates, oldest first; the last
    ``_TRIM_KEEP_LAST_TOOL_RESULTS`` tool results, the system prompt, user
    messages, and assistant text are never touched. Trimmed messages get a
    short stub so the model knows it can re-run the tool. Input messages are
    not mutated.
    """
    total = sum(_estimate_tokens(m) for m in messages)
    if total <= budget:
        return messages

    tool_indices = [i for i, m in enumerate(messages) if m.role == "tool"]
    protected = set(tool_indices[-_TRIM_KEEP_LAST_TOOL_RESULTS:])

    trimmed = list(messages)
    trimmed_count = 0
    for i in tool_indices:
        if total <= budget:
            break
        if i in protected or len(trimmed[i].content) <= len(_TRIM_STUB):
            continue
        total -= _estimate_tokens(trimmed[i])
        trimmed[i] = replace(trimmed[i], content=_TRIM_STUB)
        total += _estimate_tokens(trimmed[i])
        trimmed_count += 1

    if trimmed_count:
        logger.info(
            "Trimmed %d old tool result(s) from provider payload (~%d tokens, budget %d)",
            trimmed_count, total, budget,
        )
    return trimmed


@dataclass
class LLMToolResponse:
    """A normalized provider reply: assistant free text and/or tool calls."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class AgentLLMClient:
    """Provider-neutral tool-calling chat client (OpenAI / Ollama)."""

    def __init__(
        self,
        provider: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
        ollama_url: str | None = None,
        temperature: float | None = None,
        context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
    ) -> None:
        self.provider = provider.lower()
        self.context_token_budget = context_token_budget

        available = llm_config.get_providers()
        if self.provider not in available:
            raise ValueError(
                f"Unknown provider: {provider}. Available: {', '.join(available)}"
            )

        defaults = llm_config.get_defaults()
        self.temperature = (
            temperature if temperature is not None else defaults.get("temperature", 0.3)
        )

        if self.provider == "openai":
            self.model = model or llm_config.get_default_model("openai")
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not self.api_key or self.api_key == "paste-your-key-here":
                raise ValueError(
                    "OpenAI API key not provided. Set OPENAI_API_KEY or pass api_key."
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                timeout=_OPENAI_TIMEOUT_SECONDS,
                max_retries=_OPENAI_MAX_RETRIES,
            )
        elif self.provider == "ollama":
            self.model = model or os.getenv(
                "OLLAMA_MODEL", llm_config.get_default_model("ollama")
            )
            self.ollama_url = ollama_url or llm_config.get_ollama_default_url()
        else:  # pragma: no cover - guarded by the provider check above
            raise ValueError(f"Unknown provider: {provider}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def complete(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMToolResponse:
        """Run one tool-enabled completion and return a normalized response.

        The caller's ``messages`` are never mutated: trimming (and the per-message
        Unicode protection downstream) applies to the provider-bound copy only.
        """
        messages = trim_conversation(messages, self.context_token_budget)
        tool_payload = [self._tool_to_schema(spec) for spec in tools]
        if self.provider == "openai":
            return self._call_openai(messages, tool_payload)
        return self._call_ollama(messages, tool_payload)

    # ------------------------------------------------------------------ #
    # Schema translation (identical shape for both providers)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tool_to_schema(spec: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.json_schema(),
            },
        }

    # ------------------------------------------------------------------ #
    # OpenAI
    # ------------------------------------------------------------------ #

    def _call_openai(
        self, messages: list[Message], tool_payload: list[dict]
    ) -> LLMToolResponse:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_openai(m) for m in messages],
            "tools": tool_payload,
            "tool_choice": "auto",
        }
        # GPT-5 family only accepts the default temperature (mirrors llm_transport).
        if "gpt-5" not in self.model.lower():
            params["temperature"] = self.temperature

        response = self._client.chat.completions.create(**params)
        message = response.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                args = {}
            args = unicode_protection.restore_arguments(args)
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMToolResponse(
            text=unicode_protection.restore(message.content or ""),
            tool_calls=tool_calls,
        )

    @staticmethod
    def _message_to_openai(message: Message) -> dict[str, Any]:
        if message.role == "assistant" and message.tool_calls:
            return {
                "role": "assistant",
                "content": unicode_protection.protect(message.content) or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(
                                unicode_protection.protect_arguments(tc.arguments)
                            ),
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": unicode_protection.protect(message.content),
            }
        return {
            "role": message.role,
            "content": unicode_protection.protect(message.content),
        }

    # ------------------------------------------------------------------ #
    # Ollama
    # ------------------------------------------------------------------ #

    def _call_ollama(
        self, messages: list[Message], tool_payload: list[dict]
    ) -> LLMToolResponse:
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": [self._message_to_ollama(m) for m in messages],
                "tools": tool_payload,
                "stream": False,
                "options": {"temperature": self.temperature},
            },
            timeout=_OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        message = response.json().get("message", {})

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(message.get("tool_calls", []) or []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):  # some builds return a JSON string
                try:
                    args = json.loads(args or "{}")
                except (ValueError, TypeError):
                    args = {}
            args = unicode_protection.restore_arguments(args or {})
            # Ollama may omit ids; synthesize a stable one for echo-back.
            call_id = tc.get("id") or f"call_{i}"
            tool_calls.append(
                ToolCall(id=call_id, name=fn.get("name", ""), arguments=args)
            )
        return LLMToolResponse(
            text=unicode_protection.restore(message.get("content", "") or ""),
            tool_calls=tool_calls,
        )

    @staticmethod
    def _message_to_ollama(message: Message) -> dict[str, Any]:
        if message.role == "assistant" and message.tool_calls:
            return {
                "role": "assistant",
                "content": unicode_protection.protect(message.content),
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.name,
                            "arguments": unicode_protection.protect_arguments(
                                tc.arguments
                            ),
                        }
                    }
                    for tc in message.tool_calls
                ],
            }
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_name": message.name,
                "content": unicode_protection.protect(message.content),
            }
        return {
            "role": message.role,
            "content": unicode_protection.protect(message.content),
        }
