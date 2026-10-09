# Comment Addresser - Week Schedule (Dec 30 - Jan 4)

**Goal:** Build "The Comment Assistant Workbench" (MVP) — a Streamlit app for addressing reviewer comments using AI.

**Deadline:** Jan 4th (tool must be operational for client work starting Jan 5th)

---

## The Plan

### Why Streamlit?
- 100% Python (perfect for vibe coding)
- Handles frontend layout automatically
- Focus on logic, not web development

### Core Functionality
1. **Ingest:** Upload/select a `.docx` file
2. **Process:** Extract unresolved comments with thread context
3. **AI Generation:** Generate revision suggestions + polite responses
4. **Human Loop:** Review and edit AI suggestions
5. **Output:** Insert replies into Word + export revised document

### Risk Management
- **Phase 1 (Safe):** Insert replies into comment bubbles (easier XML)
- **Phase 2 (Stretch):** Attempt tracked changes insertion
- **Fallback:** Copy-paste text changes from app to Word

---

## Daily Schedule

### Day 1: Monday — The Foundation ✅
**Objective:** Turn script into robust data extractor

- [x] Reorganize project structure
- [x] Initialize Git and create GitHub repo
- [x] Refactor `extract_comments_final.py` → `CommentExtractor` class
- [x] Output structured data (List of CommentThread)
- [x] Test with sample document (67 comments, 22 threads)
- [x] Verify thread grouping matches old script

**Status:** COMPLETE ✅

---

### Day 2: Tuesday — The Brain ✅
**Objective:** Connect data to AI

- [x] Create `src/llm_handler.py` class
- [x] Implement OpenAI mode (GPT-5 mini via env var)
- [x] Implement Ollama mode (llama3, local fallback)
- [x] Craft MW-specific system prompt with context extraction
- [x] Configurable context window (paragraphs before/after)
- [x] Test: Feed comment thread → get revision + response + rationale
- [x] Handle edge cases (Japanese text works ✓)

**Deliverable:** Working LLM integration that produces quality suggestions

**Status:** COMPLETE ✅

---

### Day 3: Wednesday — The Interface ✅
**Objective:** Visualize the workflow

- [x] Install Streamlit (`pip install streamlit`)
- [x] Build basic app structure (`app.py`)
- [x] Sidebar: File upload, LLM settings (provider selection)
- [x] Main area: Comment card view (one at a time, navigation)
- [x] Each card shows:
  - Section heading
  - Referenced text
  - Comment thread
  - "Generate Suggestion" button
- [x] Editable text areas for AI revision + response
- [x] Basic navigation (Previous/Next, index indicator)
- [x] Accept/Skip/Regenerate buttons
- [x] Session persistence (save progress to JSON)
- [x] Filter: Show only open threads by default
- [x] Progress tracking (Done/Skipped/Pending counts)
- [x] Bug fixes: field codes, referenced text display, context brackets

**Deliverable:** Visual interface showing comments with AI generation

**Status:** COMPLETE ✅

---

### Day 4: Thursday — The Write-Back ✅
**Objective:** Make the tool modify `.docx`

- [x] **Level 1 (Essential):** Insert reply into comment thread
- [x] Create `src/docx_writer.py` for Word XML manipulation
- [x] Always work on a COPY of the file (never original)
- [x] Test with sample document
- [x] Add "Export" button to download modified `.docx`
- [ ] **Level 2 (Stretch):** Text modification (deferred - copy-paste workflow)

**Key Discovery:** Word requires comment replies to have anchors in FIVE files:
1. `comments.xml` - the reply text
2. `commentsExtended.xml` - parent linkage via paraId
3. `commentsIds.xml` - durable ID mapping
4. `commentsExtensible.xml` - UTC timestamp (Word 2018+)
5. `document.xml` - **CRITICAL** - anchor at same position as parent

Without the `document.xml` anchor, Word silently deletes the reply on save.

**Status:** COMPLETE ✅

---

### Day 5: Friday — Integration & Polish
**Objective:** End-to-end testing and safety features

- [x] State management: Save progress to `session.json`
- [x] Resume capability (don't lose work on crash)
- [x] Backup system: Auto-save before modifications (files saved to `output/` folder)
- [x] Skip/Done marking for each thread
- [x] Filter: Show only open threads
- [x] Full end-to-end test with real manuscripts (3 documents tested)
- [x] Fix bugs discovered:
  - [x] Newlines stripped from comments → Fixed with `\n` insertion in extraction
  - [x] Referenced text truncation → Removed 500-char limit
  - [x] Multi-paragraph referenced text → Fixed with `_extract_text_across_paragraphs`
  - [x] Regenerate button not working → Fixed with generation counter for widget keys
  - [x] Tracked changes text missing → Fixed by including `w:ins` elements
- [x] Compare Ollama vs OpenAI suggestions
- [ ] **KNOWN ISSUE:** ~50% of replies appear as standalone comments in Word (documented in `future_improvements.md`)
- [ ] **FUTURE:** Diff highlighting for revised text
- [ ] **FUTURE:** Track Changes insertion (Level 2)

**Deliverable:** Production-ready MVP

**Status:** COMPLETE ✅ (with known issue documented)

---

### Weekend: Buffer (Sat-Sun)
- Fix any unforeseen XML parsing errors
- Refine LLM prompts based on output quality
- Emergency bug fixes only

---

## Quick Reference

### Running the App
```bash
cd comments_addresser
source .venv/bin/activate
streamlit run app.py
```

### Key Files
| File | Purpose |
|------|---------|
| `src/comment_extractor.py` | Extract comments from .docx |
| `src/llm_handler.py` | AI integration (Day 2) |
| `src/docx_writer.py` | Write back to .docx (Day 4) |
| `app.py` | Streamlit entry point (Day 3) |

### Environment Variables
```bash
export OPENAI_API_KEY="your-key-here"
```

---

## Success Criteria (Jan 4th)

The tool is "done" when you can:

1. ✅ Upload a `.docx` with comments
2. ✅ See all unresolved comment threads as cards
3. ✅ Click "Generate" to get AI revision + response
4. ✅ Edit the suggestions if needed
5. ✅ Export a `.docx` with replies inserted (minimum)
6. ⭐ Bonus: Text changes as tracked changes (stretch goal)

