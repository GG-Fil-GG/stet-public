# Stage 1 — Milestone 5 Report: Workspace UI shell

**Status:** Complete
**Spec:** [`stage1_M5_spec.md`](stage1_M5_spec.md) (approved & implemented 2026-05-30)

---

## 1. What was done

The agentic workspace now has a **face**: a standalone three-panel page at **`/workspace`** — file sidebar | document area | agent chat — wired to the M4 JSON API. The legacy card UI at `/` is untouched.

- **Page route** — `GET /workspace` in `main.py` renders `templates/workspace.html` (standalone `<html>`, Tailwind CDN + its own CSS/JS; not a `base.html` extension).
- **Three-panel shell** — `templates/workspace.html`: header (workspace path, unsaved indicator, Open folder / Save / Save a copy / settings), a collapsible **file tree** sidebar, a read-only **document area**, and an **agent chat** panel. Plus a settings modal and a generic prompt modal (folder-path fallback, save-a-copy name).
- **Client logic** — `static/js/workspace.js`:
  - **Open folder** via `window.pywebview.api.pick_folder()`; **fallback** to a path text input when pywebview is absent (browser/dev) → `POST /api/workspace/open` → renders the tree and auto-opens the last document.
  - **File tree** built from the flat workspace-relative file list (nested by path segments); `.docx` files are clickable, others are listed but not openable (previews deferred).
  - **Open document** → `GET /document` → renders each paragraph's `html` (read-only formatted). Track-changes coloring / comment balloons / editing are M6.
  - **Agent chat** → `POST /agent/run` with `{message, provider, model, api_key, ollama_url}` from `localStorage`; renders `final_text` + a compact tool-step list; surfaces `pending_confirmation` with Confirm/Cancel → `POST /agent/confirm`. Refreshes the document and unsaved flag after each run.
  - **Save** → confirm overwrite (always asks) → `POST /save {overwrite:true}`. **Save a copy** → in-app prompt for a new in-workspace path → `POST /save {path}` (switches active document per M4) → reloads the tree.
  - **Unsaved guard** → `beforeunload` warns when the open document is dirty.
  - **Settings** → reuses the card UI's `localStorage` keys (`llm_provider`, `openai_model`, `openai_api_key`, `ollama_url`, `ollama_model`), populated from `/llm-config`.
- **Styling** — `static/css/workspace.css`: tree, read-only document render (bold/italic/super/subscript, reused diff/`mark` colors), chat bubbles, confirmation block.
- **Backend tweaks** — `src/routes/workspace.py`: `AgentRunRequest` gains `api_key` / `ollama_url` (empty → `None` → `.env` fallback), forwarded through `_build_loop` → `AgentLLMClient`; `GET /document` paragraphs gain an `html` field from `Paragraph.to_display_html()`.
- **Native dialog** — `desktop_app.py`: `Api.pick_folder()` (a `webview.FOLDER_DIALOG`), callable as `window.pywebview.api.pick_folder()`.

Commit: _see the M5 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

**Created:**

| File | Purpose |
|------|---------|
| `templates/workspace.html` | Standalone three-panel page + settings/prompt modals + toast. |
| `static/js/workspace.js` | Workspace client (open/tree/doc/chat/save/settings/unsaved guard). |
| `static/css/workspace.css` | Layout + read-only document/tree/chat styling. |
| `tests/test_workspace_page.py` | `GET /workspace` serves 200 with the panel anchors + asset refs; `/` still serves. |

**Modified:**

| File | Change |
|------|--------|
| `main.py` | `GET /workspace` route. |
| `src/routes/workspace.py` | `api_key`/`ollama_url` on `AgentRunRequest` → `_build_loop` → client; `html` field on `GET /document` paragraphs. |
| `desktop_app.py` | `Api.pick_folder()` native folder dialog. |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, `docs/specs/stage1_M5_spec.md` | Glossary / log / status / spec-status updates. |

## 3. Deviations from spec

None of substance. Two small implementation details recorded in the decision log:

