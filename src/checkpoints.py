"""Snapshot-based checkpoints for agent edits (Stage 1, Milestone 2).

A :class:`CheckpointStore` persists point-in-time snapshots of a
:class:`~src.document_model.DocumentModel` as JSON files on disk, and restores
them on demand. It is the *mechanism* behind agent-edit undo.

Scope (M2): mechanism only. *When* a checkpoint is taken (``checkpoint_policy``:
``per_agent_turn`` vs ``per_mutating_tool``) is the agent loop's decision in
**M3**, and reading ``max_checkpoints`` from ``.stet/config.json`` is wired in
**M4**. Here ``max_checkpoints`` is a constructor argument defaulting to the
module constant.

Ordering: each checkpoint carries a monotonically increasing ``sequence`` (next
= max existing + 1), so ``list()`` is reliably newest-first and FIFO pruning is
deterministic even for snapshots taken in the same microsecond.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.document_model import DocumentModel

# Default retention. M4 overrides this from .stet/config.json (max_checkpoints).
DEFAULT_MAX_CHECKPOINTS = 30


@dataclass(frozen=True)
class CheckpointMetadata:
    """Lightweight descriptor for a stored checkpoint (no model payload)."""

    checkpoint_id: str
    created_at: str  # ISO-8601 (UTC)
    label: str
    sequence: int


class CheckpointStore:
    """Save/restore/list/prune document snapshots in a directory.

    Each checkpoint is a single JSON file ``{checkpoint_id}.json`` holding the
    metadata plus ``DocumentModel.to_dict()``.
    """

    def __init__(
        self,
        checkpoints_dir: Path | str,
        max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS,
    ) -> None:
        self.checkpoints_dir = Path(checkpoints_dir)
        self.max_checkpoints = max_checkpoints
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def save(self, model: DocumentModel, label: str = "") -> str:
        """Persist a snapshot of ``model`` and return its checkpoint id.

        FIFO-prunes to ``max_checkpoints`` after writing.
        """
        checkpoint_id = uuid.uuid4().hex
        sequence = self._next_sequence()
        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            label=label,
            sequence=sequence,
        )
        payload = {
            "metadata": {
                "checkpoint_id": metadata.checkpoint_id,
                "created_at": metadata.created_at,
                "label": metadata.label,
                "sequence": metadata.sequence,
            },
            "model": model.to_dict(),
        }
        path = self._path_for(checkpoint_id)
        path.write_text(json.dumps(payload), encoding="utf-8")

        self._prune()
        return checkpoint_id

    def restore(self, checkpoint_id: str) -> DocumentModel:
        """Rebuild the DocumentModel stored under ``checkpoint_id``.

        Raises:
            KeyError: If no checkpoint with that id exists.
        """
        path = self._path_for(checkpoint_id)
        if not path.is_file():
            raise KeyError(f"Unknown checkpoint: {checkpoint_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DocumentModel.from_dict(payload["model"])

    def list(self) -> list[CheckpointMetadata]:
        """Return all checkpoints' metadata, newest-first (descending sequence)."""
        metas: list[CheckpointMetadata] = []
        for path in self.checkpoints_dir.glob("*.json"):
            meta = self._read_metadata(path)
            if meta is not None:
                metas.append(meta)
        metas.sort(key=lambda m: m.sequence, reverse=True)
        return metas

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _path_for(self, checkpoint_id: str) -> Path:
        return self.checkpoints_dir / f"{checkpoint_id}.json"

    def _read_metadata(self, path: Path) -> CheckpointMetadata | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            meta = payload["metadata"]
            return CheckpointMetadata(
                checkpoint_id=meta["checkpoint_id"],
                created_at=meta["created_at"],
                label=meta.get("label", ""),
                sequence=meta["sequence"],
            )
        except (OSError, ValueError, KeyError):
            return None

    def _next_sequence(self) -> int:
        existing = self.list()
        if not existing:
            return 1
        return max(m.sequence for m in existing) + 1

    def _prune(self) -> None:
        """Delete oldest checkpoints beyond ``max_checkpoints`` (FIFO)."""
        metas = self.list()  # newest-first
        for meta in metas[self.max_checkpoints:]:
            self._path_for(meta.checkpoint_id).unlink(missing_ok=True)
