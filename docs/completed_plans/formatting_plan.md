# Text Formatting Implementation Plan

## Overview

Add text formatting support to Stet:
- Display formatting from source documents (Referenced Text, Context)
- Allow editing formatting in revised text (user manual formatting)
- Unified editor view with real-time diff and formatting
- Optionally enable LLM formatting suggestions (future)

---

## Architecture: Revised Implementation Plan

### Core Principles

1. **HTML as source of truth** - Generate merged HTML immediately when LLM responds or user edits
2. **TipTap rich text editor** - Using TipTap (ProseMirror-based) for the unified editor:
   - Proper document model separate from DOM
   - Cursor position preservation during content updates
   - Formatted text visible with diff highlights
   - Real-time updates as user types (150ms debounce)
3. **`<w:rPrChange>` for formatting** - Use proper Word XML for formatting-only changes (not del/ins)
4. **Strip HTML for LLM** - Only when sending to LLM in "no formatting" mode

### Data Flow Architecture

```
                    ┌─────────────────────────────┐
                    │   revised_text_html         │
                    │   (Single Source of Truth)  │
                    └─────────────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
          ▼                      ▼                      ▼
   ┌─────────────┐      ┌──────────────┐      ┌──────────────┐
   │ Unified     │      │ Word Export  │      │ LLM Context  │
   │ Editor View │      │ (HTML → XML) │      │ (strip tags) │
   │ (format +   │      │ + rPrChange  │      │              │
   │  diff)      │      │              │      │              │
   └─────────────┘      └──────────────┘      └──────────────┘
```

---

## What Happens in Each Phase

### Phase 1: Display Source Formatting (read-only)
1. Extract text + formatting from DOCX → HTML
2. Display HTML in "Referenced Text" and "Context" areas
3. No LLM involvement for formatting display

### Phase 2: User Edits Revised Text
1. User types/edits in rich text editor
2. User manually applies formatting via toolbar buttons
3. **HTML created by user IS the source of truth**
4. We convert that HTML → OOXML when writing to Word

### Phase 3: LLM Suggests Formatting (optional, future)
This requires the LLM to **explicitly output** formatting:
1. Send context to LLM (could include hint about source formatting)
2. LLM returns text **with markdown markers**: `"The β~3~ receptor..."`
3. We parse markers → HTML
4. **Parsed HTML IS the source of truth**

### Current "No Formatting" Mode (default)
- Send plain text to LLM
- LLM returns plain text
- **Formatting from source is NOT preserved** in the revised text
- This is the expected behavior - user can add formatting manually (Phase 2)

---

## Important Limitation: Formatting Loss in LLM Suggestions

When the LLM modifies text, **original formatting cannot be reliably preserved**. This is because there's no way to map formatting positions from the original text to restructured LLM output.

**Example:**
- Original: `"The β<sub>3</sub> receptor is important"`
- Sent to LLM (plain): `"The β3 receptor is important"`
- LLM returns: `"The beta-3 receptor plays a crucial role"`
- Problem: Where should the subscript go? Text structure changed entirely.

### What IS Preserved

| Area | Formatting Preserved? | Notes |
|------|----------------------|-------|
| Referenced Text (display) | ✅ Yes | Phase 1 |
| Context (display) | ✅ Yes | Phase 1 |
| Revised Text (LLM output) | ❌ No | Plain text only |
| Revised Text (user edits) | ✅ Yes | Phase 2 - manual |
| Text diff (word changes) | ✅ Yes | Always works |

### Realistic Options

1. **Accept formatting loss** when LLM modifies text (current plan)
2. **LLM explicitly outputs formatting** markers (Phase 3)
3. Complex diff/alignment to try to preserve unchanged portions (fragile, **not recommended**)

### Key Clarification

**"HTML as source of truth"** is specifically about Phases 2 and 3 - when we have formatted *revised* text. It is **not** about preserving original formatting through LLM processing.

---

## Formats Supported

### Character-level (inline)
- **Bold** - `<w:b/>`
- **Italic** - `<w:i/>`
- **Underline** - `<w:u/>`
- **Superscript** - `<w:vertAlign w:val="superscript"/>`
- **Subscript** - `<w:vertAlign w:val="subscript"/>`

