# Stage 1 Glossary

**Single source of truth for canonical names introduced during Stage 1 implementation.**

Before introducing a new module, tool, route, config key, type, or JSON field, check this document. If a name already exists, reuse it. If you introduce a new name, add it here as part of the milestone report.

This file grows as each milestone completes. Empty sections are placeholders for future content.

---

## How to use this document

- **For me (the AI assistant):** Check this file before adding any new identifier in `src/` or `tests/`. After each milestone, append new names introduced by that milestone in the appropriate section, citing the spec.
- **For the project owner:** This is the place to spot naming inconsistencies before they propagate. If you see `read_paragraph` here but `get_paragraph` in code, that's a deviation worth flagging.

Naming conventions for new identifiers:

- **Modules:** snake_case, descriptive, scoped to package (`src/agent/tools.py`, not `src/tools.py`).
- **Tools (agent-callable):** snake_case verbs (`read_paragraph`, `edit_paragraph`, `export_document`).
- **Routes:** `/api/workspace/{resource}/{action}` for JSON; `/{page}` for HTML pages.
- **Config keys:** snake_case, namespaced by feature (`max_checkpoints`, `max_agent_steps`, `checkpoint_policy`).
- **Pydantic models / TypedDicts:** PascalCase (`ToolSchema`, `WorkspaceState`, `CheckpointMetadata`).

---

## Modules and packages

New Python modules created during Stage 1.

| Path | Purpose | Introduced in |
|------|---------|---------------|
| `src/agent/` | Agent tool layer package. | M1 |
| `src/agent/tools.py` | Tool handler implementations (wrap existing document/file code). | M1 |
| `src/agent/tool_schemas.py` | Canonical provider-neutral Pydantic input schemas (one per tool). | M1 |
| `src/agent/registry.py` | `name → ToolSpec` registry with `get_tool` / `list_tools`. | M1 |
| `src/agent/errors.py` | `ToolError` exception type. | M1 |
| `src/checkpoints.py` | `CheckpointStore` + `CheckpointMetadata`: snapshot save/restore/list/prune over `DocumentModel.to_dict()/from_dict()`. Standalone module (shared by M3 loop and M4 workspace). | M2 |
| `src/agent/messages.py` | Loop conversation types: `Message` (system/user/assistant/tool) + `ToolCall`. Distinct from the UI `ChatMessage`. | M3 |
| `src/agent/prompts.py` | `AGENT_SYSTEM_PROMPT` / `get_agent_system_prompt()` — task-oriented loop prompt (distinct from the card-UI suggestion prompt in `src/llm_prompts.py`). | M3 |
| `src/agent/llm_tools.py` | `AgentLLMClient` + `LLMToolResponse`: provider-neutral tool-calling client (OpenAI + Ollama). Does not touch `LLMHandler`/`llm_transport.py`. Applies special-Unicode protect/restore at the provider boundary (M9a). M9c-prep adds `trim_conversation` (oldest tool results stubbed past `context_token_budget`; provider copy only) and bounded OpenAI calls (120 s timeout); retries raised 0 → 3 after the M9d pilot (transient-drop resilience). | M3 (M9d retries) |
| `src/agent/run_transcript.py` | `RunTranscript` + `new_transcript_path`: per-run JSONL trace under `.stet/runs/`, flushed per event, written even on crash. Diagnostic tooling added mid-M9d pilot. | M9d pilot |
| `src/agent/unicode_protection.py` | Special-Unicode protect/restore for the agent transport seam: `UNICODE_PROTECTION_MAP` (superset of the `llm_transport` card-UI map — adds `M9D_AGENT_ADDITIONS`: en/em-dash, ellipsis, non-breaking hyphen), `protect`/`restore`/`protect_arguments`/`restore_arguments`. Prevents the model corrupting `≥`/`±`/en-dash/… when re-typing paragraphs. | M9a (M9d dashes) |
| `src/agent/loop.py` | `AgentLoop` + policies/result types: drives the call→tool→result cycle. M9c-prep adds per-step INFO logging, intra-step cancel (with stub tool results for skipped calls), and a `live_steps` sink for mid-run progress. M9d-pilot adds a `transcript` sink + enriched per-tool logs. | M3 |
| `src/logging_config.py` | `configure_logging()` (called from `main.py`): enables INFO for `src.*` so the agent per-step trace emits, and filters the `/agent/progress` poll out of the uvicorn access log. | M9d pilot |
| `src/workspace/` | Workspace backend package. | M4 |
| `src/workspace/config.py` | `WorkspaceConfig` + `load_config`/`save_config`/`coerce_config`; code-default constants for `.stet/config.json`. | M4 |
| `src/workspace/folder.py` | `ensure_stet_dir`, `list_files`, `resolve_path` (contained path resolution). | M4 |
| `src/workspace/state.py` | `WorkspaceSession` + in-memory registry (`open_workspace`/`get_workspace`/…); `.stet/workspace.json` persistence; working-model snapshots in `.stet/working/` (`persist_working_model`/`sync_working_model`/`clear_working_model`, restore-if-unchanged in `open_document`, M9d). | M4 (M9d durability) |
| `src/workspace/chat_log.py` | `ChatTurn` dataclass + serialize/deserialize for UI turn log (`chat_turns` in `workspace.json`). | M7 |
| `src/workspace/render.py` | Pure document renderer: `render_document(model) -> list[Block]` (block-level paragraphs/table rows, inline track changes, comment boundary segmentation, RevisionStore diff overlay for in-session edits). No I/O/session. | M6a (M6b overlay) |
| `src/routes/workspace.py` | JSON API router (`/api/workspace/...`). | M4 |

