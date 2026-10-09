"""Workspace JSON API smoke tests (Stage 1, Milestone 4).

Mirrors tests/test_routes.py: TestClient + synthetic fixtures, no real LLM.
The agent loop's LLM client is mocked with a scripted tool-call sequence.
"""

import shutil

import pytest

from src.agent.llm_tools import AgentLLMClient, LLMToolResponse
from src.agent.messages import ToolCall
from src.workspace import state as ws_state
from tests.test_support import TEST_DOCX


@pytest.fixture(autouse=True)
def clear_workspaces():
    ws_state._workspaces.clear()
    yield
    ws_state._workspaces.clear()


@pytest.fixture
def workspace_dir(temp_dir):
    shutil.copyfile(TEST_DOCX, temp_dir / "doc.docx")
    return temp_dir


def _script(monkeypatch, responses, repeat_last=False):
    """Patch AgentLLMClient.complete to return a scripted response sequence."""
    state = {"i": 0}

    def fake_complete(self, messages, tools):
        i = state["i"]
        if i < len(responses):
            if not (repeat_last and i == len(responses) - 1):
                state["i"] += 1
            return responses[i]
        return LLMToolResponse(text="(done)")

    monkeypatch.setattr(AgentLLMClient, "complete", fake_complete)


def _call(name, **args):
    return ToolCall(id=f"c_{name}", name=name, arguments=args)


def _resp(text="", *calls):
    return LLMToolResponse(text=text, tool_calls=list(calls))


def _open_ws(client, workspace_dir, with_doc=True):
    res = client.post("/api/workspace/open", json={"path": str(workspace_dir)})
    assert res.status_code == 200
    ws_id = res.json()["workspace_id"]
    if with_doc:
        res = client.post(f"/api/workspace/{ws_id}/document/open", json={"path": "doc.docx"})
        assert res.status_code == 200
    return ws_id


def _first_para_id(client, ws_id):
    res = client.get(f"/api/workspace/{ws_id}/document")
    for block in res.json()["blocks"]:
        if block["kind"] == "paragraph" and block["text"].strip():
            return block["para_id"]
    raise AssertionError("no non-empty paragraph")


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