### Paragraph-level (block)
- **Alignment** - `<w:jc w:val="left|center|right|both"/>`

---

## OOXML Reference (ECMA-376)

Based on Office Open XML Part 4 - Markup Language Reference (see `docs/microsoft_docs/`):

### Run Properties (`<w:rPr>`)
Character formatting is stored in run properties:
```xml
<w:r>
  <w:rPr>
    <w:b/>           <!-- bold -->
    <w:i/>           <!-- italic -->
    <w:u w:val="single"/>  <!-- underline -->
    <w:vertAlign w:val="subscript"/>  <!-- sub/superscript -->
  </w:rPr>
  <w:t>formatted text</w:t>
</w:r>
```

### Tracked Formatting Changes (`<w:rPrChange>`)
Per §2.13.5.32, formatting changes are tracked by storing **previous** properties inside the current properties:
```xml
<w:r>
  <w:rPr>
    <w:i/>           <!-- NEW: italic -->
    <w:rPrChange w:id="1" w:author="..." w:date="...">
      <w:rPr/>       <!-- OLD: no formatting -->
    </w:rPrChange>
  </w:rPr>
  <w:t>BMI</w:t>     <!-- Text stays unchanged -->
</w:r>
```

**Key insight:** Word does NOT use `<w:del>/<w:ins>` for formatting-only changes. The `<w:rPrChange>` element keeps the text in place and only records the formatting change. This is cleaner and matches Word's UI behavior (formatting changes shown differently from text insertions/deletions).

### Other Change Elements
- `pPrChange` (§2.13.5.31) - Paragraph property changes (alignment, etc.)
- `tcPrChange` (§2.13.5.38) - Table cell property changes
- `tblPrChange` (§2.13.5.36) - Table property changes
- `trPrChange` (§2.13.5.39) - Table row property changes

---

## Phase 1: Display Source Formatting

**Goal:** Show formatting in Referenced Text and Context areas as it appears in the source document.

**Status:** ✅ Completed

### What Was Implemented

- `_extract_paragraph_formatting()` in `comment_extractor.py` extracts run properties and builds HTML
- Paragraph cache includes `formatted_html` and `alignment` fields
- Table cells include `formatted_html` in their data structure
- Templates (`card.html`) use `formatted_html | safe` with fallback to `text`
- `context_utils.py` handles `formatted_html` for context display

### Data Structure
```python
{
    "type": "paragraph",
    "text": "This is β3 receptor",  # Plain text preserved
    "formatted_html": "This is β<sub>3</sub> receptor",  # HTML with formatting
    "alignment": "left",  # or "center", "right", "justify"
    "para_id": "123ABC"
}
```

---

## Phase 2: HTML as Source of Truth

**Goal:** Make HTML the single source of truth for all revised text. This is the foundational change that enables everything else.

**Status:** ✅ Completed

### Why This Must Come First

Everything else depends on HTML being the source of truth:
- Unified editor needs HTML to display formatting
- Diff computation needs HTML to show formatting in context
- Word export needs HTML to convert to OOXML
- LLM context needs to strip HTML to send plain text

### What Was Implemented

#### Consolidated `accepted_revisions` to store HTML

- Removed `accepted_revisions_html` - redundant now that `accepted_revisions` IS HTML
- `accepted_revisions` dict now stores merged HTML (source of truth)
- `session_utils.py`: Updated session structure comment

#### Updated `accept_suggestion` in `main.py`

- When user accepts a revision, merged HTML is stored in `accepted_revisions`
- Merges original formatting with user's formatting via `merge_formatting_for_revision()`
- Single paragraph, multi-paragraph, and table cell revisions all store HTML

#### Updated `context_utils.py` to use HTML

- `create_paragraph_entry()`: Uses HTML from `accepted_revisions` for `formatted_html`
- `get_context_paragraphs()`: Uses HTML from `accepted_revisions`
- Plain text is derived by stripping HTML tags when needed for display

#### Updated LLM context to strip HTML

