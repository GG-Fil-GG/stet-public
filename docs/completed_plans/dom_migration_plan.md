# DOM Migration Plan

**Goal:** Migrate from the current ad-hoc XML manipulation approach to a proper Document Object Model (DOM) architecture as specified in `docs/document_model_design.md`.

**Benefits:**
- Single source of truth for document state
- Automatic anchor adjustment when text changes
- Cleaner separation of concerns
- Reduced complexity (current `_extract_comments_with_ranges` has complexity 84)
- Better testability

---

## Current State → Target State

### Files to Replace

| Current File | Lines | Target | Notes |
|--------------|-------|--------|-------|
| `comment_extractor.py` | 1,781 | `document_model/parser.py` + `comments.py` | Parsing logic moves to DOM |
| `docx_writer.py` | 1,926 | `document_model/serializer.py` + `revisions.py` | Serialization moves to DOM |
| `context_utils.py` | 582 | `document_model/plain_text.py` | PlainTextView replaces paragraph cache |

### Files to Modify

| File | Lines | Changes Needed |
|------|-------|----------------|
| `main.py` | 2,618 | Use DOM model instead of extractors; route handlers simplify |
| `llm_handler.py` | 1,406 | Use PlainTextView for context; DOM model for edits |
| `diff_utils.py` | 1,591 | Keep mostly as-is; integrate with PlainTextView |
| `session_utils.py` | 300 | Serialize/deserialize DOM model (or keep virtual state) |

### New Files to Create

```
src/document_model/
├── __init__.py
├── model.py              # DocumentModel, DocumentBody (~200 lines)
├── paragraph.py          # Paragraph, Run, RunFormatting (~250 lines)
├── comments.py           # CommentStore, Comment, CommentAnchor, CommentThread (~300 lines)
├── revisions.py          # RevisionStore, Revision (~200 lines)
├── plain_text.py         # PlainTextView, TextScope, DOMPosition (~350 lines)
├── edits.py              # DocumentEdit, EditType (~100 lines)
├── parser.py             # DocumentParser (~400 lines)
├── serializer.py         # DocumentSerializer (~400 lines)
└── utils.py              # ID generators, XML helpers (~150 lines)
```

Estimated total: ~2,350 lines for new DOM module (vs ~4,300 lines being replaced)

---

## Migration Phases

### Phase 1: Core Data Structures (Foundation) ✅ COMPLETE
**Goal:** Create the DOM data structures without any parsing/serialization.
**Risk:** Low - no integration with existing code yet.

#### 1.1 Create module skeleton
- [x] Create `src/document_model/__init__.py`
- [x] Set up proper exports

#### 1.2 Implement basic dataclasses
- [x] `model.py`: `DocumentModel`, `DocumentBody`, `DocumentProperties`
- [x] `paragraph.py`: `Paragraph`, `Run`, `RunFormatting`, `ParagraphProperties`
- [x] `comments.py`: `CommentStore`, `Comment`, `CommentThread`, `CommentAnchor`, `CommentParagraph`
- [x] `revisions.py`: `RevisionStore`, `Revision`, `RevisionType`
- [x] `edits.py`: `DocumentEdit`, `EditType`
- [x] `utils.py`: ID generators (including paraId first-char constraint 0-7)

#### 1.3 Write unit tests for data structures
- [x] Test Comment/Thread creation and relationships
- [x] Test ID generators (especially paraId constraint)
- [x] Test anchor position calculations

**Checkpoint:** ✅ All dataclasses instantiable, basic methods work, 44 tests pass. (Commit: Phase 1)

---

### Phase 2: Document Parser (Read-Only) ✅ COMPLETE
**Goal:** Parse DOCX files into DocumentModel. Can run alongside existing code.
**Risk:** Medium - must match existing extraction behavior.

#### 2.1 Implement DocumentParser
- [x] `parser.py`: Main `parse()` method
- [x] Parse document structure using lxml (paragraphs, runs, tables)
- [x] Parse comments from all 4 XML files using lxml
- [x] Parse comment anchors from document.xml
- [x] Build paragraph position mappings
- [x] Build CommentStore with threading relationships

#### 2.2 Validation against current extractor
- [x] Create comparison script: `scripts/validate_parser.py`
- [x] Verify comment count matches
- [x] Verify threading relationships match
- [x] Verify anchor positions match
- [x] Test with all documents in `test_data/` (18/18 = 100% match)

