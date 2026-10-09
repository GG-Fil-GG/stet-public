# Stage 1 — M9e Spec: Field-safe editing, dash decision, comment-reply behaviour

**Status:** Implemented 2026-09-23 — see [report](stage1_M9e_report.md) (approved 2026-09-23; all §7 decisions resolved; dash A/B settled)
**Plan reference:** inserted before [M9c — Pilot + closeout](../stage1_implementation_plan.md#status); M9c closeout resumes after M9e
**Depends on:** M1–M9d
**Origin:** M9d re-pilot (2026-09-22) — see [pilot checklist §Pilot outcome](stage1_M9c_pilot_checklist.md#pilot-outcome)

---

## 1. Goal

The M9d re-pilot ran the full task on a local manuscript (not included in this repository). Durability, the run transcript, and logging all worked — which is exactly how these findings were diagnosed. But the saved `.docx` **would not open in Word**, some edits **dropped en-dashes** from year ranges, and the agent **left no replies** on the comments it addressed.

M9e makes agent editing *safe on real, citation-heavy manuscripts*: an agent edit must never be able to produce a file Word refuses to open, and when the agent changes text to answer a reviewer it should say so on that comment. Nothing here is new capability — it is making existing editing trustworthy on documents with field codes.

**Scope discipline:** direct fixes to the three re-pilot findings only. No new context-management system, no streaming/perf rework, no formatting-preserving rewrite (Stage 2). Reuse the existing field-code seam (`serializer_field_codes.py`), the plain-text revision path, and the M9a/M9d protection map — don't rebuild them.

## 2. Findings being addressed (recorded)

Diagnosed from the re-pilot run transcript (`.stet/runs/20260922-182049-5a7f58.jsonl`, 68 steps, cancelled by the user) and the saved local manuscript.

| # | Finding | Severity | Root cause (confirmed) | Fix area |
|---|---------|----------|------------------------|----------|
| 1 | Saved `.docx` won't open ("Word experienced an error trying to open the file") | **Critical (data corruption)** | The LLM **drops `[CITATION_n]` placeholders** when it rewrites a paragraph. Original paragraphs carry field codes (EndNote citations: `w:fldChar`/`w:instrText`/`w:fldData`) exposed to the agent as `[CITATION_n]` placeholders in `plain_text`. When a rewrite omits a placeholder, the field/tracked-change restore path emits **unbalanced runs** (an unmatched `</w:r>` after `</w:fldChar>`), producing structurally invalid OOXML. Reproduced deterministically: replaying the 10 real edits, the document is valid through edit 3 and first breaks at **edit 4** (para `4E3B7B9D`, 5 citations → only 2 kept). A plain parse→export round-trip with **no** edits is valid, so export itself is sound — the corruption is introduced by the edit. | Field-safe editing (serialize safety net + visibility + fixture) |
| 2 | Year ranges lost their en-dash (`2013–2017` → `2013 2017`) | Medium (output quality) | The model **discards the injected `__UNICODE_NDASH__` token** when paraphrasing, leaving a space — only in rewritten paragraphs (untouched ones keep all 103 en-dashes). Our protect/restore and export are lossless (verified); this is model behaviour. The earlier `U+2013 → U+0013` control-char corruption was the **pre-M9d** symptom, already fixed by M9d protection. | Fix in M9e (approach via A/B, §3.2) |
| 3 | No replies left on the comments the agent addressed | Medium (behaviour) | Across 68 steps the agent made 10 `edit_paragraph` calls and **zero** `add_comment`/`add_comment_reply` calls. It answered comments by editing text only; the prompt never told it to record a response on the comment it was addressing. | Comment-reply behaviour (linkage param + prompt policy) |

Observations recorded but **not fixed here** (logged to backlog — see §5): live viewer refresh during a run (#4), and search-heavy inefficiency — 40 `find_in_document` for 10 edits (#5).

## 3. Scope — three direct fixes

### 3.1 Field-safe editing (the critical fix)

The invariant we must guarantee is **structural**: an edit must never produce an unopenable document. Losing a citation is acceptable (a legitimate edit can delete a sentence and its citation); emitting *broken field runs* is not. The fix is therefore a mandatory safety net, a visibility layer, and a prompt nudge — **not** a hard block on citation removal (revised per owner decision 2026-09-23: the agent must be free to remove citations).

**Layer B — Serialize-time balance safety net (the primary, mandatory fix).**
- The field-code restore path (`serializer_field_codes.py`) already has a "detect unbalanced → fall back" philosophy on *extraction*. Add the analogous guarantee on *output*: after a paragraph's runs are assembled (field-code restore + tracked-change wrapping), the emitted paragraph XML must be **structurally balanced**. If a paragraph would be unbalanced (e.g. a citation whose placeholder the model dropped, or a restore that broke run nesting), fall back to a safe rendering that drops the orphaned field **cleanly** rather than emitting broken runs — the same "a bad input can never brick the document" rule M9d applied to snapshots.
- Net effect: **any** edit, from **any** path (agent tool, manual PATCH, re-accept, future caller), always yields a document Word can open. A citation that stays is balanced; a citation whose placeholder is gone is dropped cleanly. This alone fixes the "won't open" bug **and** permits deliberate citation removal.

**Layer A — Surface dropped citations (visibility, not a block).**
- On `edit_paragraph`, compare the field-code placeholders on the original paragraph(s) — `para.field_codes` keys (the authoritative source, not a regex guess) — against those present in `new_text` (union across the whole `new_text`, so a split that moves a citation to the second half still counts).
- Any placeholder **missing** from `new_text` is a *removed* citation: **allow it**, but record it in the run transcript and return it in the edit result (e.g. `removed_citations: ["[CITATION_7]", …]`), so accidental losses (sentence kept, marker dropped — as in the pilot's edit 7) are visible in QA rather than silent. No `ToolError`, no forced retry.
- *Deferred tightening:* if a re-pilot shows the model dropping citations **accidentally** at a meaningful rate, we can add an explicit-acknowledgment param (agent must name the citations it intends to remove; unnamed drops rejected) in a follow-up. We start with the lighter "good," not the "best."

**Layer C — Prompt guidance (reduce accidental drops).**
- Extend `AGENT_SYSTEM_PROMPT` to explain that paragraph text may contain `[CITATION_n]` placeholders standing for citations/fields, that each should be reproduced **verbatim** when the cited material is kept (never renumbered or invented), and that a placeholder should only disappear when the agent is *deliberately* removing the cited text. This mirrors the existing `__UNICODE_*__` token guidance and lowers the accidental-drop rate.

**Fixture gap (why this shipped).** No synthetic fixture contains a complex field (`fldChar`/`instrText`/`fldData`), so no automated test exercised the field path — the round-trip and diff tests all pass on field-free documents. M9e adds a small synthetic docx fixture **with** an EndNote-style citation field under `test_data/synthetic/`, and the regression tests below are built on it.

**Acceptance:** on a field-bearing paragraph, (a) an edit that keeps the `[CITATION_n]` placeholders round-trips to **valid** OOXML with the citation intact; (b) an edit that omits a placeholder still produces **valid** OOXML (citation dropped cleanly) and reports the removal in its result/transcript; (c) even a forced/out-of-sync serialize produces **valid** OOXML (document opens); (d) re-running the recovered pilot edits yields a document that opens in Word.

### 3.2 Dashes — fix in M9e (not deferred)

**Established facts (verified 2026-09-23):** our protect/restore is lossless, our edit+export preserves a raw en-dash into valid XML, and the saved re-pilot file has **zero** `U+0013` control characters — all 103 source en-dashes survived in untouched paragraphs. The `U+2013 → U+0013` control-char corruption was the **pre-M9d** symptom (raw dash sent to the model); M9d's protection already eliminated it. The **only** remaining symptom is in agent-*rewritten* paragraphs: the model **drops the `__UNICODE_NDASH__` token**, leaving a space (`2013 2017`). This is model behaviour, not a defect in our pipeline — the same family as the citation drop — but it is fixable now because we hold the original text.

**A/B outcome (2026-09-23, `gpt-5-mini`, 40 rewrites/condition):** the **token approach won decisively — 95% dashes preserved (38/40) vs 65% raw (26/40)**; feeding a raw en-dash was *worse* (the model rewrote dashes away more often — an em-dash parenthetical lost all 10 raw vs 8/10 tokenized). **Zero control characters in either condition** — `gpt-5-mini` never emits `U+0013`, so the control-char sanitizer would solve a non-problem and is dropped. Conclusion: **keep the M9d token protection; do not switch to raw.**

**Decision (chosen approach):**
- **Keep** the M9d dash/ellipsis/nb-hyphen token protection unchanged (it's the better option by the data).
- **Add a narrow numeric-range repair** in the edit path: after applying an edit, if the *original* paragraph had an en-dash **between digits** (year/number ranges — the pilot's exact complaint) and the model's `new_text` rendered that spot as `digit␠digit` or `digit-digit`, restore the en-dash. Strictly bounded to digit–digit patterns, so it can never alter prose.
- **Light prompt reinforcement** to keep numeric ranges intact.
- The rare prose em-dash drop (~5%) is genuine model behaviour and is accepted as cosmetic; pinned by a test so it can never regress to a control char or broken document.

### 3.3 Comment-reply behaviour

**Goal (user's framing):** when an edit is made *to address a reviewer comment*, the agent should reply on that comment's thread; when an edit comes from the user's *direct instruction* (not tied to a comment), it should **not** reply. Only the agent knows which driver applies, so the mechanism must be agent-driven and make that intent explicit.

**Direct fix — an explicit linkage param plus prompt policy.**
- Add an optional `addresses_thread_id: str | None = None` to `edit_paragraph`. The agent sets it when (and only when) the edit is made to satisfy a specific comment thread; it leaves it unset for user-instruction edits. The tool validates the thread exists and echoes the linkage in its result (and into the run transcript) so comment-driven edits are reviewable after the fact.
- Extend `AGENT_SYSTEM_PROMPT` with a per-comment workflow: for each open thread it intends to address — locate the paragraph, edit it with `addresses_thread_id` set, then call `add_comment_reply` on that thread with a brief note of what changed (and why, if not obvious). One reply per addressed thread. Explicitly: do **not** reply for edits driven by the user's direct instructions rather than a comment.
- Keep it lean: no auto-generated reply text (the wording is the agent's judgement), no forced blocking. The linkage param makes the "comment-driven vs instruction-driven" distinction explicit and checkable; the prompt drives the reply.

**Acceptance:** in a scripted run where the agent is asked to address a comment, it (a) sets `addresses_thread_id` on the edit and (b) leaves an `add_comment_reply` on that thread; an instruction-only edit sets neither. Manual QA on the pilot doc: addressed comments carry a visible reply; the exported doc shows the replies threaded correctly.

## 4. Files

| File | Change |
|------|--------|
| `src/document_model/serializer_field_codes.py` (and/or `serializer.py`/`serializer_revisions.py`) | **Layer B (primary):** guarantee balanced paragraph output; safe fallback that drops orphaned/out-of-sync field codes cleanly |
| `src/agent/tools.py` | `edit_paragraph`: Layer A visibility (report `removed_citations` in the result, no reject); add optional `addresses_thread_id`, validate + echo linkage |
| `src/agent/tool_schemas.py` | Declare the new optional `addresses_thread_id` param for `edit_paragraph` |
| `src/agent/prompts.py` | Citation-placeholder guidance (Layer C) + comment-reply workflow policy |
| `src/document_model/plain_text_edits.py` (or `tools.py`) | Dash fix (§3.2): narrow numeric-range en-dash repair after an edit (digit–digit only); token map unchanged |
| `src/agent/run_transcript.py` / `src/agent/loop.py` | Record `addresses_thread_id` and `removed_citations` on the edit event so both are visible in the transcript |
| `test_data/synthetic/` | New minimal docx fixture containing an EndNote-style citation field |
| `tests/` | Field-safe edit tests (valid round-trip, clean drop, serialize safety net); dash tests; comment-reply behaviour tests |

No changes to the card-UI path (`src/llm_transport.py`) or to `DocumentModel.to_dict`/`from_dict`.

## 5. Out of scope (explicitly) — logged to backlog

- **Live viewer refresh during a run (finding #4).** Today the document viewer only re-renders when the run ends/stops; only the progress counter updates mid-run. Confirmed expected behaviour, not data loss. Logged to `docs/_legacy/future_improvements.md` (Stage 2 UI).
- **Search-heavy inefficiency (finding #5).** The re-pilot spent 40 `find_in_document` + 8 `read_paragraph` for 10 edits. An efficiency concern, not correctness. Logged to `docs/_legacy/future_improvements.md` (Stage 2 agent efficiency), alongside the existing broader perf workstream.
- **Formatting-preserving agent edits** (run-level bold etc.), **image reading**, **deeper run performance/streaming** — unchanged Stage 2 backlog. (Dashes are **not** deferred — see §3.2.)
- **Auto-generating comment reply text** — the agent writes its own replies; no templating.
- **The default-route flip and Stage 1 closeout** — M9c, resumed after M9e passes a clean re-pilot.

## 6. Tests

| Test | Asserts |
|------|---------|
| Field-safe: edit preserving placeholders | Field-bearing paragraph edited with all `[CITATION_n]` kept → exported `document.xml` parses (valid), field count preserved, citation intact |
| Field-safe: clean citation removal | `edit_paragraph` whose `new_text` omits a placeholder → **valid** XML (citation dropped cleanly); result/transcript reports `removed_citations` |
| Field-safe: serialize safety net | An out-of-sync model (placeholder absent from text but field code present) serializes to **valid** XML with the orphaned field dropped, never unbalanced runs |
| Regression: recovered pilot edits | Replaying the pilot's 10 edits through the fixed path yields valid OOXML at every step |
| Dash: numeric-range repair | Original `2013–2017`, model returns `2013 2017`/`2013-2017` → post-edit repair restores `2013–2017`; a prose word-space (non-digit) is left untouched |
| Dash: token round-trip | En-dash preserved through protect/restore → real `–` in the tracked change; residue is never a control char |
| Comment reply: comment-driven | Scripted edit with `addresses_thread_id` set + `add_comment_reply` → reply threaded on that comment; linkage recorded in the transcript |
| Comment reply: instruction-driven | Edit without `addresses_thread_id` leaves no reply |
| Schema | `edit_paragraph` tool schema advertises the optional `addresses_thread_id` |

Full suite stays green, 0 warnings; the card UI at `/` and its tests are untouched.

## 7. Decisions & open questions

**Resolved (owner, 2026-09-23):**
- **#1 policy** — do **not** hard-reject citation removal. Guarantee structure via the Layer B safety net (mandatory); allow removals but surface them (Layer A). Tightening to explicit acknowledgment is a possible follow-up if a re-pilot shows accidental drops.
- **#2 dashes** — **not deferred**; fix in M9e. Approach picked by the quick A/B in §3.2.
- **#3 comment replies** — linkage param (`addresses_thread_id`) + prompt policy (as in §3.3).

- **#2 dash approach** (resolved by A/B, 2026-09-23): keep the token protection (95% vs 65% raw) + narrow numeric-range repair; the raw+control-char-sanitizer path is rejected by the data.

**Open:** none — ready to implement.
