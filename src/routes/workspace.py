"""Workspace JSON API (Stage 1, Milestone 4).

Parallel to the legacy card-UI routers: a JSON-in/JSON-out API for the agentic
workspace. Open a folder, list its (recursive) files, open a docx into an
in-memory session, run the M3 agent loop against it, restore checkpoints, and
save. No HTML/templates — the UI is M5.

``ToolError`` raised by tools/workspace code is translated to JSON by the global
handler registered in ``main.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agent import (
    AgentLLMClient,
    AgentLoop,
    CheckpointPolicy,
    Message,
    ToolErrorPolicy,
    tools,
)
from src.agent.loop import AgentResult
from src.agent.run_transcript import RunTranscript, new_transcript_path
from src.workspace import config as ws_config
from src.workspace import (
    WorkspaceSession,
    get_workspace,
    list_files,
    open_workspace,
    render_document,
    save_config,
)
from src.workspace.chat_log import ChatTurn
from src.workspace.state import close_workspace

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

DEFAULT_PROVIDER = "openai"


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #

class OpenRequest(BaseModel):
    path: str


class DocumentOpenRequest(BaseModel):
    path: str
    force: bool = False  # discard unsaved edits in the currently open document


class DocumentCloseRequest(BaseModel):
    force: bool = False  # discard unsaved edits when closing the active document


class CreateDocumentRequest(BaseModel):
    path: str
    overwrite: bool = False


class AgentRunRequest(BaseModel):
    message: str
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None      # from localStorage; empty → None → falls back to .env
    ollama_url: str | None = None


class ConfirmRequest(BaseModel):
    confirmed: bool


class RestoreRequest(BaseModel):
    checkpoint_id: str


class SaveRequest(BaseModel):
    path: str | None = None
    include_track_changes: bool = True
    overwrite: bool = False


class CloseRequest(BaseModel):
    force: bool = False


class ConfigUpdate(BaseModel):
    max_checkpoints: int | None = None
    max_agent_steps: int | None = None
    checkpoint_policy: str | None = None
    tool_error_policy: str | None = None
    context_token_budget: int | None = None


class ParagraphEditRequest(BaseModel):
    new_text: str
    track_changes: bool = True
    author: str = "Stet"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _session(workspace_id: str) -> WorkspaceSession:
    try:
        return get_workspace(workspace_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Workspace not found")


def _require_document(session: WorkspaceSession) -> None:
    if session.document is None:
        raise HTTPException(status_code=400, detail="No document open in this workspace")


def _build_loop(
    session: WorkspaceSession,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    ollama_url: str | None = None,
    transcript: RunTranscript | None = None,
) -> AgentLoop:
    client = AgentLLMClient(
        provider=provider or DEFAULT_PROVIDER,
        model=model,
        api_key=api_key or None,        # empty string → None → AgentLLMClient falls back to .env
        ollama_url=ollama_url or None,
        context_token_budget=session.config.context_token_budget,
    )
    return AgentLoop(
        client,
        model=session.document,
        workspace_root=session.workspace_root,
        checkpoint_store=session.checkpoint_store,
        max_steps=session.config.max_agent_steps,
        checkpoint_policy=CheckpointPolicy(session.config.checkpoint_policy),
        error_policy=ToolErrorPolicy(session.config.tool_error_policy),
        transcript=transcript,
    )


def _doc_summary(session: WorkspaceSession) -> dict | None:
    model = session.document
    if model is None:
        return None
    return {
        "path": session.document_path,
        "paragraph_count": model.paragraph_count,
        "comment_count": model.comment_count,
        "thread_count": model.thread_count,
        "revision_count": model.revision_count,
        "unsaved_changes": session.unsaved_changes,
    }


def _blocks(session: WorkspaceSession) -> list[dict]:
    """Render the open document into faithful, ordered display blocks (M6a)."""
    model = session.document
    if model is None:
        return []
    return [block.to_dict() for block in render_document(model)]


def _comments(session: WorkspaceSession) -> list[dict]:
    """Comment threads in document order (anchor position), for the side list.

    Same thread shape as the ``list_comments`` tool, plus a document-order sort
    so the side list lines up top-to-bottom with the anchors.
    """
    model = session.document
    if model is None:
        return []
    order = {para.para_id: i for i, para in enumerate(model.body.iter_paragraphs())}
    fallback = len(order) + 1

    rows: list[tuple[tuple[int, int], dict]] = []
    for thread in model.comments.threads.values():
        root = thread.root
        anchor = root.anchor
        referenced_text = ""
        sort_key = (fallback, 0)
        if anchor:
            para = model.get_paragraph(anchor.para_id)
            if para:
                referenced_text = para.raw_text[anchor.start_offset:anchor.end_offset]
            sort_key = (order.get(anchor.para_id, fallback), anchor.start_offset)
        rows.append((
            sort_key,
            {
                "thread_id": thread.thread_id,
                "root_comment_id": root.comment_id,
                "status": "resolved" if thread.is_resolved else "open",
                "author": root.author,
                "referenced_text": referenced_text,
                "comment_count": len(thread.all_comments),
                "comments": [
                    {
                        "comment_id": c.comment_id,
                        "author": c.author,
                        "text": c.text,
                        "is_reply": c.is_reply,
                    }
                    for c in thread.all_comments
                ],
            },
        ))

    rows.sort(key=lambda r: r[0])
    return [row for _key, row in rows]


def _block_for_para_id(session: WorkspaceSession, para_id: str) -> dict | None:
    """Re-render the block whose primary ``para_id`` matches (paragraph or table row)."""
    model = session.document
    if model is None:
        return None
    for block in render_document(model):
        if block.para_id == para_id:
            return block.to_dict()
        if block.cells:
            for cell in block.cells:
                if cell["para_id"] == para_id:
                    return block.to_dict()
    return None


def _steps_to_json(result: AgentResult) -> list[dict]:
    return [
        {
            "tool": s.tool_name,
            "arguments": s.arguments,
            "result": s.result,
            "error": s.error,
        }
        for s in result.steps
    ]


def _pending_to_json(pending) -> dict | None:
    if pending is None:
        return None
    return {
        "tool_name": pending.tool_name,
        "arguments": pending.arguments,
        "message": pending.message,
    }


def _record_chat_turn(
    session: WorkspaceSession,
    result: AgentResult,
    *,
    user_message: str | None = None,
    update_last: bool = False,
) -> None:
    """Append or update the UI turn log (M7)."""
    steps = _steps_to_json(result)
    pending = _pending_to_json(result.pending_confirmation)
    if update_last and session.chat_turns:
        prev = session.chat_turns[-1]
        turn = ChatTurn(
            user_message=prev.user_message,
            final_text=result.final_text,
            status=result.status,
            steps=[*prev.steps, *steps],
            pending_confirmation=pending,
            created_at=prev.created_at,
        )
        session.chat_turns[-1] = turn
    else:
        session.chat_turns.append(
            ChatTurn(
                user_message=user_message or session.current_turn_user_message or "",
                final_text=result.final_text,
                status=result.status,
                steps=steps,
                pending_confirmation=pending,
            )
        )
    session.current_turn_user_message = None


def _finalize(
    session: WorkspaceSession,
    result: AgentResult,
    *,
    user_message: str | None = None,
    update_last: bool = False,
) -> None:
    """Reflect agent-driven saves into doc state, then store conversation + turn log."""
    for step in result.steps:
        if step.tool_name == "export_document" and step.error is None and step.result:
            saved = step.result.get("path")
            if saved and session.document is not None:
                session.document.is_dirty = False
                session.document_path = session._to_rel(Path(saved))

    messages = result.messages
    if messages and messages[0].role == "system":
        messages = messages[1:]  # the loop owns/prepends the system message
    session.conversation = messages
    session.pending_confirmation = result.pending_confirmation
    _record_chat_turn(
        session, result, user_message=user_message, update_last=update_last
    )
    session.touch()
    session.persist()
    session.sync_working_model()  # M9d: durably snapshot agent edits (or clear if saved/none)


def _result_to_json(session: WorkspaceSession, result: AgentResult) -> dict:
    pending = result.pending_confirmation
    return {
        "status": result.status,
        "final_text": result.final_text,
        "steps": _steps_to_json(result),
        "pending_confirmation": _pending_to_json(pending),
        "unsaved_changes": session.unsaved_changes,
        "document": _doc_summary(session),
    }


async def _run_agent_loop(
    session: WorkspaceSession,
    loop: AgentLoop,
    run_fn,
    *,
    user_message: str | None = None,
):
    """Run a sync agent loop in a worker thread with cancel support (M7)."""
    cancel_event = session.begin_agent_run(user_message)
    try:
        return await asyncio.to_thread(run_fn, cancel_event.is_set)
    finally:
        session.end_agent_run()


# --------------------------------------------------------------------------- #
# Workspace lifecycle
# --------------------------------------------------------------------------- #

@router.post("/open")
async def open_ws(body: OpenRequest):
    session = open_workspace(body.path)
    return {
        "workspace_id": session.workspace_id,
        "root": str(session.workspace_root),
        "config": session.config.to_dict(),
        "open_document": session.document_path,
        "files": list_files(session.workspace_root)["files"],
    }


@router.post("/{workspace_id}/close")
async def close_ws(workspace_id: str, body: CloseRequest):
    session = _session(workspace_id)
    if session.unsaved_changes and not body.force:
        raise HTTPException(
            status_code=409,
            detail={"error": "unsaved_changes", "message": "Document has unsaved changes. Pass force=true to close anyway."},
        )
    close_workspace(workspace_id)
    return {"closed": True}


@router.get("/{workspace_id}/files")
async def get_files(workspace_id: str):
    session = _session(workspace_id)
    return list_files(session.workspace_root)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

@router.get("/{workspace_id}/config")
async def get_config(workspace_id: str):
    session = _session(workspace_id)
    return {"config": session.config.to_dict()}


@router.put("/{workspace_id}/config")
async def update_config(workspace_id: str, body: ConfigUpdate):
    session = _session(workspace_id)
    merged = {**session.config.to_dict(), **body.model_dump(exclude_unset=True)}
    new_config = ws_config.coerce_config(merged)
    session.config = new_config
    session.checkpoint_store.max_checkpoints = new_config.max_checkpoints
    save_config(session.workspace_root, new_config)
    return {"config": new_config.to_dict()}


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #

@router.post("/{workspace_id}/document/open")
async def open_document(workspace_id: str, body: DocumentOpenRequest):
    session = _session(workspace_id)
    # Opening re-parses from disk, discarding any unsaved edits in the current
    # document (incl. switching to/re-opening the same file). Guard like /close.
    if session.unsaved_changes and not body.force:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "unsaved_changes",
                "message": (
                    f"'{session.document_path}' has unsaved changes that will be lost. "
                    "Pass force=true to open anyway."
                ),
            },
        )
    session.open_document(body.path)
    return {"document": _doc_summary(session)}


@router.post("/{workspace_id}/document/close")
async def close_document(workspace_id: str, body: DocumentCloseRequest):
    session = _session(workspace_id)
    if session.document is None:
        return {"closed": True}
    if session.unsaved_changes and not body.force:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "unsaved_changes",
                "message": (
                    f"'{session.document_path}' has unsaved changes that will be lost. "
                    "Pass force=true to close anyway."
                ),
            },
        )
    session.close_document()
    return {"closed": True}


@router.get("/{workspace_id}/document")
async def get_document(workspace_id: str):
    session = _session(workspace_id)
    _require_document(session)
    return {
        "document": _doc_summary(session),
        "blocks": _blocks(session),
        "comments": _comments(session),
    }


@router.patch("/{workspace_id}/document/paragraph/{para_id}")
async def edit_document_paragraph(
    workspace_id: str, para_id: str, body: ParagraphEditRequest
):
    """Apply a manual paragraph edit with a pre-edit checkpoint (M6b)."""
    session = _session(workspace_id)
    _require_document(session)
    if session.document.get_paragraph(para_id) is None:
        raise HTTPException(status_code=404, detail=f"Paragraph not found: {para_id}")

    session.checkpoint_store.save(
        session.document, label=f"before manual edit {para_id}"
    )
    tools.edit_paragraph(
        session.document,
        para_id,
        body.new_text,
        track_changes=body.track_changes,
        author=body.author,
    )
    session.touch()
    session.persist()
    session.persist_working_model()  # M9d: manual edits are durable too

    block = _block_for_para_id(session, para_id)
    if block is None:
        raise HTTPException(status_code=500, detail="Edited paragraph could not be rendered")

    return {
        "document": _doc_summary(session),
        "block": block,
        "unsaved_changes": session.unsaved_changes,
    }


@router.post("/{workspace_id}/document/create")
async def create_document(workspace_id: str, body: CreateDocumentRequest):
    session = _session(workspace_id)
    result = tools.create_document(
        body.path, workspace_root=session.workspace_root, overwrite=body.overwrite
    )
    return {"path": result["path"], "created": result["created"]}


@router.post("/{workspace_id}/save")
async def save_document(workspace_id: str, body: SaveRequest):
    session = _session(workspace_id)
    _require_document(session)
    original_rel = session.document_path
    target_rel = body.path or original_rel
    if not target_rel:
        raise HTTPException(status_code=400, detail="No save path and no open document")
    result = tools.export_document(
        session.document,
        target_rel,
        workspace_root=session.workspace_root,
        include_track_changes=body.include_track_changes,
        overwrite=body.overwrite,
    )
    session.document.is_dirty = False
    session.set_active_document(session.document, Path(result["path"]))  # Save As → switch
    # M9d: a same-path save wrote the edits into the file → its snapshot is now
    # redundant. A save-a-copy leaves the original's snapshot intact.
    if session.document_path == original_rel:
        session.clear_working_model(original_rel)
    return {
        "path": result["path"],
        "document": _doc_summary(session),
        "unsaved_changes": session.unsaved_changes,
    }


# --------------------------------------------------------------------------- #
# Agent chat (M7)
# --------------------------------------------------------------------------- #

@router.get("/{workspace_id}/chat")
async def get_chat(workspace_id: str):
    session = _session(workspace_id)
    pending = session.pending_confirmation
    return {
        "turns": [t.to_dict() for t in session.chat_turns],
        "pending_confirmation": _pending_to_json(pending),
    }


@router.post("/{workspace_id}/chat/clear")
async def clear_chat(workspace_id: str):
    session = _session(workspace_id)
    if session.run_in_progress:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "conflict",
                "message": "Cannot clear chat while an agent run is in progress.",
            },
        )
    session.clear_chat()
    session.touch()
    session.persist()
    return {"cleared": True}


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #

@router.post("/{workspace_id}/agent/run")
async def agent_run(workspace_id: str, body: AgentRunRequest):
    session = _session(workspace_id)
    _require_document(session)
    transcript = RunTranscript(
        new_transcript_path(session.stet_dir),
        meta={
            "kind_of_run": "run",
            "provider": body.provider or DEFAULT_PROVIDER,
            "model": body.model,
            "document": session.document_path,
            "max_steps": session.config.max_agent_steps,
            "message": body.message,
        },
    )
    loop = _build_loop(session, body.provider, body.model, body.api_key, body.ollama_url,
                       transcript=transcript)
    try:
        result = await _run_agent_loop(
            session,
            loop,
            lambda cancel_check: loop.run(
                body.message,
                history=session.conversation,
                cancel_check=cancel_check,
                live_steps=session.run_live_steps,
            ),
            user_message=body.message,
        )
    except Exception as exc:  # transcript must capture crashes (e.g. APIConnectionError)
        transcript.end("error", len(session.run_live_steps), error=repr(exc))
        raise
    transcript.end(result.status, len(result.steps))
    _finalize(session, result, user_message=body.message)
    return _result_to_json(session, result)


@router.post("/{workspace_id}/agent/confirm")
async def agent_confirm(workspace_id: str, body: ConfirmRequest):
    session = _session(workspace_id)
    pending = session.pending_confirmation
    if pending is None:
        raise HTTPException(status_code=400, detail="No pending confirmation")
    transcript = RunTranscript(
        new_transcript_path(session.stet_dir),
        meta={
            "kind_of_run": "confirm",
            "document": session.document_path,
            "confirmed": body.confirmed,
            "pending_tool": pending.tool_name,
        },
    )
    loop = _build_loop(session, transcript=transcript)
    history = [Message.system(loop.system_prompt), *session.conversation]
    try:
        result = await _run_agent_loop(
            session,
            loop,
            lambda cancel_check: loop.resume(
                pending,
                confirmed=body.confirmed,
                history=history,
                cancel_check=cancel_check,
                live_steps=session.run_live_steps,
            ),
        )
    except Exception as exc:  # transcript must capture crashes
        transcript.end("error", len(session.run_live_steps), error=repr(exc))
        raise
    transcript.end(result.status, len(result.steps))
    _finalize(session, result, update_last=True)
    return _result_to_json(session, result)


@router.post("/{workspace_id}/agent/cancel")
async def agent_cancel(workspace_id: str):
    session = _session(workspace_id)
    if not session.request_cancel_agent_run():
        raise HTTPException(
            status_code=409,
            detail={
                "error": "conflict",
                "message": "No agent run is in progress.",
            },
        )
    return {"cancelled": True}


@router.get("/{workspace_id}/agent/progress")
async def agent_progress(workspace_id: str):
    """Live snapshot of the in-flight agent turn (M9c-prep).

    Cheap to poll: returns only step names + ok flags, not full arguments or
    results (those arrive with the run response / chat log).
    """
    session = _session(workspace_id)
    steps = list(session.run_live_steps)  # snapshot; the worker thread appends
    return {
        "running": session.run_in_progress,
        "step_count": len(steps),
        "steps": [
            {"tool": s.tool_name, "ok": s.error is None}
            for s in steps
        ],
    }


# --------------------------------------------------------------------------- #
# Checkpoints
# --------------------------------------------------------------------------- #

@router.get("/{workspace_id}/checkpoints")
async def list_checkpoints(workspace_id: str):
    session = _session(workspace_id)
    return {
        "checkpoints": [
            {"checkpoint_id": m.checkpoint_id, "created_at": m.created_at, "label": m.label}
            for m in session.checkpoint_store.list()
        ]
    }


@router.post("/{workspace_id}/checkpoint/restore")
async def restore_checkpoint(workspace_id: str, body: RestoreRequest):
    session = _session(workspace_id)
    try:
        model = session.checkpoint_store.restore(body.checkpoint_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    session.document = model
    session.touch()
    session.persist()
    session.sync_working_model()  # M9d: keep the snapshot in step with restored state
    return {"restored": True, "document": _doc_summary(session)}
