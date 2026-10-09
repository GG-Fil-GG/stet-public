# Stage 1 — Milestone 5 Spec: Workspace UI shell

**Status:** Complete — implemented 2026-05-30; see [`stage1_M5_report.md`](stage1_M5_report.md)
**Plan reference:** [Milestone 5](../stage1_implementation_plan.md#milestone-5--workspace-ui-shell)

---

## 1. Goal

A three-panel workspace UI at **`/workspace`** — **file sidebar | document area | agent chat** — wired to the M4 JSON API. The user can pick a folder (native dialog), browse its (nested) files, open a docx, chat with the agent, see the run result, confirm overwrites, and save. This is the **shell**: the document area is a minimal read-only stub (the full viewer is M6) and the chat is functional but not yet polished (cancel/trace/inline-change-links are M7). The legacy card UI at `/` is untouched.

---

## 2. Design constraints (from the codebase)

- **Frontend stack is CDN-based, no build step.** `templates/base.html` loads Tailwind (CDN), HTMX, and TipTap (ESM via esm.sh). New pages follow suit. Static assets live under `static/` (served at `/static`).
- **`base.html` is card-UI-specific.** Its header has an Export button and a settings modal bound to card sessions, and `<main>` is a centered `max-w-7xl`. A full-bleed three-panel app does not fit it cleanly → `/workspace` is a **standalone** template (its own `<html>`), not an extension of `base.html`.
- **Settings live in `localStorage`.** The card settings modal writes `llm_provider`, `openai_model`, `openai_api_key`, `ollama_url`, `ollama_model`. Since `localStorage` is per-origin, the workspace page can **read the same keys** and pass them to the agent. `/llm-config` (existing JSON route) supplies the provider/model catalog.
- **The M4 API is JSON and complete.** `/api/workspace/...` already supports open/files/config/document open+create+get/save/agent run+confirm/checkpoints. M5 is mostly client-side, plus one small backend tweak (below).
- **API-key gap.** `AgentLLMClient` already accepts `api_key` / `ollama_url`, but M4's `AgentRunRequest` does not forward them — it relies on the env `OPENAI_API_KEY`. In the desktop app the key lives in `localStorage`, so M5 must extend `AgentRunRequest` (+ `_build_loop`) to forward `api_key` / `ollama_url`.
- **Native dialogs go through pywebview.** `desktop_app.py` exposes a `js_api` (`Api`) with `save_export(...)`; methods are callable as `window.pywebview.api.<name>()`. In a plain browser (dev/tests) `window.pywebview` is absent → the UI needs a fallback.

---

## 3. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `templates/workspace.html` | Standalone three-panel page (sidebar / document / chat) + compact settings popover. |
| `static/js/workspace.js` | Client logic: open folder, render file tree, open doc, chat run/confirm, save, unsaved-changes guard. |
| `static/css/workspace.css` | Layout + panel styling (or a `<style>` block in the template; see Open question 3). |
| `tests/test_workspace_page.py` | `GET /workspace` returns 200 and contains the three panel anchors. |

**Modify:**

| File | Change |
|------|--------|
| `main.py` | Register `GET /workspace` → render `workspace.html`. |
| `src/routes/workspace.py` | Add `api_key` / `ollama_url` to `AgentRunRequest` (empty → `None`); forward through `_build_loop` → `AgentLLMClient`. Add a formatted `html` field (`Paragraph.to_display_html()`) to the `GET /document` paragraph payload. |
| `desktop_app.py` | Add `Api.pick_folder()` (native folder dialog → returns chosen path). Possibly a `save_in_workspace` helper (see Open question 1). |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, this spec | Glossary / log / status / spec-status updates (report step). |

---

## 4. Public API surface

### 4.1 Page route

- `GET /workspace` → `templates/workspace.html` (HTML). No server state; the page bootstraps via the JSON API.

### 4.2 Backend tweak — forward credentials to the agent

```python
class AgentRunRequest(BaseModel):
    message: str
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None      # NEW — from localStorage (desktop has no env key)
    ollama_url: str | None = None   # NEW

# _build_loop(...) passes api_key / ollama_url to AgentLLMClient(...)
# An empty-string api_key is coerced to None so it falls back to .env.
```

**Key precedence (both dev and distributable):** `AgentLLMClient` resolves `api_key or os.getenv("OPENAI_API_KEY")`, so a **UI-supplied key wins; otherwise `.env`**. Dev/local: the UI field is blank → falls back to `.env`. Distributable: the user enters a key in the UI → it takes priority. The key is never persisted server-side — it lives only in `localStorage` and the per-request body.

### 4.3 Native API (`desktop_app.py`)

```python
class Api:
    def pick_folder(self) -> dict:
        """Show a native folder-select dialog (webview.FOLDER_DIALOG).
        Returns {success, path|None, error|None}."""
```

### 4.4 Client behavior (`static/js/workspace.js`)

State held in JS: `workspaceId`, `openDocumentPath`, `pendingConfirmation`, `unsavedChanges`.

- **Open workspace:** `window.pywebview?.api.pick_folder()` → path; **fallback** (no pywebview): a path text input prompt. → `POST /api/workspace/open` → render sidebar + (auto-reopened) document.
- **File sidebar:** render `files[]` as a tree (group by path segments). Click a `.docx` → `POST /document/open` → load document area. Non-docx → type icon + filename only, **no preview** (deferred).
- **Document area:** **read-only formatted** render of `GET /document` `paragraphs[]`, using each paragraph's `html` (from `Paragraph.to_display_html()` — bold/italic/super/subscript + rendered citation field-codes), reusing the existing diff/`mark` CSS. Inline **track-changes coloring, comment balloons, and editing** are **M6**. Empty state: "Select a document".
- **Agent chat:** input + message list. Send → `POST /agent/run` with `{message, provider, model, api_key, ollama_url}` from `localStorage`. Render `final_text` and a compact step list. On `status="awaiting_confirmation"` → show the `pending_confirmation.message` with **Confirm / Cancel** → `POST /agent/confirm {confirmed}`. Refresh the document area after a run that edited the model.
- **Save / Save a copy:** "Save" → `POST /save {overwrite:true}` to the open document's path. "Save a copy" → prompt for a new in-workspace filename → `POST /save {path}` (switches active document per M4). Reflect `unsaved_changes` from responses in a header indicator.
- **Unsaved guard:** `beforeunload` warns when `unsavedChanges` (mirrors the card UI). A "Close workspace" action calls `POST /close` (with `force` after confirm).
- **Settings popover:** compact provider/model/api-key/ollama fields backed by the **same `localStorage` keys** as the card settings, populated from `/llm-config`.

---

## 5. Tests to write

- `tests/test_workspace_page.py`: `GET /workspace` → 200; body contains the sidebar/document/chat anchors and references `static/js/workspace.js`.
- Existing full suite stays green, **0 warnings**; `/` card UI unaffected.
- The rest of M5 is **manual QA** (UI behavior, native folder picker) — the plan explicitly accepts this; automated UI testing is not introduced in Stage 1.

Manual QA script (documented in the report): open `/workspace` → pick a folder containing `test_data/synthetic/test.docx` (copied into a temp project with subfolders) → see the tree → open the docx → send "list the open comments" → see a response → trigger a save-as-copy into a subfolder → confirm the original is untouched and the copy appears in the tree.

---

## 6. Out of scope for this milestone

- The full document **viewer** (formatting, track changes, comments, inline editing) — **M6**.
- Reference-file **previews** in the centre panel (PDF/XLSX/CSV rendering) — the agent reads them via `read_file`; previews are deferred.
- Chat **polish**: cancel in-flight runs, step-by-step trace toggle, inline links from messages to document changes — **M7**.
- Replacing `/` with `/workspace` as the default landing — Stage 1 keeps both (see Open question 5).
- Automated browser/E2E tests.

---

## 7. Resolved decisions

All resolved with the project owner on 2026-05-30.

1. **"Save a copy" uses an in-app dialog** (not a native OS save dialog), targeting a path inside the workspace (defaulting to e.g. `<name>_2.docx`). Respects M4 containment; native dialog deferred.

2. **Document area renders read-only formatted HTML** via `Paragraph.to_display_html()` (reused from the card UI), not just plain text — getting most of the way on representation cheaply. Inline track-changes coloring, comment balloons, and editing remain M6.

3. **CSS lives in `static/css/workspace.css`** (separate file; the page grows through M6/M7).

4. **Folder-picker fallback:** when `window.pywebview` is absent (browser/dev/test), fall back to a path **text input**.

5. **Landing page unchanged:** the card UI stays the default at `/`; the workspace lives at `/workspace` for all of Stage 1.

6. **Forward `api_key` / `ollama_url` to `agent/run`.** Precedence: UI-supplied key wins, else `.env` (dev/local uses `.env`; the distributable uses the UI-entered key). Empty UI key → `None` → falls back to `.env`. Never persisted server-side.
