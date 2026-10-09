# Stage 1 — Milestone 4 Spec: Workspace backend

**Status:** Approved & Implemented 2026-05-30 — see [report](stage1_M4_report.md)
**Plan reference:** [Milestone 4](../stage1_implementation_plan.md#milestone-4--workspace-backend)

---

## 1. Goal

Make "point Stet at a folder" real through a **JSON API**: open a workspace folder, list its files, open a docx into an in-memory workspace session, run the M3 agent loop against it, restore checkpoints, and export — all without touching the user's files on disk until an explicit save/export. No UI yet (that is M5); this milestone is exercised entirely through `TestClient`.

This is the milestone that finally **defines the `.stet/workspace.json` schema** (M0 fixed only its location) and introduces the **code constants** that hold the config defaults (M0 fixed the values/names only).

---

## 2. Design constraints (from the codebase)

- **Two session systems, side by side.** The legacy upload `sessions` dict (`src/routes/state.py`) powers the card UI and stays untouched. M4 adds a **parallel** workspace-session system. Per [Resolved decisions §7](../stage1_implementation_plan.md#7-workspace-sessions-vs-upload-sessions), workspace sessions are the long-term replacement, but M4 does **not** migrate the card UI.
- **DocumentModel is the source of truth.** Opening a docx parses it with `parse_docx` into an in-memory `DocumentModel`; edits live in memory. The file on disk is unchanged until `export`/`save` targets it (mirrors the M1/M2 tool contract).
- **The agent loop is ready and stateless.** M3's `AgentLoop.run(user_message, history)` returns the full message list + an `AgentResult`. M4 owns the conversation: it stores `history`, feeds it back in, and persists it. M4 also owns the **checkpoint policy wiring** (constructor args) and reads them from config.
- **Guarded writers already resolve relative paths.** `create_document` / `export_document` get `workspace_root` injected and resolve relative paths against it with containment checks (`_guard_write_target`). The gap M4 must close is path resolution for the **read** tools (`read_document`, `read_file`), which take only `path`.
- **Route + test conventions exist.** Routers are `APIRouter` modules under `src/routes/`, mounted in `main.py`. JSON-route tests mirror `tests/test_routes.py` (`TestClient`, JSON-shape assertions, synthetic fixtures, no network/LLM). The 0-warning baseline holds.
- **Provider/config plumbing exists.** `src/llm_config.py` supplies provider/model/url defaults; `AgentLLMClient` consumes them. M4 builds the client per workspace from config + request.

---

## 3. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `src/workspace/__init__.py` | Package exports. |
| `src/workspace/config.py` | `WorkspaceConfig` dataclass + default constants + `load_config` / `save_config` (reads/writes `.stet/config.json`, fills missing keys, ignores unknown). |
| `src/workspace/folder.py` | Folder operations: `.stet/` creation, file-tree listing (reuses `tools.list_workspace_files`), and `resolve_path` (workspace-relative → absolute, containment-checked). |
| `src/workspace/state.py` | `WorkspaceSession` + in-memory registry (`open_workspace`, `get_workspace`, …); `workspace.json` load/persist. |
| `src/routes/workspace.py` | The JSON API router (`/api/workspace/...`). |
| `tests/test_workspace_config.py` | Config load/save/defaults/forward-compat. |
| `tests/test_workspace_state.py` | Session lifecycle + `workspace.json` round-trip + conversation persistence. |
| `tests/test_workspace_api.py` | JSON route smoke tests (mirror `tests/test_routes.py`). |

**Modify:**

| File | Change |
|------|--------|
| `main.py` | Mount the workspace router. |
| `src/agent/messages.py` | Add `Message.to_dict()` / `Message.from_dict()` (+ `ToolCall`) for conversation persistence. |
| `src/agent/registry.py` | Add a declarative `path_args` to `ToolSpec` so the loop can resolve filesystem-path arguments against the workspace root *(pending Open question 4)*. |
| `src/agent/loop.py` | Resolve `path_args` against `workspace_root` before calling read-tool handlers *(pending Open question 4)*. |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, this spec | Glossary / log / status / spec-status updates (in the report step). |

---

## 4. Public API surface

### 4.1 Workspace configuration (`src/workspace/config.py`)

```python
DEFAULT_CONFIG_VERSION = 1
DEFAULT_MAX_CHECKPOINTS = 30          # reuse src/checkpoints.DEFAULT_MAX_CHECKPOINTS
DEFAULT_MAX_AGENT_STEPS = 20          # reuse src/agent/loop.DEFAULT_MAX_STEPS
DEFAULT_CHECKPOINT_POLICY = "per_agent_turn"
DEFAULT_TOOL_ERROR_POLICY = "report_and_skip"   # NEW key (see Open question 5)

@dataclass
class WorkspaceConfig:
    config_version: int = DEFAULT_CONFIG_VERSION
    max_checkpoints: int = DEFAULT_MAX_CHECKPOINTS
    max_agent_steps: int = DEFAULT_MAX_AGENT_STEPS
    checkpoint_policy: str = DEFAULT_CHECKPOINT_POLICY
    tool_error_policy: str = DEFAULT_TOOL_ERROR_POLICY

    def to_dict(self) -> dict: ...

def load_config(workspace_root: Path) -> WorkspaceConfig:
    """Read .stet/config.json. Missing file → defaults (and write it).
    Missing keys → code defaults. Unknown keys → ignored (forward-compatible).
    Invalid values → ToolError('invalid_config') (or clamp; see Open question 6)."""

def save_config(workspace_root: Path, config: WorkspaceConfig) -> None: ...
```

Validation: `max_checkpoints ≥ 1`, `max_agent_steps ≥ 1`, `checkpoint_policy ∈ {per_agent_turn, per_mutating_tool}`, `tool_error_policy ∈ {report_and_skip, stop_and_ask}`.

### 4.2 Folder operations (`src/workspace/folder.py`)

```python
def ensure_stet_dir(workspace_root: Path) -> Path:
    """Create .stet/ and .stet/checkpoints/ if absent; return the .stet path."""

def list_files(workspace_root: Path) -> dict:
    """Workspace file tree (delegates to tools.list_workspace_files; excludes .stet/)."""

def resolve_path(workspace_root: Path, path: str) -> Path:
    """Relative → resolved against workspace_root; absolute used as-is.
    Must stay inside workspace_root, else ToolError('outside_workspace')."""
```

### 4.3 Workspace session (`src/workspace/state.py`)

```python
@dataclass
class WorkspaceSession:
    workspace_id: str           # opaque id (e.g. uuid4 hex)
    workspace_root: Path
    config: WorkspaceConfig
    checkpoint_store: CheckpointStore
    document: DocumentModel | None = None
    document_path: str | None = None        # workspace-relative
    conversation: list[Message] = field(default_factory=list)   # no system message
    pending_confirmation: PendingConfirmation | None = None      # transient (not persisted)
    created_at: str = ...                    # ISO-8601 UTC
    updated_at: str = ...

    @property
    def unsaved_changes(self) -> bool: ...                # bool(document and document.is_dirty)
    def open_document(self, rel_path: str) -> None: ...   # parse_docx into memory
    def to_state_dict(self) -> dict: ...                  # for workspace.json
    def persist(self) -> None: ...                        # write .stet/workspace.json

# In-memory registry (parallel to routes.state.sessions)
def open_workspace(path: str) -> WorkspaceSession: ...     # ensure .stet/, load config + workspace.json
def get_workspace(workspace_id: str) -> WorkspaceSession:  # 404 if unknown
def list_workspaces() -> list[WorkspaceSession]: ...
def close_workspace(workspace_id: str) -> None: ...
```

### 4.4 `.stet/workspace.json` schema

```json
{
  "schema_version": 1,
  "open_document": "manuscript.docx",
  "conversation": [
    {"role": "user", "content": "address the open comments"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "list_comments", "arguments": {"comment_filter": "open"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "list_comments", "content": "{...}"}
  ],
  "updated_at": "2026-05-30T23:00:00Z"
}
```

- `open_document` is workspace-relative (portable) or `null`.
- `conversation` is the M3 message list (loop owns the system prompt, so it is **not** stored).
- The in-memory `DocumentModel` is **not** persisted here — unsaved edits live in checkpoints; persistence of in-progress edits across restarts is out of scope (see Open question 3).

### 4.5 JSON API (`src/routes/workspace.py`)

All under `/api/workspace`. JSON in, JSON out. Errors map `ToolError` / `HTTPException` to `{ "error": code, "message": ... }` with a suitable status.

| Method | Path | Body / params | Returns |
|--------|------|---------------|---------|
| `POST` | `/api/workspace/open` | `{path}` | `{workspace_id, root, config, open_document, files}` |
| `GET` | `/api/workspace/{id}/files` | — | file tree |
| `GET` | `/api/workspace/{id}/config` | — | config |
| `PUT` | `/api/workspace/{id}/config` | partial config | updated config |
| `POST` | `/api/workspace/{id}/document/open` | `{path}` | document summary |
| `GET` | `/api/workspace/{id}/document` | — | summary + paragraph list |
| `POST` | `/api/workspace/{id}/document/create` | `{path, overwrite}` | `{path, created}` |
| `POST` | `/api/workspace/{id}/agent/run` | `{message, provider?, model?}` | `{status, final_text, steps, pending_confirmation?, unsaved_changes, document?}` |
| `POST` | `/api/workspace/{id}/agent/confirm` | `{confirmed}` | resumed run result |
| `GET` | `/api/workspace/{id}/checkpoints` | — | `{checkpoints:[{checkpoint_id, created_at, label}]}` |
| `POST` | `/api/workspace/{id}/checkpoint/restore` | `{checkpoint_id}` | `{restored, document}` |
| `POST` | `/api/workspace/{id}/save` | `{path?, include_track_changes, overwrite}` | `{path, document, unsaved_changes}` |
| `POST` | `/api/workspace/{id}/close` | `{force}` | `{closed}` (409 `unsaved_changes` unless `force`) |

**Conversation ownership.** The loop owns the system prompt, so `session.conversation` stores the message list **without** the leading system message. `agent/run` passes it as `history`; the returned `messages` are stored back with the leading system message stripped. `agent/confirm` reconstructs `[system] + conversation` before calling `loop.resume(...)`.

**Agent run flow.** `agent/run` builds an `AgentLLMClient` (from config + request provider/model, default provider `openai`) and an `AgentLoop` wired with the session's `document`, `workspace_root`, `checkpoint_store`, and config-derived `max_steps` / `checkpoint_policy` / `tool_error_policy`. It calls `loop.run(message, history=session.conversation)`, stores the returned messages, persists, and returns the result. If `status == "awaiting_confirmation"`, the `pending_confirmation` is stashed on the session; `agent/confirm` calls `loop.resume(...)` and finalizes the same way.

**Save / save-as-copy (Q7).** There is no separate "export" — `save` serializes the current in-memory model (via `tools.export_document`) to a target path:
- **Save in place:** `path` omitted → defaults to the open document's own path. It exists, so the overwrite guard fires (`409 overwrite_requires_confirmation`); the UI/agent re-calls with `overwrite=true`.
- **Save a copy:** `path` is a *new* path (e.g. `Editorial/second_draft/file_2.docx`) → written directly (no confirmation needed; the original is never touched).

After any successful save, the model is marked clean (`is_dirty=False`) and **the active document switches to the saved path** (Word-like "Save As"; covers save-as-copy). Creating a brand-new blank doc remains the separate `document/create` tool/endpoint.

---

## 5. Tests to write

- `tests/test_workspace_config.py`: defaults when no file; round-trip save/load; missing keys fall back; unknown keys ignored; invalid values rejected/clamped (per Open question 6).
- `tests/test_workspace_state.py`: `open_workspace` creates `.stet/` + `config.json`; open a docx → `DocumentModel` in memory, disk file untouched; conversation persists to `workspace.json` and reloads; `Message` to_dict/from_dict round-trip (incl. tool calls).
- `tests/test_workspace_api.py` (mirrors `test_routes.py`, uses `client` + synthetic fixtures, **mock the LLM** — patch `AgentLLMClient.complete` with a scripted tool-call sequence):
  - open folder → list files → open docx → `agent/run` (mocked) returns a change summary; **the source docx on disk is unchanged**.
  - `agent/run` that triggers an overwrite → `awaiting_confirmation`; `agent/confirm {confirmed:true}` completes and writes.
  - checkpoint list + restore rolls back an edit.
  - export writes to an explicit in-workspace path; outside-workspace path → error.
  - path resolution: a read tool called with a workspace-relative path resolves correctly (per Open question 4).
- **Optional** live `agent/run` test gated on `OPENAI_API_KEY` (skipped by default).

**Baseline:** full suite green, **0 warnings**; legacy card UI (`/`, routes, workflow) untouched.

---

## 6. Out of scope for this milestone

- Any UI / templates / three-panel layout — **M5**.
- Native folder picker — **M5**.
- Streaming agent responses (run is synchronous/blocking in Stage 1).
- Persisting in-progress (unsaved) `DocumentModel` edits across server restarts (only conversation + open-document pointer persist; see Open question 3).
- Migrating the card UI off the legacy `sessions` dict.
- Multi-user / auth / concurrency hardening — **M9**.
- New file-format readers (RTF/PPTX) — **M8**.

---

## 7. Resolved decisions

All resolved with the project owner on 2026-05-30.

1. **Multiple workspaces, keyed by `workspace_id`.** The registry can hold more than one open project folder at once (always **one agent per workspace**; this is purely backend bookkeeping so project-switching is free later). The M5 UI uses one at a time. **Subfolder navigation is the normal case**, not a special feature: a workspace is the one granted project folder, and its arbitrary nested subfolders (e.g. `Resources/`, `Editorial/`, `References/`, each with per-draft subfolders) are already walked recursively by `list_workspace_files` and reachable by `resolve_path` at any depth within the root.

2. **Auto-reopen the last document.** On `/open`, if `workspace.json` records an `open_document`, parse it back into memory; skip silently if the file no longer exists.

3. **Pristine re-open across restarts; warn before closing unsaved work.** Only conversation + open-document pointer persist; the in-memory model (with unsaved edits) is not durable across restarts (checkpoints cover within-session states). The backend exposes `unsaved_changes` (`DocumentModel.is_dirty`) in document/run responses, and `/close` returns `409 unsaved_changes` unless `force=true`. The actual "you have unsaved changes" prompt is the **M5 UI's** job (as in the card UI today).

4. **Path resolution via `path_args`, reads contained to the workspace.** Add a declarative `path_args: tuple[str,...]` to `ToolSpec` (e.g. `("path",)` for `read_document` / `read_file`). The loop resolves those against `workspace_root` (and enforces containment) before calling the handler — same pattern as `mutating`. Writers (`create_document` / `export_document`) already resolve + contain internally, so they are not given `path_args`.

5. **New config key `tool_error_policy`** (`report_and_skip` default; `stop_and_ask` allowed), recorded in the glossary under M4.

6. **Invalid config values fall back to the per-key default** and continue (a hand-edited config never bricks the workspace); the substitution is logged. Unknown keys are ignored.

7. **"Save" replaces "export"; save-as-copy switches the active document.** One `save` operation serializes the current model to a target path. Save in place (no `path`) → the open document's own path → overwrite guard fires → confirm with `overwrite=true`. Save a copy (new `path`) → written directly, original untouched. After any save, the model is marked clean and **the active document switches to the saved path** (Word-like "Save As"). "Create a new document" remains the separate blank-doc operation. This is the *same* `export_document` mechanism with a different destination — no new serialization work.
