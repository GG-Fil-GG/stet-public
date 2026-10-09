# Stage 1 — Milestone 8 Spec: RTF and PPTX file readers

**Status:** Complete — implemented 2026-06-02; ready for manual QA ([report](stage1_M8_report.md))
**Plan reference:** [Milestone 8](../stage1_implementation_plan.md#milestone-8--rtf-and-pptx-file-readers) · **Roadmap:** Step 7 (reference-file reading)
**Depends on:** M1 (tool layer, `read_file` dispatch), M4 (workspace path resolution)

---

## 1. Goal

Complete the agent's `read_file` reference-reading surface so it covers **every format named in the roadmap**. Today `read_file` handles PDF, XLSX/XLS/CSV, and DOCX. M8 adds **RTF**, **PPTX**, and **plain text** readers, each returning extracted text the agent can use as context during a run (e.g. reading a reference protocol, a slide deck, or a notes file alongside the manuscript being edited).

M8 is a **read-only, parser-layer** milestone. It does **not** touch the agent loop, the chat panel, the document viewer, or the legacy card UI. No new editing capability.

---

## 2. Current state (baseline)

`read_file` (`src/agent/tools.py`) dispatches by extension to `src/file_parsers/`:

| Format | Parser | Status |
|--------|--------|--------|
| PDF | `PDFParser` (`pdfplumber`) | Exists |
| XLSX / XLS / CSV | `SpreadsheetParser` (`pandas`) | Exists |
| DOCX (reference read) | `DocxParser` (zip + ElementTree) | Exists |
| **RTF** | — | **Missing** |
| **PPTX** | — | **Missing** |
| **Plain text** (`.txt`, …) | — | **Missing** (returns `unsupported_format`) |

Every existing parser follows the same shape, which M8 will mirror:

- A `@dataclass …ParseResult` with `filename`, content fields, and an optional `error: str | None`.
- A `to_markdown()` method producing an agent-readable string with a `=== <Type>: <filename> ===` header.
- A `get_token_estimate(chars_per_token=4.0)` helper.
- A parser class whose `parse(file_path)` **never raises** for malformed input — it returns a result with `error` set.
- `read_file` raises `ToolError("parse_failed", …)` when `result.error` is set, and `ToolError("unsupported_format", …)` for unknown extensions.

`read_file` is registered with `path_args=("path",)`, so the agent loop resolves the path inside the workspace before calling it (containment already enforced).

---

## 3. Design constraints (from the codebase)

- **Mirror the existing parser contract** (§2). Consistency matters more than cleverness; the dispatch and tests assume this shape.
- **Parsers never raise on bad input** — they set `error`. `read_file` translates to `ToolError`.
- **No new agent tool.** `read_file` stays the single entry point; only its dispatch table and description grow.
- **Dependencies need project-owner approval** before they go in `requirements.txt` (workspace rule). `striprtf` and `python-pptx` are new third-party deps — see §7 Q1.
- **Committed synthetic fixtures.** Tests use `require_synthetic_file(...)` which fails fast if a fixture is missing (no silent skips). New fixtures live in `test_data/synthetic/attachments/`.
- **Quality gates.** Full suite green, 0 warnings; every new public function gets at least one test.

---

## 4. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `src/file_parsers/rtf_parser.py` | `RtfParser` + `RtfParseResult` (RTF → plain text via `striprtf`) |
| `src/file_parsers/pptx_parser.py` | `PptxParser` + `PptxParseResult` + `PptxSlide` (slide text + notes via `python-pptx`) |
| `test_data/synthetic/attachments/sample.rtf` | Minimal RTF fixture |
| `test_data/synthetic/attachments/sample.pptx` | Minimal PPTX fixture (2 slides, one with speaker notes) |
| `test_data/synthetic/attachments/sample.txt` | Minimal plain-text fixture |

**Modify:**

| File | Change |
|------|--------|
| `src/file_parsers/__init__.py` | Export `RtfParser`, `PptxParser` (+ result types) |
| `src/agent/tools.py` | Add `_RTF_EXTS`, `_PPTX_EXTS`, `_TEXT_EXTS`; dispatch branches in `read_file`; update `unsupported_format` message |
| `src/agent/tool_schemas.py` | Update `ReadFileInput.path` description to list new formats |
| `src/agent/registry.py` | Update `read_file` tool description string |
| `tests/test_file_parsers.py` | `TestRtfParser`, `TestPptxParser` (+ plain-text via `read_file`) |
| `tests/test_agent_tools.py` (or wherever `read_file` is tested) | `read_file` dispatch tests for rtf / pptx / txt |
| `tests/test_support.py` | Fixture path constants (`SAMPLE_RTF`, `SAMPLE_PPTX`, `SAMPLE_TXT`) |
| `requirements.txt` | Add `striprtf`, `python-pptx` (pending Q1 approval) |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, this spec | Glossary / log / status / report (post-implementation) |

---

## 5. Parser specifications

### 5.1 RTF — `src/file_parsers/rtf_parser.py`

Library: **`striprtf`** (`striprtf.striprtf.rtf_to_text`). Lightweight, pure-Python, extracts plain text only (no table/structure reconstruction — RTF's control-word soup makes structure unreliable; plain text is sufficient for reference reading).

```python
@dataclass
class RtfParseResult:
    filename: str
    text: str
    error: str | None = None

    def to_markdown(self) -> str: ...          # "=== RTF: <filename> ===\n\n<text>" or "[Error parsing RTF: …]"
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int: ...


class RtfParser:
    def parse(self, file_path: str) -> RtfParseResult: ...
```

Behavior:
- Read file bytes/text, run `rtf_to_text`. Decode with a UTF-8 → latin-1 → cp1252 fallback chain (mirrors `SpreadsheetParser._parse_csv`). UTF-8 first matters for non-Latin scripts (e.g. Japanese RTF).
- Truncate `text` to `MAX_CHARS = 200_000` with a `[... truncated]` marker (decision Q3).
- On any exception, return `RtfParseResult(filename, text="", error=str(exc))`.
- Empty document → `text=""`, no error (caller decides; `to_markdown` shows header + empty body).

### 5.2 PPTX — `src/file_parsers/pptx_parser.py`

Library: **`python-pptx`** (`pptx.Presentation`).

```python
@dataclass
class PptxSlide:
    slide_number: int          # 1-indexed
    title: str | None
    body_text: list[str]       # non-title shape text, in shape order
    notes: str                 # speaker notes ("" if none)

    def to_markdown(self) -> str: ...    # "## Slide N: <title>" + body bullets + "_Notes:_ …"


@dataclass
class PptxParseResult:
    filename: str
    slides: list[PptxSlide]
    error: str | None = None

    @property
    def slide_count(self) -> int: ...

    def to_markdown(self) -> str: ...    # "=== PPTX: <filename> (N slides) ===" + slides
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int: ...


class PptxParser:
    def parse(self, file_path: str) -> PptxParseResult: ...
```

Behavior:
- Iterate `presentation.slides`, up to `DEFAULT_MAX_SLIDES = 200` (decision Q3). For each slide:
  - Title = `slide.shapes.title.text` if present.
  - Body = text from each shape with a text frame (excluding the title shape), preserving paragraph breaks.
  - Notes = `slide.notes_slide.notes_text_frame.text` when `slide.has_notes_slide`, else `""`.
- **Slide cap:** if the deck has more than `DEFAULT_MAX_SLIDES` slides, extract the first 200 and append a `[... truncated, showing first 200 of N slides]` marker in `to_markdown()`. `PptxParseResult` also exposes `total_slides` (full count) alongside `slide_count` (extracted).
- **Char safety net:** after assembling `to_markdown()`, if the result exceeds `MAX_CHARS = 200_000`, truncate with a `[... truncated]` marker (same guard as text/RTF — decision Q3). Belt-and-braces for a deck that is few slides but enormous text.
- **Out of scope:** images, charts, embedded tables → text only, SmartArt, animations. (Tables-in-slides: extract cell text best-effort only if trivial; otherwise skip — see §9.)
- On exception (bad/locked file), return `PptxParseResult(filename, slides=[], error=str(exc))`.

### 5.3 Plain text

Extensions: see §7 Q2 (proposed default: `.txt` and `.md`).

Handling: **inline in `read_file`** (no parser class — it's a passthrough read with a UTF-8 → latin-1 → cp1252 encoding fallback), returning the same `{path, file_type, content, meta}` shape. `content` is the raw text, truncated to `MAX_CHARS = 200_000` with a `[... truncated]` marker (decision Q3); `meta` carries `{"line_count": N}`.

### 5.4 `read_file` dispatch (`src/agent/tools.py`)

Add extension sets and branches mirroring the existing PDF/spreadsheet/docx blocks:

```python
_RTF_EXTS = {".rtf"}
_PPTX_EXTS = {".pptx"}
_TEXT_EXTS = {".txt", ".md"}   # pending Q2
```

- RTF branch → `RtfParser().parse(...)`; `meta={"char_count": len(result.text)}`.
- PPTX branch → `PptxParser().parse(...)`; `meta={"slide_count": result.slide_count}`.
- Text branch → inline read; `meta={"line_count": …}`.
- Update the final `unsupported_format` message to: `"Supported: pdf, xlsx, xls, csv, docx, rtf, pptx, txt, md."`

Return shape is unchanged: `{"path", "file_type", "content", "meta"}`.

---

## 6. Fixtures

All committed under `test_data/synthetic/attachments/` (pattern: `require_synthetic_file`):

- **`sample.txt`** — a few lines of plain text. Hand-authored.
- **`sample.rtf`** — minimal valid RTF with a couple of paragraphs and one styled run. Hand-authored (RTF is text).
- **`sample.pptx`** — 2 slides: slide 1 title + bullets, slide 2 title + bullets + speaker notes. Generated with `python-pptx`. A small generator snippet will be included in the M8 report (or a `scripts/` helper) so the binary fixture is reproducible; the `.pptx` itself is committed.

---

## 7. Resolved decisions (2026-06-02)

1. **Dependency approval — both libraries.** Add `striprtf` (RTF → text; small, pure-Python) and `python-pptx` (PPTX reading; pulls in `lxml` — already a dep — plus `Pillow`/`XlsxWriter`) to `requirements.txt`. The transitive footprint is accepted; no hand-rolled zip+XML PPTX reader.

2. **Plain-text extensions — `.txt` and `.md`.** Only these two are treated as passthrough plain text. **RTF is _not_ plain text** — it is a distinct format with its own `RtfParser` (§5.1), so `.rtf` files (common from Japanese collaborators) are read via `striprtf`, not the text branch. Broader sets (`.log`, `.json`, `.yaml`) are excluded to avoid mis-reading structured files as flat text.

3. **Size/length guards.**
   - **Text / RTF:** truncate extracted content to `MAX_CHARS = 200_000` with a `[... truncated]` marker (avoids blowing the context window on a huge log).
   - **PPTX:** add a **slide cap** `DEFAULT_MAX_SLIDES = 200` (first 200 slides; `[... truncated, showing first 200 of N slides]` marker) **plus** the same 200k-char safety net. Rationale (project owner): occasional decks exceed 100 slides; even then the text is usually small, but a cap is prudent.

4. **Plain text — inline.** Handle `.txt`/`.md` inline in `read_file` (no `TextParser` class); it is a passthrough read with an encoding fallback.

---

## 8. Tests

**Automated** (`tests/test_file_parsers.py` + `read_file` dispatch tests):

| Test | Asserts |
|------|---------|
| `TestRtfParser::test_parse_sample_rtf` | `error is None`; extracted text contains known fixture words; `to_markdown()` has `RTF:` header |
| `TestRtfParser::test_invalid_rtf_sets_error` or graceful empty | Malformed input → `error` set (or empty text, no raise) |
| `TestPptxParser::test_parse_sample_pptx` | `error is None`; `slide_count == 2`; slide 1 title present; slide 2 notes captured; `to_markdown()` has `PPTX:` header |
| `TestPptxParser::test_invalid_pptx_sets_error` | Non-pptx bytes → `error` set, `slides == []` |
| `read_file` rtf | Returns `file_type="rtf"`, content with fixture text, `meta.char_count` |
| `read_file` pptx | Returns `file_type="pptx"`, `meta.slide_count == 2` |
| `read_file` txt/md | Returns `file_type="txt"`, raw content, `meta.line_count` |
| `read_file` unknown ext | Raises `ToolError("unsupported_format")` with updated message |

**Manual QA** (documented in report):

- Open `/workspace` on a folder containing a `.rtf`, `.pptx`, and `.txt`; ask the agent to summarize each → agent reads and responds with real content.

Full suite stays **green, 0 warnings**; card UI at `/` unaffected.

---

## 9. Out of scope for M8

- **PPTX visuals** — images, charts, SmartArt, animations, slide layouts/themes (text + notes only).
- **PPTX tables** beyond trivial cell-text extraction.
- **RTF structure** — tables, styles, embedded objects (plain text only; `striprtf` limitation).
- **Non-docx previews** in the workspace UI (deferred since M5; M8 is agent-read only).
- **Legacy `.ppt` / `.doc`** (binary formats) — only the XML-based `.pptx` / already-supported `.docx`.
- **Streaming / chunked reading** of very large files (size guard via truncation only — Q3).
- **New agent tools** — `read_file` remains the single entry point.

---

## 10. Acceptance criteria (from plan)

- [x] `read_file` returns extracted text for **all** formats: pdf, xlsx, xls, csv, docx, **rtf, pptx, txt/md**.
- [x] Agent can read a reference RTF / PPTX / text file in the workspace folder during a run.
- [x] New parsers follow the existing `…ParseResult` + `to_markdown()` + `error` contract.
- [x] Synthetic fixtures committed; tests cover happy path + malformed input per format.
- [x] Full suite green, 0 warnings; card UI untouched.
