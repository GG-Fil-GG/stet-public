"""Agent tool-calling loop (Stage 1, Milestone 3).

``AgentLoop`` drives the call→tool→result cycle: it sends the user message plus
the registry's tool schemas to an :class:`~src.agent.llm_tools.AgentLLMClient`,
executes any tool calls the model returns (injecting ``model`` / ``workspace_root``
per the registry flags), feeds the results back, and iterates until the model
answers, an error policy halts it, a guarded write needs confirmation, or the
``max_steps`` cap is reached.

Scope (M3): a pure-Python, synchronous, mock-testable engine. It does not own
conversation persistence, config loading, route wiring, or path resolution —
those are M4+. Config values (``max_steps``, ``checkpoint_policy``) arrive as
constructor args.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from src.checkpoints import CheckpointStore
from src.document_model import DocumentModel
from .errors import ToolError
from .llm_tools import AgentLLMClient
from .messages import Message, ToolCall
from .prompts import get_agent_system_prompt
from .registry import ToolSpec, get_tool, list_tools
from .tools import resolve_in_workspace

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .run_transcript import RunTranscript

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 20


def _summarize_args(arguments: dict) -> str:
    """One-line, size-bounded arg summary for per-tool INFO logs."""
    parts = []
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 60:
            parts.append(f"{key}=<{len(value)} chars>")
        else:
            parts.append(f"{key}={value!r}")
    return ", ".join(parts)


class CheckpointPolicy(str, Enum):
    """When the loop snapshots the document model."""

    PER_AGENT_TURN = "per_agent_turn"        # one snapshot before each user message
    PER_MUTATING_TOOL = "per_mutating_tool"  # one snapshot before each mutating tool


class ToolErrorPolicy(str, Enum):
    """What the loop does when a tool raises a (non-confirmation) ToolError."""

    REPORT_AND_SKIP = "report_and_skip"  # feed the error back to the model, continue
    STOP_AND_ASK = "stop_and_ask"        # halt the turn, surface the error


AgentStatus = Literal["completed", "max_steps", "stopped", "awaiting_confirmation", "cancelled"]


@dataclass
class AgentStep:
    """One executed tool call in the turn's trace."""

    tool_name: str
    arguments: dict           # LLM-supplied args only (no injected model/workspace_root)
    result: dict | None = None
    error: dict | None = None


@dataclass
class PendingConfirmation:
    """A guarded writer asked to overwrite; the loop paused (never auto-confirms)."""

    tool_name: str
    arguments: dict   # exact LLM args; re-issued with overwrite=True on confirm
    message: str


@dataclass
class AgentResult:
    """The outcome of a turn."""

    messages: list[Message]
    final_text: str
    steps: list[AgentStep]
    status: AgentStatus
    pending_confirmation: PendingConfirmation | None = None


# Internal per-call outcome marker.
_OK, _ERROR, _CONFIRM = "ok", "error", "confirm"


