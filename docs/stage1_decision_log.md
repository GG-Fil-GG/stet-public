# Stage 1 Decision Log

**Chronological record of decisions made *during* Stage 1 implementation.**

This document captures choices that arise mid-implementation and are not already covered by the up-front [Resolved decisions](stage1_implementation_plan.md#resolved-decisions) section of the implementation plan.

**Why a separate doc?** The implementation plan's "Resolved decisions" section is the constitution — finalized before coding starts. This log is the running record of follow-up choices: what to do when a spec is ambiguous, what naming convention to pick when the glossary is silent, what trade-off was taken when two acceptable paths existed.

---

## How to use this document

- **For me (the AI assistant):** When a non-trivial decision arises during implementation that is not pre-decided in the plan, log it here as part of the milestone report. Future sessions read this before starting work to avoid re-litigating settled questions.
- **For the project owner:** This is where to spot decisions you would have wanted to weigh in on. If an entry surprises you, raise it.

Each entry follows this format:

```
### YYYY-MM-DD — Milestone N — Short title

**Question:** What was unclear or required a choice.

**Choice:** What was decided.

**Rationale:** Why, in one paragraph.

**Alternatives considered:** Brief list, if any were realistic.

**Reversible?** Yes / No / Costly. (Helps future sessions know how serious it is to change.)
```

If a decision is later overturned, add a new dated entry that supersedes the older one and link both ways.

---

## Decisions

### 2026-09-23 — M9e — Field-safe editing via a serialize-time balance safety net (not a citation-removal block)

**Question:** The M9d re-pilot produced an unopenable `.docx`: when the LLM dropped a `[CITATION_n]` placeholder in a rewrite, the field-code restore path emitted unbalanced runs → invalid OOXML. How should this be prevented — block the agent from removing citations, or guarantee structural validity regardless?

**Choice:** Guarantee **structure**, do **not** block removal. `_restore_field_codes` now restores each field one placeholder at a time into a candidate and checks `_fragment_runs_balanced`; a balanced candidate keeps the citation as a live field, an unbalanced one degrades the placeholder to its citation **display text** (e.g. `[1]`). Every emitted paragraph is therefore always balanced (any caller). `edit_paragraph` separately reports `removed_citations` for visibility (Layer A) but never rejects; the prompt (Layer C) asks the agent to reproduce placeholders verbatim when the cited material is kept.

**Rationale:** The invariant that matters is "the document always opens," which is structural. A legitimate edit can delete a sentence and its citation, so a hard reject would forbid valid work (project owner's explicit steer, 2026-09-23). The safety net makes *any* edit safe while leaving the agent free to remove citations; the visibility layer surfaces accidental drops for QA without blocking.

**Alternatives considered:** Hard-reject any edit that drops a placeholder (spec's original Layer A) — rejected by the owner as best-being-the-enemy-of-good; explicit-acknowledgment param (agent must name citations it intends to remove) — deferred as a possible tightening if a re-pilot shows accidental drops at a meaningful rate.

**Reversible?** Yes (the safety net is additive; a stricter policy can be layered on top later).

---

### 2026-09-23 — M9e — Dash approach chosen by A/B: keep token protection + numeric-range repair

**Question:** Rewritten paragraphs lost en-dashes in year ranges (`2013–2017` → `2013 2017`). Two candidate fixes: keep the M9d `__UNICODE_*__` token protection, or switch to sending raw dashes plus a control-character sanitizer. Which performs better?

**Choice:** **Keep** the token protection unchanged and add a **narrow numeric-range repair** (restore an en-dash only where the original had one *between digits* and the model rendered `digit␠digit`/`digit-digit`). The raw + control-char-sanitizer path is dropped.

**Rationale:** A live A/B (`gpt-5-mini`, 40 rewrites/condition) settled it empirically: token protection preserved **95%** of dashes (38/40) vs **65%** raw (26/40) — feeding a raw dash was *worse*, and there were **zero** `U+0013` control characters in either condition, so the sanitizer would solve a non-problem. The numeric-range repair targets the pilot's exact complaint and is strictly bounded to digit–digit so it can never alter prose.

**Alternatives considered:** Raw dashes + control-char sanitizer — rejected by the data; broad prose-level dash restoration — rejected as risky (could corrupt legitimate spacing); defer dashes to Stage 2 — rejected (owner wanted it fixed now, and we hold the original text so it is cheap).

**Reversible?** Yes (protection map and repair are independent and narrow).

---

### 2026-09-23 — M9e — Comment replies via an explicit `addresses_thread_id` linkage param

**Question:** The agent addressed comments by editing text only, leaving no reply. It should reply when an edit is *comment-driven*, but not when the edit comes from the user's *direct instruction*. Only the agent knows which driver applies — how is that intent captured and checked?

**Choice:** Add an optional `addresses_thread_id: str | None` to `edit_paragraph`. The agent sets it only for comment-driven edits; the tool validates the thread exists and echoes the linkage into the result and transcript. The prompt policy then asks the agent to also call `add_comment_reply` on that thread (and to leave both unset / not reply for instruction-driven edits).

**Rationale:** An explicit, optional param makes the comment-driven vs instruction-driven distinction machine-checkable and reviewable after the fact, without auto-generating reply text (the wording stays the agent's judgement) or forcing a blocking workflow.

**Alternatives considered:** Always reply after any edit — rejected (spams instruction-driven edits with comments); infer the driver heuristically — rejected (unreliable; only the agent knows intent).

**Reversible?** Yes (optional param + prompt guidance; no schema/state migration).

---

### 2026-09-22 — M9d (pilot) — Per-run agent transcript + wired-up logging (diagnostic)

**Question:** The pilot kept ending with the agent making dozens of tool calls but no edits, and there was no way to see *why*: the M9c-prep per-step `logger.info` lines were silently dropped (nothing ever configured logging), and the in-memory step trace / `chat_turns` only persist on a clean finalize — so a stopped or crashed run left nothing to review. How should the agent's behaviour be made inspectable?

**Choice:** Two-part, taken together (the "Option B" of the two considered):
1. **`src/logging_config.py`** — `configure_logging()` (called once from `main.py`): enable INFO for `src.*` so the per-step lines actually emit, and add a filter that drops the `/agent/progress` poll from the uvicorn access log (it otherwise floods the terminal). Per-step logs were also enriched with a bounded arg summary and each tool's ok/ERROR outcome.
2. **`src/agent/run_transcript.py`** — a `RunTranscript` that writes one **JSONL file per run** under `.stet/runs/`, flushed per event (`run_start` / `assistant` / `tool_result` / `run_end`), with tool args and results size-bounded. The route attaches one per run and writes `run_end` even when the run **crashes** (e.g. `APIConnectionError`) via an `except` around the loop. So a stopped/crashed run is fully reviewable afterwards.

**Rationale:** Logging alone (the "Option A" alternative) surfaces the trace only in the shared server console — interleaved with access-log noise, tied to how the process output is captured, and not organised per run. A dedicated per-run file is self-contained, survives Stop/crash (which is exactly when the finalize-dependent UI trace gives nothing), and can be pointed at directly to answer "what did the agent actually do." The two are complementary: logging for live watching, the transcript for review.

**Alternatives considered:** Option A (enable+enrich logging only) — rejected as the primary, kept as the live-watch layer; reconstruct from `chat_turns` — rejected (only written on finalize, so useless for the failing runs); a structured DB — over-engineered for Stage 1.

**Scope note:** This is diagnostic tooling added mid-M9d-pilot at the project owner's request; it is not part of the M9d spec proper. Recorded in the M9d report's pilot-driven-additions section. Logging must never break a run — all transcript/file errors are swallowed and logged.

**Reversible?** Yes (new isolated modules; `.stet/runs/` is additive and safe to delete).

---

### 2026-09-22 — M9d (pilot) — OpenAI client retries raised from 0 to 3

**Question:** M9c-prep set `_OPENAI_MAX_RETRIES = 0` (to keep Stop responsive). The M9d re-pilot then died on **step 1** twice with `APIConnectionError: Server disconnected without sending a response` — a transient connection drop that, with 0 retries, killed the whole run. Should retries be re-enabled?

**Choice:** Set `_OPENAI_MAX_RETRIES = 3` (was 0), keeping the 120 s per-call timeout. This **supersedes** the M9c-prep 0-retry stance.

**Rationale:** Retries fire only on *failure* (connection drops, 429, 5xx); a normal call is never retried, and the OpenAI SDK's exponential backoff is short, so a Stop during a failing call is delayed by at most a few seconds — a good trade for not losing a multi-minute run to a single blip. Kept as a module constant (matching `_OPENAI_TIMEOUT_SECONDS`), not a config key, to stay minimal; can be promoted to config later if it needs per-workspace tuning.

**Alternatives considered:** Leave at 0 (rejected — makes long runs fragile); the library default of 2 (fine, but 3 gives a little more headroom for a flaky link); make it a config key now (deferred — no demonstrated need to tune per workspace yet). **Caveat recorded:** two rapid step-1 failures on a *small* request may indicate an environmental cause (VPN/proxy, or Python 3.14 + httpx/httpcore) rather than pure OpenAI flakiness; if retries don't clear it, investigate the local network/runtime.

**Reversible?** Yes (a one-line constant).

---

### 2026-09-22 — M9d — Working-model snapshot restored only when the source is unchanged

**Question:** Agent/manual edits lived only in RAM and were lost on any re-parse. How should unsaved edits be made durable without silently writing to the user's `.docx`?

**Choice:** After a mutation, snapshot the live `DocumentModel` (via the existing `to_dict()`) to `.stet/working/<doc-hash>.json` with a `source_mtime` header. `open_document` restores that snapshot **only if** the recorded `source_mtime` still matches the file on disk; a stale, corrupt, or wrong-schema snapshot is ignored (pristine parse) and logged. The user's `.docx` is never written except by explicit Save/export.

**Rationale:** Reuses the lossless serializer checkpoints already use — no new format. The mtime gate means an externally-changed file always wins, so a snapshot can never resurrect edits over newer content or brick a document (same resilience rule as config loading). Keeping writes inside `.stet/` preserves "explicit Save is the only thing that touches the source file."

**Alternatives considered:** Persist the model inside `workspace.json` (rejected — bloats the session file and couples doc state to session state); auto-save into the `.docx` (rejected — silent writes to the user's file).

**Reversible?** Yes (snapshot dir is additive; deleting it just falls back to pristine parse).

---

### 2026-09-22 — M9d — Snapshot lifecycle: same-path Save clears, save-a-copy preserves

**Question:** When should the working snapshot be deleted vs kept?

**Choice:** Clear it after a **same-path** Save (edits are now in the file) and after a checkpoint restore to a clean state (`sync_working_model` clears when `is_dirty` is False). A **save-a-copy** to a different path leaves the original path's snapshot intact.

**Rationale:** The snapshot only represents "unsaved-in-RAM-only" edits. A same-path save makes it redundant (and the file mtime would invalidate it anyway); a copy doesn't change the fact that the original still has unsaved edits until it, too, is saved.

**Alternatives considered:** Always keep the snapshot until explicit discard (rejected — leaves stale snapshots that the mtime gate would ignore anyway, just messier).

**Reversible?** Yes.

---

### 2026-09-22 — M9d — Unicode map parity relaxed to a superset (agent-only dash additions)

**Question:** En/em-dash (and ellipsis, non-breaking hyphen) needed protecting. Add them to both the agent map and the legacy card-UI map, or only the agent map and relax the parity test?

**Choice:** Add them to the **agent** map only (`src/agent/unicode_protection.py`) and relax the M9a parity test from "equal" to "agent map ⊇ card-UI map, differing by exactly the M9d additions." The card-UI map (`src/llm_transport.py`) is left untouched.

**Rationale:** Stage 1 scope discipline says leave the legacy card path untouched. The corruption was observed on the agent path; protecting it there is sufficient and avoids editing the baseline. The count-independent superset assertion won't drift if either map changes later.

**Alternatives considered:** Edit both maps to keep them identical (rejected — unnecessary edit to the legacy baseline); extract a shared map module (rejected — a refactor out of Stage 1 scope).

**Reversible?** Yes.

---

### 2026-09-22 — M9d — Filename tooltip over resizable panel for Stage 1

**Question:** Truncated sidebar filenames hid which document was open. Add a native `title` tooltip or build a resizable/scrolling file panel?

**Choice:** Native `title` tooltips on tree labels for Stage 1 (the user's stated minimum: "hovering brings up the full name"). The resizable/scrolling panel is deferred, not part of M9d.

**Rationale:** The tooltip fully resolves the finding at near-zero cost and risk; a resizable panel is a larger UI change better weighed on its own. Recorded so it isn't mistaken for forgotten.

**Alternatives considered:** Resizable/scrolling panel now (deferred); wrap long labels (rejected — noisier tree).

**Reversible?** Yes (the panel enhancement can still be added later).

---

### 2026-06-10 — M9c-prep — Trim budget as a config key, exposed in the settings UI

**Question:** Should the conversation-trim threshold be a code constant or a `WorkspaceConfig` key, and if a key, does it get a settings-modal control?

**Choice:** `context_token_budget` config key (default 60,000), project-owner decision — context management will likely grow more sophisticated later, and keeping the knob in config is good discipline now. Also exposed in the M9b Workspace settings block (one number input), so it does not recreate the M7 "config key with no UI" gap that M9b existed to close.

**Rationale:** The spec left this open; the owner resolved it toward config. The UI control is six lines on top of the M9b machinery, versus reintroducing a hand-edit-only key.

**Alternatives considered:** Code constant (spec's original lean) — rejected by owner; config key without UI — rejected as repeating the M7 gap.

**Reversible?** Yes.

### 2026-06-10 — M9c-prep — Intra-step cancel appends stub tool results for skipped calls

**Question:** When Stop bites between tool calls of one step, the assistant message already references the remaining (unexecuted) tool calls. Leave them dangling or synthesize results?

**Choice:** Append a stub tool message (`{"error": "cancelled", "message": …}`) for each skipped call before returning `status="cancelled"`.

**Rationale:** The conversation is persisted and continued on the next turn, and OpenAI rejects histories where a `tool_call` id has no matching tool message. Without stubs, every cancelled-mid-step run would poison the workspace conversation. This is required correctness for the spec's intra-step cancel, not an embellishment.

**Alternatives considered:** Dropping the assistant message's unexecuted tool calls — rewrites what the model actually said; cancelling only between steps — the M7 status quo the spec set out to fix.

**Reversible?** Yes.

### 2026-06-10 — M9c-prep — Trim operates on the provider-bound copy only

**Question:** Should context trimming mutate the session's stored conversation or only the payload sent to the provider?

**Choice:** Provider-bound copy only, inside `AgentLLMClient.complete()` — the same boundary where M9a Unicode protection lives. The persisted conversation always keeps full tool results.

**Rationale:** Keeps trimming a transport concern with zero data loss; the budget can be raised later and old results are still there. Mirrors the established protect/restore pattern so there is one place where "what the model sees" diverges from "what we store".

**Alternatives considered:** Trimming the stored history (smaller `workspace.json`, but irreversible data loss); trimming in the loop (would entangle loop logic with provider payload concerns).

**Reversible?** Yes.

### 2026-06-08 — Milestone 9b — Workspace config controls disabled-with-note; failed PUT aborts close

**Question:** In the settings modal, how should the per-workspace config controls behave when no folder is open, and what happens if saving the config fails while LLM credentials save fine?

**Choice:** When no workspace is open, the four controls are **disabled (greyed) with a note** ("Open a folder to edit workspace settings."), not hidden — so the available knobs stay visible. LLM credentials always save to `localStorage`; if a workspace is open, the config is `PUT` separately. A failed config `PUT` shows an error toast and **keeps the modal open**; the already-saved credentials are not rolled back.

**Rationale:** The two settings scopes are independent (credentials = global `localStorage`; workspace config = per-folder `.stet/config.json`), so a config-save failure should not discard a credential change, and keeping the modal open lets the user retry. Disabling-with-note matches spec §5.3 and is clearer than hiding.

**Alternatives considered:** Hide the controls without a workspace — rejected (less discoverable). Roll back credential save on config failure — rejected (different scopes; would surprise the user).

**Reversible?** Yes (UI-only).

---

### 2026-06-08 — Milestone 9a — Net-zero edits render nothing (correct); do not restrict edit count

**Question:** A QA run showed the agent making two `edit_paragraph` calls on one paragraph (a rephrase, then a "fix-up pass" that restored the original wording), after which nothing showed in the viewer or Word. Is this a bug, and should the agent be limited to one edit per paragraph?

**Choice:** No code change. An A→B→A edit correctly renders nothing — there is no net change to show or serialize (confirmed by repro: `render.py::_render_pending_revision_diff` baselines on the earliest pending deletion, so `original == revised` at net-zero). The agent is **not** restricted to one edit per paragraph; making several edits in a turn is expected and allowed. The only fix is clearer token guidance (separate entry) so the agent does not feel the need for a corrective revert.

**Rationale (project-owner directed):** (1) If the agent revises A→B→A, showing no change is the desired behaviour. (2) Agents may legitimately make a change and then make another — multiple edits per paragraph must be allowed. An earlier over-correction (a prompt rule forcing a single edit per paragraph) was added and then removed on this feedback.

**Alternatives considered:** Prompt rule forbidding a second edit / re-edit to original — rejected (too restrictive; net-zero is correct). Renderer change to surface stale net-zero revisions — rejected (would show a non-change as a change).

**Reversible?** N/A (no change retained).

---

### 2026-06-08 — Milestone 9a — Prompt safeguard so the agent retains `__UNICODE_*__` tokens when paraphrasing

**Question:** QA showed the agent dropping a `≥` when *paraphrasing* a paragraph (not garbling it). The silent placeholder swap stops corruption but leaves the model with an opaque token it can discard during a rewrite. How to make special symbols survive edits?

**Choice:** Add a line to `AGENT_SYSTEM_PROMPT` telling the model that `__UNICODE_*__` tokens each represent one real symbol (named in words — e.g. "`__UNICODE_GTE__` is the greater-than-or-equal sign") and must be kept exactly, never deleted/translated/reworded. Symbols are described in words rather than printed literally, because a literal symbol in the prompt is itself protected before sending (making the guidance circular). Mirrors the card UI's explicit handling of `[CITATION_X]` tokens.

**Rationale:** Proportionate Stage 1 fix: a one-line prompt change strongly nudges retention without new code paths. The placeholder map already prevents corruption; this addresses retention during free rewrites.

**Alternatives considered:** A hard guarantee (diff protected tokens before/after an edit and reject/repair edits that drop one) — deferred as larger; logged in the M9a report as future hardening if QA still shows drops. Revealing the literal symbols in the prompt — rejected (they get protected, defeating the purpose). Telling the model the actual `≥` via an un-protected channel — rejected (reintroduces corruption risk if it then types the raw symbol).

**Reversible?** Yes (prompt-only).

---

### 2026-06-03 — Milestone 9a — Agent Unicode map copied verbatim, not extracted to a shared module

**Question:** The card UI and the agent path both need the special-Unicode placeholder map. Share one module, or duplicate the map into the agent path?

**Choice:** Copy the 34-entry `UNICODE_PROTECTION_MAP` verbatim into `src/agent/unicode_protection.py`. Do not refactor a shared module out of `src/llm_transport.py`.

**Rationale:** Extracting a shared module would edit the card-UI baseline (`LLMTransportMixin`), which Stage 1 scope forbids touching. The duplication is small, stable, and guarded: `test_agent_unicode.py::test_map_matches_card_ui_verbatim` asserts the two maps stay equal, so drift fails the suite. A shared-module extraction can be a post-Stage-1 cleanup.

**Alternatives considered:** Import the card-UI map directly from `llm_transport` — rejected (couples the agent transport to the card-UI class and its imports). Extract a neutral shared module now — rejected (edits the card path; out of scope).

**Reversible?** Yes (the parity test makes a later extraction safe).

---

### 2026-06-03 — Milestone 9a — Unicode protection always-on, applied to provider-bound copies only

**Question:** Should agent Unicode protection have a config flag, and where in the message lifecycle should it apply?

**Choice:** Always-on (no flag), mirroring the card UI. Protect/restore only the **copies** of messages sent to / received from the provider, inside `AgentLLMClient`. The persisted `Message` history and the workspace turn log keep real Unicode.

**Rationale:** The corruption it prevents is never desirable, so a flag adds surface for no benefit. Keeping placeholders out of the persisted history means stored conversations stay human-readable and re-protection on each turn is idempotent.

**Alternatives considered:** A `WorkspaceConfig` toggle — rejected (no use case for disabling). Storing placeholdered messages in history — rejected (leaks an internal transport detail into persistence and the UI).

**Reversible?** Yes (localized to `AgentLLMClient`).

---

### 2026-06-02 — Milestone 8 — PPTX title matched by shape id, not object identity

**Question:** When excluding the title shape from a slide's body text, why did the title appear duplicated in `body_text`?

**Choice:** Compare `shape.shape_id == title_shape.shape_id` rather than `shape is title_shape`.

**Rationale:** `python-pptx` constructs a fresh wrapper object on every attribute access, so `slide.shapes.title` and the shape yielded while iterating `slide.shapes` are different Python objects for the same underlying XML — `is` identity never matches and the title leaked into the body. `shape_id` is the stable per-slide identifier. (Found during implementation verification, not in the spec.)

**Alternatives considered:** Compare by text equality — rejected (a body shape could legitimately repeat the title text). Compare by placeholder type — more brittle across layouts.

**Reversible?** Yes (internal to `_extract_slide`).

---

### 2026-06-02 — Milestone 8 — Plain text handled inline; RTF/PPTX get dedicated parsers

**Question:** Should plain text, RTF, and PPTX each get a parser class, or share handling?

**Choice:** `.txt`/`.md` are read **inline** in `read_file` (passthrough + encoding fallback + 200k truncation); RTF and PPTX get dedicated parser classes mirroring the existing `…ParseResult` + `to_markdown()` + `error` contract. RTF is **not** treated as plain text (it has its own `RtfParser` via `striprtf`).

**Rationale:** A text passthrough does not warrant a class; RTF and PPTX need real extraction logic and benefit from isolated unit tests, matching PDF/spreadsheet/docx.

**Alternatives considered:** A `TextParser` class for symmetry — rejected as overkill. Treating `.rtf` as text — rejected (control-word soup needs `striprtf`).

**Reversible?** Yes.

---

### 2026-06-01 — Milestone 7 — Workspace-scoped chat history; no reset on document open/close

**Question:** Should switching or closing documents within a workspace clear the chat panel?

**Choice:** **Keep history** — one chat per workspace. Remove M5 `resetChat()` from document open/close; reload from `GET …/chat` on workspace open.

**Rationale:** Aligns with the architecture decision (workspace-scoped agent context). The server already persisted `conversation`; wiping the UI on every doc switch was a bug.

**Alternatives considered:** Per-document chat tabs — deferred (out of scope).

**Reversible?** Yes.

---

### 2026-06-01 — Milestone 7 — `chat_turns` at schema v1; separate from LLM `conversation`

**Question:** How should the UI rebuild chat after restart without dumping raw tool messages?

**Choice:** Add optional `chat_turns: ChatTurn[]` to `.stet/workspace.json` at **`schema_version: 1`** (missing key → `[]`). Keep `conversation` for LLM context.

**Rationale:** Backward-compatible additive field; avoids a migration runner for a dev-stage feature (same pattern as M4 `conversation`).

**Alternatives considered:** Schema v2 bump — rejected as unnecessary.

**Reversible?** Yes.

---

### 2026-06-01 — Milestone 7 — Between-step cancel only; mid-LLM abort deferred

**Question:** How should cancel work given the sync agent loop and blocking LLM HTTP calls?

**Choice:** Poll `cancel_check` at the **start of each loop iteration**; run the loop in `asyncio.to_thread`. **Do not** abort in-flight provider requests until streaming exists.

**Rationale:** Avoids deadlocking the event loop without request-level abort support. Acceptable for Stage 1; noted in spec §9 and M7 report.

**Alternatives considered:** Immediate HTTP abort — requires streaming or client changes; deferred.

**Reversible?** Yes (extend when streaming lands).

---

### 2026-06-01 — Milestone 6b — Standalone `doc_editor.js`; no card UI refactor

**Question:** Where should the workspace paragraph editor live, given decision 4 (do not refactor the card UI onto a shared module)?

**Choice:** New **`static/js/doc_editor.js`**, loaded as an ES module from standalone `workspace.html`. Exposes `createParagraphEditor(elementId, initialHtml, { onSave, onCancel })` with the same TipTap capabilities as the card UI (bold/italic/underline/superscript/subscript) but **no** session/thread/card globals.

**Rationale:** `/workspace` does not extend `base.html`; keeping the card editor untouched avoids maintaining obsolete UI. Duplicating the small TipTap bootstrap is cheaper than abstracting both UIs prematurely.

**Reversible?** Yes (could extract a shared module later if a third consumer appears).

---

### 2026-06-01 — Milestone 6b — Pre-edit checkpoint on manual `PATCH /document/paragraph`

**Question:** Should a manual paragraph save snapshot before applying the edit (decision 6 from the M6 umbrella)?

**Choice:** **Yes** — `session.checkpoint_store.save(session.document, label=f"before manual edit {para_id}")` runs immediately before `edit_paragraph`. Existing `/checkpoints` + `/checkpoint/restore` cover undo; no new UI surface in M6b.

**Rationale:** Manual and agent edits share one undo model; mirrors the agent loop's pre-mutation checkpoints.

**Reversible?** Yes.

---

### 2026-06-01 — Milestone 6b — RevisionStore diff overlay in `render_document` for in-session edits

**Question:** M6a noted that `edit_paragraph` records pending insertions/deletions in `RevisionStore` while rewriting runs to the result text, so run markup alone cannot show in-session track changes. How should M6b display manual edits as coloured tracked changes?

**Choice:** Extend **`src/workspace/render.py`**: when a paragraph has pending deletions in `RevisionStore`, diff the earliest deletion baseline against current `plain_text` and emit `<ins class="diff-insert">` / `<del class="diff-delete">` (reusing M6a CSS). Parsed `<w:ins>`/`<w:del>` runs still render via run markup as before.

**Rationale:** Minimal, testable change confined to the viewer renderer; avoids rewriting `apply_edit` run structure. Comment re-segmentation on diff HTML is best-effort (unchanged for edited paragraphs with anchors).

**Reversible?** Yes.

---

### 2026-06-01 — Milestone 6a (follow-up) — Parser captures `<w:delText>` so tracked deletions render

**Question:** Manual QA of the M6a viewer found tracked **deletions** never appeared (insertions were green). Why, and where is the fix?

**Choice:** Fix the **parser**, not the renderer. `_parse_run` now reads text from `<w:delText>` in addition to `<w:t>`. The `<w:del>` branch already tagged runs `RevisionType.DELETION` and (correctly) didn't advance the offset, but Word stores deleted text in `<w:delText>`, so deleted runs parsed empty and were dropped (`_parse_run` returns `None` on empty text). With the text captured, deleted runs reach the model and the existing renderer shows them as `<del class="diff-delete">` (struck through). Did **not** touch the renderer (it already handled `is_deleted()` runs) or the serializer.

**Rationale:** The model was simply missing the data — a parser gap, dormant because nothing previously needed deleted text in the model. The fix is safe by construction: `plain_text`/`raw_text` and all offset math already exclude deleted runs (comment anchors unaffected), and the serializer's regeneration path (`_build_runs_xml_from_model`) skips deleted runs and only emits `<w:t>`, while unmodified paragraphs keep their original `<w:del>` XML verbatim — so round-tripping is unchanged (full serializer suite green).

**Alternatives considered:** Render deletions from the `RevisionStore` instead — rejected for parsed deletions (the store isn't populated by the parser; the runs are the natural carrier and the renderer already supports them). Capturing `<w:delText>` is the minimal correct fix.

**Scope note (→ M6b):** *in-session* edits (`edit_paragraph`/REPLACE) record insertions/deletions in the `RevisionStore` and rewrite runs without `INSERTION`/`DELETION` marks, so they render as their result rather than as coloured tracked changes. Surfacing in-session edits as tracked changes is deferred to M6b (edit mode), where it is the natural place to decide how viewer edits appear.

**Reversible?** Yes (additive text capture in one parser method).

---

### 2026-06-01 — Milestone 6a — Pure `render_document` block model; `GET /document` returns `blocks`

**Question:** The M5 viewer concatenated each paragraph's `to_display_html()` with no separator (so paragraphs ran together) and used a renderer that drops deleted runs, doesn't mark inserted runs, and ignores comments. Where should the faithful renderer live, and what shape should the API return?

**Choice:** A new **pure** module `src/workspace/render.py` exposes `render_document(model) -> list[Block]`, where each `Block` is `{kind: "paragraph"|"table_row", para_id, html, text, style, comment_ids, cells?}`. `GET /api/workspace/{id}/document` now returns `{document, blocks, comments}` — the flat `paragraphs` array is **replaced** by `blocks`. The renderer takes no session/I/O and is unit-tested directly against `DocumentModel` fixtures. The card UI is **not** refactored onto it (it is being retired).

**Rationale:** A pure model→blocks function keeps HTML generation server-side and testable (consistent with `src/diff_html.py`), and is trivially movable later. Returning ordered blocks (one per paragraph / table row) lets the client wrap each in its own block element, which fixes the dominant "everything on one line" finding. Reusing the card UI's `diff-insert`/`diff-delete` CSS classes keeps the visual language consistent without sharing the (diff-based, different-purpose) card renderer.

**Alternatives considered:** Keep `paragraphs` and add `blocks` alongside — rejected as redundant payload; the two API tests that read paragraph text were updated to read `blocks`. Render client-side from the model — rejected (no model on the client; server rendering is already the codebase pattern).

**Reversible?** Yes (the renderer is additive; the payload key is internal to the workspace API + its own tests).

---

### 2026-06-01 — Milestone 6a — Comments as inline highlights + side list; overlap/cross-paragraph via boundary segmentation

**Question:** How should anchored comments render — inline, in the margin, or a side panel — and how should overlapping and cross-paragraph anchors be handled without emitting illegal overlapping HTML tags?

**Choice:** Anchored ranges are highlighted **inline** by wrapping covered text in `<span class="ws-comment-ref" data-comment-ids="…">`, and each thread is listed as a card in a right-hand **comments rail** inside the document area, ordered by anchor position, with **click-linking** both ways (card→anchor scrolls+flashes the highlight; span→card flashes the card). Overlap/nesting is handled by **boundary segmentation**: the renderer splits each run at the sorted set of comment-interval boundaries and tags each segment with the space-joined ids of all comments covering it (so a region under two comments becomes one span with two ids — no overlapping tags). Cross-paragraph anchors (`end_para_id`) contribute a head to the start paragraph, a tail to the end paragraph, and full coverage to any paragraphs strictly between. Resolved vs open threads get distinct styling (the client mutes a span whose covering threads are all resolved). **Word-style aligned margin balloons + leader lines are deferred to Stage 3.**

**Rationale:** The project owner asked for a Word-like side list and for overlaps to be done "properly." Segmentation is the standard, correct way to render arbitrary overlapping ranges as flat HTML. A side list keyed by `thread_id` (== root comment id == `anchor.comment_id`) needs no new identifiers and reuses the `list_comments` thread shape. Pixel-perfect vertical alignment is a layout problem disproportionate to Stage 1's value, so it is explicitly Stage 3.

**Alternatives considered:** Nested `<span>`s per comment — rejected (illegal overlapping markup). Margin balloons now — deferred (Stage 3). Distinguishing resolved status server-side per segment — deferred to the client, which already has thread status.

**Reversible?** Yes (rendering + CSS only; the comments rail is self-contained).

---

### 2026-06-01 — Milestone 6a — Soft breaks (`<w:br/>`) not preserved; rendering deferred

**Question:** Manual testing flagged that some in-paragraph line breaks were lost. Should M6a render Word soft breaks (`<w:br/>`, i.e. Shift+Enter)?

**Choice:** No — deferred. The parser captures only `<w:t>` text and discards `<w:br/>`, so soft breaks are absent from the `DocumentModel`; the renderer cannot show what isn't parsed. The dominant "merged lines" symptom was actually **separate paragraphs** run together (fixed by block separation). The renderer *does* defensively render any newline already present in run text as `<br>`. True `<w:br/>` support needs coordinated **parser + serializer** changes (represent the break as a structural token and round-trip it back to `<w:br/>`, not a literal newline in `<w:t>`), plus care for offset/anchor math.

**Rationale:** Block separation resolves the visible problem the owner described. Faithfully round-tripping `<w:br/>` is a model/serializer change with real risk to the existing serializer suite and comment-offset arithmetic; it doesn't belong in a viewer milestone. The owner is comfortable postponing the harder display fidelity items.

**Alternatives considered:** Store `<w:br/>` as `\n` in run text now — rejected (the serializer would write a literal newline into `<w:t>`, which Word does not treat as a line break, harming round-trip fidelity). 

**Reversible?** Yes (a future parser/serializer milestone can add structural soft-break support; the renderer already maps `\n`→`<br>`).

---

### 2026-05-31 — Milestone 5 (follow-up) — Guard document switching against unsaved edits

**Question:** Manual testing found that opening another document (the only way to "leave" the current one — there is no explicit close action in the M5 UI yet) silently re-parsed it from disk and discarded the in-memory edits, with no warning. `POST /document/open` had no unsaved-changes guard, unlike `POST /close`. How should switching behave?

**Choice:** Mirror the `/close` contract on `document/open`: add `force: bool = False`; if the currently open document `is_dirty` and `force` is false, return **409 `unsaved_changes`**. The workspace UI catches the 409 and shows a confirm ("…has unsaved changes that will be lost… open anyway?"); on confirm it retries with `force=true`, otherwise it keeps the current document highlighted. The guard fires for any open while dirty (switching to a different file *or* re-opening the same one), since both re-parse and lose edits. Auto-reopen on workspace open is unaffected (it calls the session method directly with a freshly-parsed, clean model).

**Rationale:** Keeps "pristine re-open" (the M4 decision) while honoring the project owner's requirement that closing/leaving an unsaved document warns first — consistent with the card UI. Reusing the `/close` pattern (409 + `force`) makes the backend the single source of truth and keeps it unit-testable; the UI stays a thin reactor.

**Alternatives considered:** Frontend-only confirm (no backend guard) — rejected as not enforceable or testable. Persist the working model so switching is non-destructive — that is the deferred "durable working copies" idea (M4 decision), out of scope here.

**Reversible?** Yes (additive `force` flag; default preserves the guard).

**Follow-up (same day):** added an explicit **Close** document action — `POST /document/close` (`WorkspaceSession.close_document()`) clears the active document while the workspace stays open, reusing the identical `{force}` + 409 guard; the header gained a Close button. This resolves the "switching is the only exit" gap noted here.

---

### 2026-05-31 — Milestone 5 (follow-up) — Add `find_in_document` so the agent can locate a paragraph by text

**Question:** Manual testing surfaced that when the user pastes a sentence and says "edit this," the agent cannot apply the edit — it has no way to map sentence text to a `para_id`. The read tools are `read_document` (summary only — no body, no ids), `read_paragraph` (needs a `para_id` already), and `list_comments` (threads only). The agent guessed a `para_id` and `edit_paragraph` returned `not_found` twice. How should the agent discover paragraph ids?

**Choice:** Add a document-bound, non-mutating `find_in_document(query, max_results=10)` tool returning `{query, matches:[{para_id, text, style}], count, truncated}`. Matching is **case-insensitive and whitespace-normalized** (collapse whitespace runs + lowercase) substring search over `Paragraph.plain_text`, in document order. The system prompt now instructs the model to call `find_in_document` (not guess) before `edit_paragraph`.

**Rationale:** A search tool scales to long documents (returns only matches, capped by `max_results`) and directly serves the dominant "edit this pasted sentence" workflow, where the query is verbatim from the document — so a normalized substring match is reliable. The M5 `GET /document` route already exposes paragraph ids+text to the *UI*, but the agent loop's tool surface did not; this closes that gap on the agent side. Chose search over a full `get_paragraphs` dump (which could be large) for the primary fix; a paginated browse tool can still be added later if needed.

**Alternatives considered:** Extend `read_document` to return the full body (every paragraph) — rejected as the primary fix (unbounded payload on long docs); still viable as a future paginated `get_paragraphs`. Fuzzy/token-overlap matching — deferred; normalized substring covers the verbatim-paste case without false positives.

**Reversible?** Yes (additive tool + schema + one prompt line; no change to existing tools).

---

### 2026-05-31 — Milestone 5 (follow-up) — Render tool errors by message, not the raw object

**Question:** During the same test the chat step list showed `✗ [object Object]` instead of a readable error. Tool errors cross the API as a structured object (`{error: code, message}`); `workspace.js` was stringifying the whole object.

**Choice:** Add an `errorText(err)` helper in `workspace.js` that extracts `err.message` (then `err.error`, then a JSON fallback) and use it wherever a tool error is shown. Now a failed step reads e.g. "✗ Paragraph not found: …".

**Rationale:** The information was already present and correct in the response; only the client rendering was wrong. Showing the human-readable message makes failures self-explanatory (had it been rendered, the missing-`para_id` cause would have been obvious immediately).

**Reversible?** Yes (display-only helper).

---

### 2026-05-30 — Milestone 5 — `pick_folder` returns a bare path string, not a result dict

**Question:** The M5 spec sketched `Api.pick_folder() -> dict` (`{success, path, error}`, mirroring `save_export`). What does the implementation return?

**Choice:** `pick_folder()` returns the chosen absolute folder path as a **plain `str`**, or `None` on cancel/error/unavailable. The frontend treats a falsy result as "no selection" and, when `window.pywebview` is absent entirely, falls back to a path text input.

**Rationale:** A folder pick has no copy/IO side effect to report (unlike `save_export`, which copies a file and can fail mid-operation), so the richer result envelope adds no value. A `str | None` is the simplest contract the JS needs, and "cancelled" and "error" both collapse to "user must pick again."

**Alternatives considered:** Match `save_export`'s dict shape for consistency — rejected; the extra structure is unused and the JS would just read `.path` anyway.

**Reversible?** Yes (single method + its one JS caller).

---

### 2026-05-30 — Milestone 5 — `/workspace` is a standalone page; overwrite confirm uses native `confirm()`

**Question:** Should the workspace page extend `base.html`, and how should the "always ask before overwriting" guard prompt in the UI?

**Choice:** `/workspace` is a **standalone** template (its own `<html>`, Tailwind CDN + `static/css/workspace.css` + `static/js/workspace.js`), not a `base.html` extension. Save-over-existing uses a blocking `window.confirm()`; "Save a copy" and the folder-picker fallback use a small in-app prompt modal. Document rendering is read-only via `Paragraph.to_display_html()`.

**Rationale:** `base.html`'s header/Export/settings are card-session-specific and its `<main>` is centered `max-w-7xl` — a poor fit for a full-bleed three-panel app (already noted in the spec). `window.confirm()` is the lightest native-feeling yes/no for the overwrite guard and works identically in the browser and pywebview; the richer prompt modal is reserved for free-text input (copy filename, folder path).

**Alternatives considered:** Force-fit `base.html` — rejected (layout mismatch). A bespoke confirm modal for overwrite — deferred; `confirm()` is sufficient for Stage 1.

**Reversible?** Yes (page is self-contained; modals can be upgraded in M6/M7).

---

### 2026-05-30 — Milestone 4 — Workspace sessions are a parallel system, keyed by id

**Question:** How does the workspace backend relate to the legacy upload `sessions` dict, and should it hold one or many open folders?

**Choice:** A new in-memory `WorkspaceSession` registry (`src/workspace/state.py`), keyed by an opaque `workspace_id`, running **parallel** to the untouched legacy `sessions` dict. It can hold multiple open workspaces at once (always one agent per workspace). A workspace is one granted folder; its arbitrary nested subfolders are already walked recursively (`list_workspace_files`) and reachable via contained path resolution.

**Rationale:** Keying by id is nearly free and lets project-switching land later without a rewrite; the M5 UI uses one at a time. Keeping the card UI's `sessions` untouched preserves the regression baseline (it is the long-term replacement target, not an M4 migration).

**Alternatives considered:** Single global active workspace (simpler routes, no id) — rejected as a needless future rewrite. Migrate the card UI now — out of scope.

**Reversible?** Yes (additive registry; nothing else depends on it).

---

### 2026-05-30 — Milestone 4 — Only conversation + open-doc pointer persist; pristine re-open

**Question:** What survives a server restart — just the conversation, or the in-progress (unsaved) document too?

**Choice:** `.stet/workspace.json` persists `{schema_version, open_document, conversation, updated_at}` only. The in-memory `DocumentModel` (with unsaved edits) is not durable; re-opening parses the pristine file. The loop owns the system prompt, so `conversation` is stored **without** it. The backend exposes `unsaved_changes` (`is_dirty`) and `/close` returns `409` unless `force=true`; the actual close warning is the M5 UI's job.

**Rationale:** Durable working copies add real complexity; checkpoints already capture within-session states. Storing conversation without the system message avoids double-prepending it on the next run.

**Alternatives considered:** Persist the working model / auto-checkpoint on shutdown — deferred. Store the system message too — rejected (would duplicate on reload).

**Reversible?** Yes (schema is versioned; durable working copies can be added later).

---

### 2026-05-30 — Milestone 4 — Path resolution via declarative `path_args`, reads contained

**Question:** `read_document` / `read_file` take a bare `path` (no workspace_root), so LLM-supplied relative paths would resolve against the process CWD. How to fix without entangling the loop with workspace internals?

**Choice:** Add `path_args: tuple[str,...]` to `ToolSpec` (`("path",)` for the two read tools). The loop resolves those against `workspace_root` (contained to it via the shared `tools.resolve_in_workspace`) inside the tool-call try/except, so an out-of-workspace path surfaces as a normal `ToolError`. Writers already resolve + contain internally, so they have no `path_args`.

**Rationale:** Mirrors the `mutating` flag — declarative, lives in the registry, keeps the loop generic. Resolving inside the try means containment failures follow the same error policy as any tool error. Sharing `resolve_in_workspace` (extracted from `_guard_write_target`) keeps one resolver.

**Alternatives considered:** Resolve only in the route layer — rejected; loop-driven reads would stay CWD-relative. Let reads escape the workspace — rejected for safety in Stage 1.

**Reversible?** Yes (additive field, default `()`).

---

### 2026-05-30 — Milestone 4 — "Save" replaces "export"; save-as-copy switches the active document

**Question:** What is the contract for saving, and how does "save a copy" behave?

**Choice:** One `save` operation (no separate "export"): serialize the current model (via `export_document`) to a target path. No `path` → the open document's own path (exists → overwrite guard → confirm with `overwrite=true`). New `path` → written directly (original untouched). After any successful save, mark the model clean and **switch the active document to the saved path** (Word-like "Save As"). Agent-driven exports during a run get the same treatment in `_finalize`.

**Rationale:** It is the same M2 mechanism with a different destination — zero new serialization work. Switching the active document on save-as-copy matches user expectation (continue editing the copy). Defaulting in-place save to the existing path naturally triggers the "always ask before overwriting" guard.

**Alternatives considered:** Keep editing the original after a copy (copy is a frozen snapshot) — rejected as less intuitive. Separate save/export verbs — rejected; no real difference at this stage, and "export" confuses users.

**Reversible?** Yes (endpoint-level behavior).

---

### 2026-05-30 — Milestone 3 — Standalone tool-calling client, untouched legacy stack

**Question:** The agent loop needs a tool-calling LLM client. Extend the existing `LLMTransportMixin` (card-UI path), or build a new one?

**Choice:** New standalone `AgentLLMClient` in `src/agent/llm_tools.py`. It reuses `src/llm_config` only for provider/model/url defaults and builds its own provider client; `LLMHandler` and `src/llm_transport.py` are untouched.

**Rationale:** The card-UI suggestion/chat path is the regression baseline (633 existing tests). Tool-calling is a different request shape (tools, tool_choice, tool-result messages). Keeping it in a separate module isolates risk and keeps each path readable.

**Alternatives considered:** Add `_call_*_with_tools` to the mixin — rejected; entangles two response-handling regimes in the hot card-UI path.

**Reversible?** Yes (the client is additive; nothing depends on it yet outside M3 tests).

---

### 2026-05-30 — Milestone 3 — Ollama tool-calling confirmed on the existing local model

**Question:** Does tool-calling require a new local model, or does the already-downloaded `llama3.1` work?

**Choice:** Use the existing `llama3.1:latest` via Ollama `/api/chat` with `tools=…`. Verified live (Ollama 0.24.0): a single call returned a correct structured `tool_calls` response, and a full loop round-trip (`list_comments` → tool result → summary) completed successfully. No new model needed.

**Rationale:** Avoids a multi-GB download and keeps the local provider working out of the box. Llama 3.1 8B tool selection is "Good" (less reliable than OpenAI on long chains), so the deterministic loop tests use a mock and the live Ollama test is opt-in (`RUN_OLLAMA_TESTS=1`), tolerating transient cold-load hiccups by skipping.

**Alternatives considered:** Ship OpenAI-only and add Ollama later — unnecessary once the live check passed; the provider-neutral seam made dual support nearly free. Download `qwen2.5` for more reliable local tool use — deferred; not needed for M3.

**Reversible?** Yes (provider/model are constructor args).

---

### 2026-05-30 — Milestone 3 — `mutating` flag on `ToolSpec`

**Question:** The `per_mutating_tool` checkpoint policy needs to know which tools change the document. How is that expressed?

**Choice:** Add a `mutating: bool` field to `ToolSpec` (default `False`); flag `edit_paragraph`, `add_comment_reply`, `add_comment`, `remove_comment`. The guarded file writers (`create_document`, `export_document`) are deliberately **not** mutating — they write files, and a model snapshot would not undo a file write.

**Rationale:** A declarative per-tool flag keeps the policy logic trivial (`if spec.mutating: checkpoint`) and lives next to the other injection metadata. Treating file writers as mutating would create misleading checkpoints that cannot actually roll back the side effect.

**Alternatives considered:** Hard-code a mutating-tool name set in the loop — rejected; drifts from the registry. Infer from `requires_model` — wrong (read tools also require the model).

**Reversible?** Yes (additive field with a safe default).

---

### 2026-05-30 — Milestone 3 — Overwrite confirmation pauses the loop (no auto-confirm)

**Question:** When a guarded writer raises `overwrite_requires_confirmation` mid-loop, what should the loop do?

**Choice:** Pause and return `status="awaiting_confirmation"` with a `PendingConfirmation`. The caller decides; `resume(pending, confirmed, history)` either re-issues the write with `overwrite=True` (on confirm) or appends a decline note, then continues the loop. The loop never sets `overwrite=True` on its own. To keep the provider message list valid, the confirmation tool-call still receives a tool-result message (the error payload) before the pause.

**Rationale:** Matches the project-owner decision that Stet always asks before overwriting. Surfacing the decision to the caller (and ultimately the user) keeps the agent from silently clobbering files.

**Alternatives considered:** Auto-retry with `overwrite=True` — rejected; defeats the guard. Abort the whole turn — rejected; loses the in-progress work and conversation.

**Reversible?** Yes (policy lives entirely in the loop).

---

### 2026-05-30 — Milestone 3 — Loop is stateless per call; conversation returned, not persisted

**Question:** Should the M3 loop own conversation persistence and path resolution?

**Choice:** No. `run()` takes optional prior `history` and returns the full `messages` list for the caller to persist; the loop prepends its own system prompt each call. LLM-supplied `path` arguments are passed through unresolved. Both persistence and workspace-relative path resolution are M4 (workspace session).

**Rationale:** Keeps M3 a pure, mock-testable engine with no I/O ownership creep. M4 (workspace session) is the right home for path↔model mapping and conversation storage.

**Alternatives considered:** Persist into `.stet/workspace.json` now — rejected; the session schema is an M4 deliverable.

**Reversible?** Yes (the loop already returns everything M4 needs to persist).

---

### 2026-05-29 — Milestone 2 (follow-up) — Shared run-splitter bug fixed; comment anchoring delegates to it

**Question:** During M2 the shared `_split_run_and_insert` (revisions mixin) was found to emit invalid XML on a mid-run split — dropping the closing `</w:t>` and the run's `<w:rPr>`. M2 worked around it with a local splitter in `serializer_comments.py` and reported the bug. With project-owner approval (before M3), fix the shared helper?

**Choice:** Fixed `_split_run_and_insert` to replicate the run opening + `<w:rPr>` on both halves and keep `<w:t>` balanced (with `xml:space="preserve"`), plus a well-formed fallback for runs without a `<w:t>`. Removed the now-redundant local splitter (`_insert_marker_at_offset` / `_split_run_with_marker`) from `serializer_comments.py`; `_inject_root_anchor` now delegates to `_insert_at_offset` — the spec's original intent.

**Rationale:** The helper is only reached via `_insert_at_offset` for tracked **insertions** at a mid-run offset — a latent path the revisions suite did not exercise, so the bug was dormant rather than active. Fixing it once removes the duplication and benefits both the revisions and comment paths. Added direct regression tests (`tests/test_serializer.py::TestInsertAtOffsetRunSplit`) locking in well-formedness, rPr preservation on both halves, and the no-`<w:t>` fallback. Full suite stays green (607 passed, 0 warnings).

**Alternatives considered:** Keep two splitters (the M2 state) — rejected as needless duplication once the shared one is correct.

**Reversible?** Yes.

---

### 2026-05-29 — Milestone 2 — Comment removal is diffed at serialize time

**Question:** `remove_comment` drops a comment from the in-memory model, but the source DOCX parts still contain it. How/when are the five comment parts (document.xml anchors + comments/Extended/Ids/Extensible) stripped?

**Choice:** At serialize time, `_compute_removed_comments` diffs the ids present in the source `comments.xml` against `model.comments`, then recovers each removed comment's paraId (from comments.xml) and durableId (from commentsIds.xml). Each part's serializer strips its own entries by the appropriate key (comment id / paraId / durableId).

**Rationale:** The serializer already *adds* new comments by patching the original parts; mirroring that with a *strip* pass keeps all comment-XML logic in one place and needs no extra state on the model (removed comments are simply absent). Recovering paraId/durableId from the source parts means the model doesn't have to retain tombstones.

**Alternatives considered:** Track tombstones (removed ids + their paraId/durableId) on the model — rejected as extra mutable state for no benefit; the source parts already hold the mapping.

**Reversible?** Yes.

---

### 2026-05-29 — Milestone 2 — `CheckpointMetadata` carries a `sequence` field

**Question:** The spec's `CheckpointMetadata` had `checkpoint_id`, `created_at`, `label`. FIFO ordering by `created_at` can tie for snapshots taken in the same microsecond (rapid agent turns / tests). How is newest-first ordering made deterministic?

**Choice:** Added an integer `sequence` to `CheckpointMetadata` (next = max existing + 1, computed from files on disk). `list()` sorts by `sequence` descending; pruning is FIFO by `sequence`.

**Rationale:** A monotonic per-store sequence is robust against timestamp collisions and survives across `CheckpointStore` instances (read from existing files). `created_at` is retained for display.

**Alternatives considered:** Sort by `created_at` only — rejected (collisions); embed `time.time_ns()` in the id — rejected (still collision-prone in tight loops, and couples ordering to the id format).

**Reversible?** Yes (additive field; ordering key is internal).

---

### 2026-05-29 — Milestone 1 — Document binding before the workspace session exists

**Question:** Document-bound tools (`edit_paragraph`, `read_paragraph`, etc.) need to act on an open document, but the workspace session that tracks "which document is open" is not built until M4. How do tools reference the document in M1?

**Choice:** Document-bound handlers take an explicit `model: DocumentModel`; filesystem-bound handlers take `workspace_root` / `path`. The LLM-facing **schemas** expose only JSON params (path, para_id, …); resolving `path`→open-model and injecting the active `model` is deferred to the loop (M3) and workspace session (M4). The registry records `requires_model` / `requires_workspace_root` so M3/M4 know what to inject.

**Rationale:** Keeps M1 pure-Python and unit-testable with no session, no LLM, no registry-of-open-docs, while leaving a clean seam for M3/M4 to populate. Avoids prematurely building M4's state.

**Alternatives considered:** Build an open-document registry now (keyed by path) — rejected as M4 scope creep; tools taking a path and re-parsing each call — rejected because it loses in-memory edits between calls.

**Reversible?** Yes (the injection seam can change without altering tool logic).

---

### 2026-05-29 — Milestone 1 — `export_document` / `create_document` shipped unguarded

**Question:** The plan lists these tools in both M1 and M2 (guarded save/export). What ships in M1?

**Choice:** M1 ships both as functional writers with **no overwrite confirmation and no strict workspace-containment check**. Both create parent directories as needed. The guards (mandatory overwrite confirmation, path-inside-workspace enforcement, unified UI/agent save path) are M2.

**Rationale:** Lets the post-M4 demo already write files end-to-end, while keeping the safety rails as a focused M2 deliverable. Matches the plan's "Defer to Milestone 2" note for path validation/overwrite.

**Alternatives considered:** Defer both tools wholly to M2 (M1 read/edit-only) — rejected; project owner confirmed sequence is flexible and prefers functional tools early.

**Reversible?** Yes (guards are additive in M2).

---

### 2026-05-29 — Milestone 1 — Blank template location

**Question:** `create_document` needs a bundled blank docx; none existed. Where does it live?

**Choice:** Project owner created a blank `template.docx` (no text, standard Word styles). Verified it parses (1 empty paragraph, 0 comments/revisions) and round-trips through the serializer. Relocated from repo root to `assets/template.docx`; `create_document` copies it.

**Rationale:** A committed, fixed-baseline template gives predictable styles and avoids regenerating a blank doc on every call. `assets/` keeps the repo root clean.

**Alternatives considered:** Generate a blank doc in code via `python-docx` on each call — rejected for less control over baseline styles and added per-call work.

**Reversible?** Yes (the template file or the creation mechanism can change without API changes).

---

### 2026-05-29 — Milestone 0 — `config_version` field in `.stet/config.json`

**Question:** Should the initial config schema include a `config_version` field, or add one only when a migration is first needed?

**Choice:** Include `config_version: 1` from the start.

**Rationale:** A version field is near-zero cost now and lets M4+ migrate config schemas gracefully as keys are added or changed. Retrofitting a version field after configs already exist in the wild is more awkward (have to treat "absent" as version 0).

**Alternatives considered:** Omit until needed — rejected as a false economy.

**Reversible?** Yes (trivially — it is an additive field).

---

### 2026-05-29 — Milestone 0 — Per-workspace config only (no global config)

**Question:** Should Stage 1 support a global, user-level config that per-workspace `.stet/config.json` overrides, or per-workspace config only?

**Choice:** Per-workspace `.stet/config.json` only, with code constants as the default fallback. No global user-level config file in Stage 1.

**Rationale:** Keeps the model simple while the conventions settle. Each workspace is self-contained and portable (config travels with the folder). A global layer can be layered underneath later (global defaults → per-workspace overrides → code defaults) without breaking existing per-workspace files.

**Alternatives considered:** Global + per-workspace override layering now — deferred as premature; adds resolution-order complexity before there is demand.

**Reversible?** Yes (a global layer can be added later without changing the per-workspace format).

---

### 2026-05-29 — Milestone 0 — Include audit-doc hygiene in M0

**Question:** The M0 hygiene task (fixing stale `pre_transition_audit.md` references) was marked optional. Include it in M0 or leave the audit as a historical record?

**Choice:** Include it. Updated the "Codebase context" section: removed the stale `thread_objects` cache description in favor of the on-demand `get_thread_object()` reality (Tier 1 item #3), and corrected the test note (`test_data/synthetic/test.docx`; removed the resolved known-failure note).

**Rationale:** Low-risk doc-only edits that prevent future sessions from acting on outdated architecture statements. The audit's *Tier checklists* remain intact as the historical record; only the forward-looking "context" prose was corrected.

**Alternatives considered:** Leave as-is for historical fidelity — rejected; the context section is meant to orient current work, not archive past state.

**Reversible?** Yes.
