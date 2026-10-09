# Pre-Demo Audit & Testing Plan

**Created:** 2026-02-05  
**Demo Date:** Wednesday, 2026-02-12  
**Goal:** Ensure app stability and identify issues before demo

---

## Overview

This plan covers three main areas:

1. **Internal Code Audit** - Evaluate code structure, identify issues
2. **Real Document Testing** - Test with diverse real-world documents
3. **LLM Provider Testing** - Verify both OpenAI and Ollama work correctly

---

## Phase 1: Internal Code Audit

### 1.1 Automated Metrics

Run programmatic tools to gather objective metrics about code quality.

#### Tools to Use

| Tool | Purpose | Install | Command |
|------|---------|---------|---------|
| `cloc` | Line counts by file/language | `brew install cloc` | `cloc src/ main.py --by-file` |
| `radon cc` | Cyclomatic complexity | `pip install radon` | `radon cc src/ main.py -a -s` |
| `radon mi` | Maintainability index | (included with radon) | `radon mi src/ main.py -s` |
| `vulture` | Dead/unused code | `pip install vulture` | `vulture src/ main.py --min-confidence 80` |
| `pylint` | Code quality, duplication | `pip install pylint` | `pylint src/ main.py --output-format=text` |
| `mypy` | Type checking (optional) | `pip install mypy` | `mypy src/ main.py --ignore-missing-imports` |

#### Metrics to Capture

- [ ] **File sizes** - Identify files > 500 lines (candidates for splitting)
- [ ] **Function complexity** - Flag functions with complexity > 10
- [ ] **Maintainability scores** - Flag modules with MI < 20 (hard to maintain)
- [ ] **Dead code** - List unused functions, variables, imports
- [ ] **Code quality score** - Overall pylint score

#### Thresholds

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| File lines | < 300 | 300-600 | > 600 |
| Function lines | < 30 | 30-60 | > 60 |
| Cyclomatic complexity | < 5 | 5-10 | > 10 |
| Maintainability index | > 40 | 20-40 | < 20 |
| Pylint score | > 8.0 | 6.0-8.0 | < 6.0 |

### 1.2 Manual Structure Review

Based on automated metrics, manually examine:

#### Module Organization

- [ ] **`main.py`** (~2600 lines) - Likely needs splitting
  - Route handlers could move to `src/routes/`
  - Session management could be its own module
  - Export logic could move to a dedicated module

- [ ] **`src/docx_writer.py`** (~1900 lines) - Very large
  - Consider splitting by responsibility (track changes, replies, formatting)

- [ ] **`src/diff_utils.py`** (~1600 lines) - Large
  - HTML conversion, diffing, and formatting are distinct concerns

- [ ] **`src/comment_extractor.py`** - Review size and responsibilities

#### Import Analysis

- [ ] Check for circular imports
- [ ] Verify each module has clear, single responsibility
- [ ] Identify tightly coupled modules

#### Code Patterns

- [ ] Consistent error handling
- [ ] Proper logging throughout
- [ ] No hardcoded values that should be config
- [ ] Consistent naming conventions

### 1.3 Known Areas to Review

Based on recent work, pay special attention to:

- [ ] **Formatting flow** - `merge_formatting_for_revision()`, `diff_to_editable_html()`
- [ ] **Export flow** - `export_document()`, `insert_tracked_change_by_para_id()`
- [ ] **Session management** - `accepted_revisions`, `thread_status`, persistence
- [ ] **TipTap integration** - JavaScript in `base.html`, auto-save logic

### 1.4 Deliverable

Create `docs/audit_findings.md` with:
- Summary of metrics
- List of issues found (prioritized)
- Recommendations (fix now vs. fix later)

---

## Phase 2: Real Document Testing

### 2.1 Test Document Categories

| Category | What to Test | Priority |
|----------|--------------|----------|
| **Simple paragraphs** | Basic text comments, no special formatting | High |
| **Formatted text** | Bold, italic, subscript, superscript | High |
| **Tables** | Comments on table cells, multi-row selections | High |
| **Citations** | Documents with Zotero/EndNote field codes | High |
| **Track changes** | Documents with existing track changes | Medium |
| **Images** | Documents with embedded images | Medium |
| **Complex nesting** | Lists, nested tables, text boxes | Medium |
| **Large documents** | 50+ pages, many comments | Medium |
| **Multi-language** | Non-English text, special characters | Low |

### 2.2 Test Scenarios per Document

For each test document, verify:

#### Upload & Extraction
- [ ] Document uploads without error
- [ ] All comments extracted correctly
- [ ] Comment threading (replies) preserved
- [ ] Referenced text identified correctly
- [ ] Context paragraphs loaded correctly
- [ ] Formatting displayed in UI (bold, italic, etc.)

#### LLM Suggestion Generation
- [ ] Suggestion generates without error
- [ ] JSON response parsed correctly
- [ ] Revised text displayed in editor
- [ ] Original formatting preserved/merged correctly
- [ ] Diff highlighting works

#### User Editing
- [ ] Can edit revised text
- [ ] Can apply formatting (bold, italic, etc.)
- [ ] Can remove formatting
- [ ] Auto-save works (no data loss)
- [ ] Accept/Skip buttons work
- [ ] Status correctly tracks (PENDING/ACCEPTED/SKIPPED)

#### Export
- [ ] Export completes without error
- [ ] Exported file opens in Word
- [ ] Track changes visible and correct
- [ ] Replies inserted in correct threads
- [ ] Formatting changes tracked (`<w:rPrChange>`)
- [ ] Citations/field codes preserved
- [ ] No XML corruption

### 2.3 Test Logging

Implement comprehensive logging for test runs:

```python
# Proposed logging structure
{
    "test_run_id": "2026-02-05_18-30-00",
    "document": "test_doc_1.docx",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "results": {
        "upload": {"status": "success", "comments_found": 5, "time_ms": 234},
        "extraction": {"status": "success", "threads": 5, "tables": 2},
        "generation": [
            {"thread_id": "0", "status": "success", "time_ms": 1200},
            {"thread_id": "1", "status": "error", "error": "JSON parse failed"}
        ],
        "export": {"status": "success", "time_ms": 890, "warnings": []}
    }
}
```

#### Log Locations
- Console output (real-time)
- `output/{document_name}/test_log.json` (structured)
- `output/{document_name}/export_validation.json` (XML checks)

### 2.4 Automation Opportunities

| Task | Automatable? | How |
|------|--------------|-----|
| Upload document | ✅ Yes | HTTP POST to `/upload` |
| Generate all suggestions | ✅ Yes | HTTP POST to `/generate/{thread_id}` for each |
| Accept all suggestions | ✅ Yes | HTTP POST to `/accept/{thread_id}` for each |
| Export document | ✅ Yes | HTTP POST to `/export/{session_id}` |
| Validate exported XML | ✅ Yes | Parse with ElementTree, check structure |
| Verify Word opens file | ⚠️ Partial | COM automation (Windows) or manual |
| Check visual appearance | ❌ Manual | Must open in Word and review |

#### Proposed Test Script

Create `scripts/run_document_tests.py`:

```python
"""
Automated document testing script.

Usage:
    python scripts/run_document_tests.py test_data/*.docx --provider openai
    python scripts/run_document_tests.py test_data/*.docx --provider ollama --model llama3.1
"""

# Features:
# - Process multiple documents in batch
# - Log results to JSON
# - Validate exported XML
# - Generate summary report
```

### 2.5 Test Documents

#### Currently in `test_data/`
- [ ] List and categorize existing test documents
- [ ] Note what each one tests

#### To Download from Cloud
- [ ] Documents with citations
- [ ] Documents with complex tables
- [ ] Documents with existing track changes
- [ ] Large documents (stress testing)
- [ ] Edge case documents (known problematic)

---

## Phase 3: LLM Provider Testing

### 3.1 Providers to Test

| Provider | Model(s) | JSON Compliance | Priority |
|----------|----------|-----------------|----------|
| OpenAI | gpt-4o-mini | ✅ Excellent | High (primary) |
| OpenAI | gpt-4o | ✅ Excellent | Medium |
| Ollama | llama3.1 | ⚠️ Variable | High (demo requirement) |
| Ollama | Other models | ❓ Unknown | Low |

### 3.2 Test Cases for Each Provider

#### JSON Output Compliance
- [ ] Returns valid JSON (parseable)
- [ ] Contains required fields (`revised_text`, `explanation`)
- [ ] No extra text outside JSON (common Ollama issue)
- [ ] Handles special characters in output
- [ ] Handles long responses

#### Response Quality
- [ ] Suggestions are relevant to comments
- [ ] Revised text is coherent
- [ ] No hallucinated content
- [ ] Appropriate length (not too verbose)

#### Error Handling
- [ ] Graceful handling of malformed responses
- [ ] Retry logic works
- [ ] User sees helpful error message
- [ ] No app crash on LLM failure

### 3.3 Ollama-Specific Issues

Known issues with Ollama/Llama 3.1:

| Issue | Description | Mitigation |
|-------|-------------|------------|
| JSON wrapper text | Model adds "Here's the JSON:" before output | Strip non-JSON prefix/suffix |
| Incomplete JSON | Response cut off mid-JSON | Increase context length, retry |
| Extra fields | Model adds unexpected fields | Ignore unknown fields |
| Markdown in JSON | Model uses markdown inside JSON strings | Parse/clean markdown |

#### Testing Checklist for Ollama
- [ ] Basic suggestion generation works
- [ ] Chat/refinement works
- [ ] JSON parsing handles common issues
- [ ] Error messages are user-friendly
- [ ] Performance acceptable (response time)

### 3.4 Configuration Testing

- [ ] Switching between providers works
- [ ] API key handling correct (OpenAI)
- [ ] Ollama URL configuration works
- [ ] Model selection works
- [ ] Settings persist correctly

---

## Execution Timeline

### Day 1 (Thursday Evening/Friday)
- [ ] Install audit tools (`radon`, `vulture`, `pylint`)
- [ ] Run automated metrics
- [ ] Create `audit_findings.md` with initial results

### Day 2-3 (Weekend)
- [ ] Review high-priority findings
- [ ] Fix critical issues (if any)
- [ ] Set up test logging infrastructure
- [ ] Download additional test documents

### Day 4-5 (Monday-Tuesday)
- [ ] Run real document tests (batch)
- [ ] Test Ollama thoroughly
- [ ] Fix any critical bugs found
- [ ] Final review and polish

### Day 6 (Tuesday Evening)
- [ ] Freeze code (no more changes)
- [ ] Create demo document
- [ ] Rehearse demo flow
- [ ] Document any known issues to mention

---

## Findings Tracking

### Critical (Must Fix Before Demo)
| Issue | File | Status |
|-------|------|--------|
| (none yet) | | |

### High (Should Fix If Time)
| Issue | File | Status |
|-------|------|--------|
| (none yet) | | |

### Medium (Fix After Demo)
| Issue | File | Status |
|-------|------|--------|
| (none yet) | | |

### Low (Future Improvement)
| Issue | File | Status |
|-------|------|--------|
| (none yet) | | |

---

## Success Criteria

Before demo, we should have:

- [ ] All automated tests pass
- [ ] At least 5 real documents tested successfully
- [ ] Ollama working reliably (or documented workarounds)
- [ ] No critical bugs remaining
- [ ] Demo document created and tested
- [ ] Known issues documented (for honest disclosure)
