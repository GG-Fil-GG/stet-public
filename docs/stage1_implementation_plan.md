# Stage 1 Implementation Plan

Execution plan for **Stage 1: Agentic Workspace** from [`agentic_stet_roadmap.md`](agentic_stet_roadmap.md).

**Scope of this document:** build order, acceptance criteria, tests, and known caveats. The roadmap remains the vision document; this plan is the sequenced checklist for implementation.

**Prerequisites:** Tier 1 of [`pre_transition_audit.md`](pre_transition_audit.md) is complete (546 tests passing, synthetic fixtures committed, route smoke tests in place).

**Transition strategy:** Build the workspace as a **parallel route** (`/workspace`) alongside the existing card-based UI at `/`. The existing UI is the regression baseline throughout Stage 1 — do not break it.

## Sources of truth

| Document | Role |
|----------|------|
| **This plan** (`docs/stage1_implementation_plan.md`) | Milestone sequence, acceptance criteria, resolved decisions |
| [`docs/stage1_glossary.md`](stage1_glossary.md) | Canonical names for modules, tools, routes, config keys, types, JSON shapes |
| [`docs/stage1_decision_log.md`](stage1_decision_log.md) | Decisions made *during* implementation (running log) |
| [`docs/specs/`](specs/) | Per-milestone specs (`stage1_M{N}_spec.md`) and reports (`stage1_M{N}_report.md`) |
| `.cursor/rules/stage1-*.mdc` | Architectural, scope, naming, and quality invariants enforced across sessions |

Before starting any milestone, read this plan, the glossary, and the relevant cursor rules. After completing any milestone, update the glossary, decision log, and status table below.

---

## Implementation workflow

Stage 1 is implemented hands-off via a strict **spec → approve → implement → report** cycle. This is the single control point that keeps work faithful to the vision without requiring line-by-line review.

### Per-milestone cycle

```
Project owner: "Implement Milestone N."
  ↓
AI: reads plan + glossary + cursor rules + prior milestone reports.
  ↓
AI: writes docs/specs/stage1_M{N}_spec.md (see template in docs/specs/README.md).
  ↓
AI: replies "Spec ready, review and approve."
  ↓
Project owner: reads spec (~3 min). Replies "Approved" or "Change X" or "Wait, what about Y?".
  ↓
AI: implements strictly per the approved spec.
     - Runs full test suite before commit.
     - Updates stage1_glossary.md with any new names.
     - Updates stage1_decision_log.md with any mid-implementation decisions.
     - Updates the Status table in this plan.
  ↓
AI: writes docs/specs/stage1_M{N}_report.md (see template in docs/specs/README.md).
  ↓
AI: commits, pushes, replies "M{N} done, here's the report."
  ↓
Project owner: reads report (~3 min). Replies "OK proceed" or "Hold, let's discuss X."
```

### Standard session-bootstrap prompt

To start any milestone session, the project owner uses:

> "Implement Milestone N per the workflow in `docs/stage1_implementation_plan.md`. Stop after writing the spec; wait for my approval."

That is sufficient. The cursor rules, plan, glossary, and prior reports provide the rest of the context.

### Spec and report templates

See [`docs/specs/README.md`](specs/README.md) for the full templates. In brief:

- **Spec** covers: goal, files to create/modify, public API surface, tests to write, out-of-scope items, open questions.
- **Report** covers: what was done, files touched, deviations from spec, glossary additions, decision-log entries, test results, what to watch next.

### What stops a milestone from proceeding

- Spec has open questions → wait for project owner answers before coding.
- Spec implies a change that contradicts a cursor rule or a Resolved decision → flag in the spec, do not silently override.
- Full test suite fails or introduces new warnings → fix before commit, or document in the report if genuinely out of scope (with project-owner sign-off).
- Discovery of a related issue not covered by the spec → report in the milestone report, do not fix without approval (per `.cursor/rules/stage1-scope.mdc`).

---

## Stage 1 goal (recap)

Transform Stet from a per-comment card tool into an agentic workspace:

- File sidebar (workspace folder on disk)
- Scrollable document viewer with manual editing (TipTap)
- Unified agent chat panel
- Model-agnostic agent loop with tool calling
- Multi-format reference reading (including RTF and PPTX)
- In-memory editing with explicit export
- Snapshot-based undo for agent actions

**Explicitly out of scope for Stage 1 v1:**

- Non-docx **previews** in the document viewer (PDF/XLSX/RTF/PPTX shown in sidebar only; agent reads them via tools)
- **Image reading** (`.jpeg`/`.png` describe/OCR via a vision model) — `read_file` returns `unsupported_format` for images in Stage 1; logged as a **Stage 2 / backlog** item (surfaced in M8 manual QA — see [M8 report §7.1](specs/stage1_M8_report.md))
- **Formatting-preserving agent edits** — `edit_paragraph` goes through the plain-text revision path (`apply_revision_from_plain_text`), which carries no run formatting, so an edit strips run-level formatting (e.g. a bold "Methods:" label) even on unchanged spans. The serializer can preserve formatting only when given revised-HTML segments (the manual TipTap edit path supplies these; the agent path does not). Cosmetic, not data-loss; the fix is cross-cutting (shared revision engine + agent edit path). Logged as a **Stage 2 / backlog** item (surfaced in M9a manual QA — see [M9a report §7.2](specs/stage1_M9a_report.md))
- MCP server architecture (Stage 2)
- Tables, figures, per-change accept/reject UI, comment margin balloons, multi-tab (Stage 3)
- De novo document creation from rich templates (Stage 3+) — Stage 1 includes **blank docx creation at a path** only (`create_document`)