- **`pick_folder()` returns `str | None`** (the chosen path or `None`), not the `{success, path, error}` dict the spec sketched. A folder pick has no IO side effect to report, so the richer envelope was unnecessary; the JS only ever needed the path.
- **Overwrite confirmation uses `window.confirm()`** (native, works in browser + pywebview); the in-app prompt modal is reserved for free-text input (copy filename, folder-path fallback).

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Routes:** `GET /workspace`; `agent/run` request gains `api_key`/`ollama_url`; `GET /document` paragraphs gain `html`.
- **Frontend assets:** `templates/workspace.html`, `static/js/workspace.js`, `static/css/workspace.css`.

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), both 2026-05-30 / Milestone 5:

- `pick_folder` returns a bare path string, not a result dict.
- `/workspace` is a standalone page; overwrite confirm uses native `confirm()`.

## 6. Test results

- New: `tests/test_workspace_page.py` — **2 passed**.
- Full suite: **670 passed, 1 skipped, 0 warnings**. The 1 skip is the opt-in live Ollama test. Legacy card-UI baseline untouched.

## 7. Manual QA (required — UI + native dialog)

The UI behavior and the native folder picker are not auto-tested (Stage 1 introduces no browser/E2E harness; the spec accepts manual QA). Suggested script:

1. Run the desktop app (`python desktop_app.py`) → open `/workspace`.
2. **Open folder** (native dialog) → pick a project folder containing a `.docx` (ideally with nested subfolders) → the tree renders; folders collapse/expand.
3. Click a `.docx` → the document area shows formatted, read-only paragraphs.
4. In **Settings**, pick a provider/model (and key for OpenAI, or Ollama URL/model) → Save.
5. In **chat**, ask "list the open comments" → see a response with a tool-step list.
6. Ask the agent to edit a paragraph → the document refreshes; the **unsaved** indicator appears.
7. **Save** → confirm the overwrite prompt → indicator clears.
8. **Save a copy** into a subfolder (`drafts/<name>_2.docx`) → the copy appears in the tree and becomes active; the original is unchanged.
9. With unsaved edits, attempt to close/navigate away → the browser unsaved-changes warning fires.

Browser/dev fallback: opening `/workspace` in a plain browser uses the path **text input** for "Open folder" (no pywebview); everything else behaves identically.

## 8. Manual testing findings & follow-up fixes (2026-05-31)

Option-A (browser) manual testing went well until an edit request failed. The user pasted a sentence from the abstract and asked for a passive-voice revision; the agent explored (`read_document`, `list_comments`, `read_file`) but then failed `edit_paragraph` twice, and the chat step list showed an unhelpful `✗ [object Object]`. Two distinct issues, both fixed in this follow-up:

### 8.1 Substantive — the agent had no way to find a paragraph by its text

**Cause (tool gap, not a model failure):** the agent's read tools could not map sentence text → `para_id`. `read_document` returns only a summary (counts/title/author — no body, no ids); `read_paragraph` requires a `para_id` you already have; `list_comments` lists only threads. So the model had to *guess* the `para_id`, and `edit_paragraph` correctly returned `not_found`. (The M5 `GET /document` route already exposes paragraph ids+text to the **UI**, but that was never on the agent's tool surface.)

**Fix:** added a document-bound, non-mutating **`find_in_document(query, max_results=10)`** tool — case-insensitive, whitespace-normalized substring search over `Paragraph.plain_text`, returning `{query, matches:[{para_id, text, style}], count, truncated}` in document order. The agent **system prompt** now tells the model to call `find_in_document` to locate a pasted/described sentence and obtain its `para_id` before editing, rather than guessing.

- New schema `FindInDocumentInput` (`src/agent/tool_schemas.py`), handler `find_in_document` + `_normalize_ws` helper (`src/agent/tools.py`), registration (`src/agent/registry.py`), prompt update (`src/agent/prompts.py`).
- Tests: `tests/test_agent_tools.py::TestFindInDocument` (5 cases — verbatim match, case/whitespace tolerance, no-match, `max_results` truncation, empty-query error) + registry expectation updated.

### 8.2 Cosmetic — `✗ [object Object]` in the chat step list

**Cause:** tool errors cross the API as a structured object (`{error: code, message}`); `workspace.js` stringified the whole object.

