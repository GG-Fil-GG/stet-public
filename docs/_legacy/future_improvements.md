# Future Improvements

This document tracks potential enhancements that are out of scope for the current phase but would add value in future iterations.

For completed improvements, see `docs/completed_plans/completed_improvements.md`.

---

## Context Awareness Enhancements

### Awareness of Track Changes
**Priority:** Medium  
**Complexity:** Medium

The app doesn't see modifications already made to the document via Word's track changes feature.

**Proposed solution:**
- Parse `<w:ins>` and `<w:del>` elements during extraction
- Display tracked changes in the UI (possibly with visual indicators)
- Include tracked changes context in LLM prompts

### Awareness of Other Comments
**Priority:** Medium  
**Complexity:** Medium

Can't consider how one revision affects related comments in other threads.

**Proposed solution:**
- Add option to view/include preceding and subsequent comments
- Flag when accepted revisions might affect other pending comments
- Consider dependency mapping between related comments

### Overall Manuscript Context
**Priority:** High  
**Complexity:** High

By the Discussion section of longer documents, suggestions became flawed due to missing broader context, author guidelines, data, and papers.

**Proposed solution:**
- Allow uploading supplementary context documents (guidelines, data, papers)
- Add a "manuscript summary" or "key points" input area
- Consider chunking and indexing the full document for retrieval-augmented generation

---

## Agentic Architecture Roadmap

**Priority:** High (Long-term Direction)  
**Complexity:** High  
**Status:** Planning

The current architecture uses a single-shot LLM call with manually-configured context. Real-world testing revealed this is insufficient for complex comments that require:
- Understanding what changes have already been made (track changes)
- Evaluating whether the comment's request is already fulfilled
- Dynamically gathering more context when needed
- Cross-referencing other comments, sections, or attachments

### The Vision: LLM as Intelligent Agent

Instead of "gather context → send to LLM → get answer", the flow becomes:

```
User clicks Generate
    ↓
LLM receives initial context + tools
    ↓
LLM decides: Do I have enough information?
    ├── Yes → Generate suggestion
    └── No → Call a tool (expand context, check track changes, etc.)
              ↓
         Receive tool result
              ↓
         Loop back to decision
```

### Available Tools (Target State)

| Tool | Description | Current Status |
|------|-------------|----------------|
| `expand_context(direction, count)` | Get more paragraphs before/after | ✅ Exists (manual) |
| `get_track_changes(para_id)` | See insertions/deletions in paragraph | 🔲 Not built |
| `get_section(section_name)` | Read entire document section | 🔲 Not built |
| `search_document(query)` | Find relevant content anywhere | 🔲 Not built |
| `get_other_comments(scope)` | See related comments in area | 🔲 Not built |
| `read_attachment(id, pages)` | Access attached documents | 🔲 Not built |

### Progress Checklist

**Foundation**
- [x] File attachment infrastructure (PDF parsing, storage)
- [x] Token counting
- [x] Ghost paragraph detection (track changes related)
- [ ] Track changes extraction & display
- [ ] Include track changes in LLM prompt

**Agentic Infrastructure**
- [ ] Add function calling support to LLMHandler
- [ ] Implement first tool: `get_track_changes`
- [ ] Implement orchestration loop
- [ ] Add UI for agent progress
- [ ] Implement additional tools as needed

---

## Session Data Storage & Cleanup

**Priority:** High (Privacy/Security)  
**Complexity:** Medium  
**Status:** Planning

When Stet processes a document, it stores data in a hidden application folder. This data accumulates indefinitely with no cleanup mechanism.

### Recommended Approach

- **Prompt when closing:** "Delete work session?" with clear explanation
- **Manual cleanup option:** Add cleanup in Settings for users who skipped the prompt
- **Auto-expire safety net:** Delete sessions older than 30 days (configurable)

### Progress Checklist

- [ ] Design cleanup prompt UI
- [ ] Implement close-time prompt in `desktop_app.py`
- [ ] Add "Manage Session Data" to Settings modal
- [ ] Show storage usage and allow manual deletion
- [ ] Implement auto-expire logic with configurable threshold
- [ ] Add documentation about data storage location

---

## First-Run / Onboarding Screen

**Priority:** Medium (UX)  
**Complexity:** Medium  
**Status:** Planning

First-time users need guidance on:
1. **API Key Setup** - OpenAI key is required for cloud LLM
2. **Ollama Setup** - If using local LLM, Ollama must be installed separately
3. **Data Storage** - Where session data will be stored
4. **Quick Start** - Basic workflow overview

### Progress Checklist

- [ ] Design onboarding UI/UX
- [ ] Create first-run detection logic
- [ ] Implement config file storage
- [ ] Build onboarding page/modal
- [ ] Add "Re-run Setup" option in Settings
- [ ] Document Ollama installation requirements
- [ ] Test on both Windows and macOS

---

## UI/Display Enhancements

### Live Viewer Refresh During an Agent Run
**Priority:** Medium (UX)
**Complexity:** Medium
**Status:** Logged from M9d re-pilot (2026-09-22), finding #4

During an agent run the document viewer only re-renders when the run **ends or is stopped**; mid-run only the "Working… N tool calls" progress counter updates. In the re-pilot the user couldn't tell whether edits were landing until they stopped the run. This is expected current behaviour, not data loss, but it undermines trust in a long run.