#### 2.3 Edge case handling
- [x] Multi-paragraph comments
- [x] Comments in tables
- [x] Comments with existing replies
- [x] Documents with track changes
- [x] Documents without comments (edge case)

**Checkpoint:** ✅ `DocumentParser.parse()` produces identical data to `CommentExtractor` for all 18 test documents. 32 tests pass. (Commit: Phase 2)

---

### Phase 3: PlainTextView (LLM Integration) ✅ COMPLETE
**Goal:** Replace `paragraph_cache` and context utilities with PlainTextView.
**Risk:** Medium - affects LLM prompt generation.

#### 3.1 Implement PlainTextView
- [x] `plain_text.py`: `PlainTextView`, `TextScope`, `DOMPosition`
- [x] Bidirectional mapping (DOM ↔ plain text positions)
- [x] Comment range tracking in plain text coordinates
- [x] Citation/field code preservation (PreservedRegion structure ready)

#### 3.2 Integration with LLM handler
- [x] `get_context_for_thread()` function compatible with LLM handler interface
- [x] `PlainTextViewBuilder.build_for_thread()` supports accepted_revisions
- [ ] Update `llm_handler.py` to use DOM model (deferred to Phase 6)
- [ ] Verify citation quarantine still works (deferred to Phase 6)

#### 3.3 Side-by-side testing
- [x] Run both old and new context generation (`scripts/validate_plain_text_view.py`)
- [x] Compare context text (86.6% exact match, 97.3% acceptable)
- [x] Differences are whitespace handling (new code is more accurate)

**Checkpoint:** ✅ PlainTextView generates compatible context. 33 tests pass. 999 threads validated across 18 documents. (Commit: Phase 3)

---

### Phase 4: Edit Operations ✅ COMPLETE
**Goal:** Implement edit application with automatic anchor adjustment.
**Risk:** High - core functionality change.

#### 4.1 Implement edit operations
- [x] `DocumentEdit` application in `DocumentModel.apply_edit()`
- [x] Anchor shift logic in `CommentAnchor.shift()` (fixed edge case: position AT edit point)
- [x] Run splitting when edits occur mid-run
- [x] Paragraph modification with cache invalidation

#### 4.2 Implement diff-based edit computation
- [x] `PlainTextView.compute_edits()` - compute DOM edits from text diff
- [x] `PlainTextView.compute_edits_for_paragraph()` - single paragraph variant
- [x] Integrate with existing `diff_utils.py` (reuses `compute_diff()`)
- [x] Handle multi-paragraph edits (via position mapping)
- [ ] Handle formatting preservation (deferred - not needed for MVP)

#### 4.3 Track changes integration
- [x] Create `Revision` entries for tracked changes (`RevisionStore.add_*()`)
- [x] Support both direct edits and tracked changes (`track_change` flag)
- [x] Preserve existing track changes during parsing

**Checkpoint:** ✅ Can apply text edits to DOM, anchors adjust correctly, track changes work. 28 tests pass. (Commit: Phase 4)

---

### Phase 5: Document Serializer ✅ COMPLETE
**Goal:** Serialize DocumentModel back to DOCX.
**Risk:** High - must produce Word-compatible output.
**Status:** Completed 2026-02-05

#### 5.1 Implement DocumentSerializer
- [x] `serializer.py`: Main `serialize()` method
- [x] Copy original DOCX as base (preserve unknown elements)
- [x] Update document.xml with paragraph changes
- [x] Write all 4 comment XML files
- [x] Insert track change markup

#### 5.2 Comment serialization
- [x] Generate comments.xml (with sequential ordering)
- [x] Generate commentsExtended.xml (with correct threading via paraIdParent)
- [x] Generate commentsIds.xml (with valid paraIds - first char 0-7)
- [x] Generate commentsExtensible.xml (with UTC timestamps)
- [x] Insert anchor markup in document.xml (reply anchors adjacent to root)

#### 5.3 Round-trip validation
- [x] Parse → Serialize → Parse again
- [x] Compare DOM before and after
- [x] `scripts/validate_round_trip.py` validates all test files
- [x] 100% success rate: 18 files, 14162 paragraphs, 1422 comments

**Implementation Details:**
- `src/document_model/serializer.py`: DocumentSerializer class
- 23 unit tests in `tests/test_serializer.py`
- Round-trip validation script: `scripts/validate_round_trip.py`

