# Pre-Transition Audit

Findings from a full codebase audit conducted before starting the Agentic Stet roadmap. Organized by when each item should be addressed.

---

## Codebase context

This section provides essential context for anyone working on the items below without prior familiarity with the codebase.

### What Stet is

Stet is a local-first AI tool for medical writers. It parses `.docx` files, lets an AI address reviewer comments, and exports the result as a `.docx` with track changes and full formatting fidelity. It runs as a desktop app (pywebview wrapping a local web server).

### Tech stack

- **Backend:** Python 3.12+, FastAPI, Jinja2 templates, HTMX
- **Frontend:** HTMX for dynamic updates, TipTap (ProseMirror-based) for rich text editing, Tailwind CSS via CDN
- **Desktop shell:** pywebview
- **LLM providers:** OpenAI API, Ollama (local)
- **DOCX handling:** lxml for XML parsing/manipulation (not python-docx)

### Project structure

```
main.py                        # FastAPI app entry point
desktop_app.py                 # pywebview desktop wrapper
src/
  document_model/              # Core domain: DocumentModel, Paragraph, Run, comments, revisions
    model.py                   #   DocumentModel (single source of truth for document state)
    paragraph.py               #   Paragraph and Run types
    comments.py                #   CommentStore, Comment, CommentThread, CommentAnchor
    revisions.py               #   RevisionStore, Revision types
    edits.py                   #   DocumentEdit, EditType
    parser.py                  #   DocumentParser: DOCX ZIP → DocumentModel
    serializer.py              #   DocumentSerializer: DocumentModel → DOCX ZIP
    plain_text.py              #   PlainTextView: model ↔ plain text bridge for LLM
    utils.py                   #   ID generation helpers
  routes/                      # FastAPI routers, one per feature area
    state.py                   #   Global sessions dict and get_session/save_session
    helpers.py                 #   Shared rendering helpers
    upload.py, export.py, threads.py, suggestions.py, chat.py, etc.
  diff_utils.py                # Text diffing, HTML diff rendering, Word XML diff emission
  session_utils.py             # Session serialization, LLM adapter types, paragraph cache
  llm_handler.py               # LLM API calls and prompt building
  context_utils.py             # Context window building for LLM prompts
  file_parsers/                # PDF, XLSX, DOCX attachment readers
  llm_config.py, token_counter.py, output_manager.py, paths.py, constants.py, exceptions.py
templates/                     # Jinja2 HTML templates (base.html, partials/)
tests/                         # pytest test suite (~490 test functions across 15 modules)
config/                        # llm_providers.yaml
```

### Key architectural concepts