**Fix:** added an `errorText(err)` helper in `static/js/workspace.js` that surfaces `err.message` (then `err.error`, then a JSON fallback). Failed steps now read the human-readable message (e.g. "✗ Paragraph not found: …").

### 8.3 Substantive — switching documents discarded unsaved edits with no warning

**Cause:** the only way to leave a document in the M5 UI is to open another one. `POST /document/open` re-parsed the target from disk and replaced the in-memory model **without** an unsaved-changes guard (unlike `POST /close`), so an agent edit was silently lost on switch — and lost again (pristine) on switching back. No warning appeared.

**Fix:** added a `force: bool = False` flag to `document/open`; if the current document `is_dirty` and `force` is false the route returns **409 `unsaved_changes`** (same contract as `/close`). `static/js/workspace.js` catches the 409 and shows a confirm; on confirm it retries with `force=true`, otherwise it keeps the current document highlighted. Auto-reopen on workspace open is unaffected (clean model).

- `src/routes/workspace.py`: `DocumentOpenRequest.force` + the guard. `static/js/workspace.js`: `openDocument(relPath, force)` + `isUnsavedChangesError()`.
- Tests: `tests/test_workspace_api.py::TestSwitchDocument` (2 cases — blocked-while-dirty/`force` switches; clean switch allowed).

### 8.4 Enhancement — explicit "Close" document action

Following 8.3 (switching was the only way to leave a document), added a **Close** button to the workspace header and a backing `POST /document/close` endpoint that clears the active document while keeping the workspace open. It reuses the same unsaved-changes contract: `{force}`; dirty + not `force` → **409 `unsaved_changes`**; the UI confirms and retries with `force=true`. Closing clears the document view, deselects the file, and disables Save / Save-a-copy / chat. Closing when nothing is open is a no-op.

- `src/routes/workspace.py`: `DocumentCloseRequest` + `POST /document/close`. `src/workspace/state.py`: `WorkspaceSession.close_document()`. `templates/workspace.html`: header **Close** button. `static/js/workspace.js`: `closeDocument(force)`; `clearDocument()` now also disables chat, resets the chat panel, and clears the active file highlight.
- Tests: `tests/test_workspace_api.py::TestCloseDocument` (3 cases — clears active doc / workspace stays open, unsaved guard + `force`, no-op when none open).

### 8.5 Tooling — static-asset cache-busting

Retesting reported the Close button "always grayed out" and the switch warning appearing as a block/toast rather than the new confirm dialog. Root cause was **not** a code bug: the browser was serving a **cached older `workspace.js`** (the backend reloads, but `/static/js/workspace.js` was cached), so the new enable line and 409-confirm handling never ran. Fixed by appending a cache-busting `?v=<newest-mtime>` token to the workspace JS/CSS URLs, computed per request in `main.py` (`_asset_version()`), so browsers refetch whenever the assets change (this stack has no build step / content hashing). Page test now asserts the `?v=` token is present.

**Test result after follow-ups:** full suite **680 passed, 1 skipped, 0 warnings** (page test strengthened).

Decisions recorded in [`stage1_decision_log.md`](../stage1_decision_log.md) (2026-05-31, three "Milestone 5 (follow-up)" entries). Glossary updated with the `find_in_document` tool, `FindInDocumentInput` schema, and the `document/open` `force` flag + `document/close` route.

## 9. What to watch in the next milestone

- **M6 (Document viewer):** upgrade the read-only render to show track-changes coloring, comment balloons, and inline editing — the `html` field and CSS hooks (diff/`mark` classes) are already in place.
- **M7 (Chat polish):** cancel in-flight runs, a step-by-step trace toggle, and links from chat messages to the document changes they made.
- **Folder-picker UX:** the dev fallback is a raw absolute-path input; fine for local use, but the distributable relies on `pick_folder()` — worth a real-device check on each target OS.
- **Conversation reset:** the chat panel resets when a new document is opened in the same workspace; the backend conversation persists in `workspace.json`. Confirm this matches expectation once multi-document workflows are exercised.
- **`find_in_document` matching:** normalized substring covers verbatim pastes; if users describe edits in their own words (paraphrase), a future fuzzy/semantic match or a paginated `get_paragraphs` browse tool may be warranted.
