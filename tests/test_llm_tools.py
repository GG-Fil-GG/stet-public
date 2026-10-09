"""Tests for the provider-neutral tool-calling client (Stage 1, Milestone 3).

No network: schema/message translation is tested on the static helpers, and
response normalization is tested with fake provider responses.
"""

import json

import pytest

from src.agent import list_tools
from src.agent.llm_tools import (
    _OPENAI_MAX_RETRIES,
    _OPENAI_TIMEOUT_SECONDS,
    _TRIM_KEEP_LAST_TOOL_RESULTS,
    _TRIM_STUB,
    AgentLLMClient,
    LLMToolResponse,
    trim_conversation,
)
from src.agent.messages import Message, ToolCall


# --------------------------------------------------------------------------- #
# Schema translation
# --------------------------------------------------------------------------- #

class TestToolSchemaTranslation:
    def test_every_tool_translates_to_function_schema(self):
        for spec in list_tools():
            schema = AgentLLMClient._tool_to_schema(spec)
            assert schema["type"] == "function"
            fn = schema["function"]
            assert fn["name"] == spec.name
            assert fn["description"] == spec.description
            assert fn["parameters"]["type"] == "object"

    def test_schema_shape_is_provider_neutral(self):
        # The same shape is sent to both OpenAI and Ollama.
        spec = next(s for s in list_tools() if s.name == "edit_paragraph")
        schema = AgentLLMClient._tool_to_schema(spec)
        props = schema["function"]["parameters"]["properties"]
        assert "para_id" in props and "new_text" in props


# --------------------------------------------------------------------------- #
# Message translation
# --------------------------------------------------------------------------- #

class TestMessageTranslation:
    def test_openai_plain_messages(self):
        assert AgentLLMClient._message_to_openai(Message.user("hi")) == {
            "role": "user", "content": "hi"
        }

    def test_openai_assistant_tool_calls(self):
        msg = Message.assistant("", [ToolCall(id="c1", name="list_comments", arguments={"comment_filter": "open"})])
        out = AgentLLMClient._message_to_openai(msg)
        assert out["role"] == "assistant"
        assert out["tool_calls"][0]["id"] == "c1"
        assert out["tool_calls"][0]["type"] == "function"
        assert out["tool_calls"][0]["function"]["name"] == "list_comments"
        # OpenAI wants arguments as a JSON string.
        assert json.loads(out["tool_calls"][0]["function"]["arguments"]) == {"comment_filter": "open"}

    def test_openai_tool_result_keyed_by_call_id(self):
        out = AgentLLMClient._message_to_openai(Message.tool("c1", "list_comments", "{}"))
        assert out == {"role": "tool", "tool_call_id": "c1", "content": "{}"}

    def test_ollama_assistant_tool_calls_keep_dict_args(self):
        msg = Message.assistant("", [ToolCall(id="c1", name="list_comments", arguments={"comment_filter": "open"})])
        out = AgentLLMClient._message_to_ollama(msg)
        # Ollama wants arguments as a dict (not a string).
        assert out["tool_calls"][0]["function"]["arguments"] == {"comment_filter": "open"}

    def test_ollama_tool_result_keyed_by_tool_name(self):
        out = AgentLLMClient._message_to_ollama(Message.tool("c1", "list_comments", "{}"))
        assert out == {"role": "tool", "tool_name": "list_comments", "content": "{}"}


# --------------------------------------------------------------------------- #
# OpenAI response normalization
# --------------------------------------------------------------------------- #

class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResponse:
    def __init__(self, content, tool_calls):
        self.choices = [type("C", (), {"message": _FakeMessage(content, tool_calls)})()]


def _openai_client(monkeypatch, fake_response):
    client = AgentLLMClient(provider="openai", api_key="test-key", model="gpt-4o")
    monkeypatch.setattr(
        client._client.chat.completions, "create", lambda **kw: fake_response
    )
    return client


class TestOpenAINormalization:
    def test_parses_tool_calls_with_string_arguments(self, monkeypatch):
        fake = _FakeResponse(
            content=None,
            tool_calls=[_FakeToolCall("c1", "list_comments", '{"comment_filter": "open"}')],
        )
        client = _openai_client(monkeypatch, fake)
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.text == ""
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "list_comments"
        assert resp.tool_calls[0].arguments == {"comment_filter": "open"}

    def test_plain_text_response_has_no_tool_calls(self, monkeypatch):
        fake = _FakeResponse(content="All done.", tool_calls=None)
        client = _openai_client(monkeypatch, fake)
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.text == "All done."
        assert resp.tool_calls == []

    def test_malformed_arguments_default_to_empty(self, monkeypatch):
        fake = _FakeResponse(content=None, tool_calls=[_FakeToolCall("c1", "list_comments", "not json")])
        client = _openai_client(monkeypatch, fake)
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.tool_calls[0].arguments == {}