- **`DocumentModel`** is the single source of truth for document state. All mutations go through `DocumentModel.apply_edit()`. Export serializes this model back to DOCX.
- **`Paragraph.plain_text`** contains `[CITATION_X]` placeholders for field codes (sent to LLM). **`Paragraph.raw_text`** / **`display_text`** contains the original display text (e.g., `[9]`). These two representations must stay in sync.
- **Sessions** are in-memory dicts stored in `src/routes/state.py`. They hold the `DocumentModel`, suggestions, chat history, and are optionally persisted to JSON on disk.
- **Thread objects** are built **on demand** from the live `DocumentModel` via `get_thread_object()` in `src/routes/state.py` (Tier 1 item #3 removed the stale `thread_objects` cache). Callers always see current state after DOM edits.
- **Track changes** are serialized as OOXML `w:ins`/`w:del` markup by the serializer. The model stores revisions in `RevisionStore`; the serializer converts them to XML during export.

### How to run tests

```bash
.venv/bin/python -m pytest tests/ -v
```

Note: Tests use committed synthetic fixtures under `test_data/synthetic/` (e.g. `test_data/synthetic/test.docx`), so they no longer skip on a missing local file. As of Tier 1 completion the full suite passes with no known failures and a 0-warning baseline.

---

## Tier 1: Fix before starting Stage 1

These are blockers or near-blockers for the roadmap. Address as a focused cleanup sprint.

### Checklist

- [x] **1. Serializer cannot export plain edits**
  - `_serialize_document_xml` only writes body text changes when `include_track_changes=True` AND `model.revisions.pending_count > 0`. Edits with `track_change=False` update the in-memory `DocumentModel` but are silently lost on export.
  - The roadmap calls for two editing modes (tracked and plain). Plain edits must produce output.
  - **Fix:** Add a serializer path that writes the model's current paragraph text to `document.xml` when paragraphs have been modified, regardless of revision state.
  - **Files:** `src/document_model/serializer.py` (primarily `_serialize_document_xml` and `_serialize_revisions`)
  - **Test:** Add tests in `tests/test_serializer.py` that create a `DocumentModel`, apply an edit with `track_change=False`, serialize, and verify the exported DOCX contains the modified text. Run full suite afterwards: `.venv/bin/python -m pytest tests/ -v`
  - **Effort:** ~1–2 days

- [x] **2. CommentStore round-trip creates duplicate object graphs**
  - After `to_dict()` / `from_dict()`, `store.comments[id]` and `store.threads[thread_id].root` are different Python objects built from the same data. Mutating one does not update the other.
  - This undermines the snapshot/undo system, which relies on `to_dict`/`from_dict` for checkpoints. After restoring a checkpoint, comment state can silently diverge.
  - **Fix:** `CommentStore.from_dict` should wire thread trees to reference the same `Comment` instances in `store.comments`, not create separate copies.
  - **Files:** `src/document_model/comments.py` (`CommentStore.from_dict`, `CommentThread.from_dict`)
  - **Test:** Add a test in `tests/test_model_serialization.py` that round-trips a `CommentStore` and asserts `store.comments[id] is store.threads[thread_id].root` (object identity, not just equality). Run: `.venv/bin/python -m pytest tests/test_model_serialization.py tests/test_document_model.py -v`
  - **Effort:** ~half day

- [x] **3. `thread_objects` cache is never invalidated**
  - `session["thread_objects"]` is populated once in `get_session()` and never refreshed after DOM edits. Multiple routes read from this stale cache (`chat.py`, `attachments.py`, `threads.py`) instead of querying the live `DocumentModel`.
  - Causes subtle context/highlighting drift after edits are applied. Would carry forward into any new UI that reads from the same session dict.
  - **Fix:** Either remove `thread_objects` entirely (always rebuild from the live model) or add explicit invalidation after every DOM mutation.
  - **Files:** `src/routes/state.py` (`get_session`), `src/routes/chat.py`, `src/routes/attachments.py`, `src/routes/threads.py`
  - **Test:** Run full suite: `.venv/bin/python -m pytest tests/ -v`. Manual verification: upload a document, generate a suggestion, accept it, verify the thread card still shows correct context text.
  - **Effort:** ~half day

- [x] **4. `expand_context` does not persist**
  - `POST /expand_context/...` updates `session["context_settings"]` but does not call `save_session()`. Settings survive in memory but are lost on restart.
  - **Fix:** Add `save_session()` call at the end of the endpoint.
  - **Files:** `src/routes/threads.py`
  - **Test:** Run: `.venv/bin/python -m pytest tests/test_session_management.py -v`
  - **Effort:** ~minutes

- [x] **5. Convert debug prints to logging**
  - Parser and serializer use `print(..., flush=True)` extensively for field codes, diff steps, anchors, etc. These should be proper `logging.debug()` / `logging.info()` calls with a logger per module.
  - **Fix:** Replace all `print()` calls in `parser.py` and `serializer.py` with `logging` calls. Add `logger = logging.getLogger(__name__)` to each module.
  - **Files:** `src/document_model/parser.py`, `src/document_model/serializer.py`
  - **Test:** Run full suite to verify no print-dependent logic was broken: `.venv/bin/python -m pytest tests/ -v`
  - **Effort:** ~half day

- [x] **6. Split large files**
  - Several core files are far too large for comfortable maintenance. The transition will heavily modify most of them, and splitting first means cleaner diffs, easier navigation, and less risk of merge conflicts. All splits are mechanical reorganization — no behaviour changes.
  - **6a. `src/document_model/serializer.py` (3,070 lines)** — the largest file in the codebase. Does ZIP packaging, OOXML serialization for comments/revisions, paragraph/run XML surgery, diff application, field code preservation, and comment element builders.
    - **Split into:** `serializer.py` (thin orchestrator + ZIP lifecycle), `serializer_revisions.py` (revision serialization and diff application to paragraphs), `serializer_comments.py` (comment anchor serialization and comment XML builders), `serializer_formatting.py` (HTML/formatting-to-runs conversion), `serializer_field_codes.py` (field code extract/restore/split helpers), `serializer_common.py` (`_sanitize_for_xml` shared helper).
    - **[x] Done** — split via mixin classes; `DocumentSerializer` public API unchanged.
  - **6b. `src/diff_utils.py` (1,935 lines)** — core diff, HTML presentation, Word XML emission, and formatting merge all in one file.
    - **Split into:** `diff_core.py` (tokenization, `DiffOperation`, `compute_diff`, merge/normalize ops), `diff_html.py` (`diff_to_html`, `diff_to_html_paragraph_aware`, `diff_to_editable_html`, `highlight_text_in_html`), `diff_word_xml.py` (`diff_to_word_xml`, `diff_to_word_xml_with_formatting`, `html_to_word_runs`), `diff_formatting.py` (`parse_html_formatting`, `build_html_formatting_map`, `merge_formatting_for_revision`).
    - **[x] Done** — split into submodules; `diff_utils.py` re-exports all public symbols for backward compatibility.
  - **6c. `src/llm_handler.py` (1,625 lines)** — config/env loading, API transport, and prompt assembly mixed together. Will need major expansion for the agent loop; splitting now prevents it from growing to 3,000+ lines.
    - **Split into:** `llm_handler.py` (main class, orchestration), `llm_prompts.py` (prompt building, citation protection, context formatting), `llm_transport.py` (API calls, retries, response parsing per provider), `llm_types.py` (`LLMSuggestion` shared type).
    - **[x] Done** — split via mixin classes; `LLMHandler` public API unchanged.
  - **6d. `src/document_model/plain_text.py` (1,489 lines)** — view types, structural edit engine, builder, and context retrieval.
    - **Split into:** `plain_text.py` (PlainTextView, scope/position types, builder), `plain_text_edits.py` (compute_structural_edits, alignment, reordering, apply_revision_from_plain_text).
    - **[x] Done** — split into submodules; `plain_text.py` re-exports all public symbols for backward compatibility.
  - **6e. `src/session_utils.py` (1,099 lines)** — adapter dataclasses, JSON persistence, and model bridge functions.
    - **Split into:** `session_adapters.py` (LLMComment, LLMThread and conversion helpers), `session_persistence.py` (JSON load/save, merge), `session_utils.py` (model bridge functions, paragraph cache, placeholder conversion).
    - **[x] Done** — split into submodules; `session_utils.py` re-exports all public symbols for backward compatibility.
  - **6f. `tests/test_diff_utils.py` (1,236 lines)** — mirror the `diff_utils` split with parallel test modules.
    - **[x] Done** — split into `test_diff_core.py`, `test_diff_html.py`, `test_diff_word_xml.py`, `test_diff_formatting.py`.
  - **Files:** As listed above
  - **Test:** Run the full test suite after **each** split (not just at the end). Import breakage is the primary risk and will surface immediately: `.venv/bin/python -m pytest tests/ -v`. Also verify that all existing imports across `src/` and `templates/` resolve correctly.
  - **Effort:** ~2–3 days (mechanical, but needs care to preserve all imports and tests)

- [x] **7. Rename `LLMThread`/`LLMComment` to avoid confusion**
  - `session_adapters.py` defines adapter types for the LLM handler. `llm_handler.py` previously imported `LLMThread as CommentThread`, which collided conceptually with `document_model.comments.CommentThread`.
  - **Fix:** Renamed to `ThreadContext`/`CommentContext`. Updated all imports.
  - **Files:** `src/session_adapters.py`, `src/session_utils.py`, `src/llm_handler.py`, `src/llm_prompts.py`
  - **[x] Done**

- [x] **8. Clean up stale files and config**
  - Remove unused templates: `templates/partials/upload_success.html`, `templates/partials/chat_section.html`.
  - Remove stale mypy overrides in `pyproject.toml` referencing deleted modules (`comment_extractor`, `docx_writer`).
  - Fix `GET /health` to return `APP_VERSION` instead of hardcoded `"2.0.0"`.
  - **[x] Done**

- [x] **9. Add test fixtures and basic route tests**
  - `test_data/` is empty in the workspace — many tests skip when `test.docx` is absent, silently degrading test coverage.
  - No test coverage for routes (except session listing), `LLMHandler`, `token_counter`, `output_manager`, or `file_parsers/*`.
  - **Fix:** (a) Add at least one synthetic `.docx` test fixture to the repo or generate one in `conftest.py`. (b) Add basic `TestClient` tests for the primary routes (`/upload`, `/export`, generate suggestion, accept suggestion). These don't need to be exhaustive — just enough to catch regressions during the transition.
  - **Files:** `tests/conftest.py`, new test files as needed
  - **Test:** This item IS the testing work. After completion, run the full suite and verify the new tests pass and that previously-skipping tests now run: `.venv/bin/python -m pytest tests/ -v --tb=short`
  - **Effort:** ~1–2 days
  - **[x] Done** — `test_data/synthetic/` committed fixtures; `test_data/local/` gitignored; shared `tests/test_support.py`; route smoke tests in `tests/test_routes.py`; unit tests for `token_counter`, `output_manager`, `file_parsers/*`; existing tests refactored to use synthetic paths.

---

## Tier 2: Address during Stage 1

These items are important but naturally arise during Stage 1 implementation. They don't need a separate cleanup pass.

### TipTap save logic is tightly coupled to card UI

`saveTipTapContent` in `base.html` directly manipulates card DOM elements (`#card-{threadId}`, acceptance badges, chained Tailwind class selectors). For the workspace document viewer, this needs to be refactored into an editor module with callbacks.

**Files:** `templates/base.html`
**When:** During document viewer implementation (Stage 1, step 5)

### Route responses are HTMX/HTML-only

Every mutation route returns `TemplateResponse` for card partials. The workspace UI will need either new JSON endpoints or a parallel set of routes. Domain logic (`DocumentModel`, `LLMHandler`, session management) is reusable; transport is entangled with HTML.

**Files:** All files under `src/routes/`
**When:** During workspace UI implementation (Stage 1, steps 5–6)

### LLM handler has no function calling / tool use support

Currently structured as single-turn prompt-in, text-out. Adding agent-style multi-turn tool calling needs message arrays, tool definitions, tool call handling, and per-provider dispatch.

**Files:** `src/llm_handler.py`
**When:** During agent loop implementation (Stage 1, step 2)

### Test coverage should grow with the new code

As new tool functions, agent loop, and workspace routes are built, each should have tests. The pre-transition route tests (Tier 1, item 6) provide a baseline; Stage 1 work should maintain and extend it.

**When:** Throughout Stage 1

---

## Tier 3: Address during Stage 3 or when relevant

These are real issues but not blocking. They can be fixed when the relevant area of code is next touched.

### `EditType.FORMAT` is a dead end

`apply_edit` for FORMAT doesn't apply formatting to runs — it only records a revision with incorrect `original_formatting` (passes the new formatting as both old and new). The serializer has no path for formatting-only revisions. Not currently used in any workflow.

**Files:** `src/document_model/model.py` (lines ~471–485), `src/document_model/serializer.py`
**When:** Before the agent needs to make formatting-only changes

### Table model is very simplified

One synthetic paragraph per cell (all `w:t` joined with spaces), no merged cells, no borders/widths. The serializer doesn't rebuild `w:tbl` from `Table` objects. Explicitly Stage 3 work.

**Files:** `src/document_model/model.py` (`Table`), `src/document_model/parser.py` (`_parse_table`), `src/document_model/serializer.py`
**When:** Stage 3 (tables feature)

### Parser skips many OOXML elements

`_parse_paragraph` only descends into `w:r`, `w:ins`, `w:del`, `w:hyperlink`. Elements like `w:sdt`, `w:smartTag`, shapes, math, and nested constructs are ignored. For medical manuscripts with comments, this is mostly fine — these elements are uncommon.

**Files:** `src/document_model/parser.py` (`_parse_paragraph`)
**When:** When a real-world document surfaces a parsing gap

### Field code placeholder ambiguity

`str.replace` for placeholder substitution can mismap when multiple field codes have the same display text (e.g., two `[1]` citations). The global counter fix helps, but the replacement logic itself is positionally ambiguous.

**Files:** `src/document_model/paragraph.py` (`plain_text` property), `src/document_model/serializer.py` (`_inject_placeholders_into_text`)
**When:** When field code handling is next improved

### `split_paragraph` collapses formatting

After splitting, both halves become single-run paragraphs, losing multi-run formatting from the original.

**Files:** `src/document_model/model.py` (`split_paragraph`, lines ~782–793)
**When:** If the agent needs to split paragraphs and preserve formatting

### `DELETE_PARAGRAPH` on table cells leaves inconsistent state

`_migrate_anchors_for_deleted_paragraph` runs before `remove_element`, which returns `None` for table cell paragraphs. Anchors are migrated as if the paragraph is gone, but the paragraph remains.

**Files:** `src/document_model/model.py` (`_apply_delete_paragraph`)
**When:** When table cell editing is implemented

### Dependencies not pinned

`requirements.txt` uses min-version constraints only, no lockfile. Should be addressed before distributing to others or setting up CI.

### Inline styles in diff output

`diff_to_html` uses inline `style=` spans with hardcoded hex colors (Streamlit-era). `diff_to_editable_html` uses both classes and inline styles. Inconsistent with the Tailwind approach used elsewhere.

---

## Reference

This audit was conducted by examining every file under `src/`, `tests/`, `templates/`, and project configuration files. The full codebase was reviewed by five parallel analysis passes covering:

1. Document model layer (model, edits, comments, revisions, paragraph, utils)
2. Parser and serializer
3. Routes, session management, and LLM handler
4. Tests, dependencies, and project structure
5. Frontend templates, JavaScript, and diff utilities
