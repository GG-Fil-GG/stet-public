"""Agent loop tests (Stage 1, Milestone 3).

Uses a deterministic MockLLMClient (scripted tool-call sequences) — no network,
no real model flakiness. Tools run for real against the synthetic fixture.
"""

import shutil

import pytest

from src.agent import (
    AgentLoop,
    AgentResult,
    CheckpointPolicy,
    LLMToolResponse,
    Message,
    ToolCall,
    ToolErrorPolicy,
)
from src.checkpoints import CheckpointStore
from src.document_model import parse_docx
from tests.test_support import TEST_DOCX, SYNTHETIC_TEST_DATA_DIR

SAMPLE_PDF = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.pdf"


# --------------------------------------------------------------------------- #
# Mock client + helpers
# --------------------------------------------------------------------------- #

class MockLLMClient:
    """Returns a scripted list of LLMToolResponse; optionally repeats the last."""

    def __init__(self, responses, repeat_last=False):
        self._responses = list(responses)
        self._repeat_last = repeat_last
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self._responses:
            resp = self._responses[0]
            if not (self._repeat_last and len(self._responses) == 1):
                self._responses.pop(0)
            return resp
        return LLMToolResponse(text="(no more responses)")


def _call(name, **args):
    return ToolCall(id=f"c{name}", name=name, arguments=args)


def _resp(text="", *calls):
    return LLMToolResponse(text=text, tool_calls=list(calls))


def _model():
    return parse_docx(TEST_DOCX)


def _first_nonempty_para_id(model):
    for para in model.body.iter_paragraphs():
        if para.plain_text.strip():
            return para.para_id
    raise AssertionError("no non-empty paragraph")


def _first_thread_id(model):
    return next(iter(model.comments.threads.keys()))


