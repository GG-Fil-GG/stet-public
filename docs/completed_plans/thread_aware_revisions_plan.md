# Thread-Aware Revisions and Multi-Paragraph Support Plan

**Goal:** Implement thread-aware revision tracking so that regenerating suggestions for a thread excludes that thread's own previous changes, while seeing other threads' accepted changes. Additionally, implement proper multi-paragraph support including paragraph splitting and merging.

**Background:**
- DOM migration (Phases 1-7) is complete
- Current issues discovered during testing:
  1. When regenerating suggestions, thread sees its own previous accepted changes (incorrect)
  2. Multi-paragraph revisions are "flattened" into a single paragraph (broken)
  3. LLM and users cannot split/merge paragraphs (missing feature)

**Key Principle:** Plain text ↔ DOM conversion should be the central abstraction. The same code path should handle:
- LLM output → DOM (revised text with potential structural changes)
- User UI edits → DOM (user can add/remove paragraph breaks)
- DOM → Export (paragraphs serialized to DOCX)

**Existing Conversion Code:**
- **DOM → Plain Text**: Already exists and works well (`PlainTextView`, `Paragraph.plain_text`, `build_paragraph_cache_from_model()`). No changes needed.
- **Plain Text → DOM**: Partially exists (`PlainTextView.compute_edits()`), but only handles within-paragraph changes. Phase 4 extends this to handle structural changes.

---

## Current State Analysis

### What Works
- `DocumentModel` is the single source of truth
- `DocumentEdit` applies INSERT/DELETE/REPLACE/FORMAT within paragraphs
- `CommentAnchor.shift()` adjusts anchors for within-paragraph edits
- `RevisionStore` tracks changes for Word's track changes markup
- `PlainTextView` converts DOM to plain text for LLM context

### What's Missing
1. **Thread tracking**: `Revision` and `DocumentEdit` have no `thread_id` field
2. **Paragraph structure changes**: No `insert_paragraph()` or `remove_paragraph()` methods
3. **Multi-paragraph acceptance**: `/accept` flattens all paragraphs into one
4. **Anchor migration**: No logic for when paragraphs are deleted/merged/split
5. **Original text storage**: No per-thread tracking of original paragraph state
6. **UI paragraph breaks**: User can visually split paragraphs in editor, but they export as single paragraph (bug)

---

## Anchor Behavior Specification

The goal is to keep comment anchors where they were originally placed, to the best extent possible.

### Within-Paragraph Text Changes
- **Replacement**: Anchors move to surround the replacement text
  - Example: `[and stormy]` → `[and gloomy]` - anchors stay around the modified portion
- **Deletion without replacement**: Anchors collapse to zero-width at the deletion point
  - The comment remains visible, marking "where the text used to be"

### Paragraph Merging (A + B → A)
- Anchors on paragraph B migrate to the combined paragraph A
- Offsets are adjusted to maintain relative position within the merged text
- Example: If B's text becomes part of A at offset 50, B's anchors get `para_id=A` and `offset += 50`

### Paragraph Splitting (A → A + B)
- Anchors entirely before the split point: stay in paragraph A
- Anchors entirely after the split point: migrate to new paragraph B (offset adjusted)
- Anchors spanning the split point: Use multi-paragraph anchor (`end_para_id = B`)
  - This is already supported by `CommentAnchor.end_para_id`

### Paragraph Deletion (no merge/replacement)
- If entire paragraph is deleted with no replacement text:
  - Anchors migrate to the nearest adjacent paragraph at position 0 (start of next) or end of previous
  - This keeps comments visible near their original location

---

## Phase 1: Thread-Aware Revision Tracking ✅ COMPLETE

**Goal:** Enable regenerating suggestions to exclude the thread's own previous changes while seeing other threads' accepted changes.

**Status:** All tasks completed and tested. Commits: `079f6a0`, `d6722ef`, `e93dc67`

### 1.1 Add thread_id to Data Structures

**Files:** `src/document_model/edits.py`, `src/document_model/revisions.py`

- [x] Add `thread_id: Optional[str] = None` field to `DocumentEdit`
- [x] Add `thread_id: Optional[str] = None` field to `Revision`
- [x] Update `Revision.to_dict()` and `from_dict()` for serialization
- [x] Update `DocumentEdit` factory methods to accept `thread_id`

### 1.2 Update RevisionStore Methods

**File:** `src/document_model/revisions.py`