---

## Known caveats and how this plan addresses them

These were identified at Tier 1 completion. Each is assigned to a milestone rather than treated as a pre-Stage-1 blocker.

| Caveat | Impact | Addressed in |
|--------|--------|--------------|
| **Export is thread-acceptance oriented** — current `/export/{session_id}` expects accepted per-thread suggestions | Workspace needs “export in-memory model anytime” | Milestone 2 |
| **`add_comment` / `remove_comment` not fully built** — reply exists; new anchored comments and deletion are incomplete | Agent tools need write/delete comment ops | Milestone 2 |
| **LLM handler has no function calling** — single-turn prompt-in/text-out today | Agent loop cannot run without transport changes | Milestone 3 |
| **Routes return HTMX/HTML only** — no JSON API for workspace UI | Workspace needs parallel JSON endpoints | Milestone 4 |
| **TipTap save logic coupled to card DOM** — `saveTipTapContent` in `templates/base.html` targets `#card-{threadId}` | Document viewer needs decoupled editor module | Milestone 6 |
| **RTF/PPTX readers missing** — PDF/XLSX/CSV/DOCX parsers exist | `read_file` tool incomplete for roadmap formats | Milestone 8 |
| **No agent checkpoint system** — `DocumentModel.to_dict()` exists but no rollback stack | Undo model requires new API + UI hook | Milestone 2 + 9 |
| **Stale audit/doc references** — some docs still mention `test_data/test.docx`, `thread_objects` cache | Confusing for new sessions; no runtime impact | Milestone 0 (optional hygiene) |
| **Dependencies not pinned** — no lockfile | Fine for local dev; address before CI/distribution | Milestone 9 (note only) |
| **`print()` still used in some routes** — e.g. export, attachments | Noise in logs; not blocking | Opportunistic cleanup during touched files |

---

## Architecture decisions