Frontend assets (not Python):

| Path | Purpose | Introduced in |
|------|---------|---------------|
| `templates/workspace.html` | Standalone three-panel workspace page (sidebar / document / chat); not a `base.html` extension. | M5 |
| `static/js/doc_editor.js` | Standalone TipTap paragraph editor for `/workspace`: `createParagraphEditor(elementId, initialHtml, { onSave, onCancel })`. Decoupled from the card UI. | M6b |
| `static/js/workspace.js` | Workspace client: open folder, file tree, open doc, agent chat run/confirm/cancel/clear, save / save-a-copy, settings, unsaved guard. M6a adds block/comments rendering + anchor↔comment click-linking. M6b adds per-paragraph edit/save via PATCH. M7 adds persisted turn log reload, details toggle, stop/clear, step links. M9b adds workspace-config load/save in the settings modal. M9c-prep adds live run progress (2 s polling of `agent/progress` while a run is in flight) and the context-token-budget field. | M5 (M6a viewer, M6b edit, M7 chat, M9b config UI) |
| `static/css/workspace.css` | Workspace layout + document/tree/chat styling. M6a adds track-change, comment-highlight, comments-rail, and table-row styles. M6b adds paragraph edit affordance + editor toolbar styles. M7 adds chat toolbar, status banners, step links. | M5 (M6a viewer, M6b edit, M7 chat) |

---

## Agent tools

Tools callable by the agent loop. Document-bound tools receive a resolved `DocumentModel` (`requires_model`); filesystem-bound tools receive a `workspace_root` (`requires_workspace_root`). The LLM supplies only the JSON params in each tool's schema. Tools that change the in-memory model are flagged `mutating` (M3): `edit_paragraph`, `add_comment_reply`, `add_comment`, `remove_comment` — these drive the `per_mutating_tool` checkpoint policy. The guarded file writers (`create_document`, `export_document`) are *not* `mutating` (they write files, not the model).