- `llm_handler.py`: `_format_cache_item_text()` now strips HTML tags from `accepted_revisions`
- LLM always receives plain text context (no formatting in "no formatting" mode)
- Uses existing `strip_html_tags()` utility from `diff_utils.py`

#### Updated Word export in `main.py`

- Export now uses HTML from `accepted_revisions` for table cells, multi-paragraph, and single paragraph
- Passes `revised_text_html` to `insert_tracked_change_by_para_id()` for formatting preservation
- Compares plain text (stripped) for change detection

### Tests Added

- `test_paragraph_with_html_revision`: Verifies HTML preserved in `formatted_html`, stripped in `text`
- `test_table_cell_with_html_revision`: Verifies table cells handle HTML correctly
- `test_context_with_html_revisions`: Integration test for HTML revision flow

---

## Phase 3: Unified Editor with Formatting + Diff

**Goal:** Single rich text editor view that shows both formatting AND diff highlighting, eliminating the Edit/Diff toggle.

**Status:** ✅ Completed

### What Was Implemented

#### TipTap Rich Text Editor Integration

Replaced native `contenteditable` with TipTap editor to solve cursor jumping during live diff refresh:

- **TipTap loaded via ES modules** (esm.sh CDN) in `base.html`
- **Global utilities** for editor creation, saving, formatting, and diff refresh
- **Proper cursor preservation** using `state.selection.anchor` before/after content updates
- **Modern formatting commands** replacing deprecated `execCommand`

Key TipTap functions:
- `createTipTapEditor(threadId, sessionId, initialContent)` - Initialize editor
- `formatTipTapText(threadId, command)` - Apply formatting (bold, italic, underline, super/subscript)
- `saveTipTapContent(threadId, sessionId, refreshDiffAfter)` - Save with optional diff refresh
- `refreshTipTapDiff(threadId, sessionId)` - Update diff highlights with cursor preservation

#### New `diff_to_editable_html()` function in `diff_utils.py`

Generates HTML suitable for the editor with:
- **Insertions**: Wrapped in `<span class="diff-insert">` with green background
- **Deletions**: Wrapped in `<span class="diff-delete" contenteditable="false">` with red strikethrough
- **Equal text**: Preserves formatting from revised HTML

#### Updated `card.html` template

- **Removed** Diff/Edit toggle buttons for regular text (kept for table rows)
- **TipTap container** replaces raw contenteditable div
- **Formatting toolbar** always visible above editor
- **Real-time diff updates** with 150ms debounce and cursor preservation
- **Refresh button** to manually refresh diff highlights

#### Real-time diff updates

