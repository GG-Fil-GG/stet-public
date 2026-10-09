# Stage 1 — Milestone 3 Report: Agent loop

**Status:** Complete
**Spec:** [`stage1_M3_spec.md`](stage1_M3_spec.md) (approved & implemented 2026-05-30)

---

## 1. What was done

Built the multi-turn, provider-neutral tool-calling loop that drives the M1/M2 tools:

- **Conversation types** — `Message` (system/user/assistant/tool) and `ToolCall` (id, name, parsed arguments) in `src/agent/messages.py`. Distinct from the UI `ChatMessage`.
- **Tool-calling client** — `AgentLLMClient` + `LLMToolResponse` in `src/agent/llm_tools.py`. One canonical tool schema (from `ToolSpec.json_schema()`) translated to each provider's `tools` format; **OpenAI** (`chat.completions`) and **Ollama** (`POST /api/chat`) both implemented. Normalizes the two providers' differences (OpenAI arguments arrive as a JSON string, Ollama as a dict; tool-result keyed by `tool_call_id` vs `tool_name`). Reuses `src/llm_config` for defaults only; the legacy `LLMHandler` / `llm_transport.py` are untouched.
- **Agent loop** — `AgentLoop` in `src/agent/loop.py` runs the call→tool→result cycle: sends the user message + tool schemas, executes returned tool calls (injecting `model` / `workspace_root` per the registry flags), feeds results back, iterates to `max_steps`. Returns an `AgentResult` (`messages`, `final_text`, `steps`, `status`, `pending_confirmation`).
- **Policies** — `CheckpointPolicy` (`per_agent_turn` / `per_mutating_tool`, using the M2 `CheckpointStore`) and `ToolErrorPolicy` (`report_and_skip` / `stop_and_ask`).
- **Overwrite confirmation pause** — a guarded write raising `overwrite_requires_confirmation` pauses the loop (`status="awaiting_confirmation"` + `PendingConfirmation`); `resume(pending, confirmed, history)` re-issues with `overwrite=True` on consent or appends a decline note. The loop never auto-confirms.
- **`mutating` flag** — added to `ToolSpec`; flags `edit_paragraph`, `add_comment_reply`, `add_comment`, `remove_comment`.
- **Agent system prompt** — `src/agent/prompts.py` (`get_agent_system_prompt()`), task-oriented, separate from the card-UI suggestion prompt.

The loop is **stateless per call** (history in → full messages out); persistence and path resolution are M4.

Commit: _see the M3 commit on `main` (recorded in the plan Status table)._

## 2. Files touched

**Created:**

| File | Purpose |
|------|---------|
| `src/agent/messages.py` | `Message`, `ToolCall`. |
| `src/agent/prompts.py` | `AGENT_SYSTEM_PROMPT` / `get_agent_system_prompt()`. |
| `src/agent/llm_tools.py` | `AgentLLMClient` + `LLMToolResponse` (OpenAI + Ollama adapters). |
| `src/agent/loop.py` | `AgentLoop`, `AgentResult`, `AgentStep`, `PendingConfirmation`, `CheckpointPolicy`, `ToolErrorPolicy`. |
| `tests/test_llm_tools.py` | 12 tests — schema/message translation + OpenAI/Ollama response normalization (no network). |
| `tests/test_agent_loop.py` | 14 tests — happy path, injection, max-steps, unknown tool, error policies, overwrite confirm/resume, checkpoint policies. |
| `tests/test_agent_integration.py` | 2 live tests — OpenAI (gated on `OPENAI_API_KEY`), Ollama (opt-in via `RUN_OLLAMA_TESTS=1`). |

**Modified:**

| File | Change |
|------|--------|
| `src/agent/registry.py` | `mutating: bool` on `ToolSpec`; flagged the four model-mutating tools. |
| `src/agent/__init__.py` | Export the M3 surface (`AgentLoop`, `AgentLLMClient`, `Message`, etc.). |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, `docs/specs/stage1_M3_spec.md` | Glossary / log / status / spec-status updates. |

## 3. Deviations from spec

All seven open questions were resolved with the project owner before implementation and built as agreed. One thing the spec did not anticipate, surfaced by the live OpenAI test:

1. **Finding — the default OpenAI model rejects a custom temperature.** `gpt-5-mini` (the configured default) only accepts the default temperature (`1`); sending `temperature=0.3` returns a 400. The card path already guards this (`if "gpt-5" not in model: params["temperature"] = …`). The agent client now mirrors that guard: it omits `temperature` for the `gpt-5` family and sends it otherwise. Caught and fixed during the M3 test run.

No other deviations. Both providers were implemented (not OpenAI-only), as the live Ollama check made dual support nearly free.

## 4. New names added to the glossary

In [`stage1_glossary.md`](../stage1_glossary.md):

- **Modules:** `src/agent/messages.py`, `src/agent/prompts.py`, `src/agent/llm_tools.py`, `src/agent/loop.py`.
- **Types:** `Message`, `ToolCall`, `LLMToolResponse`, `AgentLLMClient`, `AgentLoop`, `AgentResult`, `AgentStep`, `PendingConfirmation`, `CheckpointPolicy`, `ToolErrorPolicy`; `ToolSpec` gains `mutating`.
- **Agent tools:** note added on which tools are `mutating`.

## 5. Decisions made mid-implementation

In [`stage1_decision_log.md`](../stage1_decision_log.md), all 2026-05-30 / Milestone 3:

- Standalone tool-calling client; legacy stack untouched.
- Ollama tool-calling confirmed on the existing local `llama3.1` (no new model).
- `mutating` flag on `ToolSpec`.
- Overwrite confirmation pauses the loop (no auto-confirm).
- Loop is stateless per call; conversation returned, not persisted.

## 6. Test results

- New: `tests/test_llm_tools.py` — **12 passed**; `tests/test_agent_loop.py` — **14 passed**.
- Live: `tests/test_agent_integration.py` — OpenAI **passed** (real `gpt-5-mini` call: listed comments via `list_comments`, returned a non-empty summary); Ollama **skipped** by default (opt-in).
- Full suite: **634 passed, 1 skipped, 0 warnings** (run with `-W error`). Legacy card-UI baseline (routes / integration / workflow) intact.

**Ollama live verification (manual, `RUN_OLLAMA_TESTS=1`):** against `llama3.1:latest` (Ollama 0.24.0), a full loop round-trip (`list_comments` → tool result → summary) completed successfully. One transient `404` was observed on a cold model reload immediately after the OpenAI test; re-running succeeded, and the opt-in test now skips on transient `requests` errors rather than failing.

## 7. What to watch in the next milestone

- **M4 (Workspace backend):** owns conversation persistence (write the returned `messages` into `.stet/workspace.json`) and **path resolution** — resolve LLM-supplied `path` args (`read_document`, `read_file`, `export_document`, `create_document`) against the workspace root before they reach the tools. M3 passes paths through unresolved. Also: read `max_agent_steps` / `checkpoint_policy` / `max_checkpoints` from `.stet/config.json` and wire `.stet/checkpoints/` to the loop's `CheckpointStore` (M3 takes these as constructor args).
- **M7 (Agent chat panel):** surfaces `PendingConfirmation` to the user and calls `resume(..., confirmed=…)`; renders `AgentStep` traces.
- **Local-model reliability:** Llama 3.1 8B tool selection is "Good" but weaker than OpenAI on long multi-step chains; if local agentic editing proves unreliable in later milestones, `qwen2.5` (or similar) is the upgrade path — no code change, just the model name.
