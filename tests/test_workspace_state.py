"""Workspace session + persistence tests (Stage 1, Milestone 4)."""

import shutil

import pytest

from src.agent.messages import Message, ToolCall
from src.workspace import state as ws_state
from src.workspace import open_workspace
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


class TestMessageSerialization:
    def test_round_trip_plain(self):
        msg = Message.user("hello")
        assert Message.from_dict(msg.to_dict()) == msg

    def test_round_trip_with_tool_calls(self):
        msg = Message.assistant("", [ToolCall(id="c1", name="list_comments", arguments={"comment_filter": "open"})])
        restored = Message.from_dict(msg.to_dict())
        assert restored.role == "assistant"
        assert restored.tool_calls[0].name == "list_comments"
        assert restored.tool_calls[0].arguments == {"comment_filter": "open"}

    def test_round_trip_tool_result(self):
        msg = Message.tool("c1", "list_comments", "{}")
        assert Message.from_dict(msg.to_dict()) == msg


class TestOpenWorkspace:
    def test_creates_stet_dir_and_config(self, workspace_dir):
        session = open_workspace(workspace_dir)
        assert (workspace_dir / ".stet").is_dir()
        assert (workspace_dir / ".stet" / "checkpoints").is_dir()
        assert (workspace_dir / ".stet" / "config.json").is_file()
        assert session.workspace_id

    def test_missing_folder_raises(self, temp_dir):
        from src.agent import ToolError
        with pytest.raises(ToolError) as exc:
            open_workspace(temp_dir / "nope")
        assert exc.value.code == "not_found"


class TestOpenDocument:
    def test_loads_model_without_touching_disk(self, workspace_dir):
        from src.agent import tools
        before = (workspace_dir / "doc.docx").read_bytes()
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        assert session.document is not None
        assert session.document_path == "doc.docx"
        # Editing in memory must not change the file on disk (until an explicit save).
        para_id = next(p.para_id for p in session.document.body.iter_paragraphs() if p.plain_text.strip())
        tools.edit_paragraph(session.document, para_id, "changed in memory", track_changes=False)
        assert (workspace_dir / "doc.docx").read_bytes() == before

    def test_unsaved_changes_flag(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        assert session.unsaved_changes is False
        session.document.is_dirty = True
        assert session.unsaved_changes is True


class TestPersistenceRoundTrip:
    def test_conversation_and_open_doc_restore(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        session.conversation = [
            Message.user("address the open comments"),
            Message.assistant("", [ToolCall(id="c1", name="list_comments", arguments={"comment_filter": "open"})]),
            Message.tool("c1", "list_comments", "{}"),
        ]
        session.persist()

        # Re-open the same folder → a fresh session restores state.
        ws_state._workspaces.clear()
        reopened = open_workspace(workspace_dir)
        assert reopened.document is not None              # auto-reopened
        assert reopened.document_path == "doc.docx"
        assert [m.to_dict() for m in reopened.conversation] == [
            m.to_dict() for m in session.conversation
        ]

    def test_missing_open_doc_skipped(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        session.persist()
        (workspace_dir / "doc.docx").unlink()  # delete the file

        ws_state._workspaces.clear()
        reopened = open_workspace(workspace_dir)
        assert reopened.document is None                  # gracefully skipped
        assert reopened.document_path is None


class TestWorkingModelPersistence:
    """M9d: unsaved edits survive a re-parse via the .stet/working/ snapshot."""

    def _edit(self, session):
        from src.agent import tools
        para_id = next(
            p.para_id for p in session.document.body.iter_paragraphs() if p.plain_text.strip()
        )
        tools.edit_paragraph(session.document, para_id, "AGENT EDIT.", track_changes=True)
        return para_id

    def test_edits_restore_in_a_fresh_session(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        self._edit(session)
        assert session.document.is_dirty is True
        rev = session.document.revision_count
        session.persist_working_model()
        assert session._working_path("doc.docx").is_file()

        # Fresh session (simulates a browser reload / restart): auto-reopen must
        # restore the edited model, not the pristine file.
        ws_state._workspaces.clear()
        reopened = open_workspace(workspace_dir)
        assert reopened.document is not None
        assert reopened.document.is_dirty is True
        assert reopened.document.revision_count == rev

    def test_stale_snapshot_is_ignored(self, workspace_dir):
        import os

        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        self._edit(session)
        session.persist_working_model()

        # Source file changes under us → snapshot must be discarded (parse disk).
        st = (workspace_dir / "doc.docx").stat()
        os.utime(workspace_dir / "doc.docx", (st.st_atime, st.st_mtime + 1000))

        ws_state._workspaces.clear()
        reopened = open_workspace(workspace_dir)
        assert reopened.document is not None
        assert reopened.document.is_dirty is False        # pristine parse, not the snapshot

    def test_clear_removes_snapshot(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        self._edit(session)
        session.persist_working_model()
        assert session._working_path("doc.docx").is_file()

        session.clear_working_model()
        assert not session._working_path("doc.docx").is_file()

    def test_sync_clears_when_not_dirty(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        self._edit(session)
        session.persist_working_model()
        assert session._working_path("doc.docx").is_file()

        session.document.is_dirty = False   # e.g. after an export
        session.sync_working_model()
        assert not session._working_path("doc.docx").is_file()

    def test_corrupt_snapshot_falls_back_to_disk(self, workspace_dir):
        session = open_workspace(workspace_dir)
        session.open_document("doc.docx")
        self._edit(session)
        session.persist_working_model()
        session._working_path("doc.docx").write_text("{not json", encoding="utf-8")

        ws_state._workspaces.clear()
        reopened = open_workspace(workspace_dir)
        assert reopened.document is not None               # did not crash
        assert reopened.document.is_dirty is False          # fell back to pristine