class TestLifecycle:
    def test_open_lists_files(self, client, workspace_dir):
        res = client.post("/api/workspace/open", json={"path": str(workspace_dir)})
        assert res.status_code == 200
        data = res.json()
        assert data["workspace_id"]
        assert "doc.docx" in {f["path"] for f in data["files"]}

    def test_open_unknown_folder_404(self, client, temp_dir):
        res = client.post("/api/workspace/open", json={"path": str(temp_dir / "nope")})
        assert res.status_code == 404

    def test_open_document_summary(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.get(f"/api/workspace/{ws_id}/document")
        assert res.status_code == 200
        assert res.json()["document"]["paragraph_count"] > 0

    def test_unknown_workspace_404(self, client):
        res = client.get("/api/workspace/deadbeef/files")
        assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Document view (M6a: blocks + comments)
# --------------------------------------------------------------------------- #

class TestDocumentView:
    def test_get_document_returns_blocks_and_comments(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        data = client.get(f"/api/workspace/{ws_id}/document").json()
        assert isinstance(data["blocks"], list) and data["blocks"]
        first = data["blocks"][0]
        assert {"kind", "para_id", "html", "text", "comment_ids"} <= set(first.keys())
        assert isinstance(data["comments"], list)

    def test_comment_surfaces_in_payload_and_anchored_block(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        data = client.get(f"/api/workspace/{ws_id}/document").json()
        if not data["comments"]:
            pytest.skip("fixture has no comment threads")
        thread = data["comments"][0]
        assert {"thread_id", "status", "author", "referenced_text", "comments"} <= set(thread.keys())
        tid = thread["thread_id"]
        anchored = [b for b in data["blocks"] if tid in b.get("comment_ids", [])]
        if not anchored:
            pytest.skip("fixture thread has no body-paragraph anchor")
        assert "ws-comment-ref" in anchored[0]["html"]


# --------------------------------------------------------------------------- #
# Manual paragraph edit (M6b)
# --------------------------------------------------------------------------- #

class TestParagraphEdit:
    def test_patch_edits_paragraph(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        doc_path = workspace_dir / "doc.docx"
        mtime_before = doc_path.stat().st_mtime

        res = client.patch(
            f"/api/workspace/{ws_id}/document/paragraph/{para_id}",
            json={"new_text": "MANUAL PATCH EDIT"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["unsaved_changes"] is True
        assert data["block"]["para_id"] == para_id
        assert "MANUAL PATCH EDIT" in data["block"]["text"]

        checkpoints = client.get(f"/api/workspace/{ws_id}/checkpoints").json()["checkpoints"]
        assert len(checkpoints) == 1
        assert "manual edit" in checkpoints[0]["label"]

        assert doc_path.stat().st_mtime == mtime_before

    def test_patch_unknown_para_404(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.patch(
            f"/api/workspace/{ws_id}/document/paragraph/NOPE1234",
            json={"new_text": "x"},
        )
        assert res.status_code == 404

    def test_patch_then_restore(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        before = client.get(f"/api/workspace/{ws_id}/document").json()
        orig_text = next(b["text"] for b in before["blocks"] if b["para_id"] == para_id)

        client.patch(
            f"/api/workspace/{ws_id}/document/paragraph/{para_id}",
            json={"new_text": "UNDO ME PLEASE"},
        )
        after = client.get(f"/api/workspace/{ws_id}/document").json()
        assert any("UNDO ME PLEASE" in b["text"] for b in after["blocks"])

        cp_id = client.get(f"/api/workspace/{ws_id}/checkpoints").json()["checkpoints"][0][
            "checkpoint_id"
        ]
        client.post(
            f"/api/workspace/{ws_id}/checkpoint/restore", json={"checkpoint_id": cp_id}
        )

        restored = client.get(f"/api/workspace/{ws_id}/document").json()
        block = next(b for b in restored["blocks"] if b["para_id"] == para_id)
        assert block["text"] == orig_text

    def test_patch_track_changes_in_block_html(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        before = client.get(f"/api/workspace/{ws_id}/document").json()
        orig_text = next(b["text"] for b in before["blocks"] if b["para_id"] == para_id)

        res = client.patch(
            f"/api/workspace/{ws_id}/document/paragraph/{para_id}",
            json={"new_text": "CHANGED TEXT FOR TC"},
        )
        assert res.status_code == 200
        html = res.json()["block"]["html"]
        assert orig_text != "CHANGED TEXT FOR TC"
        assert 'class="diff-insert"' in html or 'class="diff-delete"' in html


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

class TestConfig:
    def test_get_and_update(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        assert client.get(f"/api/workspace/{ws_id}/config").json()["config"]["max_agent_steps"] == 20

        res = client.put(f"/api/workspace/{ws_id}/config", json={"max_agent_steps": 5})
        assert res.status_code == 200
        assert res.json()["config"]["max_agent_steps"] == 5
        assert client.get(f"/api/workspace/{ws_id}/config").json()["config"]["max_agent_steps"] == 5

    def test_invalid_update_falls_back(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        res = client.put(f"/api/workspace/{ws_id}/config", json={"checkpoint_policy": "bogus"})
        assert res.status_code == 200
        assert res.json()["config"]["checkpoint_policy"] == "per_agent_turn"

    def test_context_token_budget_round_trip(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        assert (
            client.get(f"/api/workspace/{ws_id}/config").json()["config"]["context_token_budget"]
            == 60_000
        )
        res = client.put(f"/api/workspace/{ws_id}/config", json={"context_token_budget": 12_000})
        assert res.status_code == 200
        assert res.json()["config"]["context_token_budget"] == 12_000
        assert (
            client.get(f"/api/workspace/{ws_id}/config").json()["config"]["context_token_budget"]
            == 12_000
        )


class TestWorkingModelDurability:
    """M9d: agent/manual edits survive a re-parse (fresh session) and are cleared on save."""

    def test_agent_edits_survive_reopen(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Durable edit.", track_changes=True)),
            _resp("Done."),
        ])
        run = client.post(f"/api/workspace/{ws_id}/agent/run",
                          json={"message": "edit", "provider": "ollama"})
        assert run.status_code == 200
        assert run.json()["unsaved_changes"] is True

        # Simulate a browser reload / restart: drop the in-memory session, reopen.
        # The workspace auto-restores the document (with edits) from the snapshot,
        # so we don't re-open it explicitly (that would hit the unsaved guard).
        ws_state._workspaces.clear()
        ws_id2 = _open_ws(client, workspace_dir, with_doc=False)
        doc = client.get(f"/api/workspace/{ws_id2}/document").json()
        assert doc["document"]["unsaved_changes"] is True        # edits restored
        assert doc["document"]["revision_count"] >= 1

    def test_same_path_save_clears_snapshot(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Durable edit.", track_changes=True)),
            _resp("Done."),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run", json={"message": "edit", "provider": "ollama"})
        save = client.post(f"/api/workspace/{ws_id}/save", json={"path": "doc.docx", "overwrite": True})
        assert save.status_code == 200

        # After a same-path save the edits are in the file; a fresh open parses it
        # (no stale snapshot). The file now legitimately carries the tracked change,
        # but is_dirty must be False (nothing unsaved in RAM).
        ws_state._workspaces.clear()
        ws_id2 = _open_ws(client, workspace_dir)
        doc = client.get(f"/api/workspace/{ws_id2}/document").json()
        assert doc["document"]["unsaved_changes"] is False

    def test_same_path_reopen_with_unsaved_is_guarded(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        edit = client.patch(f"/api/workspace/{ws_id}/document/paragraph/{para_id}",
                            json={"new_text": "Manual edit."})
        assert edit.status_code == 200
        assert edit.json()["unsaved_changes"] is True

        # Re-opening the same document without force must be refused (409)...
        blocked = client.post(f"/api/workspace/{ws_id}/document/open", json={"path": "doc.docx"})
        assert blocked.status_code == 409
        # ...and forcing it recovers the edit from the snapshot (no data loss).
        forced = client.post(f"/api/workspace/{ws_id}/document/open",
                             json={"path": "doc.docx", "force": True})
        assert forced.status_code == 200
        assert forced.json()["document"]["unsaved_changes"] is True


# --------------------------------------------------------------------------- #
# Agent run
# --------------------------------------------------------------------------- #

class TestAgentRun:
    def test_run_edits_in_memory_only(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        before = (workspace_dir / "doc.docx").read_bytes()
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="Agent edited this.", track_changes=False)),
            _resp("Edited the paragraph."),
        ])
        res = client.post(f"/api/workspace/{ws_id}/agent/run",
                          json={"message": "edit it", "provider": "ollama"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["steps"][0]["tool"] == "edit_paragraph"
        # Source docx on disk is unchanged (no save yet).
        assert (workspace_dir / "doc.docx").read_bytes() == before

    def test_path_resolution_for_reads(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        _script(monkeypatch, [
            _resp("", _call("read_document", path="doc.docx")),  # workspace-relative
            _resp("Read it."),
        ])
        res = client.post(f"/api/workspace/{ws_id}/agent/run",
                          json={"message": "read the doc", "provider": "ollama"})
        assert res.status_code == 200
        step = res.json()["steps"][0]
        assert step["error"] is None
        assert step["result"]["paragraph_count"] > 0

    def test_run_requires_open_document(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        _script(monkeypatch, [_resp("hi")])
        res = client.post(f"/api/workspace/{ws_id}/agent/run",
                          json={"message": "hi", "provider": "ollama"})
        assert res.status_code == 400


# --------------------------------------------------------------------------- #
# Overwrite confirmation
# --------------------------------------------------------------------------- #

class TestOverwriteConfirmation:
    def test_pause_then_confirm(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        # Agent tries to export over the existing open document.
        _script(monkeypatch, [
            _resp("", _call("export_document", path="doc.docx")),
            _resp("Saved."),
        ])
        res = client.post(f"/api/workspace/{ws_id}/agent/run",
                          json={"message": "save it", "provider": "ollama"})
        assert res.status_code == 200
        assert res.json()["status"] == "awaiting_confirmation"
        assert res.json()["pending_confirmation"]["tool_name"] == "export_document"

        confirm = client.post(f"/api/workspace/{ws_id}/agent/confirm", json={"confirmed": True})
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "completed"

    def test_decline(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        _script(monkeypatch, [
            _resp("", _call("export_document", path="doc.docx")),
            _resp("Okay, leaving it."),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "save it", "provider": "ollama"})
        confirm = client.post(f"/api/workspace/{ws_id}/agent/confirm", json={"confirmed": False})
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# Save / save-as-copy
# --------------------------------------------------------------------------- #

class TestSave:
    def test_save_as_copy_switches_active_and_keeps_original(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        original = (workspace_dir / "doc.docx").read_bytes()
        res = client.post(f"/api/workspace/{ws_id}/save", json={"path": "copy.docx"})
        assert res.status_code == 200
        assert res.json()["document"]["path"] == "copy.docx"   # active doc switched
        assert (workspace_dir / "copy.docx").is_file()
        assert (workspace_dir / "doc.docx").read_bytes() == original  # untouched

    def test_save_in_place_requires_overwrite(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/save", json={})
        assert res.status_code == 409  # overwrite_requires_confirmation
        ok = client.post(f"/api/workspace/{ws_id}/save", json={"overwrite": True})
        assert ok.status_code == 200

    def test_save_outside_workspace_rejected(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/save", json={"path": "../escape.docx"})
        assert res.status_code == 400  # outside_workspace

    def test_create_blank_document(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        res = client.post(f"/api/workspace/{ws_id}/document/create", json={"path": "fresh.docx"})
        assert res.status_code == 200
        assert (workspace_dir / "fresh.docx").is_file()


# --------------------------------------------------------------------------- #
# Switching documents (unsaved-changes guard)
# --------------------------------------------------------------------------- #

class TestSwitchDocument:
    def test_switch_warns_on_unsaved(self, client, workspace_dir, monkeypatch):
        shutil.copyfile(TEST_DOCX, workspace_dir / "other.docx")
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="dirty edit", track_changes=False)),
            _resp("done"),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "edit", "provider": "ollama"})

        # Switching away from the dirty document is blocked without force.
        blocked = client.post(f"/api/workspace/{ws_id}/document/open",
                              json={"path": "other.docx"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["error"] == "unsaved_changes"

        # force=true discards the edits and switches.
        forced = client.post(f"/api/workspace/{ws_id}/document/open",
                             json={"path": "other.docx", "force": True})
        assert forced.status_code == 200
        assert forced.json()["document"]["path"] == "other.docx"

    def test_switch_allowed_when_clean(self, client, workspace_dir):
        shutil.copyfile(TEST_DOCX, workspace_dir / "other.docx")
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/document/open",
                         json={"path": "other.docx"})
        assert res.status_code == 200
        assert res.json()["document"]["path"] == "other.docx"


# --------------------------------------------------------------------------- #
# Closing a document (workspace stays open)
# --------------------------------------------------------------------------- #

class TestCloseDocument:
    def test_close_clears_active_document(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/document/close", json={})
        assert res.status_code == 200
        assert res.json()["closed"] is True
        # Document is gone; the workspace is still open.
        assert client.get(f"/api/workspace/{ws_id}/document").status_code == 400
        assert client.get(f"/api/workspace/{ws_id}/files").status_code == 200

    def test_close_warns_on_unsaved(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="dirty edit", track_changes=False)),
            _resp("done"),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "edit", "provider": "ollama"})

        blocked = client.post(f"/api/workspace/{ws_id}/document/close", json={"force": False})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["error"] == "unsaved_changes"
        forced = client.post(f"/api/workspace/{ws_id}/document/close", json={"force": True})
        assert forced.status_code == 200

    def test_close_when_none_is_noop(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir, with_doc=False)
        res = client.post(f"/api/workspace/{ws_id}/document/close", json={})
        assert res.status_code == 200
        assert res.json()["closed"] is True


# --------------------------------------------------------------------------- #
# Checkpoints
# --------------------------------------------------------------------------- #

class TestCheckpoints:
    def test_edit_then_restore(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="DISTINCT AGENT EDIT", track_changes=False)),
            _resp("done"),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "edit", "provider": "ollama"})

        # per_agent_turn → one checkpoint saved before the turn (pre-edit state).
        checkpoints = client.get(f"/api/workspace/{ws_id}/checkpoints").json()["checkpoints"]
        assert len(checkpoints) == 1

        cp_id = checkpoints[0]["checkpoint_id"]
        res = client.post(f"/api/workspace/{ws_id}/checkpoint/restore", json={"checkpoint_id": cp_id})
        assert res.status_code == 200

        doc = client.get(f"/api/workspace/{ws_id}/document").json()
        texts = " ".join(b["text"] for b in doc["blocks"])
        assert "DISTINCT AGENT EDIT" not in texts  # rolled back

    def test_restore_unknown_404(self, client, workspace_dir):
        ws_id = _open_ws(client, workspace_dir)
        res = client.post(f"/api/workspace/{ws_id}/checkpoint/restore",
                          json={"checkpoint_id": "nope"})
        assert res.status_code == 404


# --------------------------------------------------------------------------- #
# Close
# --------------------------------------------------------------------------- #

class TestClose:
    def test_close_warns_on_unsaved(self, client, workspace_dir, monkeypatch):
        ws_id = _open_ws(client, workspace_dir)
        para_id = _first_para_id(client, ws_id)
        _script(monkeypatch, [
            _resp("", _call("edit_paragraph", para_id=para_id, new_text="dirty edit", track_changes=False)),
            _resp("done"),
        ])
        client.post(f"/api/workspace/{ws_id}/agent/run",
                    json={"message": "edit", "provider": "ollama"})

        blocked = client.post(f"/api/workspace/{ws_id}/close", json={"force": False})
        assert blocked.status_code == 409
        forced = client.post(f"/api/workspace/{ws_id}/close", json={"force": True})
        assert forced.status_code == 200