**Key Features:**
- Atomic write (temp file + move)
- Preserves unknown XML elements by copying original DOCX
- Proper namespace handling via string manipulation
- XML special character escaping
- Thread-grouped ordering in commentsExtended/commentsIds

**Checkpoint:** Full round-trip working, Word accepts output.

---

### Phase 6: Integration with Application ✅ COMPLETE
**Goal:** Make DocumentModel the single source of truth for all document state.
**Risk:** Medium - many touch points but individually small changes.
**Status:** Completed 2026-02-05 (Revised approach: direct DOM, no bridge)

#### 6.1 Session management with DOM serialization
- [x] Add `to_dict()`/`from_dict()` methods to all DOM classes for JSON serialization
- [x] Update `session_utils.py` with DOM-aware session creation and persistence
- [x] `create_session_from_model()` - initializes session with DocumentModel as source of truth
- [x] Serialize entire DocumentModel to JSON for session persistence
- [x] Bridge functions for legacy LLMHandler compatibility:
  - `convert_dom_thread_for_llm()` - convert DOM thread to legacy format
  - `build_paragraph_cache_from_model()` - build cache from DOM
  - `build_thread_target_indices_from_model()` - build indices from DOM

#### 6.2 Update endpoints to use DOM model directly
- [x] `/upload`: Parse with `parse_docx()`, create session from model
- [x] `/generate`: Use DOM model for context, with legacy-compatible bridge
- [x] `/accept`: Apply `DocumentEdit` directly to model (no virtual state)
- [x] `/export`: Use `DocumentSerializer` to write modified model
- [x] Other endpoints: Lazy thread_objects generation for backward compatibility

#### 6.3 Cleanup deprecated code
- [x] Remove `src/dom_integration.py` (bridge module no longer needed)
- [x] Remove `tests/test_dom_integration.py`
- [x] Update `tests/test_workflow_integration.py` to use direct DOM approach
- [x] Remove DOM_AVAILABLE import from `llm_handler.py`

#### 6.4 Feature parity testing
- [x] Test complete workflow: upload → generate → accept → export
- [x] Test with multiple document types (18 test files)
- [x] Workflow integration tests (8 tests) - using direct DOM approach
- [x] Session serialization tests (14 tests)
- [x] Model serialization tests (27 tests)
- [x] Total: 455 tests passing

**Implementation Details:**
- `src/session_utils.py`: DOM session management with bridge functions
- `tests/test_session_utils.py`: 14 tests for session utilities
- `tests/test_model_serialization.py`: 27 tests for DOM serialization
- `tests/test_workflow_integration.py`: 8 tests for complete workflow

**Key Design Decisions:**
1. **DOM as source of truth**: DocumentModel stores all document state, not virtual dicts
2. **Direct endpoint updates**: No bridge module - endpoints use DOM model directly
3. **LLMHandler bridge**: Legacy-compatible conversion in session_utils.py until LLMHandler refactored
4. **Backward compatibility**: `get_session()` lazily creates thread_objects for legacy code paths
5. **Revisions in model**: Accepted changes stored as edits in DocumentModel, not in `accepted_revisions` dict

**Checkpoint:** Full application works with DOM as single source of truth.

---

### Phase 7: Cleanup ✅ COMPLETE
**Goal:** Remove legacy code, finalize documentation, verify quality metrics.
**Risk:** Low-Medium - systematic removal with tests after each step.
**Approach:** Incremental removal with commits after each section.

**Summary of completed work:**
- Removed 3,674 lines of legacy source code (comment_extractor.py + docx_writer.py)
- Removed 2,068 lines of legacy tests
- Removed ~500 lines of legacy code paths from main.py
- Archived 4 validation scripts
- Created LLMThread/LLMComment adapter classes for LLMHandler compatibility
- All 354 tests pass

---

#### 7.1 Remove legacy from main.py ✅
- [x] Created LLMComment and LLMThread adapter classes in session_utils.py
- [x] Removed CommentExtractor/CommentThread imports
- [x] Removed DocxWriter import and ~300 lines of legacy export code
- [x] Removed all `is_dom_session()` checks and legacy branches (~150 lines)

---

#### 7.2 Remove legacy from llm_handler.py ✅
- [x] Updated imports to use adapter classes from session_utils
- [x] Updated __main__ test block to use DOM parser
- [x] Updated docstrings to reference DocumentModel

---

