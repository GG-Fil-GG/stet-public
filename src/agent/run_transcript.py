"""Per-run agent transcript (post-M9c pilot diagnostic).

Writes one JSONL file per agent run under ``.stet/runs/`` so a run can be
reviewed afterwards — crucially even when it is **stopped or crashes before
finalize** (the in-memory step trace and the ``chat_turns`` persistence are only
written on a clean finish). Each event is flushed immediately, so the file always
reflects everything that happened up to the last completed step.

Events (``kind``): ``run_start`` (metadata), ``assistant`` (per step: the model's
text + the tool calls it requested, with arguments), ``tool_result`` (per tool:
outcome + a size-bounded result/error), ``note``, and ``run_end`` (status).

Tool arguments and results are truncated so a huge ``read_file`` result cannot
bloat the transcript — the point is to see *what the agent did*, not to mirror
every byte it read.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .loop import AgentStep
    from .messages import ToolCall

logger = logging.getLogger(__name__)

RUNS_DIRNAME = "runs"
_MAX_STR = 400          # truncate any single string value to this many chars
_MAX_TEXT = 2000        # truncate the assistant's free text to this many chars


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, limit: int = _MAX_STR) -> Any:
    """Truncate long strings; recurse into dicts/lists so results stay bounded."""
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}… <{len(value)} chars>"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value[:20]]
    return value


class RunTranscript:
    """Append-only JSONL writer for one agent run. Never raises to the caller."""

    def __init__(self, path: Path | str, *, meta: dict | None = None) -> None:
        self.path = Path(path)
        self._closed = False
        self._fh = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        except OSError as exc:  # logging must never break a run
            logger.warning("Could not open run transcript %s (%s)", self.path, exc)
            self._closed = True
        self._write("run_start", **(meta or {}))

    # ------------------------------------------------------------------ #

    def _write(self, kind: str, **data: Any) -> None:
        if self._closed or self._fh is None:
            return
        try:
            self._fh.write(json.dumps({"ts": _now_iso(), "kind": kind, **data}, ensure_ascii=False) + "\n")
            self._fh.flush()
        except (OSError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
            logger.warning("Could not write run transcript event (%s)", exc)

    def assistant_step(self, step_no: int, elapsed_s: float, text: str | None,
                       tool_calls: list["ToolCall"]) -> None:
        self._write(
            "assistant",
            step=step_no,
            elapsed_s=round(elapsed_s, 2),
            text=_clip(text or "", _MAX_TEXT),
            tool_calls=[{"name": tc.name, "arguments": _clip(tc.arguments)} for tc in tool_calls],
        )

    def tool_result(self, step_no: int, step: "AgentStep") -> None:
        self._write(
            "tool_result",
            step=step_no,
            tool=step.tool_name,
            arguments=_clip(step.arguments),
            ok=step.error is None,
            result=_clip(step.result) if step.error is None else None,
            error=step.error,
        )

    def note(self, message: str) -> None:
        self._write("note", message=message)

    def end(self, status: str, step_count: int, **extra: Any) -> None:
        self._write("run_end", status=status, step_count=step_count, **extra)
        self.close()

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        self._closed = True


def new_transcript_path(stet_dir: Path | str) -> Path:
    """Return a fresh ``.stet/runs/<timestamp>-<short-id>.jsonl`` path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(stet_dir) / RUNS_DIRNAME / f"{stamp}-{uuid.uuid4().hex[:6]}.jsonl"
