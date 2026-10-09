"""Per-run agent transcript tests (post-M9c pilot diagnostic).

The transcript exists so a run that is stopped or crashes before finalize is
still reviewable. These tests assert it is written incrementally (flushed per
event), that arguments/results are size-bounded, and that an error end-event is
recorded.
"""

import json

from src.agent.loop import AgentStep
from src.agent.messages import ToolCall
from src.agent.run_transcript import RunTranscript, new_transcript_path, _clip, RUNS_DIRNAME


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestRunTranscript:
    def test_run_start_written_on_init(self, tmp_path):
        p = tmp_path / "run.jsonl"
        RunTranscript(p, meta={"provider": "openai", "message": "hi"})
        events = _events(p)
        assert events[0]["kind"] == "run_start"
        assert events[0]["provider"] == "openai"

    def test_events_are_flushed_incrementally(self, tmp_path):
        # The whole point: readable BEFORE end() (a crashed run leaves a trace).
        p = tmp_path / "run.jsonl"
        t = RunTranscript(p, meta={})
        t.assistant_step(1, 1.23, "thinking", [ToolCall(id="c1", name="read_file", arguments={"path": "a.pdf"})])
        events = _events(p)  # not yet ended
        kinds = [e["kind"] for e in events]
        assert kinds == ["run_start", "assistant"]
        assert events[1]["tool_calls"][0]["name"] == "read_file"
        assert events[1]["elapsed_s"] == 1.23

    def test_tool_result_records_ok_and_error(self, tmp_path):
        p = tmp_path / "run.jsonl"
        t = RunTranscript(p, meta={})
        t.tool_result(1, AgentStep("edit_paragraph", {"para_id": "p1"}, result={"ok": True}))
        t.tool_result(1, AgentStep("edit_paragraph", {"para_id": "bad"}, error={"error": "not_found"}))
        t.end("completed", 2)
        events = _events(p)
        ok, bad = events[1], events[2]
        assert ok["kind"] == "tool_result" and ok["ok"] is True
        assert bad["ok"] is False and bad["error"]["error"] == "not_found"
        assert events[-1]["kind"] == "run_end" and events[-1]["status"] == "completed"

    def test_end_error_is_recorded(self, tmp_path):
        p = tmp_path / "run.jsonl"
        t = RunTranscript(p, meta={})
        t.end("error", 3, error="APIConnectionError")
        last = _events(p)[-1]
        assert last["kind"] == "run_end" and last["status"] == "error"
        assert last["error"] == "APIConnectionError"

    def test_end_is_idempotent(self, tmp_path):
        p = tmp_path / "run.jsonl"
        t = RunTranscript(p, meta={})
        t.end("completed", 1)
        t.end("completed", 1)  # second call must not append another run_end
        assert sum(1 for e in _events(p) if e["kind"] == "run_end") == 1

    def test_large_values_are_truncated(self, tmp_path):
        p = tmp_path / "run.jsonl"
        t = RunTranscript(p, meta={})
        big = "x" * 5000
        t.tool_result(1, AgentStep("read_file", {"path": "a.pdf"}, result={"text": big}))
        ev = _events(p)[1]
        assert "<5000 chars>" in ev["result"]["text"]
        assert len(ev["result"]["text"]) < 5000

    def test_clip_recurses(self):
        assert _clip("short") == "short"
        assert "<3000 chars>" in _clip("y" * 3000)
        assert _clip({"k": "z" * 3000})["k"].endswith("chars>")

    def test_new_transcript_path_shape(self, tmp_path):
        path = new_transcript_path(tmp_path)
        assert path.parent == tmp_path / RUNS_DIRNAME
        assert path.suffix == ".jsonl"

    def test_bad_path_does_not_raise(self, tmp_path):
        # A directory where a file is expected → open fails, but logging must not
        # break a run.
        target = tmp_path / "collide"
        target.mkdir()
        t = RunTranscript(target, meta={})  # should swallow the error
        t.assistant_step(1, 0.0, "x", [])
        t.end("completed", 0)  # no raise
