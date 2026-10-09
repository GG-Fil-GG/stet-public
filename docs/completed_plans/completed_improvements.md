# Completed Improvements

This document archives all completed enhancements from the original `future_improvements.md`. These features were implemented between January-February 2026.

---

## Context Awareness Enhancements

### 1. Awareness of Accepted Revisions
**Status:** ✅ RESOLVED (2026-01-20)

The app is now aware of revisions accepted earlier in the session. Subsequent suggestions will see the updated text.

**Solution: Virtual State Architecture**

```python
# Session state stores: para_id → revised_text
st.session_state.accepted_revisions = {
    "1F718498": "Revised paragraph text...",
    "68D06659": "Another revised paragraph...",
}
```

**Flow:**
1. User accepts suggestion for Thread A (targets paragraph P1)
   - Store: `accepted_revisions[P1.para_id] = revised_text`
2. User generates suggestion for Thread B (targets P2, context includes P1, P3, P4, P5)
   - `_get_expanded_context()` checks each paragraph against `accepted_revisions`
   - If P1.para_id is in `accepted_revisions`, uses the revised text
3. LLM sees the updated paragraph text in context

**Key changes:**
- `LLMSuggestion` now includes `target_para_id` field
- `LLMHandler._get_expanded_context()` accepts `accepted_revisions` parameter
- `app.py` stores revisions by `para_id` when accepting, passes to LLM when generating

**Benefits:**
- ✅ Subsequent suggestions see up-to-date context
- ✅ Works for both target paragraph AND surrounding context paragraphs
- ✅ No document modification until export
- ✅ Simple undo: remove from `accepted_revisions` dict

---

## UI/Display Enhancements

### 5. Improved Referenced Text Display
**Status:** ✅ RESOLVED (2026-01-19)

Previously referenced text was shown in the same format as sent to the LLM (with `[exact]` in `[context]` markers), which was confusing.

**Solution:**
- Added `exact_text` field to `CommentThread` - just the text directly referenced by the comment
- Added `paragraph_text` field to `CommentThread` - full paragraph containing the reference
- UI now shows the full paragraph with the exact referenced portion **highlighted in yellow**
- LLM continues using `referenced_text` (with context markers) for better understanding
- `llm_handler.py` now uses `thread.paragraph_text` when available (avoids re-parsing docx)

### 6. Expandable Context in UI
**Status:** ✅ COMPLETE (Phase 1 + Phase 2, 2026-01-20)

Allow users to dynamically expand/contract the context shown in the UI and sent to the LLM.

**Implementation:**
- Three sections: Context (Preceding), Referenced Text, Context (Following)
- [−] [+] buttons for each section
- Multi-paragraph comments show all anchored paragraphs as minimum
- Context can be reduced to 0 (section hidden from UI AND LLM prompt)
- Per-thread memory for context settings
- Virtual state integration (shows revised text from `accepted_revisions`)
- Phase 2: Referenced Text expansion buttons [⬆+] [⬆−] [⬇+] [⬇−]

**Data Structures:**
```python
# Pre-cached on document load
st.session_state.document_paragraphs = [...]

# Thread → target paragraph index
st.session_state.thread_target_indices = {...}

# Per-thread context settings
st.session_state.context_settings = {...}
```

### 7. Custom Instructions Input
**Status:** ✅ RESOLVED (2026-01-21)

Allow per-thread or per-session custom instructions to guide the LLM.

**Solution:**
- **Session-level defaults:** Editable in Settings modal (⚙️), applies to all threads
- **Per-thread overrides:** Collapsible "Instructions" section in each card, pre-filled with session defaults

Features:
- Default instructions pre-filled with working medical writing instructions
- Session instructions saved to `session.json` and `localStorage`
- Per-thread overrides saved to `session.json`
- Visual indicator (✓) when thread has custom instructions
- Auto-save on blur for thread instructions

### 10. Diff Highlighting for Revised Text (Phase 1)
**Status:** ✅ RESOLVED (2026-01-20)