- [x] Add `thread_id` parameter to `add_insertion()`
- [x] Add `thread_id` parameter to `add_deletion()`
- [x] Add `thread_id` parameter to `add_formatting_change()`
- [x] Add `get_revisions_by_thread(thread_id)` method
- [x] Add `get_revisions_excluding_thread(thread_id)` method
- [x] Add `get_revisions_for_paragraph_excluding_thread(para_id, thread_id)` method (bonus)

### 1.3 Update DocumentModel.apply_edit

**File:** `src/document_model/model.py`

- [x] Pass `thread_id` from `DocumentEdit` when creating revisions
- [x] Update all `self.revisions.add_*()` calls to include thread_id

### 1.4 Store Original Paragraph State Per Thread

**File:** `src/session_utils.py`

- [x] Create `thread_original_text: Dict[str, Dict[str, str]]` structure
  - Maps `thread_id` → `para_id` → original text before that thread's edit
- [x] Update `create_session_from_model()` to initialize this structure
- [x] Update serialization/deserialization to persist this data

### 1.5 Update /accept Endpoint

**File:** `main.py`

- [x] Pass `thread_id` when creating `DocumentEdit` objects
- [x] Store original paragraph text before applying edit (in `thread_original_text`)

### 1.6 Implement Thread-Excluded Text Computation

**File:** `src/session_utils.py`

- [x] Add `store_thread_original_text()` helper function
- [x] Add `get_text_excluding_thread()` helper function
- [x] Add `get_paragraph_text_for_llm()` - returns text appropriate for LLM context
- [x] Add `build_paragraph_cache_for_thread()` - builds cache excluding thread's changes

### 1.7 Update /generate to Use Thread-Aware Context

**File:** `main.py`

- [x] When building `paragraph_cache` for LLM context:
  - Use `build_paragraph_cache_for_thread()` which excludes current thread's changes
