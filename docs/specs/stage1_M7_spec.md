# Stage 1 — Milestone 7 Spec: Agent chat panel (complete)

**Status:** Complete — implemented 2026-06-01; ready for manual QA  
**Plan reference:** [Milestone 7](../stage1_implementation_plan.md#milestone-7--agent-chat-panel-complete) · **Roadmap:** Step 6 (agent chat panel)  
**Depends on:** M4 (workspace API + conversation persistence), M5 (chat shell), M6 (document viewer for scroll-to-change links)

---

## 1. Goal

Turn the M5 **functional chat shell** into a **production-quality agent panel**: multi-turn context that survives workspace restarts, cancellable long runs, readable summaries with an optional step trace, clear inline tool errors (both error policies), and click-through from mutating tool steps to the affected document location.

M5 deliberately deferred polish here (see [M5 spec §6](stage1_M5_spec.md#6-out-of-scope-for-this-milestone)). M6 delivered the viewer blocks needed for “jump to paragraph” links. M7 completes the right-hand panel without changing the agent tool surface or the legacy card UI at `/`.

---

## 2. Current state (baseline)

What already works (do not re-implement):

| Area | Today |
|------|--------|
| **Send / receive** | `POST …/agent/run` + `POST …/agent/confirm`; client shows `final_text`, a flat step list (`✓ tool` / `✗ error`), overwrite confirmation card |
| **LLM context persistence** | `session.conversation` (`list[Message]`) written to `.stet/workspace.json` on every run; restored on `open_workspace` for the **next** LLM turn |
| **Error text in UI** | `errorText()` avoids `[object Object]`; steps with `error` show inline |
| **Document refresh** | `renderResult` → `refreshDocument()` after each run |
| **Tool error policy** | `tool_error_policy` in config (`report_and_skip` default, `stop_and_ask` supported by loop) |

Gaps M7 closes:

| Gap | Symptom |
|-----|---------|
| **UI history** | Opening a folder or switching documents **clears** the chat panel (`resetChat()`), even though the server still has `conversation` in `workspace.json` |
| **Display persistence** | Reloaded `Message` list contains raw `tool` role entries; there is **no persisted step trace** to rebuild the details view after restart |
| **Cancel** | No way to stop a long/infinite agent loop mid-turn; `agent/run` blocks until the loop finishes |
| **Verbosity** | Step trace is **always** shown; roadmap calls for summary-by-default + “Show details” toggle |
| **`stop_and_ask`** | Loop returns `status: "stopped"` with empty `final_text`; UI does not surface this distinctly |
| **Document links** | Successful `edit_paragraph` / comment mutations do not offer “go to paragraph” in the chat |

---

## 3. Design constraints (from the codebase)

- **Chat history scope.** One chat per **workspace** (architecture decision). History is **retained when switching or closing documents** within that workspace; the panel is not cleared on document open/close. Only an explicit **Clear chat** action or closing the workspace session clears it.
- **Conversation vs display.** `session.conversation` is the **LLM-facing** transcript (includes `tool` messages). The UI should **not** dump raw tool JSON on reload. Persist a separate, UI-oriented **turn log** alongside it (see §4.2).
- **Sync agent loop.** `AgentLoop.run()` is synchronous today. Cancel requires the loop to **poll a cancel flag between steps** while the route runs the loop in a **worker thread** so `POST …/agent/cancel` can set the flag without deadlocking the event loop.
- **No new LLM providers / tools.** M7 is panel + session/API wiring only. Unicode protection for agent edits remains **M9** ([M6b report §7.2](stage1_M6b_report.md)).
- **Frontend stack unchanged.** Tailwind CDN + vanilla JS in `workspace.js` / `workspace.css`; cache-busted static assets (`?v=mtime`).
- **Card UI untouched.** `/` and its chat modes stay as-is.

---

## 4. Files to create or modify

**Create:**

| File | Purpose |
|------|---------|
| `src/workspace/chat_log.py` (or equivalent) | `ChatTurn` dataclass + serialize/deserialize for UI turn log |
| `tests/test_workspace_chat.py` (or extend `test_workspace_api.py`) | Persistence, cancel, chat GET tests |

**Modify:**

| File | Change |
|------|--------|
| `src/workspace/state.py` | `chat_turns: list[ChatTurn]` on session; persist in `workspace.json`; restore on open |
| `src/agent/loop.py` | Optional `cancel_check: Callable[[], bool]`; return `status: "cancelled"` when set mid-turn |
| `src/routes/workspace.py` | `GET …/chat`; `POST …/agent/cancel`; run loop in executor + cancel flag; append `ChatTurn` in `_finalize`; extend `_result_to_json` if needed |
| `templates/workspace.html` | Chat header: **Show details** toggle, **Stop** (while running), **Clear chat** |
| `static/js/workspace.js` | Load/render turn log; running-state UX; cancel fetch; details toggle; document links; handle `stopped` / `cancelled` / `max_steps` |
| `static/css/workspace.css` | Chat toolbar, collapsed/expanded steps, document-link chips, stopped/cancelled banners |
| `docs/stage1_glossary.md`, `docs/stage1_decision_log.md`, `docs/stage1_implementation_plan.md`, this spec | Glossary / log / status / report (post-implementation) |

---

## 5. Backend API

### 5.1 Turn log persistence

Add a UI-facing turn log parallel to `conversation`:

```python
@dataclass
class ChatTurn:
    user_message: str
    final_text: str
    status: str                    # completed | stopped | max_steps | cancelled | awaiting_confirmation
    steps: list[dict]              # same shape as agent/run ``steps`` today
    pending_confirmation: dict | None = None
    created_at: str                # ISO-8601 UTC
```

**`workspace.json` — stay at `schema_version: 1`** (decision 3). Add an optional `chat_turns` array alongside the existing `conversation` field. Loaders treat a missing `chat_turns` key as `[]`. No schema bump or migration runner — the same pattern used when `conversation` was added in M4.

```json
{
  "schema_version": 1,
  "open_document": "manuscript.docx",
  "conversation": [ … ],
  "chat_turns": [ … ],
  "updated_at": "…"
}
```

On `agent/run` and `agent/confirm` completion, `_finalize` appends one `ChatTurn` (or updates the in-flight turn if confirm resumes the same user message — see implementation note below). Old workspaces without `chat_turns` load as `[]`.

**Confirm resume:** treat confirm as completing the **same** turn started by the preceding run (replace the last turn’s `status`/`steps`/`final_text` rather than appending a second turn with an empty user message).

### 5.2 `GET /api/workspace/{workspace_id}/chat`

Returns the persisted turn log for UI reload:

```json
{
  "turns": [ { …ChatTurn… }, … ],
  "pending_confirmation": { … } | null
}
```

Also restore `session.pending_confirmation` from the last turn if status was `awaiting_confirmation` and the server still holds it in memory (transient — if server restarted mid-confirm, drop pending and show the last turn as awaiting user action in the log only).

### 5.2a `POST /api/workspace/{workspace_id}/chat/clear`

Wipes UI history and LLM context for the workspace:

1. `session.conversation = []`
2. `session.chat_turns = []`
3. `session.pending_confirmation = None`
4. `session.touch()` + `persist()`

Returns `{ "cleared": true }`. Does **not** close the document or discard unsaved edits. Client clears the chat panel and shows the empty-state placeholder.

**Guard:** if a run is in progress (`run_in_progress`), return **409** (same as cancel-when-idle inverse — cannot clear mid-run).

### 5.3 Cancel in-flight run

```python
# POST /api/workspace/{workspace_id}/agent/cancel
# Body: {} (empty)
# Response: { "cancelled": true } | 409 if no run active
```

**Session fields (in-memory only):**

- `run_cancel_event: threading.Event | None`
- `run_in_progress: bool`

**Flow:**

1. `agent/run` sets `run_in_progress`, clears/creates cancel event, runs `loop.run(..., cancel_check=event.is_set)` inside `asyncio.to_thread` / executor.
2. `agent/cancel` sets the event; returns 200 when a run is active, 409 otherwise.
3. Loop checks `cancel_check()` at the **start of each tool step** (before `client.complete`). On cancel → return `AgentResult` with `status: "cancelled"`, partial `steps`, best-effort `final_text` (e.g. `"Run cancelled."`). **Mid-LLM-call cancellation** (abort an in-flight HTTP request to the provider) is **out of scope for M7** — it depends on streaming or request-level abort and is deferred until streaming is implemented (see §9).
4. `_finalize` still persists conversation + turn log; document state reflects tools executed **before** cancel.

**Client:** while a run is in flight, disable Send, show **Stop** → `POST …/agent/cancel`; also use `AbortController` on the fetch so the browser stops waiting (the server may still finish the current LLM HTTP call before observing the cancel flag — acceptable for M7).

### 5.4 Agent run response (unchanged shape, richer `status`)

Existing `_result_to_json` already exposes `status`, `final_text`, `steps`, `pending_confirmation`. Ensure these values are used consistently:

| `status` | UI treatment |
|----------|----------------|
| `completed` | Normal assistant bubble |
| `awaiting_confirmation` | Summary + confirm card (existing) |
| `stopped` | Banner: agent stopped (`stop_and_ask` policy); show last error prominently |
| `max_steps` | Banner: step limit reached; show partial steps if details on |
| `cancelled` | Banner: run cancelled by user |

---

## 6. Client behavior (`workspace.js`)

### 6.1 Load history on workspace open

After `POST /open` succeeds (and when opening a document **without** wiping chat):

1. `GET …/chat` → render all `turns` (user bubble + agent bubble per turn).
2. Rehydrate pending confirmation from response if present.

**Stop calling `resetChat()` on document open or close** — only clear the panel when the workspace session closes or the user clicks **Clear chat**.

### 6.2 Show details toggle

- **Default off:** each agent turn shows `final_text` only (plus status banners when not `completed`).
- **Toggle on** (persist preference in `localStorage` key `ws_chat_show_details`): render `steps` list beneath each agent message (current `renderSteps` markup, enhanced per §6.4).
- Toggle lives in the chat panel header; applies to **new and reloaded** turns.

### 6.3 Running state + cancel

- On Send: append user message, show “Thinking…”, set `state.agentRunning = true`, show Stop, disable input.
- On response / error / cancel: clear running state.
- Stop → `POST …/agent/cancel` then await the run request to finish (or abort client-side).

### 6.4 Step rendering + document links

Enhance each step row:

| Tool (mutating) | Link when step succeeded |
|-----------------|--------------------------|
| `edit_paragraph` | “Paragraph `{para_id}`” → scroll `#ws-document-body [data-para-id="…"]` into view + flash (reuse M6a `flash()`) |
| `add_comment`, `add_comment_reply` | “Comment thread `{thread_id}`” → scroll side list / anchor (reuse `scrollToAnchor`) |
| `find_in_document` | Optional “{n} matches” expand — **out of scope** unless trivial; link first match only is enough |

Errors: keep `✗ {message}`; when details on, show `error.error` code in muted text.

### 6.5 `stop_and_ask` mode

When `result.status === "stopped"`, show an agent message with the last step’s error and **do not** imply success. User sends a follow-up message to continue (existing conversation flow).

---

## 7. Resolved decisions (2026-06-01)

1. **Chat scope on document switch/close.** **Keep workspace-scoped history** when switching or closing documents (fix M5 `resetChat()`). Aligns with the architecture decision (one chat per workspace, not per document).

2. **Clear chat control.** **Include in M7.** Header action + `POST …/chat/clear` wipes `conversation` and `chat_turns` on the server and clears the panel. Blocked while an agent run is in progress.

3. **`workspace.json` schema.** **Stay at `schema_version: 1`.** Add optional `chat_turns`; missing key → `[]`. No v2 bump — backward-compatible additive field, same approach as `conversation` in M4; avoids migration code for a dev-stage feature.

4. **Cancel granularity.** **Between tool steps only for M7.** Cancel is checked before each loop iteration (before the next LLM call). Aborting an in-flight provider HTTP request requires streaming or request-level abort — **defer until streaming is implemented** (noted in §9; log in decision log at implementation).

---

## 8. Tests

**Automated** (`tests/test_workspace_api.py` and/or `tests/test_workspace_chat.py`):

| Test | Asserts |
|------|---------|
| `GET …/chat` after agent run | Returns persisted turns with `user_message`, `final_text`, `steps` |
| Turn log survives `open_workspace` | New session id, same folder → turns restored from `workspace.json` |
| `POST …/agent/cancel` | With a slow mocked LLM, cancel returns `status: "cancelled"`, partial steps persisted |
| Cancel when idle | 409 |
| Confirm flow | Single turn log entry updated (not duplicated) |
| `stop_and_ask` | Mock tool error + policy → `status: "stopped"` surfaced in JSON |
| `POST …/chat/clear` | Wipes turns + conversation; 409 if run in progress |

**Manual QA** (documented in report):

- Multi-turn task retains context across turns.
- Reload page / re-open folder → chat history visible (summary mode).
- Toggle details → step trace appears for current and reloaded turns.
- Long run → Stop cancels; document reflects partial edits only.
- `edit_paragraph` step link scrolls to the correct block.
- Switch or close document within workspace → chat history **remains** (Q1).
- Clear chat → panel empty, next agent turn starts fresh context.

Full suite stays **green, 0 warnings**; card UI at `/` unaffected.

---

## 9. Out of scope for M7

- **Unicode protection** for agent edits → **M9** (already logged).
- **Streaming tokens** / partial assistant text while the model generates. When streaming lands, extend cancel to abort the in-flight provider request (today: between-step cancel only — decision 4).
- **Mid-LLM-call cancel** without streaming (same deferral as above).
- **Per-document or per-thread chat tabs.**
- **Checkpoint restore UI** in the chat panel (checkpoints API exists; dedicated UI is later).
- **Editing/regenerating** past user messages.
- **Anthropic provider** (provider-neutral client exists; wiring is not M7).
- Automated browser/E2E tests.

---

## 10. Acceptance criteria (from plan)

- [x] Multi-turn conversation with context retained (LLM + UI).
- [x] User can cancel a long-running agent task.
- [x] Chat history reloads when workspace reopens (turn log + sensible rendering).
- [x] Summary-by-default with optional step details toggle.
- [x] Inline tool errors readable; `stop_and_ask` visibly distinct.
- [x] Mutating steps link to document locations where applicable.
