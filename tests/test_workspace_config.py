"""Workspace config tests (Stage 1, Milestone 4)."""

import json

from src.workspace.config import (
    DEFAULT_CHECKPOINT_POLICY,
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    DEFAULT_MAX_AGENT_STEPS,
    DEFAULT_TOOL_ERROR_POLICY,
    WorkspaceConfig,
    coerce_config,
    load_config,
    save_config,
)
from src.checkpoints import DEFAULT_MAX_CHECKPOINTS


def _config_file(root):
    return root / ".stet" / "config.json"


class TestLoadSave:
    def test_defaults_written_on_first_load(self, temp_dir):
        config = load_config(temp_dir)
        assert config.config_version == 1
        assert config.max_checkpoints == DEFAULT_MAX_CHECKPOINTS
        assert config.max_agent_steps == DEFAULT_MAX_AGENT_STEPS
        assert config.checkpoint_policy == DEFAULT_CHECKPOINT_POLICY
        assert config.tool_error_policy == DEFAULT_TOOL_ERROR_POLICY
        assert config.context_token_budget == DEFAULT_CONTEXT_TOKEN_BUDGET
        # The file was created.
        assert _config_file(temp_dir).is_file()

    def test_round_trip(self, temp_dir):
        save_config(temp_dir, WorkspaceConfig(max_checkpoints=5, max_agent_steps=7,
                                              checkpoint_policy="per_mutating_tool",
                                              tool_error_policy="stop_and_ask",
                                              context_token_budget=12_000))
        config = load_config(temp_dir)
        assert config.max_checkpoints == 5
        assert config.max_agent_steps == 7
        assert config.checkpoint_policy == "per_mutating_tool"
        assert config.tool_error_policy == "stop_and_ask"
        assert config.context_token_budget == 12_000


class TestResilience:
    def test_missing_keys_fall_back(self, temp_dir):
        (temp_dir / ".stet").mkdir()
        _config_file(temp_dir).write_text(json.dumps({"max_checkpoints": 3}), encoding="utf-8")
        config = load_config(temp_dir)
        assert config.max_checkpoints == 3
        assert config.max_agent_steps == DEFAULT_MAX_AGENT_STEPS  # fallback

    def test_unknown_keys_ignored(self, temp_dir):
        (temp_dir / ".stet").mkdir()
        _config_file(temp_dir).write_text(
            json.dumps({"max_checkpoints": 4, "future_key": "whatever"}), encoding="utf-8"
        )
        config = load_config(temp_dir)
        assert config.max_checkpoints == 4
        assert not hasattr(config, "future_key")

    def test_invalid_values_fall_back(self, temp_dir):
        (temp_dir / ".stet").mkdir()
        _config_file(temp_dir).write_text(
            json.dumps({
                "max_checkpoints": 0,            # < 1 invalid
                "max_agent_steps": "lots",       # wrong type
                "checkpoint_policy": "bogus",    # not allowed
                "tool_error_policy": "nope",     # not allowed
                "context_token_budget": -5,      # < 1 invalid
            }),
            encoding="utf-8",
        )
        config = load_config(temp_dir)
        assert config.max_checkpoints == DEFAULT_MAX_CHECKPOINTS
        assert config.max_agent_steps == DEFAULT_MAX_AGENT_STEPS
        assert config.checkpoint_policy == DEFAULT_CHECKPOINT_POLICY
        assert config.tool_error_policy == DEFAULT_TOOL_ERROR_POLICY
        assert config.context_token_budget == DEFAULT_CONTEXT_TOKEN_BUDGET

    def test_corrupt_json_falls_back(self, temp_dir):
        (temp_dir / ".stet").mkdir()
        _config_file(temp_dir).write_text("{not json", encoding="utf-8")
        config = load_config(temp_dir)
        assert config.max_agent_steps == DEFAULT_MAX_AGENT_STEPS


class TestCoerce:
    def test_merge_keeps_valid_drops_invalid(self):
        merged = {**WorkspaceConfig().to_dict(), "max_agent_steps": 9, "checkpoint_policy": "bad"}
        config = coerce_config(merged)
        assert config.max_agent_steps == 9
        assert config.checkpoint_policy == DEFAULT_CHECKPOINT_POLICY
