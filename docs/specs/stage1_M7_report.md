# Stage 1 — Milestone 7 Report: Agent chat panel (complete)

**Status:** Complete (manual QA done; see §7)
**Spec:** [stage1_M7_spec.md](stage1_M7_spec.md)
**Date:** 2026-06-01

---

## 1. What was built

Production-quality agent chat panel on top of the M5 shell:

- **`ChatTurn` turn log** (`src/workspace/chat_log.py`) — UI-facing history parallel to `session.conversation`; persisted in `.stet/workspace.json` as optional `chat_turns` (schema stays v1).
- **`GET /api/workspace/{id}/chat`** — reload turn log + in-memory `pending_confirmation`.
- **`POST /api/workspace/{id}/chat/clear`** — wipes conversation + turn log; 409 while a run is in progress.
- **`POST /api/workspace/{id}/agent/cancel`** — sets a cancel flag; loop runs in `asyncio.to_thread` with `cancel_check` between steps; returns `status: "cancelled"`.
- **Confirm flow** — updates the **last** turn (merges steps) instead of appending a second turn.
- **Client** — chat history survives document open/close and workspace reload; header **Details** toggle (`localStorage` `ws_chat_show_details`); **Stop** + **Clear**; status banners for `stopped` / `max_steps` / `cancelled`; step links to paragraphs and comment threads.

## 2. Files

**Created**

- `src/workspace/chat_log.py` — `ChatTurn` serialize/deserialize.
- `tests/test_workspace_chat.py` — persistence, cancel, clear, confirm, `stop_and_ask`.

**Modified**

- `src/workspace/state.py` — `chat_turns`, run cancel fields, `clear_chat()`, restore `chat_turns`.
- `src/agent/loop.py` — `cancel_check`; `AgentStatus` includes `"cancelled"`.
- `src/routes/workspace.py` — chat/cancel routes; threaded agent run; `_record_chat_turn` in `_finalize`.
- `main.py` — map `conflict` ToolError → 409.
- `templates/workspace.html` — chat header toolbar.
- `static/js/workspace.js` — load/render turn log, running state, details toggle, step links.
- `static/css/workspace.css` — banners, toolbar, step links.
- `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, `docs/specs/stage1_M7_spec.md`.

## 3. Tests

Full suite: **711 passed, 1 skipped, 0 warnings**.

| Test | Asserts |
|------|---------|
| `TestChatTurnLog::test_get_chat_after_run` | GET chat returns persisted turn with steps |
| `TestChatTurnLog::test_turn_log_survives_reopen` | Re-open folder restores turns from disk |
| `TestChatTurnLog::test_confirm_updates_single_turn` | Confirm merges into one turn |
| `TestChatTurnLog::test_clear_chat` | Clear wipes turns + conversation |
| `TestAgentCancel::test_cancel_mid_run` | Cancel → `status: "cancelled"`, partial steps |
| `TestAgentCancel::test_cancel_when_idle_409` | Idle cancel → 409 |
| `TestAgentCancel::test_clear_while_running_409` | Clear during run → 409 |
| `TestStopAndAsk::test_stop_and_ask_status` | Policy → `status: "stopped"` in JSON + turn log |
| `TestConversation::test_cancel_check_stops_between_steps` | Loop unit cancel between steps |

Card UI at `/` unchanged.

## 4. Deviations from spec

None material. Mid-LLM-call cancel remains deferred (between-step cancel only), as specified in §9.

## 5. Decisions logged

See `docs/stage1_decision_log.md` (2026-06-01 M7 entries): workspace-scoped chat history, clear-chat API, `chat_turns` at schema v1, between-step cancel only.

## 6. Manual QA checklist (project owner)

Open `/workspace`, load a docx, run a few agent turns:

1. **Multi-turn** — two messages in a row; second turn sees context from the first.
2. **Reload history** — re-open the same folder (or refresh) → chat bubbles return (summary mode).
3. **Document switch** — open/close/switch documents → chat history **stays**.
4. **Details toggle** — off by default; on → step trace for current and reloaded turns.
5. **Stop** — start a multi-step run → **Stop** → banner “Run cancelled”; document shows only edits before cancel.
6. **Clear chat** — clears panel + next turn starts fresh LLM context.
7. **Step links** — `edit_paragraph` step → “Paragraph …” scrolls/flashes the block; comment tools link to thread.
8. **`stop_and_ask`** — set `tool_error_policy` to `stop_and_ask` (see §7.2 note), trigger a tool error → stopped banner (not success). **Distinct from item 5**: item 5 is the user-initiated Stop button (`status: cancelled`); item 8 is the agent halting on a failed tool under the `stop_and_ask` policy (`status: stopped`).

## 7. Manual QA outcome + follow-ups

Project-owner QA (2026-06-02): items 1–7 verified working. Item 1 confirmed via a two-turn exchange where the second message ("assess the changes already made…") relied on context from the first (paragraph IDs, Methods/Results, `test_2.docx`) without restating it — confirming `session.conversation` persists across turns, not just the UI bubbles.

### 7.1 Item 8 checklist wording was wrong (corrected)

The original item 8 said "set policy in settings." The **Agent settings** modal only exposes LLM credentials (provider, model, API key / Ollama URL+model) — it has never included `tool_error_policy`, and M7 did not add it. Item 8 is therefore **not manually testable through the UI** today. Corrected wording above.

**Coverage:** the `stop_and_ask` behavior (status + stopped banner data) is verified by `tests/test_workspace_chat.py::TestStopAndAsk::test_stop_and_ask_status`, which sets the policy via `PUT …/config`. The UI banner markup exists; only the manual path was blocked.

**Workaround to verify manually:** edit `.stet/config.json` in the workspace folder to `"tool_error_policy": "stop_and_ask"`, re-open the folder, then ask the agent to do something that fails a tool (e.g. edit a non-existent paragraph id) → the stopped banner appears.

### 7.2 Follow-up: expose `tool_error_policy` in the settings modal

`tool_error_policy` is a workspace config key (M4) editable via `PUT /api/workspace/{id}/config` but has no control in the settings UI. Adding a selector (`report_and_skip` / `stop_and_ask`) — and possibly the other config keys (`max_agent_steps`, `checkpoint_policy`, `max_checkpoints`) — would make item 8 directly testable and the config surface complete. **Logged for the project owner to schedule** (candidate for M9 — Integration and hardening, or a small standalone patch). Not fixed here per Stage 1 scope discipline.

## 8. Next

M8 — RTF and PPTX file readers per the implementation plan.
