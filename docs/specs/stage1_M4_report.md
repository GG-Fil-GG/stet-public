# Stage 1 — Milestone 4 Report: Workspace backend

**Status:** Complete
**Spec:** [`stage1_M4_spec.md`](stage1_M4_spec.md) (approved & implemented 2026-05-30)

---

## 1. What was done

"Point Stet at a folder" is now real over a **JSON API**, exercised end-to-end through `TestClient` (no UI):

- **Workspace config** — `src/workspace/config.py`: `WorkspaceConfig` + `load_config`/`save_config`/`coerce_config`. This is the code source of truth for the Stage 1 defaults (M0 fixed the values). Resilient: missing file → defaults (written), missing key → default, **invalid value → per-key default** (logged), unknown key → ignored. Adds the new `tool_error_policy` key.
- **Folder ops** — `src/workspace/folder.py`: `ensure_stet_dir`, recursive `list_files` (delegates to the M1 tool; subfolders are the normal case), and `resolve_path` (contained, delegates to the shared `tools.resolve_in_workspace`).
- **Workspace session** — `src/workspace/state.py`: `WorkspaceSession` + an in-memory registry keyed by `workspace_id` (parallel to the untouched legacy `sessions` dict, holds multiple open folders). Defines the `.stet/workspace.json` schema and persists `{schema_version, open_document, conversation, updated_at}`. Auto-reopens the last document on `open_workspace`.
- **JSON API** — `src/routes/workspace.py` mounted in `main.py`, plus a global `ToolError → JSON` exception handler. Endpoints for open/close/files/config/document open+create+get/save/agent run+confirm/checkpoints list+restore.
- **Agent wiring** — `agent/run` builds an `AgentLLMClient` + `AgentLoop` from the session (config-derived `max_steps`/`checkpoint_policy`/`tool_error_policy`), runs against the in-memory model, persists the conversation (system message stripped), and returns steps + summary. `agent/confirm` resumes a paused overwrite.
- **Save = export** — one `save` op; in-place save hits the overwrite guard, save-as-copy writes a new file and **switches the active document** to it (Word-like). Agent-driven saves get the same treatment.
- **Path resolution** — new declarative `ToolSpec.path_args` (`("path",)` on `read_document`/`read_file`); the loop resolves them against the workspace root, contained, inside the tool-call error boundary.
- **Persistence helpers** — `Message.to_dict()/from_dict()` (+ `ToolCall`).

Commit: _see the M4 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

**Created:**

| File | Purpose |
|------|---------|
| `src/workspace/__init__.py` | Package exports. |
| `src/workspace/config.py` | `WorkspaceConfig` + load/save/coerce + default constants. |
| `src/workspace/folder.py` | `.stet/` creation, file tree, contained path resolution. |
| `src/workspace/state.py` | `WorkspaceSession` + registry + `workspace.json` persistence. |
| `src/routes/workspace.py` | JSON API router. |
| `tests/test_workspace_config.py` | 7 tests — defaults / round-trip / resilience / coerce. |
| `tests/test_workspace_state.py` | 9 tests — session lifecycle, disk-untouched, persistence round-trip, message serde. |
| `tests/test_workspace_api.py` | 18 tests — JSON routes (mocked LLM): lifecycle, config, agent run, overwrite confirm, save/save-as-copy, checkpoints, close. |

**Modified:**

| File | Change |
|------|--------|
| `main.py` | Mount the workspace router; global `ToolError` → JSON handler. |
| `src/agent/messages.py` | `to_dict`/`from_dict` on `Message` and `ToolCall`. |
| `src/agent/registry.py` | `path_args` on `ToolSpec`; set `("path",)` on the two read tools. |
| `src/agent/loop.py` | Resolve `path_args` against the workspace root inside the tool-call error boundary. |
| `src/agent/tools.py` | Extract `resolve_in_workspace` (shared read-side resolver); `_guard_write_target` reuses it. |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, `docs/specs/stage1_M4_spec.md` | Glossary / log / status / spec-status updates. |

## 3. Deviations from spec

None. All seven decisions (multiple workspaces keyed by id, auto-reopen, pristine re-open + unsaved-close warning, `path_args` with contained reads, `tool_error_policy`, invalid-config fallback, save = export with save-as-copy switching the active doc) were built as agreed.

One small implementation detail worth recording: a path resolution error (`outside_workspace`) for a read tool is raised inside the loop's tool-call `try/except`, so it follows the same error policy as any other `ToolError` (reported back to the model under `report_and_skip`) rather than crashing the run.

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Modules:** `src/workspace/{config,folder,state}.py`, `src/routes/workspace.py`.
- **Routes:** the full `/api/workspace/...` table.
- **Config keys:** `tool_error_policy`.
- **Types:** `WorkspaceConfig`, `WorkspaceSession`; `ToolSpec` gains `path_args`; `.stet/workspace.json` schema finalized.

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), all 2026-05-30 / Milestone 4:

- Workspace sessions are a parallel system, keyed by id.
- Only conversation + open-doc pointer persist; pristine re-open.
- Path resolution via declarative `path_args`, reads contained.
- "Save" replaces "export"; save-as-copy switches the active document.

## 6. Test results

- New: `tests/test_workspace_config.py` — **7 passed**; `tests/test_workspace_state.py` — **9 passed**; `tests/test_workspace_api.py` — **18 passed**.
- Full suite: **668 passed, 1 skipped, 0 warnings** (run with `-W error`). The 1 skip is the opt-in live Ollama test. Legacy card-UI baseline untouched.

Proofs: opening a folder creates `.stet/` + config; opening a docx loads the model while the file on disk stays byte-identical; an agent edit does not touch disk until save; conversation + open-document round-trip through `workspace.json` (auto-reopen, and graceful skip when the file is gone); save-as-copy writes a new file, leaves the original byte-identical, and switches the active document; in-place save hits the overwrite guard (409); checkpoint restore rolls back an agent edit; close returns 409 on unsaved changes unless forced; a workspace-relative read path resolves correctly.

## 7. What to watch in the next milestone

- **M5 (Workspace UI shell):** the three-panel layout at `/workspace` wired to these endpoints; renders the file tree (nested), the document, and the agent chat; surfaces `pending_confirmation` (→ `agent/confirm`) and the unsaved-changes / close warning (backend already exposes `unsaved_changes` and the `409` on close). Native folder picker lands here.
- **Provider/model selection:** `agent/run` accepts `provider`/`model` per request (default `openai`); the UI will pass the user's choice. The OpenAI `gpt-5` temperature guard from M3 applies.
- **Conversation growth:** the full message list (including tool results) is persisted to `workspace.json`; if it grows large, M5/M9 may add trimming or summarization.
- **Agent save semantics:** an agent-driven `export_document` marks the model clean and switches the active document (via `_finalize`); watch that this matches user expectation once the chat UI exists.