class AgentLoop:
    """Orchestrates a tool-calling turn against a loaded document."""

    def __init__(
        self,
        client: AgentLLMClient,
        *,
        model: DocumentModel | None = None,
        workspace_root: Path | str | None = None,
        checkpoint_store: CheckpointStore | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        checkpoint_policy: CheckpointPolicy = CheckpointPolicy.PER_AGENT_TURN,
        error_policy: ToolErrorPolicy = ToolErrorPolicy.REPORT_AND_SKIP,
        system_prompt: str | None = None,
        transcript: "RunTranscript | None" = None,
    ) -> None:
        self.client = client
        self.model = model
        self.workspace_root = workspace_root
        self.checkpoint_store = checkpoint_store
        self.max_steps = max_steps
        self.checkpoint_policy = checkpoint_policy
        self.error_policy = error_policy
        self.system_prompt = system_prompt or get_agent_system_prompt()
        # Optional per-run transcript sink (post-M9c diagnostic). None in tests
        # and pure-engine use; the route attaches one so a stopped/crashed run is
        # still reviewable under .stet/runs/.
        self.transcript = transcript

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(
        self,
        user_message: str,
        history: list[Message] | None = None,
        *,
        cancel_check: Callable[[], bool] | None = None,
        live_steps: list[AgentStep] | None = None,
    ) -> AgentResult:
        """Process one user message and return the turn's result.

        ``history`` holds prior user/assistant/tool messages (no system message —
        the loop prepends its own). The loop is stateless: it returns the full
        message list for the caller to persist (M4).

        ``cancel_check`` is polled before each LLM call and between tool calls
        (M7/M9c-prep); when it returns True the turn ends with
        ``status="cancelled"``.

        ``live_steps``, when provided, is used as the turn's step accumulator so
        the caller can observe progress mid-run (M9c-prep). It must be empty.
        """
        messages: list[Message] = [Message.system(self.system_prompt)]
        if history:
            messages.extend(history)
        messages.append(Message.user(user_message))

        if self.checkpoint_policy == CheckpointPolicy.PER_AGENT_TURN and self._can_checkpoint():
            self.checkpoint_store.save(self.model, label=f"before: {user_message[:60]}")

        steps = live_steps if live_steps is not None else []
        return self._run_loop(messages, steps=steps, cancel_check=cancel_check)

    def resume(
        self,
        pending: PendingConfirmation,
        confirmed: bool,
        history: list[Message],
        *,
        cancel_check: Callable[[], bool] | None = None,
        live_steps: list[AgentStep] | None = None,
    ) -> AgentResult:
        """Continue after a ``PendingConfirmation``.

        ``history`` is the ``messages`` list from the paused ``AgentResult``. On
        confirm, the guarded write is re-issued with ``overwrite=True``; either
        way a short note is appended and the loop continues.
        """
        messages = list(history)
        steps: list[AgentStep] = live_steps if live_steps is not None else []

        if confirmed:
            spec = get_tool(pending.tool_name)
            kwargs = dict(pending.arguments)
            kwargs["overwrite"] = True
            self._inject(spec, kwargs)
            try:
                result = spec.handler(**kwargs)
                steps.append(AgentStep(pending.tool_name, dict(pending.arguments), result=result))
                messages.append(
                    Message.user(
                        f"Confirmed: overwrite approved. {pending.tool_name} completed "
                        f"with result {json.dumps(result)}."
                    )
                )
            except ToolError as exc:
                steps.append(AgentStep(pending.tool_name, dict(pending.arguments), error=exc.to_dict()))
                messages.append(
                    Message.user(f"The action {pending.tool_name} failed: {exc.message}")
                )
        else:
            messages.append(
                Message.user(
                    f"Declined: do not overwrite the existing file. Skip {pending.tool_name}."
                )
            )

        return self._run_loop(messages, steps, cancel_check=cancel_check)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _run_loop(
        self,
        messages: list[Message],
        steps: list[AgentStep],
        cancel_check: Callable[[], bool] | None = None,
    ) -> AgentResult:
        tools = list_tools()
        for step_no in range(1, self.max_steps + 1):
            if cancel_check and cancel_check():
                logger.info("Step %d: cancelled before LLM call", step_no)
                return AgentResult(messages, "Run cancelled.", steps, "cancelled")
            started = time.monotonic()
            response = self.client.complete(messages, tools)
            elapsed = time.monotonic() - started
            messages.append(Message.assistant(response.text, response.tool_calls))
            if self.transcript:
                self.transcript.assistant_step(step_no, elapsed, response.text, response.tool_calls)

            if not response.tool_calls:
                logger.info("Step %d: final answer after %.1fs", step_no, elapsed)
                return AgentResult(messages, response.text, steps, "completed")

            logger.info(
                "Step %d: LLM call %.1fs -> %s",
                step_no, elapsed, ", ".join(tc.name for tc in response.tool_calls),
            )

            pending: PendingConfirmation | None = None
            for i, tool_call in enumerate(response.tool_calls):
                # Cancel may have been requested during the LLM call or a prior
                # tool; stop before the next tool, stubbing results for the
                # unexecuted calls so every tool_call id keeps a tool message
                # (providers reject conversations with dangling tool calls).
                if cancel_check and cancel_check():
                    logger.info("Step %d: cancelled before tool %s", step_no, tool_call.name)
                    self._stub_cancelled_calls(messages, response.tool_calls[i:])
                    return AgentResult(messages, "Run cancelled.", steps, "cancelled")
                message, step, kind, payload = self._execute_tool_call(tool_call)
                messages.append(message)
                steps.append(step)
                outcome = "ok" if step.error is None else f"ERROR {step.error.get('error')}"
                if step.error is None and isinstance(step.result, dict):
                    dropped = step.result.get("removed_citations")
                    if dropped:
                        outcome += f" [dropped citations: {', '.join(dropped)}]"
                logger.info(
                    "Step %d: %s(%s) -> %s",
                    step_no, step.tool_name, _summarize_args(step.arguments), outcome,
                )
                if self.transcript:
                    self.transcript.tool_result(step_no, step)
                if kind == _CONFIRM and pending is None:
                    pending = payload
                elif kind == _ERROR and self.error_policy == ToolErrorPolicy.STOP_AND_ASK:
                    logger.info("Step %d: stopped on tool error (%s)", step_no, tool_call.name)
                    return AgentResult(messages, "", steps, "stopped")

            if pending is not None:
                logger.info("Step %d: awaiting confirmation (%s)", step_no, pending.tool_name)
                return AgentResult(messages, "", steps, "awaiting_confirmation", pending)

        logger.info("Run ended: max_steps (%d) reached", self.max_steps)
        return AgentResult(messages, "", steps, "max_steps")

    @staticmethod
    def _stub_cancelled_calls(messages: list[Message], tool_calls: list[ToolCall]) -> None:
        """Append stub tool results for calls skipped by a mid-step cancel."""
        stub = {"error": "cancelled", "message": "Run cancelled by user before this tool executed."}
        for tc in tool_calls:
            messages.append(Message.tool(tc.id, tc.name, json.dumps(stub)))

    def _execute_tool_call(
        self, tool_call: ToolCall
    ) -> tuple[Message, AgentStep, str, PendingConfirmation | None]:
        try:
            spec = get_tool(tool_call.name)
        except KeyError:
            error = {"error": "unknown_tool", "message": f"Unknown tool: {tool_call.name}"}
            return (
                Message.tool(tool_call.id, tool_call.name, json.dumps(error)),
                AgentStep(tool_call.name, dict(tool_call.arguments), error=error),
                _ERROR,
                None,
            )

        if (
            self.checkpoint_policy == CheckpointPolicy.PER_MUTATING_TOOL
            and spec.mutating
            and self._can_checkpoint()
        ):
            self.checkpoint_store.save(self.model, label=f"before {tool_call.name}")

        try:
            kwargs = dict(tool_call.arguments)
            self._inject(spec, kwargs)  # may raise ToolError (e.g. outside_workspace)
            result = spec.handler(**kwargs)
            return (
                Message.tool(tool_call.id, tool_call.name, json.dumps(result)),
                AgentStep(tool_call.name, dict(tool_call.arguments), result=result),
                _OK,
                None,
            )
        except ToolError as exc:
            step = AgentStep(tool_call.name, dict(tool_call.arguments), error=exc.to_dict())
            message = Message.tool(tool_call.id, tool_call.name, json.dumps(exc.to_dict()))
            if exc.code == "overwrite_requires_confirmation":
                pending = PendingConfirmation(tool_call.name, dict(tool_call.arguments), exc.message)
                return message, step, _CONFIRM, pending
            return message, step, _ERROR, None

    def _inject(self, spec: ToolSpec, kwargs: dict) -> None:
        """Inject loop-owned context args the LLM never supplies.

        Also resolves any ``path_args`` against the workspace root (contained),
        so LLM-supplied relative read paths resolve against the workspace rather
        than the process CWD. Writers resolve internally and have no path_args.
        """
        if spec.requires_model:
            kwargs["model"] = self.model
        if spec.requires_workspace_root:
            kwargs["workspace_root"] = self.workspace_root
        if spec.path_args and self.workspace_root is not None:
            for arg in spec.path_args:
                if kwargs.get(arg) is not None:
                    kwargs[arg] = str(resolve_in_workspace(self.workspace_root, kwargs[arg]))

    def _can_checkpoint(self) -> bool:
        return self.checkpoint_store is not None and self.model is not None
