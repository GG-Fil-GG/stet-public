"""Workspace configuration (Stage 1, Milestone 4).

Reads/writes ``.stet/config.json`` per workspace. This module is the **code
source of truth** for the Stage 1 config defaults (M0 fixed the names/values;
M4 introduces the constants that hold them).

Resilience: missing file → defaults (and the file is written); missing keys →
per-key default; **invalid values → per-key default** (a hand-edited config can
never brick a workspace); unknown keys → ignored (forward-compatible).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from src.checkpoints import DEFAULT_MAX_CHECKPOINTS
from src.agent.loop import DEFAULT_MAX_STEPS

logger = logging.getLogger(__name__)

RESERVED_DIR = ".stet"
CONFIG_FILENAME = "config.json"

DEFAULT_CONFIG_VERSION = 1
DEFAULT_MAX_AGENT_STEPS = DEFAULT_MAX_STEPS  # 20, single-sourced from the loop
DEFAULT_CHECKPOINT_POLICY = "per_agent_turn"
DEFAULT_TOOL_ERROR_POLICY = "report_and_skip"
DEFAULT_CONTEXT_TOKEN_BUDGET = 60_000  # provider-bound conversation trim threshold (M9c-prep)

VALID_CHECKPOINT_POLICIES = {"per_agent_turn", "per_mutating_tool"}
VALID_TOOL_ERROR_POLICIES = {"report_and_skip", "stop_and_ask"}


@dataclass
class WorkspaceConfig:
    """Per-workspace configuration with code-default fallbacks."""

    config_version: int = DEFAULT_CONFIG_VERSION
    max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS
    max_agent_steps: int = DEFAULT_MAX_AGENT_STEPS
    checkpoint_policy: str = DEFAULT_CHECKPOINT_POLICY
    tool_error_policy: str = DEFAULT_TOOL_ERROR_POLICY
    context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET

    def to_dict(self) -> dict:
        return asdict(self)


def _config_path(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / RESERVED_DIR / CONFIG_FILENAME


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _from_raw(raw: dict) -> WorkspaceConfig:
    """Build a config from raw JSON, falling back to defaults for bad/missing keys."""
    config = WorkspaceConfig()

    version = raw.get("config_version")
    if isinstance(version, int) and not isinstance(version, bool):
        config.config_version = version

    if "max_checkpoints" in raw:
        if _is_positive_int(raw["max_checkpoints"]):
            config.max_checkpoints = raw["max_checkpoints"]
        else:
            logger.warning("Invalid max_checkpoints %r; using default %d",
                           raw["max_checkpoints"], config.max_checkpoints)

    if "max_agent_steps" in raw:
        if _is_positive_int(raw["max_agent_steps"]):
            config.max_agent_steps = raw["max_agent_steps"]
        else:
            logger.warning("Invalid max_agent_steps %r; using default %d",
                           raw["max_agent_steps"], config.max_agent_steps)

    if "context_token_budget" in raw:
        if _is_positive_int(raw["context_token_budget"]):
            config.context_token_budget = raw["context_token_budget"]
        else:
            logger.warning("Invalid context_token_budget %r; using default %d",
                           raw["context_token_budget"], config.context_token_budget)

    if "checkpoint_policy" in raw:
        if raw["checkpoint_policy"] in VALID_CHECKPOINT_POLICIES:
            config.checkpoint_policy = raw["checkpoint_policy"]
        else:
            logger.warning("Invalid checkpoint_policy %r; using default %r",
                           raw["checkpoint_policy"], config.checkpoint_policy)

    if "tool_error_policy" in raw:
        if raw["tool_error_policy"] in VALID_TOOL_ERROR_POLICIES:
            config.tool_error_policy = raw["tool_error_policy"]
        else:
            logger.warning("Invalid tool_error_policy %r; using default %r",
                           raw["tool_error_policy"], config.tool_error_policy)

    return config


def coerce_config(raw: dict) -> WorkspaceConfig:
    """Build a validated ``WorkspaceConfig`` from a raw dict (bad keys → default).

    Used by config updates (PUT) to re-validate a merged config dict.
    """
    return _from_raw(raw)


def load_config(workspace_root: Path | str) -> WorkspaceConfig:
    """Load ``.stet/config.json``, writing defaults on first use."""
    path = _config_path(workspace_root)
    if not path.is_file():
        config = WorkspaceConfig()
        save_config(workspace_root, config)
        return config
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s (%s); using defaults", path, exc)
        return WorkspaceConfig()
    if not isinstance(raw, dict):
        logger.warning("Config at %s is not an object; using defaults", path)
        return WorkspaceConfig()
    return _from_raw(raw)


def save_config(workspace_root: Path | str, config: WorkspaceConfig) -> None:
    """Write ``config`` to ``.stet/config.json`` (creating ``.stet/`` if needed)."""
    path = _config_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
