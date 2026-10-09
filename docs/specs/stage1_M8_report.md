# Stage 1 — Milestone 8 Report: RTF and PPTX file readers

**Status:** Complete (manual QA done; see §7)
**Spec:** [stage1_M8_spec.md](stage1_M8_spec.md)
**Date:** 2026-06-02

---

## 1. What was built

Completed the agent's `read_file` reference-reading surface so it covers every roadmap format. Added **RTF**, **PPTX**, and **plain-text** readers alongside the existing PDF / spreadsheet / DOCX parsers. Read-only, parser-layer only — no agent-loop, viewer, chat, or card-UI changes.

- **`RtfParser`** (`src/file_parsers/rtf_parser.py`) — RTF → plain text via `striprtf`, UTF-8-first decode chain (matters for Japanese RTF), 200k-char truncation guard. Mirrors the existing `…ParseResult` + `to_markdown()` + `error` contract.
- **`PptxParser`** (`src/file_parsers/pptx_parser.py`) — slide title + body text + speaker notes via `python-pptx`. 200-slide cap + 200k-char safety net; `PptxSlide` per slide; `total_slides` vs extracted `slide_count`.
- **Plain text** — `.txt` / `.md` handled inline in `read_file` (passthrough + encoding fallback + 200k truncation); no parser class.
- **`read_file` dispatch** extended with `_RTF_EXTS` / `_PPTX_EXTS` / `_TEXT_EXTS`; schema + registry descriptions and the `unsupported_format` message updated.

## 2. Files

**Created**

- `src/file_parsers/rtf_parser.py` — `RtfParser` + `RtfParseResult`.
- `src/file_parsers/pptx_parser.py` — `PptxParser` + `PptxParseResult` + `PptxSlide`.
- `test_data/synthetic/attachments/sample.rtf`, `sample.pptx`, `sample.txt` — committed fixtures.

**Modified**

- `src/file_parsers/__init__.py` — export `RtfParser`, `PptxParser`.
- `src/agent/tools.py` — rtf/pptx/text dispatch + `_read_text_file` + extension/guard constants.
- `src/agent/tool_schemas.py`, `src/agent/registry.py` — `read_file` description lists new formats.
- `tests/test_support.py` — `SAMPLE_RTF`, `SAMPLE_PPTX`, `SAMPLE_TXT`.
- `tests/test_file_parsers.py` — `TestRtfParser`, `TestPptxParser`.
- `tests/test_agent_tools.py` — `read_file` rtf/pptx/txt/md dispatch tests; fixed stale `.rtf`-unsupported test (now `.xyz`).
- `requirements.txt` — `striprtf`, `python-pptx`.
- `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, this spec.

## 3. Tests

Full suite: **722 passed, 1 skipped, 0 warnings** (was 711).

| Test | Asserts |
|------|---------|
| `TestRtfParser::test_parse_sample_rtf` | Text extracted; `RTF:` header; token estimate > 0 |
| `TestRtfParser::test_unicode_rtf_decodes` | `\u`-escaped (non-ASCII) RTF decodes without error |
| `TestRtfParser::test_truncation_marker` | Oversized RTF truncated with marker |
| `TestRtfParser::test_missing_file_sets_error` | Missing file → `error` set, no raise |
| `TestPptxParser::test_parse_sample_pptx` | 2 slides; title not duplicated into body; notes captured; `PPTX:` header |
| `TestPptxParser::test_slide_cap_truncates` | `max_slides=1` → cap marker, `total_slides=2` |
| `TestPptxParser::test_invalid_pptx_sets_error` | Non-pptx bytes → `error` set, `slides == []` |
| `TestReadFile::test_reads_rtf` / `_pptx` / `_txt` / `_md` | Dispatch returns correct `file_type` + `meta` |
| `TestReadFile::test_unsupported_format_raises` | Unknown ext → `ToolError("unsupported_format")` |

Card UI at `/` unchanged.

## 4. Deviations from spec

One **bug fix beyond the spec**, found during implementation verification: the PPTX title leaked into `body_text` because `python-pptx` returns a fresh wrapper per access, so `shape is title_shape` identity comparison never matched. Fixed by matching on `shape_id`. Logged in the decision log (2026-06-02).

Otherwise as specified. Plain text kept inline; RTF/PPTX caps and the 200k-char guard implemented per §7 decisions.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-02 M8 entries): PPTX title matched by shape id; plain text inline while RTF/PPTX get dedicated parsers.

## 6. Manual QA checklist (project owner)

Open `/workspace` on a folder containing a `.rtf`, `.pptx`, and `.txt` (or `.md`):

1. **RTF** — ask the agent to summarize the `.rtf`; it should read real text (try a Japanese RTF to confirm encoding).
2. **PPTX** — ask about the deck; agent should see slide titles, body bullets, and speaker notes.
3. **Plain text** — ask about the `.txt`/`.md`; agent reads the raw content.
4. **Large deck (optional)** — a 200+ slide deck reads the first 200 with a truncation note.
5. **Unknown type** — asking to read an unsupported extension yields a clear "unsupported file type" error in the step trace.

## 7. Manual QA outcome + follow-ups

Project-owner QA (2026-06-02): all three new readers verified working against real files.

- **RTF** — read a local clinical-table file, including non-ASCII text. Confirms `striprtf` + UTF-8-first decoding.
- **PPTX** — read slide titles and body text from a local deck.
- **Plain text** — read a local `.txt` reference.
- **Unknown type** — a `.jpeg` correctly returned `unsupported_format` with a clear message; the agent surfaced sensible options rather than failing silently. **Expected** per §9 (images out of scope).
- **Large deck (200+ slides)** — not manually tested (none on hand); behavior is covered by the automated `TestPptxParser::test_slide_cap_truncates`.

### 7.1 Follow-up: image reading (out of M8/M9 scope)

Reading `.jpeg` / `.png` (describe/OCR via a vision model) is a meaningfully larger feature than text extraction and is **logged as a Stage 2 / backlog item**, not pulled into M9. The current `unsupported_format` handling is the correct Stage 1 behavior.

## 8. Next

M9 — Integration and hardening (includes the agent Unicode-protection and settings-config follow-ups already logged).
