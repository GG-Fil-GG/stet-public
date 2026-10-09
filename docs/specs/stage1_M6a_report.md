# Stage 1 — Milestone 6a Report: Document viewer — read fidelity

**Status:** Complete (manual QA done; one finding fixed — see §8)
**Spec:** [stage1_M6a_spec.md](stage1_M6a_spec.md) · **Umbrella:** [stage1_M6_spec.md](stage1_M6_spec.md)
**Date:** 2026-06-01

---

## 1. What was built

The M5 read-only **stub** (which concatenated each paragraph's `to_display_html()` with no separator, dropped deleted runs, didn't mark insertions, and ignored comments) is replaced by a faithful read viewer:

- **Pure renderer** `src/workspace/render.py` — `render_document(model) -> list[Block]`. Each `Block` is `{kind, para_id, html, text, style, comment_ids, cells?}` where `kind` is `"paragraph"` or `"table_row"`. No I/O, no session state.
- **Block separation** — each body paragraph (and each table row) is its own block, so the client wraps each in its own element. This fixes the dominant "everything on one line" finding from M5 manual testing.
- **Inline track changes** — inserted runs render as `<ins class="diff-insert">`, deleted runs as `<del class="diff-delete">` (no longer dropped), reusing the card UI's diff colour language.
- **Anchored comments** — comment ranges are highlighted inline via `<span class="ws-comment-ref" data-comment-ids="…">`, computed by **boundary segmentation** so overlapping and cross-paragraph anchors render as flat, legal HTML (a region under two comments becomes one span carrying both ids). Cross-paragraph anchors cover head/middle/tail paragraphs.
- **Comments side list** — a right-hand rail in the document area lists each thread (status, referenced text, author, replies) in document order, with **click-linking** both ways: clicking a card scrolls+flashes the anchor; clicking a highlighted span flashes its card.
- **Tables** — rendered as legible rows (distinct, bordered cells) rather than run-on text. (A true `<table>` grid is Stage 3.)
- **Enriched API** — `GET /api/workspace/{id}/document` now returns `{document, blocks, comments}`; the flat `paragraphs` array is replaced by `blocks`. The viewer refreshes after every agent run (existing `renderResult → refreshDocument` path), so agent edits/comments appear with the new styling.

## 2. Files

**Created**

- `src/workspace/render.py` — `Block` dataclass + `render_document` (+ boundary-segmentation helpers).
- `tests/test_document_render.py` — 14 pure-Python renderer tests.

**Modified**

- `src/workspace/__init__.py` — export `Block`, `render_document`.
- `src/routes/workspace.py` — `GET /document` returns `blocks` + `comments` (`_blocks`/`_comments` replace `_paragraphs`).
- `templates/workspace.html` — document area is now a `ws-doc-layout` (page + `#ws-comments` rail).
- `static/js/workspace.js` — `renderDocument(data)` → `renderBlocks` + `renderComments`; anchor↔comment click-linking + flash; `clearDocument`/`refreshDocument` updated.
- `static/css/workspace.css` — block paragraphs, track-change, comment-highlight (open/resolved), comments-rail, table-row, and flash styles.
- `tests/test_workspace_api.py` — `TestDocumentView` (blocks + comments shape; comment surfaces in payload and anchored block); helpers updated from `paragraphs` to `blocks`.
- `tests/test_workspace_page.py` — assert the `#ws-comments` rail is present.

## 3. Tests

- **`tests/test_document_render.py` (new, 14):** block-per-paragraph separation; empty paragraph → empty block; style/text carried; `to_dict` shape; HTML escaping; inserted→`diff-insert`; deleted→`diff-delete` (present, not dropped); newline→`<br>`; single comment span; **overlapping** comments share a segment (`data-comment-ids="1 2"`); **cross-paragraph** anchor covers head + middle + tail; resolved status still renders; table → `table_row` blocks with `cells`; paragraph/table document order preserved.
- **`tests/test_workspace_api.py`:** `GET /document` returns `blocks` + `comments` with the expected shapes; a fixture comment surfaces in `comments` and in its anchored block's `comment_ids` (with a `ws-comment-ref` span).
- **Full suite:** `696 passed, 1 skipped, 0 warnings` (the skip is the pre-existing opt-in live-Ollama test). Card UI at `/` unaffected.

## 4. Deviations from spec

