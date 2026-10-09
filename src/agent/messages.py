"""Conversation message types for the agent loop (Stage 1, Milestone 3).

These describe the loop's internal conversation with the LLM — distinct from the
UI/session ``ChatMessage`` (``src/chat_types.py``). The loop is stateless per
call: it takes a ``list[Message]`` history in and returns the extended list out.
Persisting conversation into the workspace session is Milestone 4.

Provider-neutral by design: ``AgentLLMClient`` (``src/agent/llm_tools.py``)
translates these to/from each provider's wire format (OpenAI / Ollama).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """A single tool invocation requested by the model.

    Attributes:
        id: Provider-assigned call id, echoed back on the tool-result message.
            Ollama may omit ids; the client synthesizes one when absent.
        name: Tool name (must exist in the registry).
        arguments: Parsed JSON arguments (LLM-facing params only — never the
            injected ``model`` / ``workspace_root``).
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            id=data["id"],
            name=data["name"],
            arguments=data.get("arguments", {}) or {},
        )


@dataclass
class Message:
    """One turn in the loop's conversation.

    - ``system`` / ``user``: plain ``content``.
    - ``assistant``: ``content`` and/or ``tool_calls``.
    - ``tool``: a tool result, with ``tool_call_id`` + ``name`` identifying which
      call it answers and ``content`` holding the JSON-serialized result.
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool(cls, tool_call_id: str, name: str, content: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for ``.stet/workspace.json`` persistence."""
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            data["name"] = self.name
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=data["role"],
            content=data.get("content", "") or "",
            tool_calls=[ToolCall.from_dict(tc) for tc in data.get("tool_calls", [])],
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )
