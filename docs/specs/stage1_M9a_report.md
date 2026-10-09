# Stage 1 — Milestone 9a Report: Agent Unicode protection

**Status:** Complete (automated; manual QA pending project owner — see §6)
**Spec:** [stage1_M9_spec.md](stage1_M9_spec.md) §4 (umbrella spec; no separate M9a spec by decision Q1)
**Date:** 2026-06-03

---

## 1. What was built

Added symmetric special-Unicode protection at the `AgentLLMClient` transport seam so the agent edit path (`edit_paragraph`) no longer corrupts characters like `≥ ≤ ± Δ` when the model re-types a paragraph. This closes the corruption bug surfaced in [M6b report §7.2](stage1_M6b_report.md) and brings the agent path to parity with the card UI (which has had this protection in `src/llm_transport.py`).

- Every string the model **reads** (outbound message `content` + string values inside prior assistant `tool_calls` arguments) has special characters swapped for `__UNICODE_*__` placeholders before the provider call.
- Every string the model **writes back** (response `text` + every string value in returned `ToolCall.arguments`) has those placeholders restored to the exact original character.

Because the model only ever sees placeholders, when it re-types a paragraph it reproduces the (uncorruptible) placeholder token and we restore the real character. Transforms operate on copies sent to the provider; the persisted `Message` history and turn log keep real Unicode.

## 2. Files

**Created**

- `src/agent/unicode_protection.py` — `UNICODE_PROTECTION_MAP` (34 entries, copied verbatim from `llm_transport`), `RESTORATION_MAP`, and `protect` / `restore` / `protect_arguments` / `restore_arguments` (recursive over dict values + lists; keys and non-strings untouched).
- `tests/test_agent_unicode.py` — round-trip, recursion, both provider seams, and an end-to-end loop test.

**Modified**