| Tool | LLM-facing params | Returns | Introduced in |
|------|-------------------|---------|---------------|
| `list_workspace_files` | _(none; workspace_root injected)_ | `{files:[{name,path,type,size_bytes}],count}` | M1 |
| `read_document` | `path` | `{path,paragraph_count,comment_count,thread_count,revision_count,title,author}` | M1 |
| `read_file` | `path` | `{path,file_type,content,meta}` (pdf/xlsx/xls/csv/docx/rtf/pptx/txt/md) | M1 (M8: rtf/pptx/txt/md) |
| `create_document` | `path,overwrite` | `{path,created}` (guarded: `workspace_root` injected, containment + overwrite) | M1 (M2 guarded) |
| `list_comments` | `comment_filter` | `{threads:[{thread_id,root_comment_id,status,author,referenced_text,comment_count,comments}],count}` | M1 |
| `find_in_document` | `query,max_results` | `{query,matches:[{para_id,text,style}],count,truncated}` (case-insensitive, whitespace-tolerant substring search — the `para_id` discovery tool) | M5 (follow-up) |
| `read_paragraph` | `para_id` | `{para_id,text,display_text,style,formatting_summary,comment_ids,has_revisions}` | M1 |
| `edit_paragraph` | `para_id,new_text,track_changes,author,addresses_thread_id?` | `{para_id,applied,edit_count,track_changes,author}` + optional `removed_citations` (dropped `[CITATION_n]` placeholders), `restored_ranges` (numeric en-dash repairs), `addresses_thread_id` (comment-driven linkage) | M1 (M9e: `addresses_thread_id`, `removed_citations`, `restored_ranges`) |
| `add_comment_reply` | `thread_id,text,author` | `{comment_id,thread_id,author}` | M1 |
| `add_comment` | `para_id,start,end,text,author` | `{comment_id,thread_id,para_id,start,end}` (new anchored root comment) | M2 |
| `remove_comment` | `comment_id` | `{removed,comment_id}` (root removes whole thread; reply removes itself) | M2 |
| `export_document` | `path,include_track_changes,overwrite` | `{path,include_track_changes}` (guarded: `workspace_root` injected, containment + overwrite) | M1 (M2 guarded) |

---

## HTTP routes

JSON API endpoints and HTML page routes added during Stage 1.

| Method | Path | Purpose | Request shape | Response shape | Introduced in |
|--------|------|---------|---------------|----------------|---------------|
| `POST` | `/api/workspace/open` | Open/re-open a workspace folder | `{path}` | `{workspace_id, root, config, open_document, files}` | M4 |
| `POST` | `/api/workspace/{id}/close` | Close a workspace (warns on unsaved) | `{force}` | `{closed}` (409 `unsaved_changes` unless `force`) | M4 |
| `GET` | `/api/workspace/{id}/files` | Recursive user file tree | — | `{files, count}` | M4 |
| `GET` / `PUT` | `/api/workspace/{id}/config` | Read / update workspace config | `PUT`: partial config | `{config}` | M4 |
| `POST` | `/api/workspace/{id}/document/open` | Open a docx into the session | `{path, force}` (M5 follow-up adds `force`) | `{document}` (409 `unsaved_changes` if the current doc is dirty and `force` is false) | M4 (M5 `force`) |
| `POST` | `/api/workspace/{id}/document/close` | Clear the active document (workspace stays open) | `{force}` | `{closed}` (409 `unsaved_changes` if dirty and `force` is false; no-op if none open) | M5 (follow-up) |
| `GET` | `/api/workspace/{id}/document` | Active document summary + render blocks + comment threads | — | `{document, blocks, comments}` (M6a: `blocks` replaces the M5 `paragraphs` array; `comments` is the document-ordered thread list) | M4 (M5 `html`, M6a `blocks`+`comments`) |
| `PATCH` | `/api/workspace/{id}/document/paragraph/{para_id}` | Manual paragraph edit (pre-edit checkpoint + `edit_paragraph`) | `{new_text, track_changes?, author?}` | `{document, block, unsaved_changes}` | M6b |
| `POST` | `/api/workspace/{id}/document/create` | Create a blank docx | `{path, overwrite}` | `{path, created}` | M4 |
| `POST` | `/api/workspace/{id}/save` | Save / save-as-copy (switches active doc) | `{path?, include_track_changes, overwrite}` | `{path, document, unsaved_changes}` | M4 |
| `POST` | `/api/workspace/{id}/agent/run` | Run the agent loop on a message | `{message, provider?, model?, api_key?, ollama_url?}` (M5 adds creds) | `{status, final_text, steps, pending_confirmation?, unsaved_changes, document}` | M4 (M5 creds) |
| `POST` | `/api/workspace/{id}/agent/confirm` | Resume after an overwrite pause | `{confirmed}` | same as `agent/run` | M4 |
| `GET` | `/api/workspace/{id}/agent/progress` | Live snapshot of the in-flight run (polled ~2 s by the UI) | — | `{running, step_count, steps: [{tool, ok}]}` | M9c-prep |
| `GET` | `/api/workspace/{id}/checkpoints` | List checkpoints | — | `{checkpoints}` | M4 |
| `POST` | `/api/workspace/{id}/checkpoint/restore` | Roll back to a checkpoint | `{checkpoint_id}` | `{restored, document}` | M4 |
| `GET` | `/workspace` | Three-panel workspace UI shell (HTML page; card UI stays at `/`) | — | `templates/workspace.html` | M5 |