#### 7.3 Remove legacy from session_utils.py ✅
- [x] Removed legacy serialization branches
- [x] Simplified convert_dom_thread_for_llm to use new adapter classes
- [x] Removed LegacyCommentThread/LegacyComment imports

---

#### 7.4 Remove legacy test files ✅
- [x] Deleted tests/test_comment_extractor.py (36 tests, ~600 lines)
- [x] Deleted tests/test_docx_writer.py (51 tests, ~880 lines)
- [x] Deleted tests/test_integration.py (12 tests, ~600 lines)
- [x] Removed 2 validation tests from test_document_parser.py

Test count: 455 → 354 (101 legacy tests removed)

---

#### 7.5 Archive legacy scripts ✅
- [x] Archived scripts/validate_plain_text_view.py
- [x] Archived scripts/validate_parser.py
- [x] Archived scripts/diagnose_replies.py
- [x] Archived scripts/run_document_tests.py

---

#### 7.6 Delete legacy source files ✅
- [x] Deleted src/comment_extractor.py (1,787 lines)
- [x] Deleted src/docx_writer.py (1,887 lines)

---

#### 7.7-7.9 Remaining tasks
- [ ] Review context_utils.py and diff_utils.py for unused code
- [ ] Update documentation (README, design docs)
- [ ] Run final audit (Pylint, radon, file sizes)

**Checkpoint:** ✅ Core cleanup complete. DOM model is now the only implementation.

---

## Detailed Task Breakdown

### Phase 1 Tasks (Estimated: 1-2 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Create module skeleton | 15 min | None |
| Implement `Paragraph`, `Run`, `RunFormatting` | 1 hr | Skeleton |
| Implement `Comment`, `CommentStore`, `CommentAnchor` | 1.5 hr | Paragraph |
| Implement `DocumentModel`, `DocumentBody` | 45 min | Paragraph, Comment |
| Implement `Revision`, `RevisionStore` | 45 min | Paragraph |
| Implement ID generators with tests | 30 min | None |
| Write unit tests | 1.5 hr | All above |

### Phase 2 Tasks (Estimated: 2-3 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Parse document structure (paragraphs, runs) | 2 hr | Phase 1 |
| Parse comments.xml | 1 hr | Phase 1 |
| Parse commentsExtended.xml (threading) | 1 hr | Comments |
| Parse commentsIds.xml + commentsExtensible.xml | 45 min | Comments |
| Parse comment anchors from document.xml | 1.5 hr | Comments |
| Comparison script | 1 hr | Parser |
| Edge case handling + tests | 2 hr | Parser |

### Phase 3 Tasks (Estimated: 1-2 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Implement PlainTextView core | 2 hr | Phase 2 |
| Bidirectional position mapping | 1.5 hr | PlainTextView |
| Citation preservation | 1 hr | PlainTextView |
| LLM handler integration | 1.5 hr | PlainTextView |
| Side-by-side testing | 1 hr | Integration |

### Phase 4 Tasks (Estimated: 2-3 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Edit application logic | 2 hr | Phase 3 |
| Anchor adjustment | 1.5 hr | Edit application |
| Diff-to-edit computation | 2 hr | Anchor adjustment |
| Track changes integration | 2 hr | Diff computation |
| Comprehensive edit tests | 2 hr | All above |

### Phase 5 Tasks (Estimated: 2-3 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Basic serializer structure | 1 hr | Phase 4 |
| Comment XML generation | 2 hr | Serializer |
| Anchor insertion | 1.5 hr | Comment XML |
| Track change markup | 1.5 hr | Serializer |
| Round-trip validation | 2 hr | All above |
| Word compatibility testing | 1 hr | Validation |

### Phase 6 Tasks (Estimated: 1-2 sessions)

| Task | Effort | Dependencies |
|------|--------|--------------|
| Update main.py endpoints | 2 hr | Phase 5 |
| Session management decision + impl | 1.5 hr | Main.py |
| Feature parity testing | 2 hr | All above |
| Bug fixes | Variable | Testing |

### Phase 7 Tasks (Estimated: 2-3 sessions)

