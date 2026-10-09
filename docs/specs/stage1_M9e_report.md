# Stage 1 — M9e Report: Field-safe editing, dash decision, comment-reply behaviour

**Status:** Complete (automated; manual re-pilot pending project owner — see §6)
**Spec:** [stage1_M9e_spec.md](stage1_M9e_spec.md) (approved 2026-09-23)
**Origin:** M9d re-pilot (2026-09-22) — [pilot checklist §Pilot outcome](stage1_M9c_pilot_checklist.md#pilot-outcome)
**Date:** 2026-09-23

---

## 1. What was built

The three direct fixes from the spec, nothing more: make agent editing safe on real,
citation-heavy manuscripts. No new capability, no context-management system, no
streaming/perf rework, no formatting-preserving rewrite. The existing field-code seam
(`serializer_field_codes.py`), the plain-text revision path, and the M9a/M9d protection map were
reused rather than rebuilt.

### 1.1 Field-safe editing — the critical fix (#1)

**Layer B — serialize-time balance safety net (`src/document_model/serializer_field_codes.py`).**
The root cause of the "won't open" corruption: when the LLM drops a `[CITATION_n]` placeholder in a
rewrite, the field-code restore path re-nested runs incorrectly and emitted an unbalanced `</w:r>` →
structurally invalid OOXML. The fix restores field codes **one placeholder at a time** and checks the
result:

- The original `_restore_field_codes` body is preserved verbatim as `_restore_field_codes_unsafe`.
- A new module-level `_fragment_runs_balanced(xml)` walks the run/element tags with a stack (honouring
  self-closing tags like `<w:fldChar .../>`) and reports whether the fragment is balanced.
- The new `_restore_field_codes` restores each field into a *candidate*; if the candidate is balanced
  it is kept (the citation stays a **live field**), otherwise the placeholder is degraded to its
  citation **display text** (e.g. `[1]`, HTML-escaped) and a `logger.warning` is emitted. Net
  invariant: **every paragraph emitted is structurally balanced**, from any caller (agent tool, manual
  `PATCH`, re-accept, future callers) — a bad input can never brick the document.

**Layer A — surface dropped citations (`src/agent/tools.py`).** `edit_paragraph` now compares the
original paragraph's `field_codes` keys (the authoritative source) against `new_text` and reports any
missing placeholders as `removed_citations` in its result (omitted entirely when nothing was dropped).
Removal is **allowed** — a legitimate edit can delete a sentence and its citation — but it is now
visible in the result and the run transcript for QA. No `ToolError`, no forced retry (revised per owner
decision 2026-09-23).

**Layer C — prompt guidance (`src/agent/prompts.py`).** `AGENT_SYSTEM_PROMPT` now explains that
paragraph text may contain `[CITATION_n]` placeholders standing for real Word citation fields, that
each must be reproduced verbatim when the cited material is kept (never renumbered or invented), and
that a placeholder should disappear only when deliberately removing the cited text.

**Fixture gap closed.** `test_data/synthetic/citation_field.docx` — a minimal document with EndNote-style
fields (`fldChar`/`instrText`/`fldData`) plus an en-dash year range — was added because *no* previous
synthetic fixture contained a complex field, so the field path was never exercised by an automated test.
It has one single-field paragraph (`1A2B3C40`) and one three-field paragraph with a `2013–2019` range
(`1A2B3C41`), each field carrying a unique display text (`[1]`…`[4]`) as `plain_text` substitution
requires.

### 1.2 Dashes — fixed, not deferred (#2)

Per the A/B settled in the spec (`gpt-5-mini`, 40 rewrites/condition: token protection **95%** vs raw
**65%**, zero control characters either way), the M9d token protection is **kept unchanged**, and a
**narrow numeric-range repair** was added in `src/agent/tools.py`:

- `_NUMERIC_RANGE_RE = re.compile(r"(\d+)\u2013(\d+)")` finds en-dashes that sat **between digits** in
  the *original* paragraph text.
- `_restore_numeric_range_dashes(original_text, new_text)` restores just those ranges when the model
  rendered them as `digit␠digit`, `digit-digit`, `digit␠-␠digit`, or `digit‑digit` (non-breaking
  hyphen). It is strictly bounded to digit–digit patterns seen in the original, so it can never touch
  prose. `edit_paragraph` applies it before writing and reports `restored_ranges` when it fires.

The rare prose em-dash drop (~5%) is accepted as cosmetic and pinned by tests so it can never regress to
a control character or a broken document.

### 1.3 Comment-reply behaviour (#3)

- `edit_paragraph` gained an optional `addresses_thread_id: str | None = None`
  (`src/agent/tool_schemas.py` declares it for the LLM). When set, the tool validates the thread exists
  (`ToolError("not_found", …)` otherwise) and echoes the linkage in its result and the transcript, so
  comment-driven edits are reviewable after the fact. It is omitted from the result when unset.
- `AGENT_SYSTEM_PROMPT` now carries the per-comment workflow: for a comment-driven edit, set
  `addresses_thread_id` and then call `add_comment_reply` on the same thread; for edits driven by the
  user's direct instruction (not a specific comment), leave it unset and do **not** reply.

### 1.4 Transcript visibility

The run transcript already records the full tool result (`tool_result` writes `result=_clip(step.result)`),
so `removed_citations`, `restored_ranges`, and `addresses_thread_id` are captured with no schema change.
`src/agent/loop.py`'s per-step INFO log was enriched to append `[dropped citations: …]` when an edit
drops a placeholder, so the signal is visible in the console as well as the JSONL.

## 2. Files

**Modified**

- `src/document_model/serializer_field_codes.py` — `_TAG_RE`, `_fragment_runs_balanced`;
  `_restore_field_codes` renamed to `_restore_field_codes_unsafe`; new balance-gated `_restore_field_codes`.
- `src/agent/tools.py` — `_NUMERIC_RANGE_RE`, `_restore_numeric_range_dashes`; `edit_paragraph` now
  reports `removed_citations`/`restored_ranges` and accepts/validates/echoes `addresses_thread_id`.
- `src/agent/tool_schemas.py` — `EditParagraphInput` declares `addresses_thread_id`; `new_text`
  description reinforces `[CITATION_n]` preservation.
- `src/agent/prompts.py` — citation-placeholder guidance (Layer C) + comment-reply workflow policy.
- `src/agent/loop.py` — per-step log appends dropped-citation notice.
- `tests/test_support.py` — `CITATION_FIELD_DOCX` fixture path.

**Added**

- `test_data/synthetic/citation_field.docx` — EndNote-style citation-field fixture.
- `tests/test_field_safe_editing.py` — M9e regression tests (20).
- `docs/specs/stage1_M9e_report.md` (this file).

No changes to the card-UI path (`src/llm_transport.py`) or to `DocumentModel.to_dict`/`from_dict`.

## 3. Tests

Full suite: **795 passed, 1 skipped, 0 warnings** (20 new tests in `test_field_safe_editing.py`). The
single skip is `test_agent_integration.py::…::test_summarise_open_comments`, gated behind
`RUN_OLLAMA_TESTS=1` (Ollama unreachable) — an opt-in live test, not a silent no-op and not an M9e
regression.

| Test | Asserts |
|------|---------|
| `TestCitationFixture::test_fields_parsed_as_placeholders` | Fixture exposes `[CITATION_1..4]` in `field_codes`; the `2013–2019` range survives parse |
| `…::test_plain_roundtrip_is_valid_and_preserves_fields` | No-edit parse→export is valid OOXML; all 4 fields (12 `fldChar`) intact |
| `TestFieldSafeEditing::test_keep_all_citations_is_valid_and_live` | Edit keeping every placeholder → valid XML, all 4 fields still live |
| `…::test_dropping_a_citation_is_allowed_and_valid` | Edit omitting one placeholder → `removed_citations`; valid XML; that field gone, others live |
| `…::test_dropping_all_citations_is_valid` | Removing every citation → valid XML; all reported |
| `…::test_removed_citations_absent_when_all_kept` | `removed_citations` omitted when nothing dropped |
| `TestBalanceSafetyNet::test_fragment_balance_checker` | Balanced / self-closing / unbalanced fragments classified correctly |
| `…::test_balanced_field_restores_live` | A balanced field restores as a live field code |
| `…::test_unbalancing_field_degrades_to_static_text` | A field that would unbalance runs degrades to static display text; result always balanced, no `fldChar` |
| `TestNumericRangeDashRepair::test_range_variants_restored` | `2013 2019`/`2013-2019`/`2013 - 2019`/`2013‑2019` → `2013–2019`; `restored_ranges` reported |
| `…::test_prose_not_touched_without_original_range` | No original range → prose digit-space left untouched |
| `…::test_only_original_ranges_restored` | Only ranges present in the original are restored |
| `…::test_correct_dash_left_alone` | A correct en-dash is not double-processed |
| `TestCommentLinkage::test_schema_advertises_addresses_thread_id` | `edit_paragraph` schema advertises the optional param |
| `…::test_valid_thread_is_echoed` | Valid `addresses_thread_id` validated and echoed in the result |
| `…::test_unknown_thread_raises` | Unknown thread → `ToolError("not_found")` |
| `…::test_instruction_edit_has_no_linkage` | Instruction-only edit omits the linkage from its result |

**Regression: recovered pilot edits.** Replaying the 10 real pilot edits through the fixed path was
verified ad-hoc during implementation — all 10 export to **valid** OOXML (only the accidental
`[CITATION_4]` drop degrades to static `[1,4]`). It is not committed as a test because it depends on the
private local manuscript (`test_data/local/`), not a synthetic fixture; the committed
`test_dropping_a_citation_is_allowed_and_valid` / `test_unbalancing_field_degrades_to_static_text` cover
the same code path on the synthetic fixture.

The card UI at `/` and its tests are untouched.

## 4. Deviations from spec / notes

- **Layer B lives entirely in `serializer_field_codes.py`.** The spec allowed touching
  `serializer.py`/`serializer_revisions.py` too; a per-placeholder balance gate at the field-restore seam
  was sufficient and kept the diff minimal — no change to the revision/tracked-change assembly was needed.
- **Degradation target is the citation display text**, not an empty deletion, so a dropped-but-referenced
  citation stays human-readable in the document (e.g. `[1]`) rather than vanishing silently.
- **Transcript needed no new code** (§1.4): `tool_result` already persists the full result dict. The
  spec's "record on the edit event" is satisfied; the loop log enrichment is a small extra for console
  visibility.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-09-23): #1 guaranteed via a serialize-time balance safety net
(mandatory) with citation removal allowed and surfaced (no hard reject); #2 dash approach chosen by A/B
(keep token protection + numeric-range repair; raw + control-char sanitizer rejected by the data); #3
comment replies via an `addresses_thread_id` linkage param plus prompt policy.

## 6. Manual QA (project owner — gates the M9c pilot re-run)

1. Run the agent on a **citation-heavy** manuscript so it rewrites paragraphs with EndNote citations →
   **Save** → the file **opens in Word** (no "experienced an error" dialog).
2. Ask the agent to edit a paragraph containing a **year range** (`2013–2017`) → the saved tracked change
   keeps the **en-dash**, not `2013 2017`.
3. Ask the agent to **address a comment** → the exported document shows a **reply** threaded on that
   comment; an instruction-only edit leaves no reply.
4. Check `.stet/runs/<run>.jsonl` → comment-driven edits carry `addresses_thread_id`, and any dropped
   citations appear as `removed_citations`.

## 7. Next

Resume **M9c — Pilot + closeout**: re-run the pilot task on the real manuscript with the field-safe,
dash, and comment-reply fixes in place; confirm the saved document opens and comments carry replies; then
the default-route flip, docs audit, and Stage 1 closeout.