---

## Config keys

Keys in `.stet/config.json` (workspace-level configuration; per-workspace only in Stage 1).

| Key | Type | Default | Allowed values / notes | Introduced in |
|-----|------|---------|------------------------|---------------|
| `config_version` | int | `1` | Schema version for forward-compatible migrations. | M0 |
| `max_checkpoints` | int | `30` | ≥ 1. FIFO prune when checkpoint count exceeds this. | M0 |
| `max_agent_steps` | int | `20` | ≥ 1. Hard cap on tool-call iterations per user message. | M0 |
| `checkpoint_policy` | str | `"per_agent_turn"` | `"per_agent_turn"` or `"per_mutating_tool"`. | M0 |
| `tool_error_policy` | str | `"report_and_skip"` | `"report_and_skip"` or `"stop_and_ask"`. Loop behavior on a non-confirmation tool error. | M4 |

**Resilience (M4):** missing file → defaults (written); missing key → code default; **invalid value → per-key default** (logged); unknown key → ignored.

---

## Types and protocols

Pydantic models, TypedDicts, dataclasses, and protocol classes shared across Stage 1 modules.

| Type | Defined in | Purpose | Introduced in |
|------|------------|---------|---------------|
| `ToolError` | `src/agent/errors.py` | Structured, recoverable tool failure (`code`, `message`, `to_dict()`). | M1 |
| `ToolSpec` | `src/agent/registry.py` | Registered tool: `name`, `handler`, `input_schema`, `description`, `requires_model`, `requires_workspace_root`, `mutating`, `path_args`. | M1 (M3 adds `mutating`; M4 adds `path_args`) |
| `*Input` schema models | `src/agent/tool_schemas.py` | One Pydantic model per tool's LLM-facing params (e.g. `EditParagraphInput`, `AddCommentInput`, `RemoveCommentInput`, `FindInDocumentInput`). | M1 (M2 adds `AddCommentInput`/`RemoveCommentInput`; M5 follow-up adds `FindInDocumentInput`) |
| `CheckpointStore` | `src/checkpoints.py` | Save/restore/list/prune document snapshots in a directory (FIFO at `max_checkpoints`). | M2 |
| `CheckpointMetadata` | `src/checkpoints.py` | Snapshot descriptor: `checkpoint_id`, `created_at`, `label`, `sequence`. | M2 |
| `Message` / `ToolCall` | `src/agent/messages.py` | Loop conversation turn / a model-requested tool invocation (id, name, parsed arguments). | M3 |
| `LLMToolResponse` | `src/agent/llm_tools.py` | Normalized provider reply: assistant `text` + parsed `tool_calls`. | M3 |
| `AgentLLMClient` | `src/agent/llm_tools.py` | Provider-neutral tool-calling chat client (`provider`, `model`, `complete(messages, tools)`). | M3 |
| `protect` / `restore` / `protect_arguments` / `restore_arguments` | `src/agent/unicode_protection.py` | Swap special Unicode ↔ `__UNICODE_*__` placeholders at the provider boundary; argument variants recurse over dict values + lists. Map is a superset of the card-UI map (adds dashes/ellipsis/nb-hyphen, M9d). | M9a (M9d dashes) |
| `AgentLoop` | `src/agent/loop.py` | Orchestrates a turn: `run(user_message, history)` / `resume(pending, confirmed, history)`. | M3 |
| `AgentResult` / `AgentStep` | `src/agent/loop.py` | Turn outcome (`messages`, `final_text`, `steps`, `status`, `pending_confirmation`) / one executed tool call. | M3 |
| `PendingConfirmation` | `src/agent/loop.py` | A paused guarded write awaiting overwrite confirmation (`tool_name`, `arguments`, `message`). | M3 |
| `CheckpointPolicy` / `ToolErrorPolicy` | `src/agent/loop.py` | Enums: `per_agent_turn`/`per_mutating_tool`; `report_and_skip`/`stop_and_ask`. | M3 |
| `WorkspaceConfig` | `src/workspace/config.py` | Per-workspace config dataclass (`config_version`, `max_checkpoints`, `max_agent_steps`, `checkpoint_policy`, `tool_error_policy`, `context_token_budget`). | M4 (M9c-prep budget) |
| `WorkspaceSession` | `src/workspace/state.py` | In-memory workspace state: root, config, checkpoint store, active document + path, conversation, chat turn log, pending confirmation, agent run/cancel flags, `run_live_steps` (mid-run progress, M9c-prep). | M4 (M7 chat) |
| `ChatTurn` | `src/workspace/chat_log.py` | One UI chat cycle: user message, final text, status, step trace, optional pending confirmation, timestamp. Persisted in `workspace.json` `chat_turns`. | M7 |
| `Block` | `src/workspace/render.py` | One rendered document unit: `kind` (`"paragraph"`/`"table_row"`), `para_id`, `html`, `text`, `style`, `comment_ids`, `cells?`. Serialized into `GET /document`'s `blocks`. | M6a |

