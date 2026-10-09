# File Attachments & Token Management Plan

This document tracks the implementation of file attachment support and prerequisite token management features.

---

## Overview

Medical writers often need to reference external documents when addressing reviewer comments:
- **PDF:** Papers, clinical study protocols/reports (most common)
- **Spreadsheets:** Datasets with adverse events, efficacy data, etc.
- **DOCX:** Supplementary Word documents
- **PPTX:** Presentation slides (lowest priority)

Before implementing file attachments, we need robust token counting and LLM configuration management.

---

## Phase 0: LLM Configuration & Token Counting (PREREQUISITE)

### 0.1 Centralized LLM Configuration

**Status:** ✅ Complete

**Goal:** Single source of truth for all LLM provider/model information.

**Config file:** `config/llm_providers.yaml`

**Providers:**
- **OpenAI** (requires API key)
  - GPT-5.2 (400k context, flagship model)
  - GPT-5 Mini (400k context, fast/affordable)
  - GPT-5 Nano (400k context, cheapest)
- **Ollama** (local, no API key)
  - Models discovered at runtime from local server
  - Conservative defaults for unknown models

**Config includes:**
- Context window sizes and max output tokens
- Pricing (per 1M tokens: input, cached input, output)
- Rate limits by OpenAI tier (currently set to Tier 4)
- Feature support flags (JSON, vision, reasoning tokens)
- Token counting settings

**Tasks:**
- [x] Create `config/llm_providers.yaml`
- [ ] Create `src/llm_config.py` to load and validate config
- [ ] Update `main.py` Settings modal to read from config
- [ ] Update `llm_handler.py` to use config for model info
- [ ] Remove hardcoded model lists from templates/code

**Files to modify:**
- `config/llm_providers.yaml` ✅ DONE
- `src/llm_config.py` (NEW)
- `main.py` - Settings endpoint
- `src/llm_handler.py` - Model handling
- `templates/base.html` - Settings modal (model dropdown)

### 0.2 Token Counting

**Status:** ✅ Complete

**Goal:** Count tokens for prompts and display near "Generate Suggestion" button.

**Approach:**
- Use `tiktoken` library for accurate OpenAI token counting
- Use character-based approximation (~4 chars/token) for Ollama models
- Display format: `📊 ~2,450 / 400,000 tokens`

**UI placement:** Near "Generate Suggestion" button in each card

**Visual feedback:**
- Normal: Default styling
- Warning (>80% of context): Yellow
- Over limit: Red, disable Generate button

**Tasks:**
- [ ] Create `src/token_counter.py`
- [ ] Add `tiktoken` to `requirements.txt`
- [ ] Create endpoint to calculate tokens for a thread's prompt
- [ ] Add token display in card UI (near Generate button)
- [ ] Show warning if tokens exceed model's context window

**Files to modify:**
- `src/token_counter.py` (NEW)
- `requirements.txt`
- `main.py` - Token calculation endpoint
- `templates/partials/card.html` - Token display

### 0.3 Rate Limiting (Deferred Implementation)

**Status:** 🔲 Config Only (implementation deferred to batch processing)

**Goal:** Store rate limit info in config for future use.

Rate limits are already in `llm_providers.yaml`. Actual enforcement will be implemented with batch processing (Phase 15 in future_improvements.md).

---

## Phase 1: PDF Support

**Status:** ✅ Complete (pending integration testing)

**Priority:** High (most requested file type)

### Requirements

