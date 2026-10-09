"""Workspace folder operations (Stage 1, Milestone 4).

Thin helpers over the M1 tool layer for the workspace backend: create the
``.stet/`` namespace, list the (recursive) user file tree, and resolve
LLM/UI-supplied paths against the workspace root with containment.
"""

from __future__ import annotations

from pathlib import Path

from src.agent import tools

RESERVED_DIR = ".stet"
CHECKPOINTS_DIRNAME = "checkpoints"


def ensure_stet_dir(workspace_root: Path | str) -> Path:
    """Create ``.stet/`` and ``.stet/checkpoints/`` if absent; return ``.stet/``."""
    stet = Path(workspace_root) / RESERVED_DIR
    (stet / CHECKPOINTS_DIRNAME).mkdir(parents=True, exist_ok=True)
    return stet


def list_files(workspace_root: Path | str) -> dict:
    """Return the recursive user file tree (workspace-relative; excludes .stet/)."""
    return tools.list_workspace_files(Path(workspace_root))


def resolve_path(workspace_root: Path | str, path: Path | str) -> Path:
    """Resolve ``path`` against the workspace root, contained to it.

    Delegates to ``tools.resolve_in_workspace`` (raises ``ToolError`` for paths
    that escape the workspace).
    """
    return tools.resolve_in_workspace(workspace_root, path)
