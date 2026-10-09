"""Errors raised by the agent tool layer.

Tool handlers raise ``ToolError`` for recoverable, structured failures
(missing paragraph, unknown thread, unsupported file type, etc.). The agent
loop (Milestone 3) decides how to surface these back to the LLM; in unit tests
they are asserted directly.
"""

from __future__ import annotations


class ToolError(Exception):
    """A structured, recoverable failure from a tool handler.

    Attributes:
        code: Short machine-readable identifier (e.g. ``"not_found"``).
        message: Human-readable explanation.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict[str, str]:
        """JSON-serializable representation for the agent loop."""
        return {"error": self.code, "message": self.message}
