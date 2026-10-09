"""Agent Unicode-protection tests (Stage 1, Milestone 9a).

Covers the pure protect/restore transforms, the ``AgentLLMClient`` transport
seam (outbound protection + inbound restoration for both providers), and an
end-to-end loop run proving ``edit_paragraph`` preserves a special character the
model only ever saw as a placeholder.
"""

import json

from src.agent import AgentLoop
from src.agent import unicode_protection as up
from src.agent.llm_tools import AgentLLMClient
from src.agent.messages import Message, ToolCall
from src.agent.prompts import get_agent_system_prompt
from src.document_model import parse_docx
from tests.test_support import TEST_DOCX


# --------------------------------------------------------------------------- #
# Pure transforms
# --------------------------------------------------------------------------- #

class TestProtectRestore:
    def test_round_trip_with_several_mapped_chars(self):
        s = "n ≥ 75 ± 2 (p ≠ 0.05), Δ ≈ 3°"
        protected = up.protect(s)
        assert "≥" not in protected and "±" not in protected
        assert "__UNICODE_GTE__" in protected
        assert up.restore(protected) == s

    def test_only_known_chars_are_mapped(self):
        s = "高齢者 subanalysis café"  # Japanese + accented latin: not in the map
        assert up.protect(s) == s
        assert up.restore(s) == s

    def test_empty_and_none_safe(self):
        assert up.protect("") == ""
        assert up.restore("") == ""

    def test_map_is_superset_of_card_ui(self):
        # M9d relaxed exact parity to a superset: the agent map carries every
        # card-UI entry verbatim, plus agent-only additions (dashes etc.).
        from src.llm_transport import LLMTransportMixin

        card = LLMTransportMixin.UNICODE_PROTECTION_MAP
        assert card.items() <= up.UNICODE_PROTECTION_MAP.items()  # every card entry intact
        # The agent map adds exactly the M9d punctuation and nothing else.
        assert set(up.UNICODE_PROTECTION_MAP) - set(card) == set(up.M9D_AGENT_ADDITIONS)

    def test_dashes_round_trip(self):
        # M9d: en/em dash, ellipsis, non-breaking hyphen are protected agent-side.
        s = "2013\u20132017; a\u2014b; wait\u2026; non\u2011breaking"
        protected = up.protect(s)
        for ch in ("\u2013", "\u2014", "\u2026", "\u2011"):
            assert ch not in protected
        assert "__UNICODE_NDASH__" in protected and "__UNICODE_MDASH__" in protected
        assert up.restore(protected) == s

    def test_dash_additions_not_in_card_ui(self):
        from src.llm_transport import LLMTransportMixin

        for ch in ("\u2013", "\u2014", "\u2026", "\u2011"):
            assert ch not in LLMTransportMixin.UNICODE_PROTECTION_MAP


class TestPromptSafeguard:
    def test_prompt_instructs_token_preservation(self):
        prompt = get_agent_system_prompt()
        assert "__UNICODE_" in prompt
        # Names a concrete token and demands exact preservation.
        assert "__UNICODE_GTE__" in prompt
        assert "EXACTLY" in prompt

    def test_prompt_does_not_leak_real_symbols(self):
        # Real symbols in the prompt would themselves be protected before sending,
        # making the guidance circular. The prompt must describe tokens in words.
        prompt = get_agent_system_prompt()
        for char in up.UNICODE_PROTECTION_MAP:
            assert char not in prompt


class TestArgumentRecursion:
    def test_nested_dict_and_list_protected_and_restored(self):
        obj = {"new_text": "x ≥ y", "items": ["a ≤ b", {"deep": "± 1"}], "n": 3, "ok": True}
        protected = up.protect_arguments(obj)
        assert protected["new_text"] == "x __UNICODE_GTE__ y"
        assert protected["items"][0] == "a __UNICODE_LTE__ b"
        assert protected["items"][1]["deep"] == "__UNICODE_PM__ 1"
        # Non-strings untouched.
        assert protected["n"] == 3 and protected["ok"] is True
        assert up.restore_arguments(protected) == obj

    def test_keys_are_not_transformed(self):
        # A (pathological) key containing a mapped char stays literal; only the
        # string value is protected.
        obj = {"a≥b": "v ≥ w"}
        protected = up.protect_arguments(obj)
        assert list(protected.keys()) == ["a≥b"]
        assert protected["a≥b"] == "v __UNICODE_GTE__ w"