# --------------------------------------------------------------------------- #
# Happy path + injection
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_list_then_edit_then_finish(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Rewritten by agent.", track_changes=False)),
            _resp("Done: addressed the open comments."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("Address the open comments.")

        assert result.status == "completed"
        assert result.final_text.startswith("Done")
        assert [s.tool_name for s in result.steps] == ["list_comments", "edit_paragraph"]
        assert "Rewritten by agent." in model.get_paragraph(para_id).plain_text

    def test_model_is_injected_not_supplied_by_llm(self):
        model = _model()
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="all")),
            _resp("Listed."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("List comments.")
        step = result.steps[0]
        # The recorded args are the LLM-facing ones only (no injected model).
        assert step.arguments == {"comment_filter": "all"}
        assert step.result["count"] == model.thread_count

    def test_workspace_root_is_injected(self, temp_dir):
        shutil.copyfile(TEST_DOCX, temp_dir / "doc.docx")
        client = MockLLMClient([
            _resp("", _call("list_workspace_files")),
            _resp("Listed files."),
        ])
        loop = AgentLoop(client, model=None, workspace_root=temp_dir)
        result = loop.run("What files are here?")
        assert result.status == "completed"
        assert result.steps[0].result["count"] == 1


# --------------------------------------------------------------------------- #
# Termination
# --------------------------------------------------------------------------- #

class TestTermination:
    def test_max_steps(self):
        model = _model()
        # Always returns a tool call -> never finishes.
        client = MockLLMClient([_resp("", _call("list_comments", comment_filter="open"))], repeat_last=True)
        loop = AgentLoop(client, model=model, workspace_root=None, max_steps=3)
        result = loop.run("loop forever")
        assert result.status == "max_steps"
        assert len(result.steps) == 3

    def test_unknown_tool_is_reported_and_loop_continues(self):
        model = _model()
        client = MockLLMClient([
            _resp("", _call("bogus_tool", x=1)),
            _resp("Recovered."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("call a bad tool")
        assert result.status == "completed"
        assert result.steps[0].error["error"] == "unknown_tool"


# --------------------------------------------------------------------------- #
# Error policy
# --------------------------------------------------------------------------- #

class TestErrorPolicy:
    def test_report_and_skip_feeds_error_back(self):
        model = _model()
        client = MockLLMClient([
            _resp("", _call("read_paragraph", para_id="DEADBEEF")),  # not_found
            _resp("Could not find that paragraph."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None,
                         error_policy=ToolErrorPolicy.REPORT_AND_SKIP)
        result = loop.run("read a bad paragraph")
        assert result.status == "completed"
        assert result.steps[0].error["error"] == "not_found"

    def test_stop_and_ask_halts_on_error(self):
        model = _model()
        client = MockLLMClient([
            _resp("", _call("read_paragraph", para_id="DEADBEEF")),
            _resp("should not be reached"),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None,
                         error_policy=ToolErrorPolicy.STOP_AND_ASK)
        result = loop.run("read a bad paragraph")
        assert result.status == "stopped"
        assert client.calls == 1  # did not call the model again


# --------------------------------------------------------------------------- #
# Overwrite confirmation
# --------------------------------------------------------------------------- #

class TestOverwriteConfirmation:
    def _existing_target(self, temp_dir):
        target = temp_dir / "out.docx"
        target.write_bytes(b"old")  # exists -> triggers confirmation
        return target

    def test_pauses_for_confirmation(self, temp_dir):
        model = _model()
        self._existing_target(temp_dir)
        client = MockLLMClient([
            _resp("", _call("export_document", path="out.docx")),
            _resp("Saved."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=temp_dir)
        result = loop.run("save the document")
        assert result.status == "awaiting_confirmation"
        assert result.pending_confirmation.tool_name == "export_document"

    def test_resume_confirmed_writes(self, temp_dir):
        model = _model()
        target = self._existing_target(temp_dir)
        client = MockLLMClient([
            _resp("", _call("export_document", path="out.docx")),
            _resp("Saved."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=temp_dir)
        paused = loop.run("save the document")
        resumed = loop.resume(paused.pending_confirmation, confirmed=True, history=paused.messages)
        assert resumed.status == "completed"
        # The file was overwritten with a real docx (much larger than b"old").
        assert target.stat().st_size > 1000

    def test_resume_declined_does_not_write(self, temp_dir):
        model = _model()
        target = self._existing_target(temp_dir)
        client = MockLLMClient([
            _resp("", _call("export_document", path="out.docx")),
            _resp("Okay, leaving it as is."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=temp_dir)
        paused = loop.run("save the document")
        resumed = loop.resume(paused.pending_confirmation, confirmed=False, history=paused.messages)
        assert resumed.status == "completed"
        assert target.read_bytes() == b"old"  # untouched


# --------------------------------------------------------------------------- #
# Checkpoint policy
# --------------------------------------------------------------------------- #

class TestCheckpointPolicy:
    def test_per_agent_turn_saves_once(self, temp_dir):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        store = CheckpointStore(temp_dir / "cp")
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="x", track_changes=False)),
            _resp("done"),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None, checkpoint_store=store,
                         checkpoint_policy=CheckpointPolicy.PER_AGENT_TURN)
        loop.run("edit")
        assert len(store.list()) == 1

    def test_per_mutating_tool_saves_per_mutation(self, temp_dir):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        thread_id = _first_thread_id(model)
        store = CheckpointStore(temp_dir / "cp")
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),       # non-mutating
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="x", track_changes=False)),  # mutating
            _resp("", _call("add_comment_reply", thread_id=thread_id, text="ok")),  # mutating
            _resp("done"),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None, checkpoint_store=store,
                         checkpoint_policy=CheckpointPolicy.PER_MUTATING_TOOL)
        loop.run("edit twice")
        assert len(store.list()) == 2  # only the two mutating calls

    def test_per_mutating_tool_no_save_for_readonly(self, temp_dir):
        model = _model()
        store = CheckpointStore(temp_dir / "cp")
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("done"),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None, checkpoint_store=store,
                         checkpoint_policy=CheckpointPolicy.PER_MUTATING_TOOL)
        loop.run("just read")
        assert len(store.list()) == 0


# --------------------------------------------------------------------------- #
# Conversation shape
# --------------------------------------------------------------------------- #

class TestConversation:
    def test_history_is_returned_and_stateless(self):
        model = _model()
        client = MockLLMClient([_resp("Hello there.")])
        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("hi")
        # system + user + assistant
        assert result.messages[0].role == "system"
        assert result.messages[1].role == "user"
        assert result.messages[-1].role == "assistant"
        assert isinstance(result, AgentResult)

    def test_cancel_check_stops_between_steps(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        client = MockLLMClient([
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="x", track_changes=False)),
            _resp("Should not run."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)

        # Cancel becomes true once the edit landed -> the first step completes,
        # then the loop stops before the next LLM call.
        def cancel_check():
            return "x" in model.get_paragraph(para_id).plain_text

        result = loop.run("edit", cancel_check=cancel_check)
        assert result.status == "cancelled"
        assert len(result.steps) == 1
        assert client.calls == 1  # did not call the model again


# --------------------------------------------------------------------------- #
# M9c-prep: intra-step cancel, live steps, per-step logging
# --------------------------------------------------------------------------- #

class TestIntraStepCancel:
    def test_cancel_between_tools_stops_and_stubs_remaining(self):
        model = _model()
        para_id = _first_nonempty_para_id(model)
        client = MockLLMClient([
            LLMToolResponse(text="", tool_calls=[
                ToolCall(id="c1", name="edit_paragraph",
                         arguments={"para_id": para_id, "new_text": "Edited.", "track_changes": False}),
                ToolCall(id="c2", name="read_paragraph", arguments={"para_id": para_id}),
            ]),
            _resp("Should not run."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)

        # Cancel becomes true once the first tool's edit landed -> the loop must
        # stop before executing the second tool of the same step.
        def cancel_check():
            return "Edited." in model.get_paragraph(para_id).plain_text

        result = loop.run("edit then read", cancel_check=cancel_check)
        assert result.status == "cancelled"
        assert [s.tool_name for s in result.steps] == ["edit_paragraph"]
        assert client.calls == 1

        # Protocol stays valid: the skipped call still gets a (stub) tool result.
        tool_msgs = {m.tool_call_id: m for m in result.messages if m.role == "tool"}
        assert set(tool_msgs) == {"c1", "c2"}
        assert "cancelled" in tool_msgs["c2"].content


class TestLiveSteps:
    def test_live_steps_list_is_used_as_accumulator(self):
        model = _model()
        live: list = []
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("Done."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)
        result = loop.run("list comments", live_steps=live)
        assert result.steps is live
        assert [s.tool_name for s in live] == ["list_comments"]


class TestPerStepLogging:
    def test_each_step_logs_tools_and_final_answer(self, caplog):
        model = _model()
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("Done."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None)
        with caplog.at_level("INFO", logger="src.agent.loop"):
            loop.run("list comments")
        assert "Step 1" in caplog.text and "list_comments" in caplog.text
        assert "Step 2" in caplog.text and "final answer" in caplog.text


class TestTranscriptSink:
    def test_run_records_assistant_and_tool_events(self, tmp_path):
        import json
        from src.agent.run_transcript import RunTranscript

        model = _model()
        path = tmp_path / "run.jsonl"
        transcript = RunTranscript(path, meta={"kind_of_run": "run"})
        client = MockLLMClient([
            _resp("", _call("list_comments", comment_filter="open")),
            _resp("All done."),
        ])
        loop = AgentLoop(client, model=model, workspace_root=None, transcript=transcript)
        loop.run("list comments")
        transcript.end("completed", 1)

        events = [json.loads(line) for line in path.read_text().splitlines()]
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "run_start"
        assert "assistant" in kinds and "tool_result" in kinds
        tool_ev = next(e for e in events if e["kind"] == "tool_result")
        assert tool_ev["tool"] == "list_comments" and tool_ev["ok"] is True
        assert events[-1]["kind"] == "run_end"