**Proposed solution:**
- Incrementally refresh the viewer (or a "changes so far" indicator) as tracked changes are applied, reusing the existing `agent/progress` polling seam
- At minimum, surface a running count of paragraphs edited / comments replied to alongside the tool-call count

### Agent Search Efficiency
**Priority:** Medium
**Complexity:** Medium
**Status:** Logged from M9d re-pilot (2026-09-22), finding #5

The re-pilot spent **40 `find_in_document` + 8 `read_paragraph` calls to make 10 edits** (68 steps before the user stopped it). Much of the run was the agent hunting for text rather than editing — a correctness-neutral but costly inefficiency that compounds the perceived slowness.

**Proposed solution:**
- Return `para_id`s directly from `list_comments` (referenced paragraph) so the agent doesn't re-search for text it was just given
- Consider a combined "locate + read" tool, or caching find results within a run
- Fits under the broader agent-run performance workstream below

### Images in Comments
**Priority:** Low  
**Complexity:** Medium-High

Some reviewers include images (screenshots, figures) in their comments. Currently these are not displayed.

**Proposed solution:**
- Extract embedded images from comment XML
- Display in the UI alongside comment text
- For LLM generation, send to multimodal models (GPT-4V, Claude 3, etc.)

### Formatting Preservation in Comments
**Priority:** Low  
**Complexity:** Medium

Comments may include formatting like **bold**, *italics*, or highlighting that carries meaning. Currently we extract plain text only.

**Proposed solution:**
- Parse `<w:r>` elements for formatting properties (`<w:b>`, `<w:i>`, `<w:highlight>`)
- Convert to markdown or HTML for display
- Consider whether to send formatting hints to LLM

### Real-Time Editable Diff (Phase 2)
**Priority:** Low  
**Complexity:** High

The ideal UX would be a single editable area where diff styling updates in real-time as the user types.

**Technical requirements:**
- Custom Streamlit component with JavaScript
- Or use rich text editor library (e.g., Slate.js, ProseMirror)
- Real-time diff computation on keystroke
- Inline styling: strikethrough for deletions, highlight for insertions

**Estimated effort:** 4-8 hours for custom component

### Pretty Table Rendering (Phase 2)
**Priority:** Low-Medium  
**Complexity:** High

A more sophisticated approach: render a **continuous view of the document** with **draggable selection rectangles** overlaid, solving table column alignment issues.

**Estimated effort:** 1-2 days

---

## LLM Enhancements

### Language Region Directive (UK/US English)
**Priority:** Medium  
**Complexity:** Low

LLMs default to US English, but many medical manuscripts require UK English spelling and conventions.

**Proposed solution:**
- Add a setting in sidebar: "Language: US English / UK English / Match document"
- Modify system prompt to include directive

### Response Verbosity Directive
**Priority:** Medium  
**Complexity:** Low

LLM responses are sometimes overly detailed, describing what was changed when the revision itself is visible next to the comment.

**Proposed solution:**
- Add instruction to system prompt for concise responses
- Consider making verbosity level configurable (Brief / Normal / Detailed)

---

## New Functionality

### Parallel Comment Processing
**Priority:** Medium  
**Complexity:** Medium-High

Allow processing multiple comments simultaneously without blocking the entire UI.

**Phase 1: Per-Card Processing (Non-Blocking UI)**
- Per-card loading indicator instead of full-page overlay
- User can click "Generate" on other cards while one is processing
- Each card processes independently and updates when its response arrives

**Phase 2: Bulk Generate**
- "Generate All Pending" button for batch processing
- Process 3-5 threads concurrently (configurable)
- Progress tracking
- Overlap handling via dependency graph

---

## Export Enhancements

### Tracked Changes - Remaining Edge Cases
**Priority:** Low  
**Complexity:** Medium

- [ ] Handle edge cases (empty paragraphs, special characters)

### Automated Testing Framework
**Priority:** Medium  
**Complexity:** Medium-High

Automated regression testing using a library of real-world documents to catch issues before they reach users.

**Scope:**

| Test Type | Automatable | Notes |
|-----------|-------------|-------|
| XML validity after export | ✅ Yes | Parse with ElementTree |
| Field code preservation | ✅ Yes | Count field codes before/after |
| Reply insertion | ✅ Yes | Verify comment threading in XML |
| Track changes structure | ✅ Yes | Validate `<w:ins>`/`<w:del>` structure |
| Word opens file | ⚠️ Partial | Could use COM automation on Windows |
| Content accuracy | ❌ Manual | Requires human review |
| Visual appearance | ❌ Manual | Requires opening in Word |

**Proposed implementation:**
1. Test document library in `test_data/regression/`
2. Test harness: `tests/test_regression.py` (pytest-based)
3. Validation checks for XML, field codes, threading, track changes
4. CI integration

---

## Known Issues

### Resolved Threads Appearing as Unresolved
**Status:** To investigate  
**Severity:** Medium

Some threads appear as open (unresolved) in the app but are marked as resolved or not visible in Word.

**Investigation needed:**
- Check if `commentsExtended.xml` or `commentsExtensible.xml` contains "done" status
- Verify how Word marks resolved comments
- Add filtering for resolved threads

### Reply Insertion Inconsistency
**Status:** Largely resolved via paraId constraint discovery  
**Severity:** Low (was Medium)

Some programmatically inserted replies previously appeared as standalone comments. This was traced to the `w14:paraId` constraint (first character must be 0-7).

**Remaining edge cases:**
- Re-uploading an already-exported `_with_replies.docx` file causes issues
- Always use the original `.docx` file, not the exported version