| Task | Effort | Dependencies | Commit |
|------|--------|--------------|--------|
| 7.1 Remove legacy from main.py | 45 min | Phase 6 | Yes |
| 7.2 Remove legacy from llm_handler.py | 30 min | 7.1 | Yes |
| 7.3 Remove legacy from session_utils.py | 30 min | 7.2 | Yes |
| 7.4 Remove legacy test files | 30 min | 7.3 | Yes |
| 7.5 Archive legacy scripts | 15 min | 7.4 | Yes |
| 7.6 Delete legacy source files | 15 min | 7.5 | Yes |
| 7.7 Clean up utility modules | 30 min | 7.6 | Yes |
| 7.8 Documentation | 45 min | 7.7 | Yes |
| 7.9 Final audit | 30 min | 7.8 | Final |
| **Total** | **~4.5 hr** | | 9 commits |

---

## Risk Mitigation

### High Risk: Phase 4 & 5 (Edit Operations & Serialization)
**Mitigation:**
- Keep old `docx_writer.py` functional until Phase 6 is complete
- Build comprehensive test suite before modifying
- Test each document in `test_data/` after each change
- Commit frequently with descriptive messages

### Medium Risk: Phase 2 & 3 (Parsing & PlainTextView)
**Mitigation:**
- Create comparison scripts to validate against current behavior
- Run both old and new code paths in parallel during transition
- Log any discrepancies for investigation

### Low Risk: Phase 1 & 7 (Data Structures & Cleanup)
**Mitigation:**
- Standard code review practices
- Comprehensive unit tests

---

## Testing Strategy

### Unit Tests (per phase)
- Phase 1: Data structure instantiation, ID generation, anchor calculations
- Phase 2: Parser output matches expected structures
- Phase 3: Position mapping accuracy, round-trip text → DOM → text
- Phase 4: Edit application correctness, anchor adjustment
- Phase 5: Serialized XML validity, Word compatibility

### Integration Tests
- Full workflow: upload → generate → accept → export
- Chat mode with DOM backend
- Context expansion with PlainTextView
- Multiple accepts on same document

### Regression Tests
- All documents in `test_data/`
- Specific edge cases:
  - Multi-paragraph comments
  - Comments in tables
  - Documents with existing track changes
  - Documents with citations/field codes

### Manual Tests
- Open exported documents in Microsoft Word
- Verify comment threading displays correctly
- Verify track changes can be accepted/rejected
- Verify no corruption warnings

---

## Decision Points

### 1. Session Storage Strategy
**Option A:** Full DOM serialization to JSON
- Pros: True persistence, can resume exactly
- Cons: Complex serialization, large session files

**Option B:** Keep virtual state pattern (current approach)
- Pros: Simpler, proven to work
- Cons: DOM rebuilt on each request

**Recommendation:** Start with Option B (virtual state), consider Option A later if needed.

### 2. Parallel vs. Replacement Strategy
**Option A:** Build DOM module in parallel, switch over at Phase 6
- Pros: Can always fall back, lower risk
- Cons: Maintaining two code paths

**Option B:** Replace incrementally, remove old code as we go
- Pros: Simpler codebase during migration
- Cons: Harder to roll back

**Recommendation:** Option A - build in parallel until Phase 6.

### 3. python-docx Usage
**Current design:** Use python-docx for document structure, lxml for comments/track changes.

**Alternative:** Pure lxml for everything.
- Pros: Full control
- Cons: Much more work parsing standard elements

**Recommendation:** Stick with hybrid approach as designed.

---

## Success Criteria

### Functional
- [ ] All existing features work identically
- [ ] All test documents process correctly
- [ ] Word accepts all exported documents
- [ ] Comment threading works (validated with paraId constraint)

### Quality
- [ ] No functions with complexity > 20
- [ ] No files over 600 lines
- [ ] Pylint score > 7.5 (up from 5.75)
- [ ] All new code has unit tests

### Performance
- [ ] Document parsing time comparable to current (~1-2s for typical doc)
- [ ] Memory usage reasonable (< 100MB for large documents)

---

## Schedule Estimate

| Phase | Sessions | Calendar Days (assuming 1-2 sessions/day) |
|-------|----------|------------------------------------------|
| Phase 1 | 1-2 | 1-2 days |
| Phase 2 | 2-3 | 2-3 days |
| Phase 3 | 1-2 | 1-2 days |
| Phase 4 | 2-3 | 2-3 days |
| Phase 5 | 2-3 | 2-3 days |
| Phase 6 | 1-2 | 1-2 days |
| Phase 7 | 1 | 1 day |
| **Total** | **10-16** | **~2 weeks** |

*Note: This is a rough estimate. Actual time depends on issues discovered and complexity of edge cases.*