Show additions (green/highlighted) and deletions (red/strikethrough) in the AI-suggested revised text compared to the original.

**Phase 1: Toggle View**
- Toggle between "📊 Diff View" (read-only, styled) and "✏️ Edit View" (editable textarea)
- Uses `compute_diff()` and `diff_to_html()` from `diff_utils.py`
- Compares `thread.paragraph_text` (original) vs `suggestion["revised_text"]` (LLM output)
- Deletions shown in red with strikethrough, insertions in green with highlight

---

## LLM Enhancements

### 11.1 Table Parsing in DOCX
**Status:** ✅ RESOLVED (2026-01-22)

Tables in DOCX files were previously treated as individual cell paragraphs, breaking context awareness and display.

**Solution: Row-Based Approach**

Treating **table rows as the fundamental unit** for both UI display and LLM interaction.

**Implementation:**
1. **Table Detection & Extraction** (`src/comment_extractor.py`)
   - `get_paragraph_cache()` splits tables into individual rows
   - Each row stored as `type: 'table_row'` with cells array, text, row_number, total_rows, col_count

2. **Paragraph Cache Structure**
   ```python
   {
       'idx': 5,
       'para_id': '1A2B3C4D',
       'text': 'AUTHOR(S): | Maggioni, Muiesan, Pontremoli',
       'type': 'table_row',
       'cells': [...],
       'row_number': 1,
       'total_rows': 11,
       'col_count': 2
   }
   ```

3. **UI Display** - Rows show with 📊 icon and metadata, monospace display with horizontal scroll

4. **LLM Integration** - Target rows sent as pipe-separated text

5. **Accept Flow** - Parse revised text, map cells to `para_id`s

6. **Export** - Apply tracked changes per-cell

**Verified with:** two local manuscripts (one table with merged cells; one with 10 tables). Those files are not in this repository.

### 14. Structured JSON I/O
**Status:** ✅ RESOLVED (2026-01-21)

Use JSON format for LLM input/output for more robust parsing.

**Solution:**
- LLM prompt now requests JSON output with `revised_text`, `response`, and `rationale` fields
- OpenAI calls use `response_format={"type": "json_object"}` for guaranteed JSON
- Ollama calls use `format="json"` 
- Robust parsing with fallback to text-based parsing if JSON fails
- Supports various key name variations for flexibility

---

## New Functionality

### 16. Chat Mode for Complex Comments
**Status:** ✅ IMPLEMENTED (2026-01-27)

Conversational interface for complex threads where iteration is needed.

**Solution:**
- "💬 Chat" button per thread (appears after generating a suggestion)
- Expandable chat section below card with message bubbles
- Back-and-forth conversation with the LLM to refine revisions
- LLM can optionally update revision and/or reply based on user feedback
- "Commit & Accept" commits the final revision to the workflow
- "Discard" reverts to the original suggestion
- "Clear History" starts fresh while preserving current revision
- Chat history persists across page refresh
- Keyboard shortcuts: Enter to send, Shift+Enter for newline
- Sliding window for long conversations (max 20 messages)

**Implementation:**
- New files: `src/chat_types.py`, `templates/partials/chat_section.html`
- 6 new endpoints: enter_chat, chat, commit_chat, discard_chat, exit_chat, clear_chat_history
- `generate_chat_response()` method in LLMHandler

---

## Text Extraction Enhancements

### 17. Newline Preservation in Comments
**Status:** ✅ RESOLVED

Multi-paragraph comments now preserve newlines.

**Solution:** Fixed by inserting `\n` between `<w:p>` elements in `_extract_text_from_element()` and using `white-space: pre-wrap` in the UI.

---

## Export Enhancements

### 18. Tracked Changes Insertion - Core Features
**Status:** ✅ RESOLVED (2026-01-19)

Insert revised text as tracked changes (`<w:ins>`, `<w:del>`) in `document.xml`.

