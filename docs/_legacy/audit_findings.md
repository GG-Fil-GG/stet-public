# Code Audit Findings

**Date:** 2026-02-05 (Updated 2026-02-25)  
**Scope:** Internal code structure and quality metrics

---

## Executive Summary

| Metric | Value | Assessment |
|--------|-------|------------|
| Total Python lines | ~32,000 | Large codebase |
| Pylint score | 5.90/10 | Below target (8.0+) |
| Average complexity | A (4.9) | Good overall |
| Test count | 482 | Comprehensive coverage |
| Files over 500 lines | 7 | Need attention |
| Functions with E/F complexity | 4 | Should refactor |
| Dead code items | 11 | Minor - mostly false positives |

**Key Change:** The DOM Migration added `src/document_model/` (8,260 lines across 10 files) replacing the deprecated `docx_writer.py` and `comment_extractor.py`.

---

## 1. Architecture Overview (Post-DOM Migration)

### New Module: `src/document_model/` (8,260 lines)

| File | Lines | Purpose |
|------|-------|---------|
| `serializer.py` | 2,731 | DOCX export with track changes |
| `plain_text.py` | 1,414 | Plain text ↔ DOM conversion |
| `model.py` | 1,154 | DocumentModel core class |
| `parser.py` | 694 | DOCX parsing into DOM |
| `paragraph.py` | 647 | Paragraph/Run data structures |
| `comments.py` | 554 | Comment thread management |
| `revisions.py` | 433 | Revision tracking |
| `edits.py` | 368 | Edit operation definitions |
| `utils.py` | 131 | Utility functions |
| `__init__.py` | 134 | Public API exports |

### Deprecated Files (Removed)

- ~~`src/docx_writer.py`~~ → Replaced by `serializer.py`
- ~~`src/comment_extractor.py`~~ → Replaced by `parser.py` + `comments.py`

---

## 2. File Size Analysis

### Files Exceeding 600 Lines (Source)

| File | Lines | Status | Notes |
|------|-------|--------|-------|
| `main.py` | 2,768 | 🔴 Large | Core application, many endpoints |
| `src/document_model/serializer.py` | 2,731 | 🔴 Large | Complex DOCX generation, track changes |
| `src/diff_utils.py` | 1,659 | 🔴 Large | Diffing, HTML conversion, formatting |
| `src/llm_handler.py` | 1,457 | 🟡 Elevated | LLM integration, prompts |
| `src/document_model/plain_text.py` | 1,414 | 🟡 Elevated | Structural change handling |
| `src/document_model/model.py` | 1,154 | 🟡 Elevated | Core DOM model |
| `src/session_utils.py` | 1,073 | 🟡 Elevated | Session management |

### Files Within Acceptable Range

| File | Lines | Status |
|------|-------|--------|
| `src/document_model/parser.py` | 694 | ✅ OK |
| `src/context_utils.py` | 696 | ✅ OK |
| `src/document_model/paragraph.py` | 647 | ✅ OK |
| `src/document_model/comments.py` | 554 | ✅ OK |
| `src/document_model/revisions.py` | 433 | ✅ OK |
| `src/document_model/edits.py` | 368 | ✅ OK |
| `src/llm_config.py` | ~370 | ✅ OK |
| `src/file_parsers/*.py` | 300-400 | ✅ OK |
| `src/output_manager.py` | ~235 | ✅ OK |
| `src/token_counter.py` | ~195 | ✅ OK |
| `src/paths.py` | ~123 | ✅ OK |
| `src/chat_types.py` | ~125 | ✅ OK |
| `src/constants.py` | ~104 | ✅ OK |
| `src/exceptions.py` | ~259 | ✅ OK |

---

## 3. Code Quality Metrics

### Pylint Score: 5.90/10

Top issues by frequency:

| Issue | Severity | Action |
|-------|----------|--------|
| `trailing-whitespace` | Low | Auto-fix with formatter |
| `line-too-long` | Low | Auto-fix with formatter |
| `duplicate-code` | Medium | Some intentional (NS dict) |
| `too-many-locals` | Medium | Refactor complex functions |
| `broad-exception-caught` | Medium | Improve error handling |

### Cyclomatic Complexity

**Critical Functions (E/F grade - complexity > 30):**

