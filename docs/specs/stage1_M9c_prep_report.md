# Stage 1 — M9c-prep Report: Make long agent runs workable

**Status:** Complete (automated; manual re-pilot pending project owner — see §6)
**Spec:** [stage1_M9c_prep_spec.md](stage1_M9c_prep_spec.md) (approved 2026-06-10)
**Date:** 2026-06-10

---

## 1. What was built

The four direct fixes from the spec, plus the light prompt guidance — no context-management system, no streaming, no SSE.

### 1.1 Per-step server logging (`src/agent/loop.py`)

`AgentLoop._run_loop` now logs one INFO line per step: step number, LLM-call elapsed time, and the tool name(s) or "final answer" (plus lines for cancel, stop-on-error, awaiting-confirmation, and max-steps exits). The unused `verbose` constructor flag was removed (nothing referenced it). A long run is now legible in the server terminal.

### 1.2 Live progress in the UI (polling)

- `WorkspaceSession.run_live_steps` — a fresh list created by `begin_agent_run()`; the loop uses it as its step accumulator (`run()`/`resume()` accept a `live_steps` sink), so the route can read progress while the worker thread runs.
- New route `GET /api/workspace/{id}/agent/progress` → `{running, step_count, steps: [{tool, ok}]}` — names and ok-flags only, cheap to poll; full args/results still arrive with the run response.
- `workspace.js`: while a run is in flight, the static "Thinking…" placeholder is polled-updated every 2 s into "Working… N tool calls so far" plus the last six step names with ✓/✗. The final render on completion is unchanged; poll errors are ignored (the run response stays authoritative). Both `sendChat` and `confirmAgent` poll.

### 1.3 Context discipline (`trim_conversation` in `src/agent/llm_tools.py`)

Before each provider call, if the conversation exceeds `context_token_budget` (chars/4 estimate, including tool-call arguments), the **oldest tool-result contents** are replaced with `[result trimmed to save space — call the tool again if needed]` until under budget. Never touched: system prompt, user messages, assistant text, and the last 4 tool results. Trimming operates on the provider-bound copy only — the session's persisted conversation keeps full results (same boundary pattern as M9a Unicode protection).

`context_token_budget` is a `WorkspaceConfig` key (default 60,000, positive-int validation, per the resolved spec question) — wired through `ConfigUpdate`, `_build_loop` → `AgentLLMClient`, and exposed in the M9b settings UI as a number input.

### 1.4 Responsive cancel

- OpenAI client now constructed with **timeout=120 s, max_retries=0** (was library default 600 s × 2 retries). A slow/failed call surfaces as an error and the existing error policy applies.
- `cancel_check` is polled **between tool calls within a step** too, not just before each LLM call. When a cancel lands mid-step, the remaining (unexecuted) tool calls get stub tool-result messages (`{"error": "cancelled", …}`) so every `tool_call` id keeps a matching tool message — providers reject conversations with dangling tool calls, and the conversation is persisted and continued on the next turn (see §4).

### 1.5 Task-shape guidance (`src/agent/prompts.py`)

One bullet added: for large multi-comment tasks, work in document order, keep going until done or out of steps, and don't re-read files already read this turn. Kept minimal per the M9a over-steering lesson.

## 2. Files

**Modified**

- `src/agent/loop.py` — per-step logging; intra-step cancel + `_stub_cancelled_calls`; `live_steps` sink on `run()`/`resume()`; `verbose` flag removed.
- `src/agent/llm_tools.py` — `trim_conversation` + `_estimate_tokens`; OpenAI timeout/retries; `context_token_budget` on the client; trim applied in `complete()`.
- `src/agent/prompts.py` — task-shape bullet.
- `src/workspace/config.py` — `context_token_budget` key (default 60,000; invalid → default + warning).
- `src/workspace/state.py` — `run_live_steps` on the session, reset per run.
- `src/routes/workspace.py` — progress route; `ConfigUpdate.context_token_budget`; budget passed to `AgentLLMClient`; `live_steps` passed to `run`/`resume`.
- `templates/workspace.html` — Context token budget input (`ws-context-token-budget`) in the Workspace settings block.
- `static/js/workspace.js` — `startProgressPolling()`; budget field load/save.
- Tests: `test_llm_tools.py`, `test_agent_loop.py`, `test_workspace_chat.py`, `test_workspace_api.py`, `test_workspace_config.py`, `test_workspace_page.py`.

## 3. Tests

Full suite: **749 passed, 1 skipped, 0 warnings** (737 before; 12 new tests). The skip is the pre-existing env-gated live-Ollama integration test (`RUN_OLLAMA_TESTS != 1`), unchanged.

| Test | Asserts |
|------|---------|
| `TestConversationTrim::test_under_budget_passes_through_identical` | Below budget → same objects, untouched |
| `…::test_over_budget_stubs_oldest_protects_tail` | Oldest tool results stubbed; last 4 + system/user/assistant intact |
| `…::test_input_messages_not_mutated` | Caller's history keeps full results |
| `…::test_complete_trims_provider_copy_only` | `complete()` trims the provider copy, not the session conversation |
| `TestOpenAIClientConfig::test_timeout_and_retries_are_bounded` | OpenAI client built with timeout=120, max_retries=0 |
| `TestIntraStepCancel::test_cancel_between_tools_stops_and_stubs_remaining` | Cancel after tool 1 of 2 → cancelled, tool 2 skipped, stub result keeps protocol valid |
| `TestLiveSteps::test_live_steps_list_is_used_as_accumulator` | `run(live_steps=…)` populates the caller's list |
| `TestPerStepLogging::test_each_step_logs_tools_and_final_answer` | INFO lines per step via caplog |
| `TestAgentProgress` (3 tests) | Idle shape; 404 on unknown workspace; live steps observable mid-run from a second request, `running=false` after |
| `TestConfig::test_context_token_budget_round_trip` | Default 60,000; PUT round-trips |
| config/page test extensions | Key defaults/round-trip/invalid-fallback; settings control renders |

Two existing cancel tests were updated for the intentionally changed behavior: a cancel that lands during the LLM call now stops **before** the first tool executes (previously the whole step's tools still ran). Assertions now reflect the faster stop.

## 4. Deviations from spec / notes

- **Stub results for cancelled-mid-step tool calls** (not in the spec text): when Stop bites between tool calls, the assistant message already references the remaining tool calls. OpenAI rejects a follow-up conversation in which a `tool_call` id has no tool message, and the conversation *is* persisted and continued next turn — so the skipped calls get explicit `{"error": "cancelled"}` stubs. Necessary correctness for the spec's intra-step cancel, logged in the decision log.
- **Budget UI control**: the spec's resolved decision called for a config key; it is also exposed in the M9b settings modal (one number input) so it doesn't recreate the M7 "config key with no UI" gap. Recorded in spec §8.
- `confirmAgent` (resume-after-confirmation) polls progress too, not just `sendChat` — same run shape, same blindness otherwise.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-10): trim budget as config key with UI exposure (project-owner decision); trim-on-provider-copy boundary; stub tool results on intra-step cancel; OpenAI 120 s / 0-retry bounds.

## 6. Manual QA (project owner — gates the M9c pilot re-run)

1. Start a multi-step agent run → the chat shows "Working… N tool calls so far" with step names updating every ~2 s, and the server terminal logs one line per step.
2. Click **Stop** during a run → it takes effect after the current tool or current (≤120 s) LLM call, not minutes later.
3. Open settings → **Context token budget** shows 60000, edits persist to `.stet/config.json`.
4. Re-run the §2 pilot task (`test_data/local/stage1_M9c`) → progress visible throughout; per-call latency stays roughly flat instead of growing each step. (Completing all 41 comments is a pilot outcome, not a gate.)

## 7. Next

Resume **M9c — Pilot + closeout**: run the pilot checklist (`stage1_M9c_pilot_checklist.md`) including the real-manuscript task, then default-route flip, audit docs, Stage 1 closeout.