# --------------------------------------------------------------------------- #
# Outbound protection (message → provider payload)
# --------------------------------------------------------------------------- #

class TestOutboundProtection:
    def test_openai_user_content_protected(self):
        out = AgentLLMClient._message_to_openai(Message.user("require n ≥ 75"))
        assert out["content"] == "require n __UNICODE_GTE__ 75"

    def test_openai_tool_result_content_protected(self):
        out = AgentLLMClient._message_to_openai(Message.tool("c1", "read_paragraph", "value ± 2"))
        assert out["content"] == "value __UNICODE_PM__ 2"

    def test_openai_assistant_tool_call_arguments_protected(self):
        msg = Message.assistant("", [ToolCall(id="c1", name="edit_paragraph",
                                              arguments={"new_text": "x ≥ y"})])
        out = AgentLLMClient._message_to_openai(msg)
        args = json.loads(out["tool_calls"][0]["function"]["arguments"])
        assert args["new_text"] == "x __UNICODE_GTE__ y"

    def test_ollama_content_and_args_protected(self):
        msg = Message.assistant("note ≤ here",
                                [ToolCall(id="c1", name="edit_paragraph",
                                          arguments={"new_text": "a ≠ b"})])
        out = AgentLLMClient._message_to_ollama(msg)
        assert out["content"] == "note __UNICODE_LTE__ here"
        assert out["tool_calls"][0]["function"]["arguments"]["new_text"] == "a __UNICODE_NEQ__ b"


# --------------------------------------------------------------------------- #
# Inbound restoration (provider response → normalized) — fakes reused below
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


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class TestInboundRestoration:
    def test_openai_tool_call_argument_restored(self, monkeypatch):
        from src.agent import list_tools

        client = AgentLLMClient(provider="openai", api_key="test-key", model="gpt-4o")
        fake = _FakeResponse(
            content="result is __UNICODE_GTE__ done",
            tool_calls=[_FakeToolCall("c1", "edit_paragraph",
                                      '{"new_text": "x __UNICODE_GTE__ y"}')],
        )
        monkeypatch.setattr(client._client.chat.completions, "create", lambda **kw: fake)
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.text == "result is ≥ done"
        assert resp.tool_calls[0].arguments["new_text"] == "x ≥ y"

    def test_ollama_tool_call_argument_restored(self, monkeypatch):
        from src.agent import list_tools

        client = AgentLLMClient(provider="ollama", model="llama3.1")
        payload = {
            "message": {
                "content": "note __UNICODE_PM__ 2",
                "tool_calls": [
                    {"function": {"name": "edit_paragraph",
                                  "arguments": {"new_text": "a __UNICODE_LTE__ b"}}}
                ],
            }
        }
        monkeypatch.setattr("src.agent.llm_tools.requests.post",
                            lambda *a, **k: _FakeHTTPResponse(payload))
        resp = client.complete([Message.user("hi")], list_tools())
        assert resp.text == "note ± 2"
        assert resp.tool_calls[0].arguments["new_text"] == "a ≤ b"


# --------------------------------------------------------------------------- #
# End-to-end loop integration (real AgentLLMClient, mocked provider)
# --------------------------------------------------------------------------- #

class TestLoopIntegration:
    def test_edit_paragraph_preserves_special_char(self, monkeypatch):
        from src.agent import list_tools

        model = parse_docx(TEST_DOCX)
        para_id = next(p.para_id for p in model.body.iter_paragraphs() if p.plain_text.strip())

        client = AgentLLMClient(provider="openai", api_key="test-key", model="gpt-4o")

        # The model only ever sees/echoes the placeholder — never a corruptible ≥.
        responses = [
            _FakeResponse(
                content=None,
                tool_calls=[_FakeToolCall(
                    "c1", "edit_paragraph",
                    '{"para_id": "%s", "new_text": "Threshold __UNICODE_GTE__ 75 years.", '
                    '"track_changes": false}' % para_id,
                )],
            ),
            _FakeResponse(content="Done.", tool_calls=None),
        ]
        calls = {"n": 0}

        def fake_create(**kw):
            resp = responses[min(calls["n"], len(responses) - 1)]
            calls["n"] += 1
            return resp

        monkeypatch.setattr(client._client.chat.completions, "create", fake_create)

        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("Set the age threshold.")

        assert result.status == "completed"
        # The applied edit carries the real character, not the placeholder.
        text = model.get_paragraph(para_id).plain_text
        assert "≥ 75" in text
        assert "__UNICODE_GTE__" not in text