- [x] This ensures regenerating Thread A sees: original + (all other threads' changes)

### 1.8 Write Tests for Phase 1

**File:** `tests/test_thread_aware_revisions.py`

- [x] Test: Thread A accepts, Thread A regenerates → sees original
- [x] Test: Thread A accepts, Thread B generates → sees Thread A's changes
- [x] Test: Thread A accepts, Thread B accepts, Thread A regenerates → sees original + B
- [x] Test: Revision serialization includes thread_id
- [x] Test: `get_revisions_by_thread()` filters correctly
- [x] 27 total tests covering all Phase 1 functionality

### 1.9 UI Synchronization (Additional Fix)

**File:** `main.py`

- [x] Add `find_threads_sharing_paragraphs()` helper to identify affected threads
- [x] Update `/accept` endpoint to return HTMX out-of-band swaps for affected threads
- [x] Cards for threads sharing the same paragraph now auto-update when one accepts

**Checkpoint:** ✅ Committed

---

## Phase 2: Multi-Paragraph Edit Support (Same Count) ✅ COMPLETE

**Goal:** Fix acceptance of multi-paragraph revisions where paragraph count remains the same.

**Status:** All tasks completed and tested.

### 2.1 Fix /accept for Multi-Paragraph (Non-Table)

**File:** `main.py`

- [x] When `all_target_para_ids` has multiple entries and NOT a table:
  - Parse revised text by `\n\n` separator
  - Match revised paragraphs to `all_target_para_ids` by index
  - Apply separate `DocumentEdit` to each paragraph
  - Pass `thread_id` to each edit

### 2.2 Handle Formatting Merge for Each Paragraph

**File:** `main.py`

- [x] For each paragraph in multi-paragraph revision:
  - Formatting is preserved via `revised_text_html` from suggestion (created during `/generate`)
  - DOM edits use plain text; formatting applied at display/export time

### 2.3 Write Tests for Phase 2

**File:** `tests/test_multi_paragraph.py`

- [x] Test: Two-paragraph revision applies to both paragraphs
- [x] Test: Three-paragraph revision with formatting preserved
- [x] Test: Multi-paragraph with thread tracking
- [x] Additional tests: detection logic, parsing, edge cases (14 tests total)

**Checkpoint:** ✅ Committed

---

## Phase 3: Paragraph Structural Changes ✅ COMPLETE

**Goal:** Enable LLM and users to split and merge paragraphs.

**Status:** All tasks completed and tested. Commit: `69e9896`

### 3.1 Add DocumentBody Manipulation Methods

**File:** `src/document_model/model.py`

- [x] Add `insert_element_at(index: int, element: BodyElement)` method
  - Insert paragraph at specific position
  - Update `_para_id_index`
  - Renumber subsequent element indices
- [x] Add `remove_element(para_id: str)` method
  - Remove paragraph by para_id
  - Update `_para_id_index`
  - Renumber subsequent element indices
- [x] Add `get_element_index(para_id: str) -> int` method

### 3.2 Add New EditTypes for Structural Changes

**File:** `src/document_model/edits.py`

- [x] Add `EditType.INSERT_PARAGRAPH` - create new paragraph
- [x] Add `EditType.DELETE_PARAGRAPH` - remove entire paragraph
- [x] Add factory methods: `DocumentEdit.insert_paragraph()`, `DocumentEdit.delete_paragraph()`

### 3.3 Generate Valid Para IDs for New Paragraphs

**File:** `src/document_model/utils.py`

- [x] `generate_valid_para_id()` function already exists
- [x] First character is 0-7 (Word requirement) - validated
- [x] Uniqueness check within document - implemented

### 3.4 Update DocumentModel.apply_edit for Structural Changes

**File:** `src/document_model/model.py`

- [x] Handle `EditType.INSERT_PARAGRAPH`:
  - Create new `Paragraph` with generated para_id and text_id
  - Insert at specified position via `body.insert_element_at()`
  - Create revision if `track_change=True`
- [x] Handle `EditType.DELETE_PARAGRAPH`:
  - Remove paragraph via `body.remove_element()`
  - Handle anchor migration via `_migrate_anchors_for_deleted_paragraph()`
  - Create revision if `track_change=True`

### 3.5 Implement Anchor Migration for Paragraph Deletion/Merge

**File:** `src/document_model/model.py`

- [x] `_migrate_anchors_for_deleted_paragraph()` - handles pure deletion
- [x] `_migrate_anchors_for_merge()` - handles merge scenario (B into A)
- [x] Migration to nearest adjacent paragraph when deleted
- [x] Multi-paragraph anchor handling when start/end deleted

### 3.6 Implement Anchor Migration for Paragraph Splitting

**File:** `src/document_model/model.py`

- [x] `split_paragraph()` method added to DocumentModel
- [x] `_migrate_anchors_for_split_paragraph()` handles:
  - **Anchors entirely before N** (end_offset ≤ N): stay in A, no changes
  - **Anchors entirely after N** (start_offset ≥ N): migrate to B with adjusted offsets
  - **Anchors spanning N**: convert to multi-paragraph anchor using `end_para_id`
- [x] `merge_paragraphs()` method added for the reverse operation

### 3.7 Write Tests for Structural Changes

**File:** `tests/test_paragraph_structure.py`

- [x] Test: DocumentBody manipulation (insert, remove, get_element_index) - 10 tests
- [x] Test: INSERT_PARAGRAPH and DELETE_PARAGRAPH edits - 6 tests
- [x] Test: Paragraph splitting with anchor migration - 6 tests
- [x] Test: Paragraph merging with anchor migration - 4 tests
- [x] Test: Anchor migration for deleted paragraphs - 2 tests
- [x] Test: Para_id generation validity and uniqueness - 4 tests
- [x] Test: Integration tests (split-merge roundtrip, multiple inserts) - 3 tests
- [x] 35 total tests, all passing

**Checkpoint:** ✅ Committed

---

## Phase 4: Extend Plain Text → DOM Conversion for Structural Changes ✅ COMPLETE

**Goal:** Extend existing plain text → DOM conversion to handle paragraph structure changes (splits, merges, insertions, deletions). Create a single unified entry point for all plain text → DOM conversion.

**Status:** All tasks completed and tested. 29 new tests added.

**Implementation:**
- Added `compute_structural_edits()` - computes edits including structural changes
- Added `_align_paragraphs()` - sequence alignment algorithm for detecting splits/merges
- Added `_compute_within_paragraph_edits()` - uses REPLACE for atomic paragraph updates
- Added `apply_revision_from_plain_text()` - THE unified entry point for plain text → DOM
- Updated `/accept` endpoint to use unified entry point for non-table revisions
- Table revisions retain special cell-parsing logic

### 4.1 Create Structural Diff Layer

**File:** `src/document_model/plain_text.py` (extend existing, not new file)

- [x] Add `compute_structural_edits(original_para_texts: List[str], revised_para_texts: List[str], para_ids: List[str]) -> List[DocumentEdit]`
  - Compare paragraph counts
  - If same count: delegate each paragraph to REPLACE edit
  - If different count: use alignment algorithm to detect structural changes

### 4.2 Implement Paragraph Alignment Algorithm

**File:** `src/document_model/plain_text.py`

- [x] Use sequence alignment (like diff) at paragraph level (`_align_paragraphs()`)
- [x] Detect and generate edits for:
  - Paragraph content changed → REPLACE edit
  - Paragraph split → REPLACE (shortened) + INSERT_PARAGRAPH (new content)
  - Paragraphs merged → DELETE_PARAGRAPH + REPLACE (extended content)
  - Paragraph inserted → INSERT_PARAGRAPH
  - Paragraph deleted → DELETE_PARAGRAPH

### 4.3 Create Unified Entry Point

**File:** `src/document_model/plain_text.py`

- [x] Add `apply_revision_from_plain_text(model: DocumentModel, para_ids: List[str], revised_text: str, thread_id: str, track_changes: bool = True) -> List[DocumentEdit]`
  - Parse revised_text into paragraphs by `\n\n`
  - Get original paragraph texts from model
  - Call `compute_structural_edits()` to get edit list
  - Apply edits to model via `model.apply_edit()`
  - Return applied edits for tracking
- [x] This becomes THE single function for all plain text → DOM conversion

### 4.4 Update All Call Sites to Use Unified Entry Point

**File:** `main.py`

- [x] `/accept` endpoint: Uses `apply_revision_from_plain_text()` for non-table revisions
- [x] Table revisions retain existing cell-parsing logic (different structure)

### 4.5 Write Tests for Extended Conversion

**File:** `tests/test_plain_text_conversion.py`

- [x] Test: Same paragraph count, no changes → no edits
- [x] Test: Same paragraph count, content changes → REPLACE edits
- [x] Test: One paragraph → two paragraphs (split) → structural edits generated
- [x] Test: Two paragraphs → one paragraph (merge) → structural edits generated
- [x] Test: Insert new paragraph in middle
- [x] Test: Delete middle paragraph
- [x] Test: Empty paragraph handling
- [x] Test: Thread ID propagation
- [x] Test: Integration with DocumentModel

**Checkpoint:** Commit "Phase 4: Unified plain text → DOM conversion with structural support"

---

## Phase 4.5: Architecture Refactoring - Eliminate Cache Duplication

**Goal:** Simplify the data architecture by making DOM the true single source of truth, eliminating redundant cached copies that can become inconsistent.

**Problem Statement:**
The current architecture stores multiple cached copies of document data:
- `paragraph_cache` - flattened view of DOM, rebuilt frequently
- `original_paragraph_cache` - snapshot at session creation
- `original_thread_target_indices` - snapshot of index mappings
- `thread_target_indices` - rebuilt frequently
- `suggestions[thread_id]["revised_text_html"]` - derived from revised_text

This leads to:
1. **Inconsistency bugs** - indices computed from current model don't match original cache
2. **Unnecessary storage** - same data stored multiple times in different forms
3. **Complex data flow** - hard to reason about which cache to use when

**Target Architecture:**
```
Storage (minimal):
├── model (DocumentModel) - current state, source of truth
├── original_model (DocumentModel) - snapshot at session creation
├── suggestions[thread_id]["revised_text"] - raw LLM output only
└── thread_original_text - per-thread delta tracking (still needed)

Computed on demand (via helper functions):
├── build_paragraph_cache_from_model(model) → paragraph cache
├── build_thread_target_indices_from_model(model) → indices
├── model.get_paragraph(para_id).to_html() → HTML for display
└── model.get_paragraph(para_id).plain_text → text for LLM
```

**Key Principle:** When you need original document data, compute it from `original_model`. When you need current data, compute it from `model`. No stored caches that can drift.

### 4.5.1 Store Original Model Instead of Caches ✅

**File:** `src/session_utils.py`

- [x] In `create_session_from_model()`:
  - Store deep copy of model as `original_model_data` (using `model.to_dict()`)
  - Remove `original_paragraph_cache` from session creation
  - Remove `original_thread_target_indices` from session creation
- [x] Update serialization to save/load `original_model_data` instead of caches
- [x] Add helper function: `get_original_model(session) -> DocumentModel`

### 4.5.2 Create On-Demand Computation Helpers ✅

**File:** `src/session_utils.py`

- [x] Add `get_paragraph_cache(session, use_original: bool = False) -> list`
  - If `use_original`: compute from `original_model`
  - Else: compute from `model`
  - No storage, just returns computed result
- [x] Add `get_thread_target_indices(session, use_original: bool = False) -> dict`
  - Same pattern - compute from appropriate model

### 4.5.3 Update All Call Sites in main.py ✅

**File:** `main.py`

- [x] Find all uses of `session.get("original_paragraph_cache", ...)`
  - Replace with `get_paragraph_cache(session, use_original=True)`
- [x] Find all uses of `session.get("original_thread_target_indices", ...)`
  - Replace with `get_thread_target_indices(session, use_original=True)`
- [x] Find all uses of `session.get("paragraph_cache", ...)`
  - Replace with `get_paragraph_cache(session, use_original=False)`
- [x] Find all uses of `session.get("thread_target_indices", ...)`
  - Replace with `get_thread_target_indices(session, use_original=False)`
- [x] Remove any code that stores these caches back to session

### 4.5.4 Clean Up Suggestion Storage - DEFERRED

**Note:** This task is deferred as it would change UI editing semantics. Currently, users can edit HTML directly in the UI, and that HTML is stored. Computing HTML on demand would lose any user formatting edits.

**File:** `main.py`

- [ ] Stop storing `revised_text_html` in suggestions
- [ ] Create helper: `get_revised_text_html(session, thread_id) -> str`
  - Computes HTML by merging `revised_text` with original formatting on demand
- [ ] Update all places that read `suggestions[thread_id]["revised_text_html"]`

### 4.5.5 Update Tests ✅

**File:** `tests/test_session_utils.py` and others

- [x] Update tests that check for `original_paragraph_cache` in session (now checks for `original_model_data`)
- [x] Verify session serialization/deserialization still works
- [x] All 467 tests passing

### 4.5.6 Verify No Regressions ✅

- [x] Run full test suite - 467 tests passing
- [ ] Manual test: upload document, generate, accept, export (user can verify)
- [ ] Verify diffs show correctly after acceptance (user can verify)
- [ ] Verify table diffs work correctly (user can verify)

**Checkpoint:** Commit "Phase 4.5: Refactor to compute caches on demand from DOM" ✅

---

## Phase 5: Serializer Updates for New Paragraphs ✅ COMPLETE

**Goal:** Ensure new/modified paragraph structure exports correctly to DOCX.

### 5.1 Update Serializer for Inserted Paragraphs

**File:** `src/document_model/serializer.py`

- [x] Detect paragraphs added by Stet (not in original DOCX)
- [x] Generate proper XML for new paragraphs:
  - Valid `w14:paraId` attribute
  - Basic paragraph properties (plain text, no special formatting from Stet)
  - Wrap content in track changes insertion markup (`<w:ins>`) per design decision #2

### 5.2 Update Serializer for Deleted Paragraphs

**File:** `src/document_model/serializer.py`

- [x] Detect paragraphs removed from model but in original DOCX
- [x] Wrap deleted paragraph content in track changes deletion markup (`<w:del>`)
- [x] This ensures reviewers can see what was removed (per design decision #2)

### 5.3 Round-Trip Testing

**File:** `tests/test_serializer.py` (added to existing test file)

- [x] Test: Extract all para_ids from document XML
- [x] Test: Mark paragraph as deleted with track changes
- [x] Test: Insert new paragraph with track changes
- [x] Test: Find previous existing paragraph for positioning
- [x] Integration test: Export with new paragraph → Word opens correctly

**Checkpoint:** Commit "Phase 5: Serializer handles structural changes"

---

## Phase 6: UI Integration ✅ COMPLETE

**Goal:** Fix the current bug where paragraph breaks in the UI editor don't result in actual paragraph breaks in export. Ensure user can split/merge paragraphs via the Revised Text editor.

**Known Bug:** User can visually split paragraphs in the contenteditable editor, but they export as a single paragraph. This needs to be fixed.

### 6.1 Investigate Current UI Edit Handling

**File:** `main.py` (wherever UI edits are processed)

- [x] Identify how user edits to `revised_text_html` are currently processed
  - TipTap editor produces `<p>` tags for paragraphs
  - `/update_suggestion` stores HTML directly
  - `/accept` strips HTML and applies as REPLACE edit
- [x] Determine what HTML is generated when user presses Enter in the editor
  - TipTap produces `<p>First</p><p>Second</p>` for paragraph breaks
- [x] Trace why paragraph breaks are lost during acceptance/export
  - `strip_html_tags()` was stripping `<p>` tags without preserving structure
  - `/accept` was doing single REPLACE edit regardless of paragraph structure

### 6.2 Fix Paragraph Break Detection

**File:** `src/diff_utils.py`

- [x] Updated `strip_html_tags()` to preserve paragraph structure:
  - `<p>`, `<div>`, `<li>`, etc. closing tags → double newline (`\n\n`)
  - `<br>` tags → single newline (`\n`)
  - Multiple consecutive newlines collapsed to double
  - Added `preserve_paragraphs` parameter (default True)

**File:** `main.py`

- [x] Updated `/accept` and `/commit_chat` endpoints:
  - Detect when revised text contains `\n\n` (paragraph breaks)
  - Use `apply_revision_from_plain_text()` for structural changes
  - Continue using simple REPLACE for non-structural changes (efficiency)

### 6.3 Update UI Editor if Needed

**Files:** `templates/partials/card.html`

- [x] TipTap editor already produces consistent `<p>` paragraph markup
- [x] No additional UI changes needed - Enter key naturally creates paragraphs

### 6.4 Testing ✅ COMPLETE

- [x] Manual test: User adds paragraph break in editor → new paragraph in export
- [x] Manual test: User removes paragraph break → paragraphs merged in export
- [x] Manual test: LLM-generated paragraph splits with field codes

**Checkpoint:** Commit "Phase 6: UI paragraph editing support"

---

## Phase 7: Final Integration and Cleanup

### 7.1 Update Caches After Structural Changes ✅ COMPLETE

**Note:** This was addressed in Phase 4.5. Caches are now computed on-demand from the DocumentModel via helper functions (`get_paragraph_cache`, `get_thread_target_indices`), so they automatically reflect structural changes.

### 7.2 Documentation (Light Touch) ✅ COMPLETE

- [x] Brief update to README noting paragraph split/merge support

### 7.3 End-to-End Tests (Focused) ✅ COMPLETE

**File:** `tests/test_workflow_integration.py`

- [x] TestParagraphSplitWorkflow::test_paragraph_split_basic
- [x] TestParagraphSplitWorkflow::test_paragraph_split_with_field_codes
- [x] TestParagraphSplitWorkflow::test_paragraph_merge

### 7.4 Light Code Cleanup ✅ COMPLETE

- [x] All tests passing (482 tests)
- [x] All key files compile without errors
- [x] (User will do comprehensive audit separately)

**Checkpoint:** Commit "Phase 7: Thread-aware revisions complete"

---

## Summary

| Phase | Description | Complexity | Dependencies | Status |
|-------|-------------|------------|--------------|--------|
| 1 | Thread-aware revision tracking | Medium | None | ✅ Complete |
| 2 | Multi-paragraph acceptance (same count) | Low | Phase 1 | ✅ Complete |
| 3 | Paragraph structural changes | High | None (can parallel Phase 1-2) | ✅ Complete |
| 4 | Unified plain text ↔ DOM conversion | High | Phase 3 | ✅ Complete |
| 4.5 | Architecture refactoring (eliminate cache duplication) | Medium | Phase 4 | ✅ Complete |
| 5 | Serializer updates | Medium | Phase 3-4 | ✅ Complete |
| 6 | UI integration | Low | Phase 4 | ✅ Complete |
| 7 | Final integration (light cleanup) | Low | All above | ✅ Complete |

**Estimated effort:** 3-5 sessions for Phase 1-2, 4-6 sessions for Phase 3-7.

---

## Risk Mitigation

### High Risk: Phase 3-4 (Structural Changes)
- Anchor migration is complex; test extensively
- Paragraph alignment algorithm needs edge case handling
- Keep ability to fall back to "same count" mode if issues

### Medium Risk: Phase 5 (Serialization)
- New paragraphs must have valid XML structure
- Test with multiple Word versions if possible

### Low Risk: Phase 1-2 (Thread Tracking)
- Additive changes, low regression risk
- Well-defined behavior

---

## Design Decisions (Resolved)

1. **Paragraph style inheritance:** New paragraphs should be plain text (no bold/italic/underline/superscript/subscript applied by Stet). Word will handle inheriting other styles from surrounding text naturally.

2. **Track changes for structure:** YES - paragraph insertion and deletion should appear as track changes in Word, visible to reviewers.

3. **UI paragraph detection:** Currently BROKEN - user can visually split paragraphs in the editor, but they export as a single paragraph. This must be fixed in Phase 6. Need to:
   - Detect paragraph breaks in HTML (likely `<br>` or `<p>` tags)
   - Convert these to actual paragraph structure in DOM
   - Ensure export creates separate `<w:p>` elements
