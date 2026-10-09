"""Agent tool layer + tool-calling loop for the Stage 1 agentic workspace.

Public surface:
- Tool handlers (``src.agent.tools``)
- Canonical input schemas (``src.agent.tool_schemas``)
- The tool registry (``TOOLS``, ``get_tool``, ``list_tools``, ``ToolSpec``)
- ``ToolError`` for structured failures
- Conversation types (``Message``, ``ToolCall``)
- The LLM tool client (``AgentLLMClient``, ``LLMToolResponse``)
- The agent loop (``AgentLoop``, ``AgentResult``, ``AgentStep``,
  ``PendingConfirmation``, ``CheckpointPolicy``, ``ToolErrorPolicy``)
"""

from .errors import ToolError
from .registry import TOOLS, ToolSpec, get_tool, list_tools
from .messages import Message, ToolCall, Role
from .llm_tools import AgentLLMClient, LLMToolResponse
from .loop import (
    AgentLoop,
    AgentResult,
    AgentStep,
    PendingConfirmation,
    CheckpointPolicy,
    ToolErrorPolicy,
)

__all__ = [
    "ToolError",
    "ToolSpec",
    "TOOLS",
    "get_tool",
    "list_tools",
    "Message",
    "ToolCall",
    "Role",
    "AgentLLMClient",
    "LLMToolResponse",
    "AgentLoop",
    "AgentResult",
    "AgentStep",
    "PendingConfirmation",
    "CheckpointPolicy",
    "ToolErrorPolicy",
]