- **Soft breaks (`<w:br/>`) not rendered — deferred.** The parser captures only `<w:t>` text and discards `<w:br/>`, so soft breaks are absent from the `DocumentModel`; the renderer cannot show what isn't parsed. The visible "merged lines" symptom the owner reported was actually **separate paragraphs run together**, which the block separation fixes. The renderer defensively maps any `\n` already in run text to `<br>`. True `<w:br/>` support needs coordinated parser + serializer changes (round-trip the break, not a literal newline in `<w:t>`) and is logged as a future item. See [decision log, 2026-06-01](../stage1_decision_log.md#2026-06-01--milestone-6a--soft-breaks-wbr-not-preserved-rendering-deferred).
- **Comment side-list alignment.** As agreed (umbrella §2.2), M6a delivers inline highlights + an ordered side list + click-linking; pixel-perfect card-to-anchor vertical alignment and persistent leader lines are Stage 3.

## 5. Decisions logged

Three M6a entries in [`stage1_decision_log.md`](../stage1_decision_log.md): the pure `render_document` block model (+ `blocks` replacing `paragraphs`); comments as inline highlights + side list with boundary segmentation (balloons → Stage 3); and the soft-break deferral. Glossary updated (`render.py`, `Block`, the `GET /document` shape, frontend asset notes).

## 6. Manual QA checklist (for the project owner)

Open a real manuscript from `test_data/local/` (and synthetic `test.docx`) at `/workspace` and verify:

1. Paragraphs are separated (no more run-on lines); the table shows as distinct rows.
2. A tracked change shows insertion (green) / deletion (red strike-through) inline.
3. Anchored comments are highlighted in the text and listed in the right-hand rail; resolved threads look muted.
4. Clicking a comment card scrolls to + flashes its anchor; clicking a highlighted span flashes its card.
5. After an agent edit/comment, the viewer refreshes and shows the change.

## 7. Next

M6b (edit mode) — standalone TipTap editor, `PATCH /document/paragraph/{para_id}` with a pre-edit checkpoint. See [stage1_M6b_spec.md](stage1_M6b_spec.md).

## 8. Manual QA outcome + follow-up fix

Project-owner QA confirmed: paragraph separation ✓, table as real cells ✓, comment highlights + muted resolved threads ✓, click-linking ✓, refresh-after-run ✓. **One finding:** tracked **insertions** showed (green) but tracked **deletions** did not appear at all (they show as red strike-through in the card UI).

**Root cause:** the parser dropped deletions. The `<w:del>` branch in `_parse_paragraph` correctly tagged runs `RevisionType.DELETION` and left the offset un-advanced, but `_parse_run` read text only from `<w:t>`. Word stores deleted text in **`<w:delText>`**, so deleted runs parsed empty (`text == ""`) and were discarded (`_parse_run` returns `None`). The deletion never reached the model, so the renderer (which already emits `<del class="diff-delete">` for `is_deleted()` runs) had nothing to show.

**Fix (`src/document_model/parser.py`):** `_parse_run` now also captures `<w:delText>` text. Deleted runs survive into the model with their text and `RevisionType.DELETION`, so the existing renderer shows them struck-through. Safe by construction:
- `plain_text`/`raw_text` and all offset math already **exclude** deleted runs → comment anchors/offsets unchanged.
- The serializer's model-regeneration path (`_build_runs_xml_from_model`) **skips** deleted runs and only emits `<w:t>`, so captured deletions are never re-emitted as normal text; unmodified paragraphs keep their original `<w:del>` XML verbatim. Full serializer + round-trip suites stay green.

**Test:** `tests/test_document_parser.py::TestParserEdgeCases::test_deleted_run_text_captured_from_deltext` (hand-built `<w:del><w:delText>` → one deleted run with the right text; `plain_text` excludes it; `full_text` includes it). Full suite: **697 passed, 1 skipped, 0 warnings**.

**Known limitation (→ M6b):** *in-session* tracked changes made by the agent/user render as their **result**, not as coloured tracked changes. `edit_paragraph` (REPLACE) physically removes old text from runs and adds the new text as a plain run, recording both in the `RevisionStore` — so the model's runs don't carry `INSERTION`/`DELETION` marks for those edits. Faithfully showing in-session edits as tracked changes (rendering from the `RevisionStore`, or marking edited runs) is folded into M6b, where editing in the viewer makes this the natural place to solve it. (The insertions the owner saw in green were the opened document's pre-existing `<w:ins>` runs, which is why this gap didn't surface in QA.)