---

## Workspace layout

Files and directories inside a workspace folder. `.stet/` is the namespace Stet owns.

| Path | Purpose | Introduced in |
|------|---------|---------------|
| `.stet/` | Reserved namespace Stet owns; excluded from file scans. Safe to delete (loses session state + undo only) and to gitignore. | M0 |
| `.stet/workspace.json` | Session state: `{schema_version, open_document (workspace-relative or null), conversation (M3 messages, no system), chat_turns (M7 UI log, optional), updated_at}`. The in-memory model is not persisted here — unsaved edits live in `.stet/working/` (M9d). | M0 (location), M4 (schema), M7 (`chat_turns`) |
| `.stet/config.json` | Workspace configuration (see Config keys above). | M0 |
| `.stet/checkpoints/` | Agent `DocumentModel` snapshots; FIFO pruned at `max_checkpoints`. | M0 (layout), M2 (mechanism) |
| `.stet/working/` | Working-model snapshots of unsaved in-RAM edits, one JSON per open document (`<doc-hash>.json`, header carries `source_mtime`). Restored on re-open only if the source file is unchanged; cleared on same-path Save. Safe to delete (falls back to pristine parse). | M9d |
| `.stet/runs/` | Per-run agent transcripts (one JSONL per run, `run_start`/`assistant`/`tool_result`/`run_end`), flushed per event so a stopped/crashed run is still reviewable. Diagnostic only; safe to delete. | M9d pilot |

---

## Renames and aliases

If we ever rename something, record the old → new mapping here so older code, comments, or session transcripts remain interpretable.

| Old name | New name | Reason | Date |
|----------|----------|--------|------|
| _(empty)_ | | | |
