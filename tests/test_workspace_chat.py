"""Workspace chat panel API tests (Stage 1, Milestone 7)."""

import shutil
import threading
import time

import pytest

from src.agent.llm_tools import AgentLLMClient, LLMToolResponse
from src.agent.messages import ToolCall
from src.workspace import state as ws_state
from tests.test_support import TEST_DOCX
from tests.test_workspace_api import _call, _first_para_id, _open_ws, _resp, _script


@pytest.fixture(autouse=True)
def clear_workspaces():
    ws_state._workspaces.clear()
    yield
    ws_state._workspaces.clear()


@pytest.fixture
def workspace_dir(temp_dir):
    shutil.copyfile(TEST_DOCX, temp_dir / "doc.docx")
    return temp_dir


def _read_transcripts(workspace_dir):
    import json
    runs_dir = workspace_dir / ".stet" / "runs"
    files = sorted(runs_dir.glob("*.jsonl")) if runs_dir.is_dir() else []
    return [[json.loads(line) for line in f.read_text().splitlines()] for f in files]


class TestRunTranscriptRoute:
    def test_run_writes_a_transcript(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Hi.", track_changes=False)),
            _resp("Done."),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "edit intro", "provider": "ollama"})
        transcripts = _read_transcripts(workspace_dir)
        assert len(transcripts) == 1
        events = transcripts[0]
        assert events[0]["kind"] == "run_start"
        assert any(e["kind"] == "tool_result" and e["tool"] == "edit_paragraph" for e in events)
        assert events[-1]["kind"] == "run_end" and events[-1]["status"] == "completed"

    def test_crashed_run_still_records_run_end_error(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)

        def boom(self, messages, tools):
            raise RuntimeError("connection exploded")

        monkeypatch.setattr(AgentLLMClient, "complete", boom)
        # TestClient re-raises server exceptions; the point is the transcript is
        # still written (in the route's except) before the error propagates.
        with pytest.raises(RuntimeError, match="connection exploded"):
            client.post(f"/api/workspace/{ws_id}/agent/run",
                        json={"message": "go", "provider": "ollama"})

        transcripts = _read_transcripts(workspace_dir)
        assert len(transcripts) == 1
        end = transcripts[0][-1]
        assert end["kind"] == "run_end" and end["status"] == "error"
        assert "connection exploded" in end["error"]