# --------------------------------------------------------------------------- #
# Ollama response normalization
# --------------------------------------------------------------------------- #

class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestOllamaNormalization:
    def test_parses_tool_calls_with_dict_arguments(self, monkeypatch):
        client = AgentLLMClient(provider="ollama", model="llama3.1")
        payload = {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "list_comments", "arguments": {"comment_filter": "open"}}}
                ],
            }
        }
        monkeypatch.setattr("src.agent.llm_tools.requests.post", lambda *a, **k: _FakeHTTPResponse(payload))
        resp = client.complete([Message.user("hi")], list_tools())
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "list_comments"
        assert resp.tool_calls[0].arguments == {"comment_filter": "open"}
        # Ollama may omit an id; the client synthesizes one.
        assert resp.tool_calls[0].id

    def test_plain_text_response(self, monkeypatch):
        client = AgentLLMClient(provider="ollama", model="llama3.1")
        payload = {"message": {"content": "Finished.", "tool_calls": []}}
        monkeypatch.setattr("src.agent.llm_tools.requests.post", lambda *a, **k: _FakeHTTPResponse(payload))
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.text == "Finished."
        assert resp.tool_calls == []


# --------------------------------------------------------------------------- #
# Conversation trim (M9c-prep)
# --------------------------------------------------------------------------- #

def _trim_fixture(tool_results=10, size=4_000):
    """System + user + ``tool_results`` assistant/tool pairs of ``size`` chars."""
    msgs = [Message.system("You are Stet."), Message.user("Address all comments.")]
    for i in range(tool_results):
        msgs.append(Message.assistant("", [ToolCall(id=f"c{i}", name="read_file", arguments={})]))
        msgs.append(Message.tool(f"c{i}", "read_file", "x" * size))
    return msgs


class TestConversationTrim:
    def test_under_budget_passes_through_identical(self):
        msgs = _trim_fixture(tool_results=2)
        out = trim_conversation(msgs, budget=100_000)
        assert out == msgs
        assert all(o is m for o, m in zip(out, msgs))  # same objects, no copies

    def test_over_budget_stubs_oldest_protects_tail(self):
        msgs = _trim_fixture(tool_results=10, size=4_000)  # ~10k tokens of tool results
        out = trim_conversation(msgs, budget=5_000)

        tool_msgs = [m for m in out if m.role == "tool"]
        assert tool_msgs[0].content == _TRIM_STUB  # oldest trimmed first
        # The protected tail is intact.
        for m in tool_msgs[-_TRIM_KEEP_LAST_TOOL_RESULTS:]:
            assert m.content != _TRIM_STUB
        # System / user / assistant messages are never touched.
        assert out[0].content == "You are Stet."
        assert out[1].content == "Address all comments."
        assert all(m.content == "" for m in out if m.role == "assistant")

    def test_input_messages_not_mutated(self):
        msgs = _trim_fixture(tool_results=10, size=4_000)
        trim_conversation(msgs, budget=5_000)
        assert all(m.content == "x" * 4_000 for m in msgs if m.role == "tool")

    def test_complete_trims_provider_copy_only(self, monkeypatch):
        captured = {}

        def fake_call(self, messages, tool_payload):
            captured["messages"] = messages
            return LLMToolResponse(text="ok")

        monkeypatch.setattr(AgentLLMClient, "_call_ollama", fake_call)
        client = AgentLLMClient(provider="ollama", model="llama3.1", context_token_budget=5_000)
        msgs = _trim_fixture(tool_results=10, size=4_000)
        client.complete(msgs, list_tools())

        assert any(m.content == _TRIM_STUB for m in captured["messages"])
        # The caller's (persisted) history keeps the full results.
        assert all(m.content == "x" * 4_000 for m in msgs if m.role == "tool")


# --------------------------------------------------------------------------- #
# Bounded OpenAI calls (M9c-prep)
# --------------------------------------------------------------------------- #

class TestOpenAIClientConfig:
    def test_timeout_and_retries_are_bounded(self):
        client = AgentLLMClient(provider="openai", api_key="test-key", model="gpt-4o")
        assert client._client.timeout == _OPENAI_TIMEOUT_SECONDS == 120
        # Bounded (not the library default of 2) but non-zero so a transient
        # connection drop is retried rather than killing the run (post-M9c-prep).
        assert client._client.max_retries == _OPENAI_MAX_RETRIES == 3
