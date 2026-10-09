"""Workspace session state + registry (Stage 1, Milestone 4).

A ``WorkspaceSession`` is the agentic-workspace analogue of the legacy upload
``sessions`` dict (``src/routes/state.py``) — held in memory, keyed by an opaque
``workspace_id``, and the long-term replacement for it (the card UI is not
migrated here). Multiple sessions can be open at once (one agent per workspace).

Persistence: only the open-document pointer + conversation are written to
``.stet/workspace.json`` (the loop owns the system prompt, so it is not stored).
The in-memory ``DocumentModel`` (with unsaved edits) is intentionally *not*
durable across restarts — re-opening yields the pristine file; checkpoints cover
within-session undo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.agent.errors import ToolError
from src.agent.loop import AgentStep, PendingConfirmation
from src.agent.messages import Message
from src.checkpoints import CheckpointStore
from src.document_model import DocumentModel, parse_docx
from .chat_log import ChatTurn
from .config import WorkspaceConfig, load_config
from .folder import CHECKPOINTS_DIRNAME, RESERVED_DIR, ensure_stet_dir, resolve_path

logger = logging.getLogger(__name__)

WORKSPACE_FILENAME = "workspace.json"
WORKSPACE_SCHEMA_VERSION = 1

# Working-model persistence (M9d): unsaved in-memory edits are snapshotted under
# .stet/working/ so they survive a re-parse (file-tree click, folder re-open,
# browser reload, restart). One snapshot per open document, keyed by a hash of
# its workspace-relative path. Restored only when the source file is unchanged.
WORKING_DIRNAME = "working"
WORKING_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkspaceSession:
    """In-memory state for one open workspace folder."""

    workspace_id: str
    workspace_root: Path
    config: WorkspaceConfig
    checkpoint_store: CheckpointStore
    document: DocumentModel | None = None
    document_path: str | None = None  # workspace-relative POSIX, or None
    conversation: list[Message] = field(default_factory=list)  # no system message
    chat_turns: list[ChatTurn] = field(default_factory=list)
    pending_confirmation: PendingConfirmation | None = None  # transient
    run_in_progress: bool = False
    run_cancel_event: threading.Event | None = None
    run_live_steps: list[AgentStep] = field(default_factory=list)  # current turn, mid-run (M9c-prep)
    current_turn_user_message: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #

    @property
    def stet_dir(self) -> Path:
        return self.workspace_root / RESERVED_DIR

    @property
    def workspace_json(self) -> Path:
        return self.stet_dir / WORKSPACE_FILENAME

    # ------------------------------------------------------------------ #
    # Document
    # ------------------------------------------------------------------ #

    @property
    def unsaved_changes(self) -> bool:
        return bool(self.document is not None and self.document.is_dirty)

    def _to_rel(self, target: Path) -> str:
        return target.resolve().relative_to(self.workspace_root.resolve()).as_posix()

    def open_document(self, rel_path: str) -> None:
        """Make a workspace docx the active document.

        Restores unsaved edits from a working snapshot (M9d) when one exists for
        this path and the source file is unchanged; otherwise parses the pristine
        file from disk. A stale/corrupt snapshot can never block opening.
        """
        target = resolve_path(self.workspace_root, rel_path)
        if not target.is_file():
            raise ToolError("not_found", f"Document not found: {rel_path}")
        rel = self._to_rel(target)

        restored = self._load_working_model(rel, target)
        self.document = restored if restored is not None else parse_docx(target)
        self.document_path = rel
        self.touch()
        self.persist()

    def set_active_document(self, model: DocumentModel, abs_path: Path) -> None:
        """Switch the active document to ``model`` saved at ``abs_path`` (Save As)."""
        self.document = model
        self.document_path = self._to_rel(abs_path)
        self.touch()
        self.persist()

    def close_document(self) -> None:
        """Clear the active document (the workspace stays open)."""
        self.document = None
        self.document_path = None
        self.touch()
        self.persist()

    # ------------------------------------------------------------------ #
    # Working-model persistence (M9d) — unsaved edits survive a re-parse
    # ------------------------------------------------------------------ #

    @property
    def working_dir(self) -> Path:
        return self.stet_dir / WORKING_DIRNAME

    def _working_path(self, rel_path: str) -> Path:
        digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:16]
        return self.working_dir / f"{digest}.json"

    @staticmethod
    def _source_mtime(target: Path) -> float | None:
        try:
            return target.stat().st_mtime
        except OSError:
            return None

    def persist_working_model(self) -> None:
        """Snapshot the active document's in-memory edits to ``.stet/working/``.

        No-op when there is no dirty document. Called after any mutation so an
        unforced re-open (or a fresh session) recovers the edited state.
        """
        if self.document is None or self.document_path is None:
            return
        if not self.document.is_dirty:
            return
        target = resolve_path(self.workspace_root, self.document_path)
        payload = {
            "schema_version": WORKING_SCHEMA_VERSION,
            "document_path": self.document_path,
            "source_mtime": self._source_mtime(target),
            "saved_at": _now(),
            "model": self.document.to_dict(),
        }
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self._working_path(self.document_path).write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def clear_working_model(self, rel_path: str | None = None) -> None:
        """Delete the working snapshot for ``rel_path`` (default: active document)."""
        rel = rel_path or self.document_path
        if not rel:
            return
        self._working_path(rel).unlink(missing_ok=True)

    def sync_working_model(self) -> None:
        """Persist the snapshot if the document is dirty, else clear it."""
        if self.document is not None and self.document.is_dirty:
            self.persist_working_model()
        else:
            self.clear_working_model()

    def _load_working_model(self, rel_path: str, target: Path):
        """Return the snapshotted model for ``rel_path`` if valid, else ``None``.

        Valid means: snapshot exists, parses, and its recorded source mtime still
        matches the file on disk (the underlying file has not changed under us).
        """
        path = self._working_path(rel_path)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != WORKING_SCHEMA_VERSION:
                return None
            if raw.get("source_mtime") != self._source_mtime(target):
                logger.info("Working snapshot for %s is stale (source changed); using disk", rel_path)
                return None
            model = DocumentModel.from_dict(raw["model"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Could not load working snapshot %s (%s); using disk", path, exc)
            return None
        logger.info("Restored unsaved edits for %s from working snapshot", rel_path)
        return model

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def touch(self) -> None:
        self.updated_at = _now()

    def to_state_dict(self) -> dict:
        return {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "open_document": self.document_path,
            "conversation": [m.to_dict() for m in self.conversation],
            "chat_turns": [t.to_dict() for t in self.chat_turns],
            "updated_at": self.updated_at,
        }

    def begin_agent_run(self, user_message: str | None = None) -> threading.Event:
        """Mark an agent turn in flight and return its cancel event."""
        if self.run_in_progress:
            raise ToolError("conflict", "An agent run is already in progress.")
        self.run_in_progress = True
        self.run_cancel_event = threading.Event()
        self.run_live_steps = []  # fresh list per turn; the loop appends to it
        if user_message is not None:
            self.current_turn_user_message = user_message
        return self.run_cancel_event

    def end_agent_run(self) -> None:
        self.run_in_progress = False
        self.run_cancel_event = None

    def request_cancel_agent_run(self) -> bool:
        if not self.run_in_progress or self.run_cancel_event is None:
            return False
        self.run_cancel_event.set()
        return True

    def clear_chat(self) -> None:
        self.conversation = []
        self.chat_turns = []
        self.pending_confirmation = None
        self.current_turn_user_message = None

    def persist(self) -> None:
        ensure_stet_dir(self.workspace_root)
        self.workspace_json.write_text(
            json.dumps(self.to_state_dict(), indent=2), encoding="utf-8"
        )


# --------------------------------------------------------------------------- #
# In-memory registry (parallel to routes.state.sessions)
# --------------------------------------------------------------------------- #

_workspaces: dict[str, WorkspaceSession] = {}


def open_workspace(path: str | Path) -> WorkspaceSession:
    """Open (or re-open) a workspace folder and register a session.

    Creates ``.stet/`` + config on first use, restores ``workspace.json`` if
    present (auto-reopening the last document), and returns the session.
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ToolError("not_found", f"Workspace folder not found: {root}")

    ensure_stet_dir(root)
    config = load_config(root)
    store = CheckpointStore(
        root / RESERVED_DIR / CHECKPOINTS_DIRNAME,
        max_checkpoints=config.max_checkpoints,
    )
    session = WorkspaceSession(
        workspace_id=uuid.uuid4().hex,
        workspace_root=root,
        config=config,
        checkpoint_store=store,
    )
    _restore_state(session)
    _workspaces[session.workspace_id] = session
    return session


def get_workspace(workspace_id: str) -> WorkspaceSession:
    """Return a registered session or raise ``KeyError``."""
    session = _workspaces.get(workspace_id)
    if session is None:
        raise KeyError(workspace_id)
    return session


def list_workspaces() -> list[WorkspaceSession]:
    return list(_workspaces.values())


def close_workspace(workspace_id: str) -> None:
    _workspaces.pop(workspace_id, None)


def _restore_state(session: WorkspaceSession) -> None:
    """Load conversation + auto-reopen the last document from workspace.json."""
    path = session.workspace_json
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s (%s); starting fresh", path, exc)
        return

    session.conversation = [Message.from_dict(m) for m in raw.get("conversation", [])]
    session.chat_turns = [ChatTurn.from_dict(t) for t in raw.get("chat_turns", [])]

    open_doc = raw.get("open_document")
    if open_doc:
        target = session.workspace_root / open_doc
        if target.is_file():
            try:
                session.open_document(open_doc)
            except Exception as exc:  # noqa: BLE001 - never fail open on reopen
                logger.warning("Could not auto-reopen %s (%s)", open_doc, exc)
        else:
            logger.info("Last open document %s no longer exists; skipping", open_doc)