- `onUnifiedEditorInput()`: Debounced auto-save + diff refresh (1.5s delay)
- `refreshDiff()`: Fetches updated editable diff HTML from server
- `stripDiffMarkers()`: Removes diff spans before saving (they're visual only)

#### New API endpoint

- `GET /editable_diff_html/{session_id}/{thread_id}`: Returns editable diff HTML

### Tests Added

- 7 new tests for `diff_to_editable_html()` covering insertions, deletions, formatting preservation

### Table rows

Table rows still use the original diff view (tables are complex). A "Edit table text" collapsible section is available for direct editing.

---

## Phase 4: Word Export with Proper Track Changes

**Goal:** Convert HTML to OOXML with proper track changes, including `<w:rPrChange>` for formatting-only changes.

**Status:** ✅ Completed

### Scenario Matrix

All combinations of text and formatting changes that must be handled:

| # | Original | Revised | Change Type | Word XML Required |
|---|----------|---------|-------------|-------------------|
| 1 | `text` | `text` | No change | No modification |
| 2 | `text` | `**text**` | Formatting only (add) | `<w:rPrChange>` |
| 3 | `**text**` | `text` | Formatting only (remove) | `<w:rPrChange>` |
| 4 | `**text**` | `*text*` | Formatting only (change) | `<w:rPrChange>` |
| 5 | `text` | `new` | Text only | `<w:del>` + `<w:ins>` |
| 6 | `text` | `**new**` | Text change + formatting on new | `<w:del>` + `<w:ins>` with `<w:rPr>` |
| 7 | `**text**` | `new` | Text change + formatting removed | `<w:del>` (preserves fmt) + `<w:ins>` (plain) |
| 8 | `**text**` | `*new*` | Text change + different formatting | `<w:del>` + `<w:ins>` with different `<w:rPr>` |

### Mixed Changes Within a Paragraph

A single paragraph may contain multiple change types:

**Example:**
- Original: `The β3 receptor is important for signaling.`
- Revised: `The β₃ receptor is **critical** for signaling.`

This requires:
1. `The ` — EQUAL, no formatting change → keep original run
2. `β3` → `β₃` — EQUAL, formatting change (subscript added) → `<w:rPrChange>`
3. ` receptor is ` — EQUAL, no formatting change → keep original run
4. `important` → `critical` — DELETE + INSERT with bold → `<w:del>` + `<w:ins>` with `<w:b/>`
5. ` for signaling.` — EQUAL, no formatting change → keep original run

### Implementation Steps

#### Step 4.0: Fix bug in `_apply_formatting_only()`
- [x] **Bug:** `html_to_word_runs(revised_text_html)` called without required `rsid` parameter
- [x] **Fix:** Add `rsid = self._generate_rsid()` before the call
- [x] **Location:** `src/docx_writer.py`, line ~949

#### Step 4.1: Extract original paragraph formatting

Create function to extract formatting from Word runs:

- [x] **Function:** `_extract_runs_with_formatting(para: ET.Element) -> List[Dict]`
- [x] **Returns:** List of `{'text': str, 'formatting': Set[str], 'xml': str}` for each run
- [x] **Handles:** `<w:b/>`, `<w:i/>`, `<w:u/>`, `<w:vertAlign val="superscript|subscript"/>`
- [x] **Handles:** Text inside `<w:ins>` elements (visible text)
- [x] **Skips:** Text inside `<w:del>` elements (deleted text)
- [x] **Location:** `src/docx_writer.py`

#### Step 4.2: Build formatting comparison logic

Create function to compare formatting between original and revised:

- [x] **Function:** `_get_formatting_for_text_position()` - extracts formatting for a position
- [x] **Function:** `_parse_rPr_to_formatting_set()` - parses Word XML to formatting set
- [x] **Purpose:** For each diff operation, determine what Word XML to generate
- [x] **Integrated into:** `_generate_preserved_formatting_xml()` in `src/docx_writer.py`

#### Step 4.3: Generate `<w:rPrChange>` XML

Create function to generate tracked formatting changes:

- [x] **Function:** `_generate_rPrChange_run(text, old_fmt, new_fmt, rev_id, author, timestamp, rsid) -> str`
- [x] **Generates:** Complete `<w:r>` element with `<w:rPrChange>` inside `<w:rPr>`
- [x] **Handles:** Adding formatting (old empty, new has tags)
- [x] **Handles:** Removing formatting (old has tags, new empty)
- [x] **Handles:** Changing formatting (old has tags, new has different tags)
- [x] **Location:** `src/docx_writer.py`

**XML structure:**
```xml
<w:r w:rsidR="ABC12345">
  <w:rPr>
    <w:b/>  <!-- NEW formatting -->
    <w:rPrChange w:id="7" w:author="Stet" w:date="2026-02-05T10:30:00Z">
      <w:rPr>
        <w:i/>  <!-- OLD formatting -->
      </w:rPr>
    </w:rPrChange>
  </w:rPr>
  <w:t xml:space="preserve">text</w:t>
</w:r>
```

#### Step 4.4: Refactor `_apply_tracked_change()` for EQUAL segments

Update the main tracked change function to handle formatting changes on unchanged text:

- [x] **Current behavior:** EQUAL segments keep original runs unchanged
- [x] **New behavior:** EQUAL segments compare formatting; use `<w:rPrChange>` if different
- [x] **Integration:** Call `_generate_rPrChange_run()` when formatting differs
- [x] **Preserve:** Existing DELETE and INSERT handling (already works)
- [x] **Location:** `src/docx_writer.py`, `_generate_preserved_formatting_xml()` method

#### Step 4.5: Refactor `_apply_formatting_only()`

This becomes a special case where entire paragraph is EQUAL but formatting differs:

- [x] **Bug fixed:** Added missing `rsid` parameter
- [ ] **Future:** Could be refactored to use `<w:rPrChange>` instead of direct replacement
- [x] **Location:** `src/docx_writer.py`

#### Step 4.6: Update revision ID handling

Ensure unique IDs across all track change types:

- [x] **Update:** `_get_max_revision_id()` now scans `<w:rPrChange>`, `<w:pPrChange>`, etc.
- [x] **Verify:** IDs are unique across `<w:ins>`, `<w:del>`, and `<w:rPrChange>`
- [x] **Location:** `src/docx_writer.py`

#### Step 4.7: HTML to OOXML tag mapping utilities

Ensure complete mapping exists (may already be implemented):

- [x] `<b>`, `<strong>` → `<w:b/>`
- [x] `<i>`, `<em>` → `<w:i/>`
- [x] `<u>` → `<w:u w:val="single"/>`
- [x] `<sup>` → `<w:vertAlign w:val="superscript"/>`
- [x] `<sub>` → `<w:vertAlign w:val="subscript"/>`
- [x] **Reverse mapping** (Word XML → formatting set): `_parse_rPr_to_formatting_set()`
- [x] **Forward mapping** (formatting set → Word XML): `_formatting_set_to_rPr_xml()`
- [x] **Location:** `src/docx_writer.py`

### Estimated Effort: 8-10 hours

---

## Phase 5: LLM Formatting Suggestions (Optional)

**Goal:** Allow LLM to suggest formatting using markdown-style syntax.

**Status:** Future / Optional (depends on Phases 2-4)

### Implementation Steps

#### Step 5.1: Add setting toggle
- In Settings modal: "Enable formatting suggestions"
- Store in localStorage
- Pass to backend via request headers or body

#### Step 5.2: Update LLM prompt (llm_handler.py)
When enabled, add to system prompt:
```
You may use formatting markers in your response:
- **bold** for bold text
- *italic* for italic text  
- __underline__ for underlined text
- ^superscript^ for superscript (e.g., m^2^)
- ~subscript~ for subscript (e.g., H~2~O)
```

#### Step 5.3: Create formatting_parser.py
- Parse markdown-style markers from LLM output
- Convert to HTML
- Handle nested formatting
- Graceful fallback on malformed input

#### Step 5.4: Integrate parser into LLM response handling
- If formatting enabled, parse response before storing
- Store parsed HTML as `revised_text_html`
- Display formatted HTML in unified editor
- Allow user to edit/adjust formatting

### Markdown Convention
```
**bold text**
*italic text*
__underline__
^superscript^
~subscript~
```

### Estimated Effort: 2-3 hours

---

## Implementation Order

1. ✅ **Phase 1**: Display source formatting - **Completed**
2. ✅ **Phase 2**: HTML as source of truth - **Completed**
3. ✅ **Phase 3**: Unified editor with formatting + diff - **Completed**
4. ✅ **Phase 4**: Word export with `<w:rPrChange>` - **Completed**
   - ✅ Text changes with `<w:ins>`/`<w:del>`
   - ✅ User formatting exports (without track changes)
   - ✅ Bug fix: `_apply_formatting_only()` rsid parameter
   - ✅ Extract original paragraph formatting (enhanced `_extract_runs_with_formatting`)
   - ✅ Build formatting comparison logic (`_parse_rPr_to_formatting_set`, `_get_formatting_for_text_position`)
   - ✅ Generate `<w:rPrChange>` XML (`_generate_rPrChange_run`)
   - ✅ Handle EQUAL segments with formatting changes in `_generate_preserved_formatting_xml()`
   - ✅ Handle INSERT segments with formatting changes (adds `<w:rPrChange>` to new formatted text)
   - ✅ Update revision ID handling (`_get_max_revision_id`)
   - ✅ Fix `merge_formatting_for_revision()` to respect user formatting removals
   - ✅ Unit tests for all scenarios (22+ new tests)
   - ✅ Manual Word compatibility testing (SBP italic removal, BMI italic removal verified)
5. ⬜ **Phase 5**: LLM formatting suggestions (opt-in, future)

---

## Testing Checklist

### Phase 1 ✅
- [x] Bold text displays correctly in Referenced Text
- [x] Italic text displays correctly
- [x] Underline displays correctly
- [x] Superscript (e.g., x², m²) displays correctly
- [x] Subscript (e.g., H₂O, β₃) displays correctly
- [x] Paragraph alignment applied correctly
- [x] Tables preserve cell formatting
- [x] Plain `text` field still populated (backward compat)
- [x] No regression in existing functionality

### Phase 2 (HTML as Source of Truth) ✅
- [x] `revised_text_html` stored in suggestion data
- [x] HTML saved from contenteditable (not stripped)
- [x] Plain text derived from HTML when needed
- [x] LLM receives stripped plain text
- [x] LLM response stored as `revised_text_html`
- [x] Existing functionality preserved

### Phase 3 (Unified Editor) ✅
- [x] Single editor view (no Edit/Diff toggle)
- [x] Formatting visible in editor (bold, italic, etc.)
- [x] Diff highlighting visible in editor (insertions green, deletions struck)
- [x] Real-time diff updates as user types (TipTap with cursor preservation)
- [x] Keyboard shortcuts work (Cmd/Ctrl+B, I, U)
- [x] Formatting persists on save
- [x] Original formatting preserved on unchanged text
- [x] User can add/change formatting on any text

### Phase 4 (Word Export) - ✅ Completed

#### Bug Fixes
- [x] Fix `_apply_formatting_only()` missing `rsid` parameter
- [x] Fix `merge_formatting_for_revision()` to respect user formatting removals

#### Core Implementation
- [x] `_extract_runs_with_formatting()` enhanced with `formatting` set
- [x] `_parse_rPr_to_formatting_set()` function created
- [x] `_formatting_set_to_rPr_xml()` function created
- [x] `_get_formatting_for_text_position()` function created
- [x] `_generate_rPrChange_run()` function created
- [x] `_generate_preserved_formatting_xml()` handles formatting changes on EQUAL segments
- [x] `_get_max_revision_id()` scans `<w:rPrChange>` and other change elements
- [x] `text_to_word_runs_with_segmented_formatting()` supports `<w:rPrChange>` for INSERT text

#### Scenario 1: No change (baseline)
- [x] Unchanged text with unchanged formatting exports correctly
- [x] No track change markers added for unchanged content

#### Scenario 2: Formatting only - Add formatting
- [x] Plain text → bold exports with `<w:rPrChange>` (unit test)
- [x] Plain text → italic exports with `<w:rPrChange>` (tested with SBP)
- [x] Plain text → underline exports with `<w:rPrChange>`
- [x] Plain text → superscript exports with `<w:rPrChange>`
- [x] Plain text → subscript exports with `<w:rPrChange>`
- [x] Plain text → multiple formats (e.g., bold+italic) exports correctly

#### Scenario 3: Formatting only - Remove formatting
- [x] Bold text → plain exports with `<w:rPrChange>` (old has `<w:b/>`) (unit test)
- [x] Italic text → plain exports with `<w:rPrChange>` (tested with SBP and BMI)
- [x] Multiple formats → plain exports correctly

#### Scenario 4: Formatting only - Change formatting
- [x] Bold → italic exports with `<w:rPrChange>` (unit test)
- [x] Subscript → superscript exports with `<w:rPrChange>`
- [x] Bold+italic → underline exports correctly

#### Scenario 5: Text change only (no formatting)
- [x] Text deletion exports with `<w:del>`
- [x] Text insertion exports with `<w:ins>`
- [x] Text replacement exports with `<w:del>` + `<w:ins>`

#### Scenario 6: Text change + formatting on new text
- [x] `word` → `**new**` exports with `<w:del>` + `<w:ins>` containing `<w:b/>` and `<w:rPrChange>`
- [x] Inserted text carries user's formatting from HTML with tracked formatting change

#### Scenario 7: Text change + formatting removed
- [x] `**word**` → `new` exports with `<w:del>` (preserving bold) + plain `<w:ins>`
- [x] Original formatting preserved in deleted text

#### Scenario 8: Text change + different formatting
- [x] `**word**` → `*new*` exports correctly (bold deleted, italic inserted with rPrChange)

#### Mixed changes within paragraph
- [x] Paragraph with both text changes AND formatting changes on unchanged text (tested with dummy doc)
- [x] Multiple EQUAL segments with different formatting changes
- [x] Interleaved DELETE/INSERT/EQUAL with formatting

#### Word compatibility
- [x] Exported file opens in Microsoft Word without errors
- [x] Track changes panel shows formatting changes correctly
- [x] Accept/Reject works for `<w:rPrChange>` changes
- [x] Accept/Reject works for mixed text+formatting changes
- [x] Formatting changes display with correct visual indicator in Word

#### Edge cases
- [x] Single character formatting change (tested with "p" italic in `p<0.001`)
- [x] Formatting change at paragraph start (tested with "Results:" bold)
- [x] Formatting change at paragraph end (tested with "BMI" italic removal)
- [x] Partial word formatting (e.g., `p` italic in `p<0.001`)
- [x] Consecutive formatting changes (e.g., `**bold** *italic*`)
- [x] Nested formatting in original preserved correctly

### Phase 5 (LLM Formatting)
- [ ] Toggle visible in Settings
- [ ] Setting persists in localStorage
- [ ] LLM produces formatted output when enabled
- [ ] Parser correctly converts all marker types
- [ ] Nested markers handled correctly
- [ ] Graceful fallback on parse errors
- [ ] Can be disabled without issues
- [ ] No formatting markers when disabled

---

## Files to Modify

### Phase 1 ✅ (Completed)
- `src/comment_extractor.py` - Extract formatting from OOXML ✅
- `src/context_utils.py` - Handle formatted_html in context ✅
- `templates/partials/card.html` - Display formatted HTML ✅

### Phase 2 (HTML as Source of Truth) ✅
- `main.py` - Store `revised_text_html`, derive plain text ✅
- `src/context_utils.py` - Use `revised_text_html` as canonical source ✅
- `src/llm_handler.py` - Strip HTML before sending to LLM ✅
- `src/session_utils.py` - Save/load `revised_text_html` in session ✅

### Phase 3 (Unified Editor) ✅
- `templates/base.html` - TipTap editor integration via ES modules ✅
- `templates/partials/card.html` - Unified view with TipTap ✅
- `src/diff_utils.py` - `diff_to_editable_html()` with original formatting preservation ✅

### Phase 4 (Word Export) ✅
- `src/docx_writer.py` - Text changes with `<w:ins>`/`<w:del>` ✅
- `src/docx_writer.py` - Bug fix: `_apply_formatting_only()` missing `rsid` ✅
- `src/docx_writer.py` - Enhanced: `_extract_runs_with_formatting()` with formatting set ✅
- `src/docx_writer.py` - New: `_parse_rPr_to_formatting_set()` ✅
- `src/docx_writer.py` - New: `_formatting_set_to_rPr_xml()` ✅
- `src/docx_writer.py` - New: `_get_formatting_for_text_position()` ✅
- `src/docx_writer.py` - New: `_generate_rPrChange_run()` ✅
- `src/docx_writer.py` - Update: `_generate_preserved_formatting_xml()` for EQUAL formatting ✅
- `src/docx_writer.py` - Update: `_get_max_revision_id()` to scan rPrChange ✅
- `src/diff_utils.py` - Update: `text_to_word_runs_with_segmented_formatting()` for INSERT rPrChange ✅
- `src/diff_utils.py` - Fix: `merge_formatting_for_revision()` respects user formatting removals ✅
- `tests/test_docx_writer.py` - New tests for `<w:rPrChange>` scenarios ✅
- `tests/test_diff_utils.py` - New test for user removing formatting ✅
- Manual Word compatibility testing ✅

### Phase 5 (LLM Formatting - Future)
- `src/formatting_parser.py` - New file
- `src/llm_handler.py` - Updated prompts
- `templates/partials/settings_modal.html` - Toggle setting
- `static/js/main.js` - Setting persistence
