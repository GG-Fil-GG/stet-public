# Stage 1 — Milestone 3 Spec: Agent loop

**Status:** Approved & Implemented 2026-05-30 — see [report](stage1_M3_report.md)
**Plan reference:** [Milestone 3](../stage1_implementation_plan.md#milestone-3--agent-loop)

---

## 1. Goal

Build a **multi-turn, provider-neutral tool-calling loop** that connects an LLM to the M1/M2 tool registry: the model receives the tools' JSON schemas, emits tool calls, the loop executes the registered handlers (injecting `model` / `workspace_root`), feeds results back, and iterates until the model produces a final answer or a stop condition is hit.

This is the first milestone where the agent can actually *do* something end-to-end: given a user message and a loaded document, drive `list_comments → read_paragraph → edit_paragraph → …` and answer.

Out of scope by design: any UI, any route, workspace session/persistence, reading config from `.stet/config.json`. Those are M4/M5/M7. M3 is a pure-Python, mock-testable engine.

---

## 2. Design constraints (from the codebase)

- **Legacy is the baseline.** `LLMHandler` (suggestion + chat for the `/` card UI) and `src/llm_transport.py` stay untouched as the regression baseline. M3 adds a *parallel* tool-calling path; it does not refactor the suggestion/chat path.
- **Sync core.** The existing LLM clients are sync (OpenAI `chat.completions.create`, Ollama via `requests`). The M3 loop is **sync** and pure-Python so it is unit-testable with a mock client and no event loop. Wrapping it for async routes (`asyncio.to_thread`) is an M4/M7 concern.
- **Provider-neutral.** One canonical tool schema (`ToolSpec.json_schema()`); thin per-provider adapters translate to OpenAI `tools` / Ollama tools. Anthropic plugs in later as a transport-only change ([Resolved decisions §2](../stage1_implementation_plan.md#2-anthropic-and-model-agnostic-design)).
- **Tools already exist.** The registry has 11 tools with `requires_model` / `requires_workspace_root` flags. The loop reads those flags to inject context; the LLM supplies only schema params.

---

## 3. Files to create or modify

| File | Change |
|------|--------|
| `src/agent/messages.py` | New — minimal `Message` type (role, content, tool calls, tool results) for the loop's conversation, distinct from the UI/session `ChatMessage`. |
| `src/agent/llm_tools.py` | New — provider-neutral tool-calling client: translate registry schemas → provider tool format, make the call, parse tool calls / final text. OpenAI + Ollama adapters. |
| `src/agent/loop.py` | New — `AgentLoop`: orchestrates the call→tool→result cycle, step cap, checkpoint policy, error policy, verbosity, and the overwrite-confirmation pause. |
| `src/agent/prompts.py` | New — the agent **system prompt** (task-oriented; separate from the medical-writer suggestion prompt). |
| `src/agent/registry.py` | Add `mutating: bool = False` to `ToolSpec`; flag the model-mutating tools (drives `per_mutating_tool` checkpointing). |
| `src/agent/__init__.py` | Export the new public surface (`AgentLoop`, result/types, client). |
| `tests/test_agent_loop.py` | New — mock-LLM scripted sequences (no network). |
| `tests/test_llm_tools.py` | New — schema translation + tool-call parsing per provider (mock responses). |
| `tests/test_agent_integration.py` | New — one real-LLM smoke test, skipped without `OPENAI_API_KEY`. |

No changes to `src/llm_handler.py`, `src/llm_transport.py`, `src/llm_prompts.py`, routes, or templates.

---

## 4. Public API surface

### 4.1 Messages (`src/agent/messages.py`)

```python
Role = Literal["system", "user", "assistant", "tool"]

@dataclass
class ToolCall:
    id: str                 # provider-assigned call id (echoed back in the tool result)
    name: str               # tool name (must be in the registry)
    arguments: dict         # parsed JSON args (LLM-facing params only)

@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)  # assistant turns
    tool_call_id: str | None = None                           # tool-result turns
    name: str | None = None                                   # tool name on tool-result turns
```

The loop is **stateless per call**: it takes the running `list[Message]` in and returns the extended list out. Persisting conversation to the workspace session is M4.

### 4.2 LLM tool client (`src/agent/llm_tools.py`)

```python
@dataclass
class LLMToolResponse:
    text: str                       # assistant free-text ("" if only tool calls)
    tool_calls: list[ToolCall]      # empty when the model is done

class AgentLLMClient:
    """Provider-neutral tool-calling chat client.

    Reuses src/llm_config for model/key/url defaults; constructs its own
    provider client so the legacy LLMHandler is untouched.
    """
    def __init__(self, provider: str = "openai", model: str | None = None,
                 api_key: str | None = None, ollama_url: str | None = None,
                 temperature: float | None = None): ...

    def complete(self, messages: list[Message], tools: list[ToolSpec]) -> LLMToolResponse:
        ...
```

- **Adapters** (internal): `_to_openai_tools(tools)` / `_to_ollama_tools(tools)` translate `ToolSpec.json_schema()` → provider `tools` arrays; `_call_openai(...)` / `_call_ollama(...)` issue the request and normalize the response into `LLMToolResponse`.
- **OpenAI:** `chat.completions.create(model, messages, tools=…, tool_choice="auto")`; read `message.tool_calls`. `arguments` arrive as a JSON **string** → `json.loads`.
- **Ollama:** `POST /api/chat` with `tools=…`, `stream: false`; read `message.tool_calls`. `arguments` arrive already **parsed** (dict). Confirmed working locally against `llama3.1:latest` on Ollama 0.24.0 (see [Resolved decisions §6.2](#6-resolved-decisions)).

**Provider response differences the adapter normalizes** (both into `LLMToolResponse`):

| | OpenAI | Ollama |
|---|---|---|
| Call site | `chat.completions.create` | `POST /api/chat` (sync `requests`) |
| Tool schema | `{"type":"function","function":{name,description,parameters}}` | identical |
| `arguments` | JSON **string** (`json.loads`) | already a **dict** |
| Tool-result message | `{"role":"tool","tool_call_id":…,"content":…}` | `{"role":"tool","tool_name":…,"content":…}` |

### 4.3 The loop (`src/agent/loop.py`)

```python
class CheckpointPolicy(str, Enum):
    PER_AGENT_TURN = "per_agent_turn"
    PER_MUTATING_TOOL = "per_mutating_tool"

class ToolErrorPolicy(str, Enum):
    REPORT_AND_SKIP = "report_and_skip"   # default: feed the error back to the model, keep going
    STOP_AND_ASK = "stop_and_ask"         # halt the turn, surface the error to the user

@dataclass
class AgentStep:
    tool_name: str
    arguments: dict
    result: dict | None          # tool success payload
    error: dict | None           # ToolError.to_dict() on failure

@dataclass
class AgentResult:
    messages: list[Message]              # full conversation incl. this turn
    final_text: str                      # assistant's final answer ("" if paused/aborted)
    steps: list[AgentStep]               # ordered tool-call trace
    status: Literal["completed", "max_steps", "stopped", "awaiting_confirmation"]
    pending_confirmation: PendingConfirmation | None = None

@dataclass
class PendingConfirmation:
    """A guarded writer asked to overwrite; the loop paused (never auto-confirms)."""
    tool_name: str
    arguments: dict              # the exact args to re-issue with overwrite=True
    message: str                 # human-readable prompt for the user

class AgentLoop:
    def __init__(self, client: AgentLLMClient, *,
                 model: DocumentModel | None,
                 workspace_root: Path | str | None,
                 checkpoint_store: CheckpointStore | None = None,
                 max_steps: int = 20,
                 checkpoint_policy: CheckpointPolicy = CheckpointPolicy.PER_AGENT_TURN,
                 error_policy: ToolErrorPolicy = ToolErrorPolicy.REPORT_AND_SKIP,
                 verbose: bool = False): ...

    def run(self, user_message: str, history: list[Message] | None = None) -> AgentResult:
        ...

    def resume(self, pending: PendingConfirmation, confirmed: bool,
               history: list[Message]) -> AgentResult:
        """Continue after a PendingConfirmation: re-issue with overwrite=True if
        confirmed, else feed a declination back to the model."""
        ...
```

**Loop algorithm (`run`):**

1. If `checkpoint_policy == per_agent_turn` and a `checkpoint_store` + `model` are present, `save` one checkpoint labelled with the user message.
2. Build `messages = [system, *history, user]`.
3. Up to `max_steps` iterations:
   - `resp = client.complete(messages, tools=list_tools())`.
   - Append the assistant message (text + tool_calls).
   - If `resp.tool_calls` is empty → **completed**; return with `final_text`.
   - For each tool call:
     - Look up the `ToolSpec`. Unknown tool → `ToolError("unknown_tool", …)`-style result.
     - If `checkpoint_policy == per_mutating_tool` and `spec.mutating` → `save` a checkpoint first.
     - Inject `model` (if `requires_model`) / `workspace_root` (if `requires_workspace_root`).
     - Call the handler.
       - **Success** → append a `tool` message with the JSON result; record an `AgentStep`.
       - **`ToolError("overwrite_requires_confirmation")`** → stop the turn, return `status="awaiting_confirmation"` with a `PendingConfirmation` (never auto-confirm; [Resolved decisions §4](../stage1_implementation_plan.md#4-save-export-and-create-document)).
       - **Other `ToolError`** → `report_and_skip`: append the error as the tool result and continue; `stop_and_ask`: return `status="stopped"` with the error surfaced.
4. If the step cap is reached → `status="max_steps"`, return a partial summary.

**Injection:** the LLM never supplies `model` / `workspace_root`; the loop injects them from its constructor based on the registry flags. Path-bearing args supplied by the LLM (`read_document`/`read_file` `path`) are passed through as-is in M3 (see §6.5).

### 4.4 Registry change

Add `mutating: bool = False` to `ToolSpec`. Mutating (model-changing) tools: `edit_paragraph`, `add_comment`, `remove_comment`, `add_comment_reply`. Non-mutating: all readers, `list_workspace_files`, `read_*`, `list_comments`, `export_document`, `create_document` (these write **files**, not the in-memory model, so a model checkpoint is not what protects them — undo of a file write is out of scope for Stage 1).

---

## 5. Tests to write

- `tests/test_llm_tools.py` (mock provider responses — no network):
  - `ToolSpec.json_schema()` → OpenAI tools array shape (name/description/parameters) for every registered tool.
  - Same for the Ollama tools shape.
  - Parsing a provider response with `tool_calls` → `list[ToolCall]` with parsed args; parsing a plain-text response → `final_text`, no tool calls.
- `tests/test_agent_loop.py` (a `MockLLMClient` returning a **scripted** sequence of `LLMToolResponse`s):
  - **Happy path:** script `list_comments` → `edit_paragraph` → final text; assert the document changed, the trace has 2 steps, `status="completed"`.
  - **Injection:** a `requires_model` tool receives the loop's model; a `requires_workspace_root` tool receives the workspace root; the LLM args never contain these.
  - **max_steps:** a script that always calls a tool terminates at `max_steps` with `status="max_steps"`.
  - **report_and_skip:** a tool raises a `ToolError`; the error is fed back as the tool result and the loop continues to a final answer.
  - **stop_and_ask:** same error with `error_policy=STOP_AND_ASK` → `status="stopped"`.
  - **overwrite confirmation:** `export_document` to an existing path → `status="awaiting_confirmation"` with `PendingConfirmation`; `resume(..., confirmed=True)` completes the write; `resume(..., confirmed=False)` does not write.
  - **checkpoint policy:** `per_agent_turn` saves exactly one checkpoint per `run`; `per_mutating_tool` saves one per mutating call and none for read-only calls.
  - **unknown tool:** a scripted call to a non-registered tool surfaces a structured error result (does not crash).
- `tests/test_agent_integration.py`:
  - One real OpenAI call (`@pytest.mark.skipif(not OPENAI_API_KEY)`): given the synthetic fixture loaded, ask "summarise the open comments" and assert at least one `list_comments` call happened and a non-empty final answer returned.
  - **Optional Ollama smoke test**, skipped by default (gated on an explicit env flag, e.g. `RUN_OLLAMA_TESTS=1`, and a reachable Ollama). Llama 3.1 8B tool selection is "Good" but not as reliable as OpenAI, so this is a manual/opt-in check, never part of the default suite.

**Baseline:** full suite green, **0 warnings**; legacy `/` card UI untouched.

---

## 6. Resolved decisions

All seven resolved with the project owner on 2026-05-30.

1. **Transport seam → new standalone client.** A new `AgentLLMClient` in `src/agent/llm_tools.py` reuses `src/llm_config` for defaults but builds its own provider client; `LLMHandler` / `llm_transport.py` (the card-UI baseline) are untouched.

2. **Both OpenAI and Ollama in M3.** Verified the existing local model works: a live `/api/chat` tool call against `llama3.1:latest` (Ollama 0.24.0) returned a correct structured `tool_calls` response — **no new model download needed**. Llama 3.1 8B tool selection is rated "Good" (less reliable than OpenAI for long multi-step chains), so the core loop tests use a deterministic mock and the Ollama integration test is opt-in/skipped by default. (`qwen2.5` is the usual upgrade if more reliable local tool use is wanted later — not needed for M3.)

3. **Add `mutating: bool` to `ToolSpec`.** Approved; flags the model-mutating tools for `per_mutating_tool` checkpointing.

4. **Loop is stateless per call** (history in → messages out). Conversation persistence into the workspace session is **M4**.

5. **Defer path-resolution for `read_document` / `read_file` to M4.** M3 passes LLM-supplied paths through; the workspace session will resolve them against the workspace root in M4. M3 tests use explicit paths.

6. **Agent system prompt** — a concise, sensible default in `src/agent/prompts.py` (task-oriented: use tools to inspect/edit the open document, tracked changes by default, never overwrite without confirmation, summarise what was done). Tunable later.

7. **Agent edit defaults:** author `"Stet"`, `track_changes=True`. The loop does not override the tool defaults.

---

## 7. Out of scope for this milestone

- Any route, template, `desktop_app.py`, or UI change (chat panel is **M7**, workspace API is **M4**).
- Reading `max_agent_steps` / `checkpoint_policy` / provider+model from `.stet/config.json` — **M4** (M3 takes them as constructor args / defaults).
- Workspace session, conversation persistence, path↔open-model resolution — **M4**.
- Anthropic adapter — later (transport-only change; the seam is built now).
- Streaming tokens to a client — not in Stage 1 as currently planned.
- Async transport — the loop is sync; async wrapping is M4/M7.
```