- Extract text from PDF documents
- Extract tables (best-effort - PDF tables are notoriously difficult)
- Page selection (don't load entire 100-page documents by default)
- Handle two-column layouts (common in academic papers)
- Future: Image extraction for multimodal models

### Libraries

| Library | Purpose | Notes |
|---------|---------|-------|
| `pdfplumber` | Text & table extraction | Good table detection |
| `PyMuPDF` (fitz) | Fast text extraction, images | Better for images |
| `pytesseract` | OCR for scanned PDFs | Optional, adds complexity |

### Implementation Plan

1. **Basic text extraction**
   - Use `pdfplumber` for text
   - Return text with page numbers
   - Respect token limits

2. **Table extraction**
   - Detect tables using `pdfplumber.extract_tables()`
   - Convert to markdown format (reuse existing table approach)
   - Mark table boundaries clearly

3. **Page selection UI**
   - Show page count after upload
   - Let user select specific pages or ranges
   - Default: first 10 pages or until token limit

4. **Token management**
   - Calculate tokens per page
   - Warn if total exceeds limit
   - Reject if over limit (user decision)

### Tasks

- [ ] Add `pdfplumber` to `requirements.txt`
- [ ] Create `src/file_parsers/pdf_parser.py`
- [ ] Implement text extraction with page tracking
- [ ] Implement table extraction
- [ ] Add PDF upload UI to thread cards
- [ ] Add page selection UI
- [ ] Integrate with LLM prompt building
- [ ] Test with real medical papers

---

## Phase 2: Spreadsheet Support

**Status:** 🔲 Not Started

**Priority:** High (critical for data accuracy)

### Requirements

- Support XLSX, CSV, XLS formats
- **Multi-sheet:** Include ALL sheets (with sheet name headers)
- Preserve row/column headers for accurate cell references
- Handle large datasets gracefully
- **Accuracy is critical** - cell references must be reliable

### Libraries

| Library | Purpose | Notes |
|---------|---------|-------|
| `pandas` | Universal spreadsheet reading | Handles xlsx, csv, xls |
| `openpyxl` | XLSX-specific features | Sheet names, formatting |
| `xlrd` | Legacy XLS files | Only if needed |

### Implementation Plan

1. **Multi-format parsing** - Support XLSX, CSV, XLS using pandas/openpyxl

2. **Output format** - Markdown tables with:
   - Sheet name headers (e.g., `=== Sheet: AE Summary ===`)
   - Row numbers and column letters for accurate cell references
   - All sheets included automatically

3. **Size management**
   - Calculate tokens for entire spreadsheet
   - If over limit: REJECT (per user decision)
   - Show warning with token count before adding

### Tasks

- [ ] Add `openpyxl` to `requirements.txt` (pandas already there?)
- [ ] Create `src/file_parsers/spreadsheet_parser.py`
- [ ] Implement multi-sheet parsing with headers
- [ ] Convert to markdown with row/column indices
- [ ] Add spreadsheet upload UI
- [ ] Token counting and limit enforcement
- [ ] Test with real clinical datasets

---

## Phase 3: DOCX Attachment Support

**Status:** 🔲 Not Started

**Priority:** Medium

### Requirements

- Extract text and tables from attached DOCX files
- Reuse existing `CommentExtractor` table parsing logic
- Section selection (don't load entire document)

### Implementation Plan

1. **Reuse existing parser**
   - Extend `CommentExtractor` or extract shared utilities
   - Already handles tables → markdown conversion

2. **Section extraction**
   - Parse document structure (headings)
   - Let user select relevant sections
   - Or include all with section headers

### Tasks

- [ ] Create `src/file_parsers/docx_parser.py` (extract from `CommentExtractor`)
- [ ] Add section detection
- [ ] Add DOCX upload UI
- [ ] Token counting integration
- [ ] Test with supplementary documents

---

## Phase 4: PowerPoint Support (Optional)

**Status:** 🔲 Not Started

**Priority:** Low (only if minimal effort)

### Requirements

- Extract text from slides
- Preserve slide numbers for reference
- Tables if present

### Libraries

| Library | Purpose |
|---------|---------|
| `python-pptx` | PPTX parsing |

### Implementation Plan

Only implement if Phases 1-3 go smoothly and effort is minimal.

### Tasks

- [ ] Evaluate effort required
- [ ] If feasible: Create `src/file_parsers/pptx_parser.py`
- [ ] Add upload UI
- [ ] Test with real presentations

---

## UI Design

### Attachment Area (Per Thread)

Location: Below "Custom Instructions" section in each card

```
┌─────────────────────────────────────────────────────┐
│ 📎 Attachments                              [+ Add] │
├─────────────────────────────────────────────────────┤
│ 📄 clinical_protocol.pdf (pages 1-15, ~3,200 tok)   │
│ 📊 ae_summary.xlsx (2 sheets, ~1,800 tokens)   [×]  │
└─────────────────────────────────────────────────────┘
```

### Token Counter

Location: Near "Generate Suggestion" button

```
┌─────────────────────────────────────────────────────┐
│ [Generate Suggestion]     📊 ~5,450 / 128,000 tokens│
└─────────────────────────────────────────────────────┘
```

If approaching limit (>80%): Show in yellow  
If over limit: Show in red, disable Generate button

---

## File Storage

```
output/{session_slug}/
├── attachments/
│   ├── thread_5/
│   │   ├── clinical_protocol.pdf
│   │   └── ae_summary.xlsx
│   └── thread_12/
│       └── reference_paper.pdf
├── llm/
├── session.json
└── ...
```

---

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Multi-sheet XLSX | Include ALL sheets | Simpler UX, medical writers need full context |
| Large file handling | REJECT | Sufficient for most cases, avoids complexity |
| Token display location | Near Generate button | Most relevant context |
| Rate limiting | Config only (for now) | Implement with batch processing |
| Image extraction | Deferred | Requires multimodal models, add later |

---

## Progress Tracker

### Phase 0: LLM Config & Token Counting ✅ COMPLETE
- [x] 0.1.1 Create `config/llm_providers.yaml`
- [x] 0.1.2 Create `src/llm_config.py`
- [x] 0.1.3 Update Settings to use config
- [x] 0.1.4 Update `llm_handler.py` to use config
- [x] 0.2.1 Create `src/token_counter.py`
- [x] 0.2.2 Add `tiktoken` to requirements
- [x] 0.2.3 Add token count endpoint
- [x] 0.2.4 Add token display in UI

### Phase 1: PDF Support ✅ COMPLETE
- [x] 1.1 Add `pdfplumber` to requirements
- [x] 1.2 Create PDF parser (`src/file_parsers/pdf_parser.py`)
- [x] 1.3 Implement text extraction (with page tracking)
- [x] 1.4 Implement table extraction (markdown format)
- [x] 1.5 Add upload UI (in card template, below Instructions)
- [x] 1.6 Add page selection (text input with range support, e.g., "1-10" or "1,3,5-8")
- [ ] 1.7 Integration testing

### Phase 2: Spreadsheet Support ✅ COMPLETE
- [x] 2.1 Add `openpyxl` and `pandas` to requirements
- [x] 2.2 Create spreadsheet parser (`src/file_parsers/spreadsheet_parser.py`)
- [x] 2.3 Multi-sheet handling (all sheets included automatically)
- [x] 2.4 Markdown conversion with row numbers and column letters
- [x] 2.5 Add upload UI (integrated with existing attachment UI)
- [ ] 2.6 Integration testing

### Phase 3: DOCX Attachment Support ✅ COMPLETE
- [x] 3.1 Create DOCX parser (`src/file_parsers/docx_parser.py`)
- [x] 3.2 Section detection (heading styles, outline levels)
- [x] 3.3 Add upload UI (integrated with existing attachment UI)
- [ ] 3.4 Integration testing

### Phase 4: PowerPoint (Optional)
- [ ] 4.1 Evaluate effort
- [ ] 4.2 Implement if feasible

---

## Changelog

### February 2, 2026 (continued)
- **Phase 3 Complete:** Implemented DOCX attachment support
- New files:
  - `src/file_parsers/docx_parser.py` - DOCX parser with section/heading detection
- Modified files:
  - `src/file_parsers/__init__.py` - Export DocxParser
  - `main.py` - Added DOCX handling in attachment endpoint
  - `templates/partials/card.html` - Display paragraph/table count for DOCX
- Features:
  - Upload DOCX files per thread
  - Section detection via heading styles and outline levels
  - Table extraction in markdown format
  - Paragraph count and table count displayed in UI
  - Token estimate display

### February 2, 2026
- **Phase 2 Complete:** Implemented spreadsheet attachment support
- New files:
  - `src/file_parsers/spreadsheet_parser.py` - Spreadsheet parser with multi-sheet and markdown conversion
- Modified files:
  - `requirements.txt` - Added openpyxl and pandas
  - `src/file_parsers/__init__.py` - Export SpreadsheetParser
  - `main.py` - Added spreadsheet handling in attachment endpoint
  - `templates/partials/card.html` - Display sheet count and row count for spreadsheets
- Features:
  - Upload XLSX, XLS, CSV files per thread
  - Multi-sheet handling (all sheets included)
  - Markdown format with row numbers (1, 2, 3...) and column letters (A, B, C...)
  - Token estimate display
  - Sheet count and total rows displayed in UI

### January 27, 2026
- **Phase 1 Complete:** Implemented PDF attachment support
- New files:
  - `src/file_parsers/__init__.py` - File parsers package
  - `src/file_parsers/pdf_parser.py` - PDF parser with text/table extraction
- Modified files:
  - `requirements.txt` - Added pdfplumber
  - `main.py` - Added attachment endpoints, session storage, template context
  - `src/llm_handler.py` - Added attachments parameter to prompt building
  - `templates/partials/card.html` - Added attachments UI section
- Features:
  - Upload PDF files per thread
  - Page range selection (default: first 10 pages, max 10)
  - Token estimate display
  - Remove attachment
  - Attachment content included in LLM prompts

### January 22, 2026
- Initial plan created
- Decisions documented: multi-sheet (all), large files (reject), token display (near Generate)
- Phase 0 (LLM config + token counting) identified as prerequisite
- Created `config/llm_providers.yaml` with:
  - OpenAI models: GPT-5.2, GPT-5 Mini, GPT-5 Nano (verified specs)
  - Ollama: Dynamic model discovery with sensible defaults
  - Tier 4 rate limits, pricing, feature flags
- **Phase 0 Complete:**
  - `src/llm_config.py`: Config loader with provider/model helpers
  - `src/token_counter.py`: Token counting with tiktoken (OpenAI) and approximation (Ollama)
  - Updated `llm_handler.py` to use centralized config
  - Updated Settings modal to dynamically load providers/models from `/llm-config` endpoint
  - Added `/token-count/{session_id}/{thread_id}` endpoint
  - Token counter displays near "Generate Suggestion" button with color-coded warnings