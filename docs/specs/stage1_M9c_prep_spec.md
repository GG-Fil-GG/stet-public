# Stage 1 — M9c-prep Spec: Make long agent runs workable

**Status:** Approved 2026-06-10 (open question resolved — see §8)
**Plan reference:** precedes [M9c — Pilot + closeout](../stage1_implementation_plan.md#milestone-9--integration-and-hardening)
**Depends on:** M1–M9b
**Origin:** First M9c pilot attempt (2026-06-10) — see §2

---

## 1. Goal

The first real-manuscript pilot run was abandoned: the agent appeared frozen ("Thinking…" for minutes, no visible activity), Stop took minutes to bite, and the project owner reasonably concluded the product was unworkable. Investigation showed the run was actually **alive and progressing** — the problem is that long runs are invisible, ever-slower, and effectively uncancellable. M9c-prep fixes exactly that, so the pilot can be run meaningfully.

**Scope discipline (project-owner directive):** direct solutions to the observed problems only. No complex context-management system, no streaming tokens, no websockets/SSE, no run orchestration framework.

## 2. Pilot findings being addressed (recorded)

Pilot setup: `test_data/local/stage1_M9c` — a real manuscript (653 paragraphs, **41 open comment threads**, ~11k tokens body text) plus ~12 reference files (2 papers, 7 RTF data sheets, COI forms; 6 representative reads measured at **~29k tokens** of extracted content). Instruction: address all comments using the reference materials. First run hit the 20-step cap; `max_agent_steps` was raised to 100; a second and third run were cancelled out of frustration.

Root causes confirmed by investigation (server logs, live process inspection, code reading, file measurements):

1. **No feedback during a run.** `sendChat` makes one blocking POST for the entire run (up to 100 steps) and renders a static "Thinking…" until it returns; the step trace only renders at the end. The server terminal is equally silent — `AgentLoop` logs nothing per step (its `verbose` flag is unused). A healthy 45-minute run and a hang are indistinguishable, for the user and the developer.
2. **Unbounded context growth.** The loop re-sends the full conversation — including every complete `read_file`/`read_document` result — on every step. By mid-run on this task the context plausibly reaches 50–150k tokens; with a reasoning model (GPT-5 Mini) each call takes ~30s–3min and grows slower as the run proceeds. 100+ steps at that rate is hours.
3. **Stop cannot interrupt a call.** `cancel_check` is polled only between steps (mid-LLM cancel deferred at M7); the in-flight provider call must finish first. The OpenAI client uses library defaults (**600s timeout, 2 retries**), so one degenerate call can block Stop for ~10+ minutes. The server log recorded ten consecutive cancel clicks.
4. **Task shape.** "Address all 41 comments" in one monolithic turn is the wrong granularity for the current loop, but the agent has no guidance to batch its work or report progress.

Not bugs (confirmed working): the agent loop itself, tool dispatch, edits/track changes, checkpoints, Unicode protection. A cancelled run showing only read-tool steps and no edits is expected — the agent was still exploring when stopped.

## 3. Scope — four direct fixes

### 3.1 Per-step server logging (observability)

`AgentLoop._run_loop` logs one line per step via `logging.getLogger(__name__)`: step number, tool name(s) or "final answer", and elapsed time for the LLM call. Remove the unused `verbose` flag or wire it; either way the default INFO log shows run progress in the terminal.

### 3.2 Live progress in the UI (polling — no SSE/websockets)

- The session exposes the running turn's live state: the loop appends to a shared `steps` list the route can read (the loop already builds `steps` incrementally; the session holds a reference while a run is in progress).
- New route: `GET /api/workspace/{id}/agent/progress` → `{running: bool, step_count: int, steps: [{tool_name, ok}]}` (lightweight — names and status only, not full args/results).
- UI: while a run is in flight, poll progress every ~2s; replace the static "Thinking…" with a live line ("Step 23 — read_file ✓") and append step entries incrementally. On completion the existing full render replaces the live view (unchanged).
- Stop button stays as-is but now visibly reflects that the run continues until the current call returns.

### 3.3 Context discipline (trim, don't summarize)

Direct rule, no summarization pipeline: before each LLM call, if the conversation exceeds a **token budget** (estimate: chars/4; `context_token_budget` config key, default 60,000 — see §8), replace the **content of the oldest tool-result messages** with a short stub — `[result trimmed to save space — call the tool again if needed]` — until under budget. Never trim: the system prompt, the current user message, the last N (default 4) tool results, or any assistant text. The stored/persisted conversation keeps the full results (trimming happens on the provider-bound copy, same pattern as Unicode protection).

This is one function with a loop and a threshold — not a context-management system.

### 3.4 Responsive cancel (bounded calls)

- Construct the OpenAI client with an explicit **timeout (120s) and max_retries=0** (mirroring the Ollama path's explicit 300s timeout; a failed/slow call surfaces as a tool-level error and the existing error policy applies).
- Poll `cancel_check` **between tool calls within a step** too, not just before the LLM call — so Stop bites after the current tool finishes, not only after the whole step.

### 3.5 (Light) task-shape guidance

One sentence in `AGENT_SYSTEM_PROMPT`: for large multi-comment tasks, work through comments in order and keep going until done or out of steps — do not re-read files already read this turn. *(Kept minimal deliberately; prompt over-steering caused the M9a double-edit regression.)*

## 4. Out of scope (explicitly)

- **Streaming token output / SSE / websockets** — polling is sufficient.
- **Conversation summarization, embeddings, retrieval,** or any persistent context store.
- **Mid-LLM-call abort** (killing an in-flight HTTP request) — the 120s timeout bounds the wait instead.
- **Parallel tool execution, sub-agents, task queues.**
- **Changing checkpoint or error-policy behavior.**
- **Auto-resume / auto-continuation** of `max_steps` runs.

## 5. Files

| File | Change |
|------|--------|
| `src/agent/loop.py` | Per-step logging; intra-step cancel polls; live-steps reference hook |
| `src/agent/llm_tools.py` | OpenAI client timeout/retries; conversation trim before provider calls |
| `src/agent/unicode_protection.py` | *(unchanged — listed to note trim happens alongside protect, same copy)* |
| `src/agent/prompts.py` | One task-shape sentence |
| `src/workspace/config.py` | `context_token_budget` key (default 60,000; positive-int validation) |
| `src/workspace/state.py` | Hold live run progress (steps reference) during a run |
| `src/routes/workspace.py` | `GET …/agent/progress` route; `ConfigUpdate.context_token_budget`; budget passed to the client |
| `templates/workspace.html` | `context_token_budget` number input in the M9b Workspace settings block |
| `static/js/workspace.js` | Poll progress during run; live step rendering; budget field load/save |
| `tests/` | Loop logging/cancel tests, trim unit tests, progress route test, page test if markup changes |

## 6. Tests

| Test | Asserts |
|------|---------|
| Trim: under budget untouched | Conversation below budget passes through identical |
| Trim: oldest-first, protected tail | Over budget → oldest tool results stubbed; system/user/last-N intact |
| Trim: persisted history unaffected | Session `conversation` retains full results after a trimmed call |
| Intra-step cancel | Cancel flag set during a multi-tool step stops before the next tool |
| Progress route | During a (mock) run, returns `running=true` + step names; after, `running=false` |
| Client config | OpenAI client constructed with timeout=120, max_retries=0 |

Full suite stays green, 0 warnings; card UI untouched.

## 7. Acceptance criteria

- [ ] A multi-step run shows live step progress in the chat panel (poll-based) and per-step lines in the server log.
- [ ] Stop takes effect within one tool call or one (≤120s-bounded) LLM call, whichever is in flight.
- [ ] A long run's per-call latency stays roughly flat (trim keeps the provider payload under budget) instead of growing each step.
- [ ] Re-run of the §2 pilot task is *workable*: visible progress, responsive stop. (Whether it completes all 41 comments is a pilot outcome, not an acceptance gate.)
- [ ] Full suite green, 0 warnings.

## 8. Resolved decisions (2026-06-10)

1. **Trim budget is a `WorkspaceConfig` key** — `context_token_budget`, default 60,000 (project-owner decision: context management will likely grow more sophisticated later; keeping the knob in config is good discipline now). Exposed in the M9b settings UI alongside the other four keys so it does not recreate the M7 "config key with no UI" gap.
