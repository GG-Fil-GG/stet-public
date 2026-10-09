# Migration Plan: Streamlit → FastAPI + Jinja2 + HTMX

**Goal:** Migrate the Comment Addresser app from Streamlit to a FastAPI + Jinja2 + HTMX stack for better UI control and distribution.

**Target Layout:** Two-column design mimicking Microsoft Word's comment pane.

---

## Phase 1: Project Setup ✅ COMPLETE
- [x] Create `main.py` with FastAPI app skeleton
- [x] Create `templates/` folder structure
- [x] Create `base.html` with Tailwind CSS (CDN) and HTMX
- [x] Create `index.html` with file upload form
- [x] Create `static/` folder for any custom CSS/JS
- [x] Verify server runs (`uvicorn main:app --reload`)
- [x] Set minimum width enforcement (1200px with horizontal scroll below)

## Phase 2: File Upload & Document Loading ✅ COMPLETE
- [x] Create `POST /upload` endpoint
- [x] Integrate with existing `CommentExtractor` from `/src/`
- [x] Create session management (adapt existing `OutputManager` patterns)
- [x] Store extracted threads in session
- [x] Return/render list of thread cards
- [x] Handle file validation and errors

## Phase 3: Comment Card UI (Two-Column Layout) ✅ COMPLETE
- [x] Create `card.html` partial template
- [x] **Left column (60-65%):**
  - [x] Context (Preceding) with [+][-] buttons
  - [x] Referenced Text with [↑+][↑−][↓+][↓−] buttons
  - [x] Context (Following) with [+][-] buttons
  - [x] Yellow highlighting for exact referenced text
  - [x] "(edited earlier)" indicators for revised paragraphs
- [x] **Right column (35-40%):**
  - [x] Comment Thread display (author, date, text, replies)
- [x] HTMX: `POST /expand_context/{thread_id}` for context buttons
- [x] Style with Tailwind for clean, modern appearance

## Phase 4: LLM Integration & Suggestion Display ✅ COMPLETE
- [x] Create `POST /generate/{thread_id}` endpoint
- [x] Integrate with existing `LLMHandler` from `/src/`
- [x] Citation quarantine (reuse existing logic)
- [x] Virtual state integration (pass accepted_revisions)
- [x] **Left column (below context):**
  - [x] Revised Text with diff highlighting
  - [x] Toggle between Diff View and Edit View
  - [x] Editable textarea with auto-save
- [x] **Right column (below comment):**
  - [x] Response to Reviewer (editable with auto-save)
  - [x] Rationale (collapsible, collapsed by default)
- [x] **Action buttons row (centered):**
  - [x] [Generate] / [Regenerate]
  - [x] [Accept] / [Skip]
- [x] HTMX partial updates (no full page reload)
- [x] Loading spinner during generation

## Phase 5: Accept/Skip/Regenerate Flow ✅ COMPLETE
- [x] Create `POST /accept/{thread_id}` endpoint
- [x] Create `POST /skip/{thread_id}` endpoint
- [x] Create `POST /regenerate/{thread_id}` endpoint
- [x] Update virtual state (`accepted_revisions`) on accept
- [x] Update thread status (pending/accepted/skipped)
- [x] HTMX updates to reflect state changes
- [x] Visual indication of accepted/skipped threads
- [x] Thread filtering (All / Pending / Accepted / Skipped)

## Phase 6: Export & Sidebar ✅ COMPLETE
- [x] Create `POST /export` endpoint
- [x] Integrate with existing `DocxWriter` from `/src/`
- [x] Insert tracked changes (reuse existing diff-based logic)
- [x] Insert replies
- [x] File download response
- [x] **Settings modal:**
  - [x] LLM provider selection (OpenAI / Ollama)
  - [x] Model selection
  - [x] API key input (stored in localStorage)
  - [x] "Insert as tracked changes" toggle (in export modal)
- [x] Session persistence (session.json saves accepted revisions, thread status, context settings)

## Phase 7: Polish & Testing
- [ ] Test with all documents in `/test_data/`
- [x] Error handling with user-friendly messages
- [x] Loading states and progress indicators
- [ ] Keyboard shortcuts (optional, low priority)
- [x] "Open" filter for unresolved threads
- [x] Text overflow handling in all content areas
- [ ] Final styling pass
- [ ] Documentation update (README)

## Phase 8: Distribution (Future)
- [ ] PyInstaller bundling research
- [ ] Create standalone executable
- [ ] Test on clean machine
- [ ] Installation instructions

