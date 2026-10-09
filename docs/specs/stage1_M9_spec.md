# Stage 1 — Milestone 9 Spec: Integration and hardening

**Status:** Approved (M9a + M9b) — decisions resolved 2026-06-03 (§8); M9c gets its own spec post-pilot
**Plan reference:** [Milestone 9](../stage1_implementation_plan.md#milestone-9--integration-and-hardening) · **Roadmap:** Stage 1 closeout
**Depends on:** M1–M8 (all prior milestones)

---

## 1. Goal

Close out Stage 1: harden the agent edit path, finish the workspace config surface, run a real-manuscript pilot, and make the workspace the primary experience. M9 is the **final** Stage 1 milestone — after it, Stage 1 is "done" and ready for the pilot users.

M9 is heterogeneous: two concrete **code** workstreams, one **manual** pilot, and a few **decision-gated** closeout steps. To keep diffs reviewable and the spec→approve→implement→report cycle clean (as with M6a/M6b), M9 is **split** (decision Q1) into:

- **M9a — Agent Unicode protection** (code + tests). Self-contained; highest user value (fixes a known corruption bug from M6b QA).
- **M9b — Workspace config in the settings UI** (code + tests). Self-contained; closes the M7 QA gap.
- **M9c — Pilot + closeout** (manual + decision-gated): end-to-end walkthrough on a real manuscript, default-route flip (`/` → `/workspace`, card UI → `/legacy`), dependency-pinning note, audit-doc update, and marking Stage 1 complete.

**Spec/report structure (decision Q1):** this single umbrella spec **is** the spec for M9a and M9b — they are detailed concretely below, so no separate `M9a`/`M9b` spec docs are created (avoids duplication/drift; differs from M6 where the umbrella was thin). Each sub-milestone gets its **own report** as it lands (`stage1_M9a_report.md`, `stage1_M9b_report.md`). **M9c gets its own dedicated spec** once the pilot has run and the route-flip details are concrete.

---

## 2. Current state (baseline)

| Area | Today |
|------|--------|
| **Agent edits** | `edit_paragraph(new_text=…)` writes the model's re-typed paragraph verbatim. The model sometimes corrupts special Unicode (`≥`→garbled) when re-typing — surfaced in [M6b report §7.2](stage1_M6b_report.md). |
| **Card UI Unicode protection** | `src/llm_prompts.py` (`_protect_unicode`/`_restore_unicode`) + `src/llm_transport.py` (`UNICODE_PROTECTION_MAP`, 34 chars). Replaces special chars with `__UNICODE_*__` placeholders before the LLM call, restores after. The **agent path has no equivalent**. |
| **Agent transport seam** | `src/agent/llm_tools.py` `AgentLLMClient.complete(messages, tools)` — the single boundary where messages go to the provider and responses come back. |
| **Workspace config** | `WorkspaceConfig` (`max_checkpoints`, `max_agent_steps`, `checkpoint_policy`, `tool_error_policy`); `GET`/`PUT /api/workspace/{id}/config` work and are tested. **No UI control** — the settings modal only edits LLM credentials (localStorage). Surfaced in [M7 report §7.2](stage1_M7_report.md). |
| **Settings modal** | `templates/workspace.html` + `static/js/workspace.js` (`openSettings`/`saveSettings`): provider, model, API key / Ollama URL+model. All in `localStorage`. |
| **Routing** | `/` = card UI (regression baseline); `/workspace` = agentic UI. Card-UI integration tests target `/`. |
| **Desktop app** | `desktop_app.py` `Api` exposes `pick_folder()` (used by M5) and `save_export()` (native save dialog, used by the card UI). Workspace Save/Save-a-copy use the JSON API only. |

---

## 3. Design constraints (from the codebase)

- **Do not touch the card UI baseline.** `src/llm_prompts.py` / `src/llm_transport.py` and `/` stay as-is. M9a **copies** the placeholder map into the agent path rather than refactoring a shared module out of `llm_transport` (extraction would edit the card path — out of scope). The duplication is deliberate; note it in the report.
- **Localized transport seam.** Unicode protection belongs at `AgentLLMClient`'s provider boundary, not scattered across tools. Persisted `Message`s and the turn log keep **real Unicode**; only the copies sent to the provider carry placeholders.
- **Two config scopes.** LLM credentials are **global** (`localStorage`); workspace config is **per-open-folder** (`.stet/config.json` via the API). The settings modal must treat them differently (workspace-config controls require an open workspace).
- **Quality gates.** Full suite green, 0 warnings; every new public function gets a test; card UI at `/` and its integration tests keep passing.

---

## 4. M9a — Agent Unicode protection

### 4.1 Approach

Add a symmetric transform at the `AgentLLMClient` boundary:

- **Protect (char → placeholder)** every string the model **reads**: the `content` of each outbound message (user / tool / assistant text) and string values inside prior assistant `tool_calls` arguments. The model therefore only ever sees `__UNICODE_GTE__`, never a corruptible `≥`.
- **Restore (placeholder → char)** every string the model **writes back**: `LLMToolResponse.text` and every string value in each returned `ToolCall.arguments`.

Because the model only sees placeholders, when it re-types a paragraph it reproduces the placeholder token (which it cannot corrupt), and we restore the exact original character. New characters the model genuinely introduces are unaffected (it would have to emit a placeholder to round-trip, which is acceptable — the goal is preventing corruption of *existing* symbols).

### 4.2 Files

**Create:**

| File | Purpose |
|------|---------|
| `src/agent/unicode_protection.py` | `UNICODE_PROTECTION_MAP` (copied from `llm_transport`), `RESTORATION_MAP`, and `protect(text)` / `restore(text)` / `protect_arguments(obj)` / `restore_arguments(obj)` (recursive over dict/list/str) |
| `tests/test_agent_unicode.py` | Round-trip + seam tests |

**Modify:**

| File | Change |
|------|--------|
| `src/agent/llm_tools.py` | Protect message content in `_message_to_openai` / `_message_to_ollama`; restore `text` + tool-call arguments when normalizing the provider response in `_call_openai` / `_call_ollama` |

### 4.3 Behavior details

- The map is **copied verbatim** from `llm_transport.UNICODE_PROTECTION_MAP` (34 entries: `≥ ≤ ± ≠ ≈ ° × ÷ µ` Greek letters, arrows, set/logic symbols). Placeholders are `__UNICODE_*__` (alphanumeric + underscore → safe inside JSON tool arguments).
- Only **string values** are transformed — never tool names, JSON keys, numbers, or booleans.
- Transform **copies**: the stored `Message` list and persisted `conversation` keep real Unicode. Re-protection on each turn is idempotent and consistent.
- Always-on (no config flag) — mirrors the card UI.

### 4.4 Tests

| Test | Asserts |
|------|---------|
| `protect`/`restore` round-trip | `restore(protect(s)) == s` for a string with several mapped chars |
| `protect` only maps known chars | Unmapped Unicode (e.g. Japanese) passes through untouched |
| `restore_arguments` recursion | Nested `{"new_text": "x ≥ y"}` → placeholder out, restored back |
| OpenAI seam | Monkeypatch `_client.chat.completions.create` to return a tool call whose `new_text` contains a placeholder → `complete()` returns a `ToolCall` with the real `≥` |
| Outbound protection | `_message_to_openai`/`_message_to_ollama` on a message containing `≥` emits the placeholder in `content` |
| Loop integration | A scripted run where a tool result contains `≥` and the (mock) model echoes the placeholder in `edit_paragraph` → the applied edit contains the real `≥` (validates end-to-end via the real `AgentLLMClient`, not `MockLLMClient`) |

---

## 5. M9b — Workspace config in the settings UI

### 5.1 Approach

Extend the existing **Agent settings** modal with a **Workspace** section exposing the four `WorkspaceConfig` keys, backed by the existing `GET`/`PUT /api/workspace/{id}/config`. LLM-credential handling is unchanged.

### 5.2 Files

**Modify:**

| File | Change |
|------|--------|
| `templates/workspace.html` | Add a "Workspace settings" block to the settings modal: `tool_error_policy` (select: `report_and_skip` / `stop_and_ask`), `checkpoint_policy` (select: `per_agent_turn` / `per_mutating_tool`), `max_agent_steps` (number), `max_checkpoints` (number) |
| `static/js/workspace.js` | On open settings: if a workspace is open, `GET …/config` and populate + enable the block; else disable it with a "Open a folder to edit workspace settings" note. On save: keep saving LLM creds to `localStorage`, and if a workspace is open, `PUT …/config` with the four values |
| `tests/test_workspace_page.py` | Assert the new form controls render in the page |

The config API and its validation/coercion already exist and are tested (`tests/test_workspace_config.py`, M4). No backend change.

### 5.3 Behavior details

- Workspace-config controls are **disabled** until a folder is open (config is per-workspace).
- Saving config calls `PUT …/config`; on success, toast and update `state` (the running config is read per-run from the session, so the next agent turn picks it up).
- Invalid numbers are coerced server-side (existing behavior: invalid value → per-key default, logged). Client should still constrain inputs (`min=1`).

### 5.4 Tests

| Test | Asserts |
|------|---------|
| `test_workspace_page` | Settings modal markup includes the four workspace-config controls (ids present) |
| (existing) `test_workspace_config` | `PUT …/config` round-trips `tool_error_policy` etc. — already covered |

Manual QA (report): change `tool_error_policy` to `stop_and_ask` in the UI, trigger a tool error, confirm the **stopped** banner (this is the manual path M7 QA could not exercise).

---

## 6. M9c — Pilot + closeout (outline; firms up post-pilot)

Decision-gated and manual; full details land in a dedicated M9c spec post-pilot (decisions in §8).

- **End-to-end pilot** on a real manuscript from `test_data/local/`: open folder (docx + reference PDF/XLSX/RTF/PPTX) → open in viewer → agent addresses a comment → tracked change visible → manual TipTap edit → checkpoint restore → export → verify track changes in Word. Documented in the M9c report.
- **Default-route flip** (decision Q2): `/` → redirect to `/workspace`; card UI to `/legacy`. Requires repointing card-UI integration tests (`test_routes.py`, `test_integration.py`) from `/` to `/legacy`. **Gated on explicit go-ahead after pilot sign-off.**
- **Dependency pinning** (decision Q4): note-only for Stage 1; pin `requirements.txt` when CI/distribution is set up.
- **Audit doc + status**: update `docs/pre_transition_audit.md` Tier 2 items; mark Stage 1 complete in the plan and roadmap.

**Deferred (not in M9c):** desktop "save anywhere" native dialog (decision Q3) — current save is in-workspace only, which is sufficient for the pilot; saving outside the workspace folder is deferred past Stage 1.

---

## 7. Out of scope for M9

- **Refactoring the card UI** Unicode functions into a shared module (M9a copies the map instead).
- **New LLM providers** (Anthropic) — provider-neutral client exists; wiring is post-Stage-1.
- **Streaming / mid-LLM cancel** (deferred since M7).
- **Image reading** (`.jpeg`/`.png`) — Stage 2 backlog (M8 QA).
- **Removing the card UI** — it moves to `/legacy`; removal is a later cleanup ([plan](../stage1_implementation_plan.md): "Remove upload flow and `sessions` dict once `/legacy` is removed").
- **Margin comment balloons, per-change accept/reject** — Stage 3.

---

## 8. Resolved decisions (2026-06-03)

1. **Split M9? — YES.** Proceed as **M9a / M9b / M9c**. **No separate `M9a`/`M9b` spec docs**: this umbrella spec already details them concretely, so duplicating would invite drift (differs from M6, where the umbrella was thin). Each sub-milestone gets its **own report** (`stage1_M9a_report.md`, `stage1_M9b_report.md`); **M9c gets its own dedicated spec** post-pilot when route-flip details are concrete.

2. **Default-route flip — YES, in M9c.** "Flip" = which UI is served at `/`. Currently `/` = card UI, `/workspace` = agentic UI. The flip makes `/` redirect to `/workspace` and moves the card UI to `/legacy`. Done in **M9c, gated on explicit go-ahead after the pilot.** Repoints card-UI integration tests from `/` to `/legacy`.

3. **Desktop save dialog — DEFER.** Current save is in-workspace only (target path must resolve inside the active workspace folder), which is sufficient. "Save anywhere" (native OS dialog to an arbitrary location) is deferred past Stage 1.

4. **Dependency pinning — note-only for Stage 1.** Pin `requirements.txt` versions when CI/distribution is set up.

5. **Unicode map parity — verbatim copy.** Copy the card UI's character map as-is for parity; fewer surprises.

---

## 9. Tests (M9a + M9b)

Automated, per §4.4 and §5.4. Full suite stays **green, 0 warnings**; card UI at `/` and its integration tests unaffected (until the M9c route flip, which updates them deliberately).

Manual QA (report): agent edit of a paragraph containing `≥`/`±` preserves the symbols in the tracked change (M9a); changing `tool_error_policy` in the UI produces the stopped banner on a tool error (M9b).

---

## 10. Acceptance criteria (from plan)

- [x] Agent `edit_paragraph` preserves special Unicode (`≥`, `≤`, `±`, …) — no corruption when the model re-types a paragraph. *(M9a — done; [report](stage1_M9a_report.md))*
- [x] Workspace config (`tool_error_policy`, `checkpoint_policy`, `max_agent_steps`, `max_checkpoints`) editable from the settings UI. *(M9b — done; [report](stage1_M9b_report.md))*
- [ ] End-to-end pilot on a real manuscript passes (open → agent edit → manual edit → checkpoint restore → export → verify in Word). *(M9c)*
- [ ] Default route flipped: `/` → `/workspace`, card UI → `/legacy` (gated on post-pilot go-ahead). *(M9c, decision Q2)*
- [ ] Full suite green, 0 warnings; card UI still functional.
- [ ] Stage 1 marked complete in the plan/roadmap. *(M9c)*
