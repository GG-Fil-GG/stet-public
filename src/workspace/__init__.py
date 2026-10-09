"""Workspace backend for the Stage 1 agentic workspace (Milestone 4).

Public surface:
- ``WorkspaceConfig`` + ``load_config`` / ``save_config`` (``.stet/config.json``)
- Folder helpers (``ensure_stet_dir``, ``list_files``, ``resolve_path``)
- ``WorkspaceSession`` + registry (``open_workspace``, ``get_workspace``, …)
"""

from .config import (
    WorkspaceConfig,
    load_config,
    save_config,
    DEFAULT_MAX_AGENT_STEPS,
    DEFAULT_CHECKPOINT_POLICY,
    DEFAULT_TOOL_ERROR_POLICY,
)
from .folder import ensure_stet_dir, list_files, resolve_path
from .chat_log import ChatTurn
from .render import Block, render_document
from .state import (
    WorkspaceSession,
    open_workspace,
    get_workspace,
    list_workspaces,
    close_workspace,
)

__all__ = [
    "WorkspaceConfig",
    "load_config",
    "save_config",
    "DEFAULT_MAX_AGENT_STEPS",
    "DEFAULT_CHECKPOINT_POLICY",
    "DEFAULT_TOOL_ERROR_POLICY",
    "ensure_stet_dir",
    "list_files",
    "resolve_path",
    "ChatTurn",
    "Block",
    "render_document",
    "WorkspaceSession",
    "open_workspace",
    "get_workspace",
    "list_workspaces",
    "close_workspace",
]