class TestChatTurnLog:
    def test_get_chat_after_run(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Hi.", track_changes=False)),
            _resp("Done."),
        ])
        run = client.post(
            f"/api/workspace/{ws_id}/agent/run",
            json={"message": "edit intro", "provider": "ollama"},
        )
        assert run.status_code == 200

        chat = client.get(f"/api/workspace/{ws_id}/chat")
        assert chat.status_code == 200
        turns = chat.json()["turns"]
        assert len(turns) == 1
        assert turns[0]["user_message"] == "edit intro"
        assert turns[0]["final_text"] == "Done."
        assert turns[0]["status"] == "completed"
        assert turns[0]["steps"][0]["tool"] == "edit_paragraph"

    def test_turn_log_survives_reopen(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        _script(monkeypatch, [_resp("Hello there.")])
        client.post(
            f"/api/workspace/{ws_id}/agent/run",
            json={"message": "say hi", "provider": "ollama"},
        )
        ws_state.close_workspace(ws_id)
        ws_state._workspaces.clear()

        ws_id2 = _open_ws(client, workspace_dir)
        assert ws_id2 != ws_id
        chat = client.get(f"/api/workspace/{ws_id2}/chat").json()
        assert len(chat["turns"]) == 1
        assert chat["turns"][0]["user_message"] == "say hi"

    def test_confirm_updates_single_turn(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        _script(monkeypatch, [
            _resp("", _call("export_document", path="doc.docx")),
            _resp("Saved."),
        ])
        client.post(
            f"/api/workspace/{ws_id}/agent/run",
            json={"message": "save it", "provider": "ollama"},
        )
        client.post(f"/api/workspace/{ws_id}/agent/confirm", json={"confirmed": True})

        turns = client.get(f"/api/workspace/{ws_id}/chat").json()["turns"]
        assert len(turns) == 1
        assert turns[0]["status"] == "completed"
        assert any(s["tool"] == "export_document" for s in turns[0]["steps"])

    def test_clear_chat(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        _script(monkeypatch, [_resp("Hi.")])
        client.post(
            f"/api/workspace/{ws_id}/agent/run",
            json={"message": "hello", "provider": "ollama"},
        )
        cleared = client.post(f"/api/workspace/{ws_id}/chat/clear")
        assert cleared.status_code == 200
        chat = client.get(f"/api/workspace/{ws_id}/chat").json()
        assert chat["turns"] == []
        assert chat["pending_confirmation"] is None


class TestAgentCancel:
    def _slow_script(self, monkeypatch):
        state = {"n": 0}

        def slow_complete(self, messages, tools):
            state["n"] += 1
            if state["n"] == 1:
                time.sleep(0.35)
                return _resp("", _call("read_document", path="doc.docx"))
            return _resp("Should not reach.")

        monkeypatch.setattr(AgentLLMClient, "complete", slow_complete)

    def test_cancel_mid_run(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        self._slow_script(monkeypatch)
        results: dict = {}

        def run_agent():
            results["res"] = client.post(
                f"/api/workspace/{ws_id}/agent/run",
                json={"message": "read slowly", "provider": "ollama"},
            )

        t = threading.Thread(target=run_agent)
        t.start()
        time.sleep(0.2)
        cancel = client.post(f"/api/workspace/{ws_id}/agent/cancel")
        t.join(timeout=10)
        assert cancel.status_code == 200
        assert results["res"].status_code == 200
        data = results["res"].json()
        assert data["status"] == "cancelled"
        turns = client.get(f"/api/workspace/{ws_id}/chat").json()["turns"]
        assert len(turns) == 1
        assert turns[0]["status"] == "cancelled"
        # M9c-prep: cancel is polled between tool calls too, so a cancel that
        # lands during the LLM call now stops the run before the tool executes.
        assert turns[0]["steps"] == []

    def test_cancel_when_idle_409(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/agent/cancel")
        assert res.status_code == 409

    def test_clear_while_running_409(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        self._slow_script(monkeypatch)
        results: dict = {}

        def run_agent():
            results["res"] = client.post(
                f"/api/workspace/{ws_id}/agent/run",
                json={"message": "read slowly", "provider": "ollama"},
            )

        t = threading.Thread(target=run_agent)
        t.start()
        time.sleep(0.2)
        blocked = client.post(f"/api/workspace/{ws_id}/chat/clear")
        t.join(timeout=10)
        assert blocked.status_code == 409


class TestAgentProgress:
    def test_progress_idle(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.get(f"/api/workspace/{ws_id}/agent/progress")
        assert res.status_code == 200
        assert res.json() == {"running": False, "step_count": 0, "steps": []}

    def test_progress_unknown_workspace_404(self, client):
        assert client.get("/api/workspace/nope/agent/progress").status_code == 404

    def test_progress_during_and_after_run(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        state = {"n": 0}

        def scripted(self, messages, tools):
            state["n"] += 1
            if state["n"] == 1:
                return _resp("", _call("read_document", path="doc.docx"))
            time.sleep(0.5)  # keep the run alive so progress can be observed
            return _resp("Done.")

        monkeypatch.setattr(AgentLLMClient, "complete", scripted)
        results: dict = {}

        def run_agent():
            results["res"] = client.post(
                f"/api/workspace/{ws_id}/agent/run",
                json={"message": "read it", "provider": "ollama"},
            )

        t = threading.Thread(target=run_agent)
        t.start()
        seen = None
        deadline = time.time() + 5
        while time.time() < deadline:
            data = client.get(f"/api/workspace/{ws_id}/agent/progress").json()
            if data["running"] and data["step_count"] >= 1:
                seen = data
                break
            time.sleep(0.05)
        t.join(timeout=10)

        assert seen is not None, "never observed a running step via the progress route"
        assert seen["steps"][0] == {"tool": "read_document", "ok": True}
        assert results["res"].status_code == 200

        after = client.get(f"/api/workspace/{ws_id}/agent/progress").json()
        assert after["running"] is False


class TestStopAndAsk:
    def test_stop_and_ask_status(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        client.put(
            f"/api/workspace/{ws_id}/config",
            json={"tool_error_policy": "stop_and_ask"},
        )
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id="missing-id", new_text="nope")),
        ])
        res = client.post(
            f"/api/workspace/{ws_id}/agent/run",
            json={"message": "break it", "provider": "ollama"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "stopped"
        turn = client.get(f"/api/workspace/{ws_id}/chat").json()["turns"][-1]
        assert turn["status"] == "stopped"