| Function | File | Complexity | Grade |
|----------|------|------------|-------|
| `_parse_response` | llm_handler.py:1215 | 43 | F |
| `get_thread_card` | main.py:445 | 39 | E |
| `accept_suggestion` | main.py:875 | 36 | E |
| `_get_expanded_context` | llm_handler.py:1012 | 34 | E |

**Elevated Functions (D grade - complexity 20-30):**

| Function | File | Complexity |
|----------|------|------------|
| `send_chat_message` | main.py:1509 | 27 |
| `_render_thread_card` | main.py:1915 | 27 |
| `get_token_count` | main.py:2082 | 23 |
| `add_attachment` | main.py:2373 | 23 |

**Average complexity:** A (4.9) - Good overall despite some outliers

### Maintainability Index

| File | MI Score | Grade | Status |
|------|----------|-------|--------|
| `main.py` | 0.00 | C | 🔴 Needs attention |
| `src/document_model/serializer.py` | 0.00 | C | 🔴 Needs attention |
| `src/llm_handler.py` | 9.05 | B | 🟡 Warning |
| `src/diff_utils.py` | 11.49 | B | 🟡 Warning |
| `src/document_model/plain_text.py` | 17.03 | B | 🟡 OK |
| `src/document_model/model.py` | 19.72 | A | ✅ OK |
| `src/session_utils.py` | 39.31 | A | ✅ OK |
| `src/context_utils.py` | 39.05 | A | ✅ OK |
| `src/document_model/parser.py` | 33.16 | A | ✅ OK |
| `src/document_model/paragraph.py` | 34.36 | A | ✅ OK |
| `src/document_model/comments.py` | 44.57 | A | ✅ OK |
| `src/document_model/revisions.py` | 47.83 | A | ✅ OK |
| `src/document_model/edits.py` | 60.68 | A | ✅ OK |
| `src/llm_config.py` | 55.10 | A | ✅ OK |
| `src/output_manager.py` | 66.49 | A | ✅ OK |
| `src/token_counter.py` | 66.28 | A | ✅ OK |
| `src/paths.py` | 69.87 | A | ✅ OK |
| `src/chat_types.py` | 100.00 | A | ✅ OK |
| `src/constants.py` | 100.00 | A | ✅ OK |
| `src/exceptions.py` | 100.00 | A | ✅ OK |

### Dead/Unused Code (Vulture 80%+ confidence)

| Item | File | Type | Status |
|------|------|------|--------|
| `DOMCommentThread` | main.py:24 | Unused import | ⚠️ Check if needed |
| `clear_thread_original_text` | main.py:39 | Unused import | ⚠️ Check if needed |
| `create_empty_session` | main.py:39 | Unused import | ⚠️ Check if needed |
| `get_threads_from_session` | main.py:39 | Unused import | ⚠️ Check if needed |
| `tempfile` | serializer.py:15 | Unused import | ⚠️ Check if needed |
| `DOMCommentThread` | session_utils.py:1073 | Unused import | ⚠️ Check if needed |
| `text_start` | diff_utils.py:468 | Unused variable | ❌ False positive |
| `attrs` (4 instances) | diff_utils.py | Unused variable | ❌ False positive (HTMLParser) |

---

## 4. Test Coverage

### Test Files (8,234 lines total, 482 tests)

| File | Lines | Focus |
|------|-------|-------|
| `test_diff_utils.py` | 1,141 | Diffing, HTML conversion |
| `test_document_model.py` | 718 | Core DOM operations |
| `test_serializer.py` | 704 | DOCX export |
| `test_multi_paragraph.py` | 637 | Multi-paragraph edits |
| `test_plain_text_view.py` | 637 | Plain text abstraction |
| `test_edit_operations.py` | 611 | Edit application |
| `test_workflow_integration.py` | 563 | E2E workflows |
| `test_paragraph_structure.py` | 556 | Structural changes |
| `test_context_utils.py` | 543 | Context generation |
| `test_plain_text_conversion.py` | 526 | Text conversion |
| `test_thread_aware_revisions.py` | 464 | Thread-aware edits |
| `test_model_serialization.py` | 446 | Model serialization |
| `test_session_utils.py` | 321 | Session management |
| `test_document_parser.py` | 168 | DOCX parsing |
| `conftest.py` | 199 | Test fixtures |

**Total:** 482 tests, all passing

---

## 5. Completed Plans

The following plans have been completed and archived:

| Plan | Status | Location |
|------|--------|----------|
| DOM Migration | ✅ Complete | `docs/completed_plans/dom_migration_plan.md` |
| Thread-Aware Revisions | ✅ Complete | `docs/completed_plans/thread_aware_revisions_plan.md` |
| Formatting Plan | ✅ Complete | `docs/formatting_plan.md` |

---

## 6. Current Architecture Strengths

1. **Single Source of Truth:** `DocumentModel` is the canonical representation
2. **Comprehensive Testing:** 482 tests covering all major features
3. **Clean Separation:** DOM operations isolated in `document_model/` package
4. **Session Management:** On-demand cache computation eliminates stale data issues
5. **Structural Changes:** Paragraph split/merge properly supported with field code preservation

---

## 7. Areas for Potential Improvement

### High Value (If Time Permits)

| Task | Effort | Benefit |
|------|--------|---------|
| Split `main.py` into route modules | 4-6 hours | Easier navigation, ~500 lines per file |
| Split `serializer.py` into focused modules | 3-4 hours | Separate track changes, field codes, structure |
| Add type hints to remaining functions | 2-3 hours | Better IDE support, fewer bugs |

### Low Priority (Working Code)

| Item | Notes |
|------|-------|
| `diff_utils.py` size | Complex but well-tested |
| `llm_handler.py` size | Contains necessary prompt logic |
| Some duplicate code patterns | Working correctly, DRY can wait |

---

## 8. Risk Assessment

### Low Risk (Stable, Well-Tested)

- `src/document_model/` - New, comprehensive tests
- `src/session_utils.py` - Recently refactored, good coverage
- `src/context_utils.py` - Stable, good tests
- `src/file_parsers/` - Simple, unchanged
- `src/paths.py`, `src/constants.py`, `src/exceptions.py` - Simple utilities

### Medium Risk (Monitor)

- `main.py` - Large but functional, many endpoints
- `src/diff_utils.py` - Complex but well-tested
- `src/llm_handler.py` - LLM integration, prompt changes

### Areas Recently Stabilized

- Paragraph split/merge - Fixed positioning issues
- Field code restoration - Fixed for new paragraphs
- HTML ↔ plain text conversion - Paragraph structure preserved

---

## 9. Quick Reference: Key Functions

### DOM Operations

| Function | Location | Purpose |
|----------|----------|---------|
| `parse_docx()` | `document_model/parser.py` | Parse DOCX to DOM |
| `model.apply_edit()` | `document_model/model.py` | Apply edits to DOM |
| `apply_revision_from_plain_text()` | `document_model/plain_text.py` | Plain text → DOM edits |
| `serializer.serialize()` | `document_model/serializer.py` | DOM → DOCX export |

### Session Management

| Function | Location | Purpose |
|----------|----------|---------|
| `get_model_from_session()` | `session_utils.py` | Get DOM from session |
| `get_paragraph_cache()` | `session_utils.py` | Computed on demand |
| `get_thread_target_indices()` | `session_utils.py` | Computed on demand |

### Text Processing

| Function | Location | Purpose |
|----------|----------|---------|
| `strip_html_tags()` | `diff_utils.py` | HTML → plain text |
| `compute_diff()` | `diff_utils.py` | Text diffing |
| `merge_formatting_for_revision()` | `diff_utils.py` | Combine formatting |

---

## 10. Files Analyzed (Current)

```
Total: ~32,000 lines of Python code

Source files: ~16,500 lines
  src/document_model/ (10 files): 8,260 lines
  - main.py: 2,768
  - src/diff_utils.py: 1,659
  - src/llm_handler.py: 1,457
  - src/session_utils.py: 1,073
  - src/context_utils.py: 696
  - src/llm_config.py: ~370
  - src/file_parsers/ (4 files): ~1,000
  - Other src/ files: ~500

Test files: ~8,200 lines (16 files)
  - 482 tests, all passing

Scripts: ~2,500 lines
  - Various validation and diagnostic scripts
```

---

## 11. Recommendations

### Before Any Major Changes

1. Run full test suite: `pytest tests/ -v`
2. Manual smoke test with test.docx
3. Verify export opens in Word without errors

### If Refactoring

1. Start with `main.py` → route modules (lowest risk, highest readability gain)
2. Consider `serializer.py` split only if actively modifying it
3. Keep comprehensive tests - they're the safety net

### Maintenance

1. Continue committing frequently
2. Run tests after significant changes
3. Manual test paragraph split/merge scenarios (edge cases)