**Implemented:**
- Phase 1 (MVP) and Phase 2 (Diff-Based) approach
- User opt-in via checkbox in sidebar
- Uses `difflib.SequenceMatcher` for word-level diff
- `diff_utils.py` module with `compute_diff`, `diff_to_word_xml`, `diff_to_html`
- 53 unit tests passing

#### Field Code Preservation (EndNote, Citations)
**Status:** ✅ RESOLVED (2026-01-19)

**Solution:**
1. Extract field codes from paragraph XML, replace with placeholders (`⟦CITE_0⟧`)
2. Run diff on placeholder text - citations treated as atomic, immutable units
3. Restore field codes - substitute placeholders back with original field code XML

**New methods:** `_extract_field_codes()`, `_extract_field_display_text()`, `_restore_field_codes()`

#### Citation Quarantine from LLM
**Status:** ✅ RESOLVED (2026-01-20)

**Solution:** Quarantine citations from LLM modification.

**New methods:** `_extract_citations()`, `_restore_citations()`, `_build_prompt_with_citation_protection()`

LLM receives instructions not to modify `[CITATION_X]` markers.

**Additional safeguards (2026-01-21):**
- Per-paragraph citation tracking
- Auto-restore missing markers
- Fixed citation extraction bug

#### Nested Track Changes (Diff-Based Approach)
**Status:** ✅ RESOLVED (2026-01-19)

Can now apply changes to paragraphs that already have track changes using diff-based approach.

### 19. Per-Reply Timestamps
**Status:** ✅ RESOLVED (2026-01-21)

Each reply and track change now uses the timestamp from when the user clicked "Accept", not the export time.

**Solution:**
- Accept timestamp recording: `datetime.now()` stored in `suggestion["accepted_at"]`
- `add_reply()` updated to accept optional `timestamp` parameter
- Export uses acceptance time for both `insert_tracked_change` and `add_reply`
- Persistence: Timestamp saved to `session.json`
- Local time: Uses machine's local timezone

---

## Changelog

### January 27, 2026
- **Major:** Implemented Chat Mode (#16) for iterative suggestion refinement

### January 22, 2026
- **Major:** Completed table parsing implementation (#11.1) with row-based approach

### January 21, 2026
- Implemented Custom Instructions (#7)
- Implemented Structured JSON I/O (#14)
- Implemented Per-Reply Timestamps (#19)
- Citation quarantine improvements

### January 20, 2026
- Implemented Awareness of Accepted Revisions (#1)
- Implemented Expandable Context (#6) Phase 1 + Phase 2
- Implemented Diff Highlighting (#10) Phase 1
- Implemented Citation Quarantine

### January 19, 2026
- Implemented Improved Referenced Text Display (#5)
- Implemented Tracked Changes Insertion (#18) core features
- Implemented Field Code Preservation
- Implemented Nested Track Changes support
- Created `diff_utils.py` module

---

## Desktop Application Packaging
**Status:** ✅ COMPLETE (2026-02)

Stet is distributed as an installable desktop application using PyWebView + PyInstaller.

**Approach:** PyWebView creates a native desktop window containing a webview. The FastAPI app runs as a local server inside the app. PyInstaller bundles Python + all dependencies into a single executable.

**Completed:**
- macOS build working (in `dist/`)
- Windows build completed on Windows machine
- `desktop_app.py` entry point created
- `src/paths.py` with path helpers for frozen/dev modes
- Templates, static files, and config properly bundled

**Remaining polish (deferred):**
- App icon
- First-run API key wizard
- Code signing
- Auto-update mechanism
- CI pipeline for automated builds

---

## LLM Enhancements (Additional)

### File Attachments for Context
**Status:** ✅ COMPLETE

Users can attach external files (PDFs, spreadsheets) to provide additional context for comments.

**Implementation:**
- File upload area per thread
- `src/file_parsers/pdf_parser.py` - PDF text extraction
- `src/file_parsers/spreadsheet_parser.py` - Excel/CSV parsing
- Extracted text included in LLM prompt as additional context
- Attachments stored in session directory