---

## Files to Create

```
comments_addresser/
├── main.py                    # FastAPI app (replaces app.py)
├── templates/
│   ├── base.html              # Base template with Tailwind + HTMX
│   ├── index.html             # Main page with upload
│   ├── partials/
│   │   ├── card.html          # Single thread card
│   │   ├── context.html       # Context section (reusable)
│   │   ├── suggestion.html    # Suggestion display after generation
│   │   └── thread_list.html   # List of all thread cards
│   └── components/
│       ├── sidebar.html       # Settings sidebar
│       └── diff_view.html     # Diff visualization
├── static/
│   └── styles.css             # Custom CSS (if needed beyond Tailwind)
└── src/                       # UNCHANGED - all backend logic stays
    ├── comment_extractor.py
    ├── docx_writer.py
    ├── llm_handler.py
    ├── diff_utils.py
    └── output_manager.py
```

## What Gets Reused (No Changes)

| Module | Purpose |
|--------|---------|
| `src/comment_extractor.py` | DOCX parsing, thread extraction |
| `src/docx_writer.py` | Reply insertion, tracked changes |
| `src/llm_handler.py` | LLM API calls, prompt building |
| `src/diff_utils.py` | Diff computation, HTML/XML generation |
| `src/output_manager.py` | File/session management |

## Target Layout Mockup

```
┌─────────────────────────────────────────────────────────────────────────┐
│  📄 Comment Addresser                              [Settings] [Export]  │
├─────────────────────────────────────────────────────────────────────────┤
│  Upload: [Choose File] [Load]     Filter: [All ▼]    Progress: 3/12    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ Thread 1 ──────────────────────────────────────────────────────┐   │
│  │                                        │                        │   │
│  │  Context (Preceding)          [+][-]   │  💬 Comment Thread     │   │
│  │  ┌────────────────────────────────┐    │                        │   │
│  │  │ Previous paragraph text...     │    │  Author Name           │   │
│  │  └────────────────────────────────┘    │  2025-01-15 14:32      │   │
│  │                                        │                        │   │
│  │  Referenced Text    [↑+][↑−][↓+][↓−]   │  "Please revise this   │   │
│  │  ┌────────────────────────────────┐    │   section to include   │   │
│  │  │ The <mark>exact text</mark>    │    │   more detail about    │   │
│  │  │ that was commented on...       │    │   the methodology."    │   │
│  │  └────────────────────────────────┘    │                        │   │
│  │                                        │  ↳ Reply from Jane     │   │
│  │  Context (Following)          [+][-]   │    "Will do, thanks"   │   │
│  │  ┌────────────────────────────────┐    │                        │   │
│  │  │ Following paragraph text...    │    │                        │   │
│  │  └────────────────────────────────┘    │                        │   │
│  │                                        │                        │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │           [Generate Suggestion]  [Accept]  [Skip]               │   │
│  │  ─────────────────────────────────────────────────────────────  │   │
│  │                                        │                        │   │
│  │  Revised Text (Diff View)              │  Response to Reviewer  │   │
│  │  ┌────────────────────────────────┐    │  ┌────────────────┐    │   │
│  │  │ The exact text that was        │    │  │ Thank you for  │    │   │
│  │  │ <del>commented</del>           │    │  │ the feedback.  │    │   │
│  │  │ <ins>reviewed</ins> on...      │    │  │ I have...      │    │   │
│  │  └────────────────────────────────┘    │  └────────────────┘    │   │
│  │                                        │  ▶ Rationale           │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─ Thread 2 ──────────────────────────────────────────────────────┐   │
│  │  ...                                                            │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Progress Log

| Date | Phase | Notes |
|------|-------|-------|
| 2026-01-21 | Planning | Migration plan created |
| 2026-01-21 | Phase 1 | Project setup complete - server running at http://127.0.0.1:8000 |
| 2026-01-21 | Phase 2 | File upload + CommentExtractor integration |
| 2026-01-21 | Phase 3 | Two-column card UI with context expansion |
| 2026-01-21 | Phase 4 | LLM integration, diff highlighting, editable text areas |
| 2026-01-21 | Phase 5 | Accept/Skip/Regenerate flow, thread filtering |
| 2026-01-21 | Phase 6 | Export with tracked changes and replies, settings modal |
| 2026-01-21 | Phase 7 | Multi-paragraph revision fix, citation marker fix, "Open" filter |
| | | |