- `src/agent/llm_tools.py` — protect content + tool-call arguments in `_message_to_openai` / `_message_to_ollama`; restore `text` + tool-call arguments in `_call_openai` / `_call_ollama`.
- `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, the M9 spec.

## 3. Tests

Full suite: **735 passed, 1 skipped, 0 warnings** (was 722). The 1 skip is the pre-existing opt-in Ollama live test (`test_agent_integration.py`, gated on `RUN_OLLAMA_TESTS`) — intentional, not introduced here.

| Test | Asserts |
|------|---------|
| `TestProtectRestore::test_round_trip_with_several_mapped_chars` | `restore(protect(s)) == s` for a multi-symbol string |
| `TestProtectRestore::test_only_known_chars_are_mapped` | Japanese / accented Latin pass through untouched |
| `TestProtectRestore::test_map_matches_card_ui_verbatim` | Agent map `==` card-UI `LLMTransportMixin.UNICODE_PROTECTION_MAP` |
| `TestArgumentRecursion::test_nested_dict_and_list_protected_and_restored` | Recursion through dict/list; non-strings untouched; round-trips |
| `TestArgumentRecursion::test_keys_are_not_transformed` | Dict keys left literal; only values protected |
| `TestOutboundProtection::*` (4) | OpenAI + Ollama emit placeholders in `content` and tool-call args |
| `TestInboundRestoration::test_openai_tool_call_argument_restored` | OpenAI seam: placeholder in response `text` + `new_text` → real `≥`/`±` |
| `TestInboundRestoration::test_ollama_tool_call_argument_restored` | Ollama seam: same restoration |
| `TestLoopIntegration::test_edit_paragraph_preserves_special_char` | Real `AgentLLMClient` (mocked provider): model echoes `__UNICODE_GTE__` in `edit_paragraph` → applied paragraph contains real `≥ 75`, no placeholder |

Card UI at `/` and `src/llm_transport.py` unchanged.

## 4. Deviations from spec

None. Implemented as specified in §4. One incidental correction: the spec referenced the card-UI map as `llm_transport.UNICODE_PROTECTION_MAP`; the actual home is the class `LLMTransportMixin` in that module. The parity test asserts against the real symbol.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-03): map copied verbatim (no shared-module extraction — would edit the card-UI baseline, out of scope); protection always-on (no config flag), mirroring the card UI; transforms on provider-bound copies only so persisted history keeps real Unicode.

## 6. Manual QA checklist (project owner)

In `/workspace`, on a document whose body contains special symbols (`≥`, `≤`, `±`, `°`, a Greek letter):

1. Ask the agent to lightly rewrite a paragraph that contains `≥`/`±` (e.g. "tidy the wording of the eligibility sentence").
2. Confirm the tracked change shows the **real** symbol (`≥ 75`), not garbled bytes or a `__UNICODE_*__` placeholder.
3. Export and open in Word — the symbol is intact in the tracked change.

(Live providers exercise the seam end-to-end; the automated loop test already proves the mechanism with a mocked provider.)

## 7. Follow-up (2026-06-08): prompt safeguard for token retention

Project-owner QA surfaced a gap the placeholder mechanism alone does not cover. M9a prevents **corruption** of special symbols the model echoes verbatim, but the swap is *silent* — the model sees an opaque `__UNICODE_*__` token, not a `≥`. When the agent **paraphrases** a paragraph (rather than echoing it), it can simply drop the token, so a `≥` disappears from the edit even though it was never garbled. (Observed: "aged ≥18 years" rewritten to "aged 18 years"; the model's own summary still showed "≥140" because that prose echoed the token, which we then restored.)

This is the same class of issue the card UI handles for `[CITATION_X]` tokens via an explicit prompt instruction. Fix: a line in `AGENT_SYSTEM_PROMPT` (`src/agent/prompts.py`) telling the agent that `__UNICODE_*__` tokens each stand for one real symbol (named in words, not the symbol itself — a literal symbol in the prompt would itself be protected and make the guidance circular) and must be preserved exactly, never deleted/translated/reworded.

Tests added in `tests/test_agent_unicode.py`: `TestPromptSafeguard` (prompt names a concrete token and demands exact preservation; prompt contains no real protected symbol). Suite: **737 passed, 1 skipped, 0 warnings**.

Note: this nudges the model strongly but cannot *guarantee* retention (LLM behavior). It is the proportionate Stage 1 fix; a hard guarantee (e.g. diffing protected tokens in/out and rejecting edits that drop one) would be a larger change, logged here as a possible future hardening if QA shows it is still needed.

### 7.1 Follow-up (2026-06-08): double-edit "no visible change" was correct behaviour, not a bug

A later QA run showed the agent making **two** `edit_paragraph` calls on the same paragraph — a rephrase, then a "second pass to fix the ≥ tokens" that, by its own summary, *restored the original wording* — after which nothing showed in the viewer or Word.

Investigated and confirmed by repro that this is **correct behaviour**: `src/workspace/render.py::_render_pending_revision_diff` baselines the diff on the earliest pending deletion (the true original) and compares it to the current `plain_text`. When a later edit returns the text to the original, `original == revised`, so there is genuinely no net change to display or serialize. An edit of A→B→A *should* show nothing.

So the only real issue was the **agent's mistake** — it reverted a change it meant to keep, out of token confusion. The proportionate fix is clearer token guidance (above); deciding when to make one edit vs. several is the agent's judgement and is deliberately **not** restricted (multiple edits per paragraph are expected and allowed). No code or renderer change. An initial over-correction (a prompt rule forcing a single edit per paragraph) was added and then removed after project-owner feedback. Suite after revert: **737 passed, 1 skipped, 0 warnings**.

### 7.2 Follow-up (2026-06-08): agent edits strip run formatting — logged to Stage 2 backlog

QA confirmed the agent edit path otherwise working (tracked changes correct, ≥ preserved), but a successful edit stripped the **bold** from the "Methods:" label. Cause: `edit_paragraph` uses the plain-text revision path (`apply_revision_from_plain_text`), which carries no run formatting; the whole-paragraph REPLACE rebuilds runs as plain text, so even unchanged spans lose their formatting. The revision serializer preserves formatting only when given revised-HTML segments — the manual TipTap edit path supplies these, the agent path does not.

This is cosmetic (not data-loss) and the fix is cross-cutting (shared revision engine + agent edit path), so per project-owner decision it is **logged as a Stage 2 / backlog item** ([plan](../stage1_implementation_plan.md)), not addressed in Stage 1.

## 8. Next

M9b — Workspace config in the settings UI.
