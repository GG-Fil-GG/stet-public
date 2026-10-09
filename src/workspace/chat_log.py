"""UI-facing agent chat turn log (Stage 1, Milestone 7).

Parallel to ``session.conversation`` (LLM transcript incl. tool messages). The turn
log holds display-ready summaries for the workspace chat panel and survives restarts
via ``.stet/workspace.json`` ``chat_turns``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatTurn:
    """One user message + agent response cycle as shown in the chat panel."""

    user_message: str
    final_text: str
    status: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "user_message": self.user_message,
            "final_text": self.final_text,
            "status": self.status,
            "steps": self.steps,
            "created_at": self.created_at,
        }
        if self.pending_confirmation is not None:
            data["pending_confirmation"] = self.pending_confirmation
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatTurn":
        return cls(
            user_message=data.get("user_message", ""),
            final_text=data.get("final_text", ""),
            status=data.get("status", "completed"),
            steps=list(data.get("steps") or []),
            pending_confirmation=data.get("pending_confirmation"),
            created_at=data.get("created_at") or _now(),
        )
