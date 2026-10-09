"""HTTP route smoke tests (no LLM calls)."""

from src.constants import ThreadStatus
from src.routes.state import sessions
from tests.test_support import SAMPLE_XLSX, upload_docx, get_first_thread_id


def _inject_mock_suggestion(session, thread_id):
    thread = session["model"].comments.threads[thread_id]
    anchor = thread.root.anchor
    assert anchor, "Thread has no anchor"
    para_id = anchor.para_id
    para = session["model"].body.get_element_by_para_id(para_id)
    revised = para.plain_text + " [route test edit]"
    session["suggestions"][thread_id] = {
        "revised_text": revised,
        "revised_text_html": f"<p>{revised}</p>",
        "response": "Mock response for route testing",
        "target_para_id": para_id,
        "all_target_para_ids": [para_id],
    }


class TestConfigRoutes:
    def test_llm_config(self, client):
        response = client.get("/llm-config")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) >= 1

    def test_update_and_get_instructions(self, client):
        session_id = upload_docx(client)
        thread_id = get_first_thread_id(sessions[session_id])

        response = client.post(
            f"/update_instructions/{session_id}",
            data={"instructions": "Custom session instructions for testing"},
        )
        assert response.status_code == 200
        assert sessions[session_id]["default_instructions"] == "Custom session instructions for testing"

        response = client.post(
            f"/update_thread_instructions/{session_id}/{thread_id}",
            data={"instructions": "Thread-specific instructions"},
        )
        assert response.status_code == 200

        response = client.get(f"/get_instructions/{session_id}/{thread_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["instructions"] == "Thread-specific instructions"
        assert data["is_custom"] is True


class TestSuggestionRoutes:
    def test_skip_thread(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        response = client.post(f"/skip/{session_id}/{thread_id}")
        assert response.status_code == 200
        assert session["thread_status"][thread_id] == ThreadStatus.SKIPPED

    def test_update_suggestion(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)
        _inject_mock_suggestion(session, thread_id)

        response = client.post(
            f"/update_suggestion/{session_id}/{thread_id}",
            data={
                "revised_text": "Updated revised text for route test.",
                "response": "Updated response text.",
            },
        )
        assert response.status_code == 200
        assert "Updated revised text" in session["suggestions"][thread_id]["revised_text"]


class TestThreadRoutes:
    def test_expand_context(self, client):
        session_id = upload_docx(client)
        thread_id = get_first_thread_id(sessions[session_id])

        response = client.post(
            f"/expand_context/{session_id}/{thread_id}",
            data={"action": "before_plus"},
        )
        assert response.status_code == 200
        settings = sessions[session_id]["context_settings"][thread_id]
        assert settings["before_count"] >= 1

    def test_diff_html_endpoints(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)
        _inject_mock_suggestion(session, thread_id)

        for path in (
            f"/diff_html/{session_id}/{thread_id}",
            f"/editable_diff_html/{session_id}/{thread_id}",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert len(response.text) > 0

    def test_token_count_endpoint(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)
        _inject_mock_suggestion(session, thread_id)

        response = client.get(
            f"/token-count/{session_id}/{thread_id}",
            params={"format": "json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "token_count" in data
        assert data["token_count"] >= 0


class TestChatRoutes:
    def test_enter_and_exit_chat(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)
        _inject_mock_suggestion(session, thread_id)

        response = client.post(f"/enter_chat/{session_id}/{thread_id}")
        assert response.status_code == 200
        assert session["chat_mode_active"].get(thread_id) is True

        response = client.post(f"/exit_chat/{session_id}/{thread_id}")
        assert response.status_code == 200
        assert session["chat_mode_active"].get(thread_id) is False

    def test_clear_chat_history(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)
        _inject_mock_suggestion(session, thread_id)
        session["chat_history"][thread_id] = [{"role": "user", "content": "hello"}]

        response = client.post(f"/clear_chat_history/{session_id}/{thread_id}")
        assert response.status_code == 200
        history = session["chat_history"].get(thread_id, [])
        assert len(history) == 1
        assert history[0].role == "assistant"
        assert "Chat history cleared" in history[0].content


class TestAttachmentRoutes:
    def test_add_spreadsheet_attachment(self, client):
        session_id = upload_docx(client)
        thread_id = get_first_thread_id(sessions[session_id])

        with open(SAMPLE_XLSX, "rb") as f:
            response = client.post(
                f"/add_attachment/{session_id}/{thread_id}",
                files={"file": ("adsl.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )

        assert response.status_code == 200
        attachments = sessions[session_id]["attachments"].get(thread_id, [])
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "adsl.xlsx"


class TestSessionRoutes:
    def test_sessions_list_after_upload(self, client):
        upload_docx(client)
        response = client.get("/sessions/list")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
        assert data["count"] >= 0