Resolved before implementation. See [Resolved decisions](#resolved-decisions) for rationale.

| Decision | Choice |
|----------|--------|
| Workspace route | `/workspace` (HTML shell) |
| Workspace JSON API | `/api/workspace/...` |
| Workspace = folder on disk | User selects folder via **native folder picker** (`desktop_app.py`); Stet never overwrites source files unless save/export targets that path explicitly |
| Active document state | In-memory `DocumentModel` per open docx |
| Long-term session model | **Workspace sessions replace** the current upload/session dict (parallel during Stage 1; card UI retired after pilot) |
| Agent chat scope | One chat history per workspace session (not per-thread) |
| Save / export | Path-driven: agent tools and user UI both call the same save/export APIs with an explicit target path (see [Resolved decisions §4](#4-save-export-and-create-document)) |
| Checkpoints | Serialized `DocumentModel.to_dict()` snapshots in `.stet/checkpoints/`; **default max 30**, FIFO prune, **configurable** (see [Resolved decisions §3](#3-checkpoint-retention)) |
| Agent loop limits | **Default max 20 tool-call steps** per user message; **configurable** |
| LLM providers (M3) | **Provider-neutral** tool schema + transport adapter; OpenAI + Ollama first; Anthropic plugs in later without loop changes |
| Default app entry (post-pilot) | `/` redirects to `/workspace`; legacy card UI at `/legacy` until removed (see [Resolved decisions §5](#5-default-route-after-stage-1)) |
| New dependencies | `striprtf`, `python-pptx` (require explicit approval per [`ai_development_process.md`](ai_development_process.md)) |

---

## Milestones

### Milestone 0 — Baseline and conventions

**Effort:** ~0.5 day  
**Goal:** Agree on boundaries before feature code.  
**Status:** Complete — see [`stage1_M0_spec.md`](specs/stage1_M0_spec.md) and [`stage1_M0_report.md`](specs/stage1_M0_report.md).

**Tasks:**

- [x] Define workspace on-disk layout (finalized below).
- [x] Finalize `.stet/config.json` schema (finalized below).
- [x] Document test conventions (finalized below).
- [x] Update stale sections of `pre_transition_audit.md` (Codebase context: `thread_objects` cache → on-demand `get_thread_object()`; `test_data/test.docx` → `test_data/synthetic/test.docx`; removed obsolete known-failure note).

#### Workspace conventions (finalized)

**Folder layout.** `.stet/` is a reserved namespace Stet owns; everything else is user content.

```
{workspace_folder}/
  manuscript.docx              # user files — any name, any depth; unchanged until save/export targets them
  references/                  # optional, user-organized (not enforced)
    style_guide.pdf
    notes.rtf
  .stet/                       # reserved — Stet owns this dir
    workspace.json             # session state: open doc, chat history, settings (schema finalized in M4)
    config.json                # workspace configuration (schema below)
    checkpoints/               # agent DocumentModel snapshots (FIFO, default max 30)
```

Rules: file scans (M1 `list_workspace_files`) exclude `.stet/`; user files may live at any depth; Stet never modifies user files until a save/export explicitly targets that path; `.stet/` is safe to delete (loses session state + undo history only) and safe to add to a user `.gitignore`.

**`.stet/config.json` schema (initial Stage 1 key set).** Created with defaults on first workspace open (writing code is M4). Unknown keys are ignored; missing keys fall back to code defaults.

```json
{
  "config_version": 1,
  "max_checkpoints": 30,
  "max_agent_steps": 20,
  "checkpoint_policy": "per_agent_turn"
}
```

| Key | Type | Default | Allowed values / notes |
|-----|------|---------|------------------------|
| `config_version` | int | `1` | Schema version for forward-compatible migrations. |
| `max_checkpoints` | int | `30` | ≥ 1. FIFO prune when checkpoint count exceeds this. |
| `max_agent_steps` | int | `20` | ≥ 1. Hard cap on tool-call iterations per user message. |
| `checkpoint_policy` | str | `"per_agent_turn"` | `"per_agent_turn"` (snapshot before each user message) or `"per_mutating_tool"` (snapshot before each mutating tool call). |

This is the *initial* set. Later milestones add their own keys, each recorded in the glossary by the milestone that introduces it. **Config is per-workspace only in Stage 1** (no global user-level config); a global layer can be added later without breaking this.

**Test conventions.** Synthetic committed fixtures in `test_data/synthetic/`; local-only fixtures in `test_data/local/` (gitignored). New workspace/JSON tests mirror the `tests/test_routes.py` pattern (`TestClient`, JSON-shape assertions, synthetic fixtures, no network/LLM). Agent-loop tests mock the LLM transport; real-LLM integration tests gate on `OPENAI_API_KEY` and skip cleanly when absent. The post-Tier-1 **0-warning baseline** is maintained.

**Acceptance criteria:**

- Workspace folder layout and `.stet/config.json` schema documented in this file (finalized). ✓
- Architecture decisions table complete (no open blockers for M1). ✓
- No user-facing changes. ✓

**Tests:** Existing full suite still passes (546 passing, 0 warnings).

---

### Milestone 1 — Tool layer

**Effort:** ~2–3 days  
**Goal:** Callable tools wrapping existing code, testable without UI or LLM.  
**Maps to roadmap:** Step 1 (tool schemas).

**New modules (proposed):**

```
src/agent/
  tools.py           # Tool function implementations
  tool_schemas.py    # Pydantic models / JSON schemas for LLM providers
  registry.py        # name → handler + schema
```

**Tools to implement:**

| Tool | Wraps / notes |
|------|----------------|
| `list_workspace_files()` | Scan workspace folder; return name, path, type, size |
| `read_document(path)` | `parse_docx` → summary (paragraph count, thread count, metadata) |
| `list_comments(path, filter?)` | Threads with IDs, status, referenced text |
| `read_paragraph(doc, para_id)` | Text, formatting summary, associated comments |
| `edit_paragraph(doc, para_id, new_text, track_changes)` | `DocumentModel.apply_edit` — both modes (Tier 1 plain-edit export already fixed) |
| `add_comment_reply(doc, thread_id, text)` | Existing `DocumentModel.add_reply` |
| `read_file(path)` | Dispatch to `file_parsers/*` (PDF, XLSX, CSV, DOCX attachment parser initially) |
| `export_document(doc, path)` | Serialize in-memory model to `path` (workspace-relative or absolute within workspace) |
| `create_document(path)` | Create a new blank docx at `path` from a bundled minimal template; open in workspace |

**Defer to Milestone 2:** `add_comment`, `remove_comment` (domain gaps). Path validation and **mandatory overwrite confirmation** for save/create tools (see [Resolved decisions §4](#4-save-export-and-create-document)).

**Acceptance criteria:**

- Each tool callable from Python with typed inputs/outputs.
- JSON-serializable tool results for agent loop consumption.
- No LLM or browser required to test.

**Tests:**

- New `tests/test_agent_tools.py` (unit tests per tool, synthetic docx fixtures).
- Reuse patterns from `tests/test_file_parsers.py`, `tests/test_serializer.py`.

---

### Milestone 2 — Domain gaps for agent editing

**Effort:** ~2–3 days  
**Goal:** Close gaps the tool layer cannot wrap yet.  
**Maps to roadmap:** Steps 8–9 (comment write/delete, snapshots) + file mutation model (export anytime).

**Tasks:**

1. **`add_comment(doc, para_id, start, end, text)`**
   - High-level API on `DocumentModel` / `CommentStore`
   - Create anchor + comment XML via serializer (`serializer_comments.py`)

2. **`remove_comment(doc, comment_id)`**
   - Model mutation removing comment and range markers
   - Serializer path to strip `w:comment`, `w:commentRangeStart`, `w:commentRangeEnd`

3. **Workspace save / export**
   - Single code path for agent tools and user UI
   - `export_document(doc, path)` — write current in-memory model to `path`
   - `create_document(path)` — new blank docx from bundled template (enables “create file X in subdirectory” via agent)
   - Paths must resolve inside the workspace folder (or prompt for confirmation if overwriting an existing file)
   - Keep existing `/export/{session_id}` for legacy card UI until `/legacy` is removed

4. **Agent checkpoints**
   - `save_checkpoint(model) → checkpoint_id`
   - `restore_checkpoint(checkpoint_id) → DocumentModel`
   - Use `to_dict()` / `from_dict()`; verify comment identity after restore (Tier 1 item 2 guarantees)
   - Retention: FIFO prune when count exceeds `max_checkpoints` (default **30**, configurable in `.stet/config.json`)
   - Policy: default one checkpoint **per agent turn** (before tools run); optional `per_mutating_tool` for finer undo (configurable)

**Caveat addressed:** Export acceptance coupling, missing comment ops, no undo infrastructure, verbal save/create via shared tools.

**Acceptance criteria:**

- Agent can add a new comment, reply, remove a comment, edit a paragraph, export — all without card UI.
- Checkpoint restore returns identical model state (including comment object identity where applicable).

**Tests:**

- `tests/test_comment_write_delete.py` (new)
- Extend `tests/test_model_serialization.py` for checkpoint round-trip
- Serializer tests for new comment XML paths

---

### Milestone 3 — Agent loop

**Effort:** ~2–3 days  
**Goal:** Multi-turn, provider-agnostic tool-calling loop.  
**Maps to roadmap:** Step 2.  
**Addresses Tier 2:** LLM handler lacks function calling.

**New modules (proposed):**

```
src/agent/
  loop.py            # Agent loop orchestration
  llm_tools.py       # Provider-specific tool-call dispatch (extends llm_transport.py)
```

**Tasks:**

- [ ] **Provider-neutral adapter layer** — tool schemas in a single format; per-provider translation in `llm_tools.py` (OpenAI and Ollama first). Anthropic adapter added later without changing the loop or tool handlers.
- [ ] Extend `src/llm_transport.py` for function/tool calling (OpenAI + Ollama minimum).
- [ ] Tool registry integration: LLM receives schemas, returns tool calls, loop executes handlers, feeds results back.
- [ ] Error policy: **report and skip** by default; configurable **stop and ask**.
- [ ] Verbosity: summary mode (default) vs detailed tool trace (for testing/debug).
- [ ] Enforce `max_agent_steps` (default **20**, configurable) per user message.
- [ ] Register Milestone 2 tools including `add_comment`, `remove_comment`, `create_document`.

**Acceptance criteria:**

- Given a user message and loaded document, agent can call `list_comments` → `edit_paragraph` → respond with summary.
- Loop terminates cleanly on completion, error, or max steps.
- Works with mock LLM in tests; one optional integration test with real API (gated on `OPENAI_API_KEY`).

**Tests:**

- `tests/test_agent_loop.py` — mock tool-call sequences
- Optional: `tests/test_agent_integration.py` — real LLM, skipped without key

**Note:** Anthropic is not wired in M3 (no API account yet). The adapter interface must be ready so adding Anthropic later is a transport-only change.

---

### Milestone 4 — Workspace backend

**Effort:** ~1–2 days  
**Goal:** “Point Stet at a folder” via JSON API, no UI polish yet.  
**Maps to roadmap:** Step 3.  
**Addresses Tier 2:** Route responses HTML-only → parallel JSON routes.

**New modules (proposed):**

```
src/routes/workspace.py      # JSON API router
src/workspace/               # Workspace state management
  state.py
  folder.py
```

**Endpoints (proposed):**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/workspace/open` | Set workspace folder path |
| `GET` | `/api/workspace/files` | File tree for sidebar |
| `POST` | `/api/workspace/document/open` | Load docx into workspace session |
| `GET` | `/api/workspace/document` | Current document summary / paragraph list |
| `POST` | `/api/workspace/agent/run` | Send message, run agent loop |
| `POST` | `/api/workspace/checkpoint/restore` | Roll back to checkpoint |
| `POST` | `/api/workspace/export` | Save/export active document to explicit path |
| `POST` | `/api/workspace/document/create` | Create new blank docx at path |

**Tasks:**

- [ ] Workspace session distinct from (but reusing patterns of) existing upload sessions — **long-term replaces** upload session dict (see [Resolved decisions §7](#7-workspace-sessions-vs-upload-sessions)).
- [ ] Persist workspace state to `.stet/workspace.json` (or equivalent per M0 layout).
- [ ] Wire agent loop from M3 to `/agent/run`.

**Acceptance criteria:**

- TestClient can open a folder, list files, open a docx, run agent message, receive JSON response with change summary.
- Original docx on disk unchanged until export.

**Tests:**

- `tests/test_workspace_api.py` — JSON route smoke tests (mirror `tests/test_routes.py`)

**Caveat:** Remaining `print()` in routes — convert to logging in files touched here if straightforward.

---

### Milestone 5 — Workspace UI shell

**Effort:** ~2–3 days  
**Goal:** Three-panel layout at `/workspace`, wired to M4 backend.  
**Maps to roadmap:** Step 4 (file sidebar) + partial Step 6 (chat shell).

**Tasks:**

- [x] New template: `templates/workspace.html` — file sidebar | document area | agent chat.
- [x] Register `GET /workspace` in `main.py`.
- [x] **Native folder picker** (`Api.pick_folder()`) in `desktop_app.py`; browser/dev fallback to a path text input.
- [x] File sidebar: tree view from `/api/workspace/{id}/files`; docx click → open document.
- [x] **Non-docx files:** show in sidebar with type icon and filename only — **no preview panel** (deferred).
- [x] **Save / Save a copy** buttons call `/api/workspace/{id}/save` (overwrite confirm; copy uses an in-app prompt and switches the active doc); same underlying API as agent verbal save.
- [x] Agent chat panel (input + message list + confirm) wired to `/api/workspace/{id}/agent/run` + `/agent/confirm`; forwards `api_key`/`ollama_url`.
- [x] Document area: read-only **formatted** render (`to_display_html()`); full viewer is M6.

**Acceptance criteria:**

- User can open `/workspace`, select folder, see file tree, open a docx, send agent message, see response in chat.
- Existing `/` card UI unchanged and still works.

**Tests:**

- Manual QA + existing suite passes.
- Optional: minimal route test that `/workspace` returns 200.

**Deferred:** Reference file previews in centre panel (PDF text, XLSX table, etc.) — agent reads via `read_file` tool regardless.

---

### Milestone 6 — Document viewer

> **Split (2026-06-01):** delivered in two approve→implement→report cycles — **M6a** (read fidelity: renderer, inline track changes, anchored comments + side list) then **M6b** (edit mode: standalone TipTap editor, per-paragraph save, pre-edit checkpoint). See [M6 umbrella](specs/stage1_M6_spec.md), [M6a](specs/stage1_M6a_spec.md), [M6b](specs/stage1_M6b_spec.md).

**Effort:** ~3–5 days  
**Goal:** Continuous scrolling docx view with reading, track changes, comments, and editing.  
**Maps to roadmap:** Step 5.  
**Addresses Tier 2:** TipTap save logic decoupled from card UI.

**Tasks:**

1. **Read mode**
   - Render all body paragraphs sequentially in scroll container.
   - Reuse HTML conversion from `src/routes/helpers.py`, `src/diff_html.py`.

2. **Track changes inline**
   - Insertions highlighted, deletions with strikethrough (same visual language as cards).

3. **Comments inline**
   - Show anchored comments beside referenced text (margin balloon layout deferred to Stage 3).

4. **Edit mode**
   - Extract TipTap initialisation/save into a reusable JS module with callbacks (not `#card-{threadId}` selectors).
   - Toolbar: bold, italic, underline, superscript, subscript (existing capabilities).
   - Saves apply to `DocumentModel` via new JSON endpoint (e.g. `PATCH /api/workspace/paragraph/{para_id}`).

5. **Refresh after agent run**
   - Document viewer reloads when agent completes a turn.

**Acceptance criteria:**

- Full docx visible in scroll view with formatting, track changes, and comments.
- User can click a paragraph, edit in TipTap, save — change reflected in model and viewer.
- Card UI at `/` still works independently.

**Tests:**

- HTML rendering unit tests (paragraph list → expected structure).
- Manual QA on `test_data/synthetic/test.docx` and a real manuscript from `test_data/local/`.

**Out of scope:** Tables as HTML (Stage 3), headings/outline, images.

---

### Milestone 7 — Agent chat panel (complete)

**Effort:** ~2–3 days  
**Goal:** Production-quality unified chat, not just shell.  
**Maps to roadmap:** Step 6.

**Can overlap with M6** once M4 backend exists.

**Tasks:**

- [ ] Chat history persisted in workspace state (survives restart).
- [ ] Interrupt/cancel in-flight agent run (`POST /api/workspace/agent/cancel` or equivalent).
- [ ] “Show details” toggle: summary vs step-by-step tool trace.
- [ ] Display agent errors inline (report-and-skip vs stop-and-ask modes).
- [ ] Link chat messages to document changes where applicable (“Updated paragraph 12…”).

**Acceptance criteria:**

- Multi-turn conversation with context retained.
- User can cancel a long-running agent task.
- Chat history reloads when workspace reopens.

**Tests:**

- API tests for chat persistence and cancel.
- Manual QA: multi-step agent task with details toggle.

---

### Milestone 8 — RTF and PPTX file readers

**Effort:** ~1–2 days  
**Goal:** Complete `read_file` for all roadmap formats.  
**Maps to roadmap:** Step 7.

**Included per project decision:** RTF and PPTX are in scope. Non-docx **previews** remain deferred (M5).

**Tasks:**

- [ ] Add `src/file_parsers/rtf_parser.py` using `striprtf`.
- [ ] Add `src/file_parsers/pptx_parser.py` using `python-pptx` (slide text + notes → markdown/plain).
- [ ] Unified `read_file(path)` dispatch in `src/agent/tools.py` covering:

  | Format | Status |
  |--------|--------|
  | PDF | Exists |
  | CSV/XLSX/XLS | Exists |
  | DOCX (reference read) | Exists (`docx_parser.py`) |
  | Plain text | Add if not already covered |
  | RTF | **New** |
  | PPTX | **New** |

- [ ] Add `striprtf`, `python-pptx` to `requirements.txt` (with project owner approval).
- [ ] Add synthetic fixtures: minimal `.rtf` and `.pptx` in `test_data/synthetic/attachments/`.

**Acceptance criteria:**

- `read_file` returns extracted text for all formats above.
- Agent can read a reference RTF/PPTX in workspace folder during a run.

**Tests:**

- Extend `tests/test_file_parsers.py` for RTF and PPTX.
- Agent tool test calling `read_file` on each fixture.

**Caveat addressed:** RTF/PPTX readers missing.

---

### Milestone 9 — Integration and hardening

**Effort:** ~2–3 days  
**Goal:** Stage 1 complete; ready for real-manuscript pilot.  
**Addresses Tier 2:** Test coverage grows with new code.

**Tasks:**

- [ ] End-to-end walkthrough:
  1. Open workspace folder with docx + reference PDF/XLSX/RTF/PPTX
  2. Open manuscript in viewer
  3. Agent addresses a comment via natural language
  4. User sees tracked change in viewer
  5. User edits manually in TipTap
  6. User restores a checkpoint
  7. User exports; open in Word and verify track changes

- [ ] Expand automated tests for all new routes, tools, and parsers.
- [ ] **Agent Unicode protection:** port the card UI's special-character placeholders (`llm_prompts._protect_unicode` / `llm_transport.UNICODE_PROTECTION_MAP`) into the M3 agent path so `edit_paragraph` `new_text` does not corrupt symbols like `≥`, `≤`, `±` when the LLM re-types a paragraph. (Surfaced in M6b manual QA — see [M6b report §7.2](specs/stage1_M6b_report.md).)
- [ ] **Expose workspace config in the settings UI:** the `/workspace` settings modal only edits LLM credentials; `tool_error_policy` (and `max_agent_steps`, `checkpoint_policy`, `max_checkpoints`) are editable via `PUT …/config` but have no UI control. Add selectors so `stop_and_ask` is testable from the UI and the config surface is complete. (Surfaced in M7 manual QA — see [M7 report §7.2](specs/stage1_M7_report.md).)
- [ ] Decide default route after pilot sign-off: **`/` redirects to `/workspace`**; card UI moves to `/legacy` until removed (see [Resolved decisions §5](#5-default-route-after-stage-1)).
- [ ] Desktop app (`desktop_app.py`): folder picker (M5) + save dialog for Save/Save As.
- [ ] *(Note only)* Dependencies not pinned — document as follow-up before CI/distribution (Tier 3 audit item).
- [ ] Update `docs/pre_transition_audit.md` Tier 2 items as completed where applicable.
- [ ] Mark Stage 1 complete in roadmap / this plan.

**Acceptance criteria:**

- Full test suite passes (target: maintain 0 warnings policy from post-Tier-1 cleanup).
- Manual pilot on at least one real manuscript from `test_data/local/`.
- Existing card UI at `/` still functional.

---

## Build order summary

```
M0  Baseline and conventions
 ↓
M1  Tool layer (read / edit / list / read_file partial)
 ↓
M2  Comment add/remove, workspace export, checkpoints
 ↓
M3  Agent loop (tool calling)
 ↓
M4  Workspace JSON API
 ↓
M5  Workspace UI shell (sidebar + chat shell; no docx preview yet)
 ↓
M6  Document viewer (parallel with M7)
M7  Agent chat panel (complete)
 ↓
M8  RTF + PPTX readers
 ↓
M9  Integration and hardening
```

**Recommended first demo (after M4):** Open folder → agent lists comments → edits paragraph → JSON response shows summary. Validates tools + loop before document viewer exists.

---

## Testing strategy (Stage 1)

| Layer | Approach |
|-------|----------|
| Tool functions | Unit tests, synthetic fixtures, no LLM |
| Domain (comments, checkpoints) | Unit + serializer round-trip tests |
| Agent loop | Mock LLM tool-call sequences; optional real-LLM integration test |
| Workspace API | TestClient JSON tests (`tests/test_workspace_api.py`) |
| Document viewer | HTML structure tests + manual QA |
| Regression | Full suite before every commit; card UI smoke via `tests/test_integration.py` |

Real-manuscript validation remains the project owner's responsibility per [`ai_development_process.md`](ai_development_process.md).

---

## Relationship to other documents

| Document | Role |
|----------|------|
| [`agentic_stet_roadmap.md`](agentic_stet_roadmap.md) | Vision, stages, design principles |
| **This document** | Stage 1 execution sequence and acceptance criteria |
| [`stage1_glossary.md`](stage1_glossary.md) | Canonical names introduced during Stage 1 |
| [`stage1_decision_log.md`](stage1_decision_log.md) | Decisions made during Stage 1 implementation |
| [`specs/README.md`](specs/README.md) | Per-milestone spec and report templates |
| [`pre_transition_audit.md`](pre_transition_audit.md) | Pre-transition cleanup (Tier 1 done; Tier 2 items mapped above) |
| [`ai_development_process.md`](ai_development_process.md) | Spec-first development doctrine; this plan applies it to Stage 1 |
| `.cursor/rules/stage1-*.mdc` | Persistent invariants enforced across sessions |

---

## Resolved decisions

All open questions from the initial plan are resolved.

### 1. Workspace folder picker

**Decision:** Native folder-picker dialog in `desktop_app.py` is **required for M5** (not optional manual path entry).

---

### 2. Anthropic and model-agnostic design

**Decision:** Stage 1 agent loop is **provider-neutral by design**. OpenAI and Ollama are implemented first. Anthropic is added later via a transport adapter when an API account is available — no changes to tool schemas, tool handlers, or loop logic.

**Implementation note (M3):** One canonical tool schema (JSON Schema / Pydantic); thin per-provider adapters translate to OpenAI `tools`, Ollama tool format, and later Anthropic `tools`.

---

### 3. Checkpoint retention

**What checkpoints are:** Yes — **document snapshots**. Before the agent mutates the document, Stet serializes the in-memory `DocumentModel` (`to_dict()`) to disk. Rolling back restores that snapshot into memory (and refreshes the viewer). This is undo for agent-driven edits, separate from per-thread chat suggestion rollback.

**Recommended defaults:**

| Setting | Default | Configurable |
|---------|---------|--------------|
| `max_checkpoints` | **30** | Yes (`.stet/config.json`) |
| `checkpoint_policy` | `per_agent_turn` — one snapshot before each user message is processed | Yes; alternative `per_mutating_tool` for finer undo (more disk use) |
| Pruning | FIFO — delete oldest when over limit | — |

**Why 30?** Agent turns are frequent; medical manuscripts produce large JSON snapshots. Thirty turns of undo is generous for a working session without unbounded disk growth. Tune after pilot testing.

**Why configurable?** Power users and long sessions may want more (or fewer) snapshots; policy choice affects disk vs granularity.

---

### 4. Save, export, and create document

**Original question was:** where does the Export button write files?

**Expanded requirement:** Saving docx files must work **three ways**, all through the **same backend APIs**:

| Trigger | Example | Mechanism |
|---------|---------|-----------|
| **Agent (verbal)** | “Create a new docx called `draft.docx` in `revisions/`” | Agent calls `create_document(path)` |
| **Agent (verbal)** | “Revise to address comments in `manuscript.docx` and save as `manuscript_v2.docx`” | Agent edits in memory, then calls `export_document(doc, path)` |
| **User (UI)** | Save / Save As buttons | Native **save dialog** → same `export_document` API with chosen path |

**Rules:**

- Paths are **always explicit** (agent supplies path in tool args; user supplies path in save dialog).
- Paths must lie **inside the workspace folder** (prevent accidental writes elsewhere).
- **Overwrite always requires explicit confirmation** for both triggers:
  - **User (UI):** native OS confirmation dialog (“File exists — overwrite?”) before write.
  - **Agent (verbal):** agent must ask the user in chat and receive a confirmation reply before calling `export_document` / `create_document` on an existing path. Never overwrite silently, even if the agent inferred the user’s intent.
  - Writing to a **new** path proceeds without prompting.
- Stage 1 errs on the side of caution. We may relax to “only ask on first overwrite per session” later if it proves annoying.
- Original uploaded files are **not** modified until save/export targets that path — in-memory editing remains the default.

**Scope note:** “Create new docx” uses a **bundled blank template** (minimal valid docx with standard styles). Full de novo authoring from scratch remains Stage 3+ polish; Stage 1 only needs empty-file creation at a path.

---

### 5. Default route after Stage 1

**What this question means:**

Today, opening Stet loads **`/`** — the **card-based UI** (upload a docx, one card per comment thread). Stage 1 builds **`/workspace`** — the new three-panel agentic UI.

The question is: **which UI opens by default when the user launches the app?**

| Phase | Behaviour |
|-------|-----------|
| **During Stage 1 development** | `/` stays the card UI (regression baseline). `/workspace` is accessed explicitly. |
| **After pilot sign-off (M9)** | **`/` redirects to `/workspace`**. Card UI remains temporarily at **`/legacy`** for fallback, then removed in a later cleanup. |

This avoids breaking the app mid-development while making the workspace the primary experience once it is ready.

---

### 6. Agent max steps

**Decision:** Hard cap on tool-call iterations per user message. **Default: 20 steps.** Configurable in `.stet/config.json` (`max_agent_steps`). Tune after real-world testing.

---

### 7. Workspace sessions vs upload sessions

**Decision:** **Long-term, workspace sessions replace** the current upload/session dict in `src/routes/state.py`.

**During Stage 1:** Both coexist — workspace has its own state; card UI keeps the existing session model so nothing breaks.

**What moves into workspace session state:**

| Current session field | Workspace equivalent |
|----------------------|----------------------|
| `model` (DocumentModel) | Same — per open document |
| `filename`, filepath | Same — plus workspace-relative paths |
| `output_dir` | `.stet/` inside workspace folder |
| `thread_status`, `suggestions` | Retired — agent applies edits directly; viewer shows track changes |
| Per-thread `chat_history`, `chat_mode_active` | Replaced by **unified workspace agent chat** |
| `context_settings`, `thread_instructions` | Agent context from tools + workspace chat; per-thread card settings retired |
| `attachments` | Workspace-level reference files (folder contents) + optional per-doc attachments |
| Persistence (`session.json`) | `.stet/workspace.json` |

**Recommendation:** Yes — include all information needed to restore a working session, but **do not copy** card-UI-specific structures (suggestions pending accept, per-thread chat mode) into the long-term model. The workspace session is simpler: open document(s), agent chat history, checkpoints, config.

**End state:** Remove upload flow and `sessions` dict once `/legacy` is removed.

---

## Effort estimate (total)

| Milestone | Days |
|-----------|------|
| M0 | 0.5 |
| M1 | 2–3 |
| M2 | 2–3 |
| M3 | 2–3 |
| M4 | 1–2 |
| M5 | 2–3 |
| M6 | 3–5 |
| M7 | 2–3 |
| M8 | 1–2 |
| M9 | 2–3 |
| **Total** | **~18–28 days** |

Aligns with the roadmap’s “medium” Stage 1 estimate. Milestones M6 and M7 are the largest unknowns.

---

## Status

Update this table as part of each milestone report.

| Milestone | Status | Spec | Implementation commit | Report | Deviations? |
|-----------|--------|------|------------------------|--------|-------------|
| M0 — Baseline and conventions | Complete | [spec](specs/stage1_M0_spec.md) | _docs-only_ | [report](specs/stage1_M0_report.md) | None |
| M1 — Tool layer | Complete | [spec](specs/stage1_M1_spec.md) | `src/agent/` + tests | [report](specs/stage1_M1_report.md) | None |
| M2 — Domain gaps for agent editing | Complete | [spec](specs/stage1_M2_spec.md) | comments add/remove + checkpoints + guarded writers | [report](specs/stage1_M2_report.md) | 1 finding (shared run-splitter bug) — fixed in follow-up |
| M3 — Agent loop | Complete | [spec](specs/stage1_M3_spec.md) | `src/agent/{messages,prompts,llm_tools,loop}.py` + `mutating` flag + tests | [report](specs/stage1_M3_report.md) | None (OpenAI + Ollama both implemented; live Ollama verified) |
| M4 — Workspace backend | Complete | [spec](specs/stage1_M4_spec.md) | `src/workspace/` + `src/routes/workspace.py` + `path_args` + tests | [report](specs/stage1_M4_report.md) | None |
| M5 — Workspace UI shell | Complete | [spec](specs/stage1_M5_spec.md) | `/workspace` page + `templates/workspace.html` + `static/{js,css}/workspace.*` + creds/`html` API tweaks + `Api.pick_folder()` + tests | [report](specs/stage1_M5_report.md) | Manual-testing follow-ups (report §8): added `find_in_document` tool, fixed `[object Object]` error rendering, added the unsaved-changes guard on document switch, and added a Close-document action |
| M6 — Document viewer (umbrella) | Split into M6a + M6b | [spec](specs/stage1_M6_spec.md) | — | — | — |
| M6a — Document viewer: read fidelity | Complete | [spec](specs/stage1_M6a_spec.md) | `src/workspace/render.py` (`render_document`/`Block`) + `GET /document` `blocks`+`comments` + viewer (blocks, track changes, comment highlights, side list, click-linking) + parser `<w:delText>` capture + tests | [report](specs/stage1_M6a_report.md) | QA fix: deletions now render (parser captured `<w:delText>`). Deferred: soft breaks (`<w:br/>`); in-session edits as tracked changes → M6b; side-list alignment/balloons → Stage 3 |
| M6b — Document viewer: edit mode | Complete | [spec](specs/stage1_M6b_spec.md) | `PATCH /document/paragraph/{para_id}` + `doc_editor.js` + viewer edit flow + RevisionStore diff overlay + tests | [report](specs/stage1_M6b_report.md) | QA: table alignment fixed (M6b regression). Agent Unicode mangling → M9 |
| M7 — Agent chat panel | Complete | [spec](specs/stage1_M7_spec.md) | chat log + cancel/clear API + panel UX | [report](specs/stage1_M7_report.md) | None (mid-LLM cancel deferred per spec §9) |
| M8 — RTF and PPTX file readers | Complete | [spec](specs/stage1_M8_spec.md) | `rtf_parser.py` + `pptx_parser.py` + `read_file` dispatch + tests | [report](specs/stage1_M8_report.md) | PPTX title-dedup bug fixed during impl (decision log) |
| M9 — Integration and hardening (umbrella) | Split into M9a + M9b + M9c | [spec](specs/stage1_M9_spec.md) | — | — | Decisions resolved 2026-06-03 (spec §8). One umbrella spec covers M9a+M9b; M9c gets its own spec post-pilot |
| M9a — Agent Unicode protection | Complete | [spec](specs/stage1_M9_spec.md) §4 | `src/agent/unicode_protection.py` + protect/restore wired into `AgentLLMClient` + tests | [report](specs/stage1_M9a_report.md) | Verbatim card-UI map (parity test guards drift); always-on; provider-bound copies only |
| M9b — Workspace config in settings UI | Complete | [spec](specs/stage1_M9_spec.md) §5 | Workspace settings block in modal + `loadWorkspaceSettings`/`PUT config` in `workspace.js` + page test | [report](specs/stage1_M9b_report.md) | UI-only (config API existed since M4); closes M7 QA gap; browser-verified |
| M9c-prep — Make long agent runs workable | Complete (manual re-pilot pending) | [spec](specs/stage1_M9c_prep_spec.md) | Per-step logging + `agent/progress` route/polling + `trim_conversation` (`context_token_budget` key) + bounded OpenAI calls + intra-step cancel + tests | [report](specs/stage1_M9c_prep_report.md) | First pilot attempt (2026-06-10) found long runs invisible/slow/uncancellable; fixed without new context-management machinery |
| M9d — Post-pilot correctness & UX fixes | Complete (manual re-pilot pending) | [spec](specs/stage1_M9d_spec.md) | Working-model snapshots in `.stet/working/` (restore-if-unchanged, clear on same-path save) + open-guard test + file-tree tooltips + agent dash/ellipsis/nb-hyphen protection (parity relaxed to superset) + tests. Pilot-driven additions (report §7a): OpenAI retries 0→3, per-run transcripts in `.stet/runs/` + wired-up INFO logging | [report](specs/stage1_M9d_report.md) | Fixes the M9c pilot's edit-durability data loss, truncated filenames, en/em-dash corruption; reuses existing model serialization + the M9a seam. Route-flip closeout resumes after a clean re-pilot |
| M9e — Field-safe editing, dashes, comment-reply behaviour | Complete (manual re-pilot pending) | [spec](specs/stage1_M9e_spec.md) | Serialize-time balance safety net (always-valid export; clean citation drop) + `removed_citations` visibility + EndNote-field fixture (`citation_field.docx`) + citation/comment-reply prompt policy + `addresses_thread_id` linkage param + dash fix (A/B chose: keep token protection + numeric-range repair) + tests (795 passed, 1 skipped, 0 warnings) | [report](specs/stage1_M9e_report.md) | M9d re-pilot (2026-09-22) saved an unopenable `.docx` (LLM drops `[CITATION_n]` placeholders → unbalanced field runs), dropped en-dashes, and left no comment replies. Findings #4 (live viewer refresh) + #5 (search efficiency) logged to future_improvements. Route-flip closeout resumes after a clean re-pilot |
| M9c — Pilot + closeout | Pilot run 2026-06-10 (blocked); closeout pending M9e | [checklist](specs/stage1_M9c_pilot_checklist.md) | — | — | Pilot findings → [M9d](specs/stage1_M9d_spec.md) then [M9e](specs/stage1_M9e_spec.md); default-route flip on HOLD until a clean re-pilot; audit/status update; save-anywhere + dep-pin deferred |

**Status values:** Not started · Spec drafted · Spec approved · In progress · Complete · Held

**Spec / Report columns:** link to `docs/specs/stage1_M{N}_spec.md` / `stage1_M{N}_report.md` once created.

**Deviations column:** link to the relevant section of the report if implementation differed from the approved spec.
