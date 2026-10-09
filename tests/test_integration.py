"""
Integration test for the full Stet workflow.

Tests the complete round-trip: upload → parse → generate → accept → export.
Uses the real FastAPI app via TestClient (no external server needed).

Usage:
    # Full test including real LLM call (requires OPENAI_API_KEY in .env):
    .venv/bin/python -m pytest tests/test_integration.py -v

    # Skip LLM call (structural checks only):
    .venv/bin/python -m pytest tests/test_integration.py -v -k "not llm"
"""

import os
import zipfile
import tempfile
from pathlib import Path

import pytest

from src.constants import APP_VERSION, ThreadStatus
from src.routes.state import sessions
from tests.test_support import TEST_DOCX, upload_docx, get_first_thread_id


class TestUploadAndParse:
    """Test document upload and parsing (no LLM calls)."""

    def test_upload_creates_session(self, client):
        session_id = upload_docx(client)
        assert session_id in sessions

    def test_upload_parses_threads(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        model = session["model"]
        assert model.comments.thread_count == 6

    def test_upload_parses_paragraphs(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        model = session["model"]
        assert model.body.paragraph_count >= 20

    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == APP_VERSION

    def test_sessions_endpoint(self, client):
        """Verify the /sessions debugging endpoint works."""
        session_id = upload_docx(client)
        response = client.get("/sessions")
        assert response.status_code == 200
        data = response.json()
        assert session_id in data
        assert data[session_id]["thread_count"] == 6
        assert data[session_id]["filename"] == "test.docx"

    def test_thread_card_renders(self, client):
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        response = client.get(f"/thread/{session_id}/{thread_id}")
        assert response.status_code == 200
        html = response.text
        assert "Dr. Reviewer" in html or "comment" in html.lower()


class TestGenerateAndAccept:
    """Test suggestion generation and acceptance (requires OPENAI_API_KEY)."""

    @pytest.fixture
    def api_key(self):
        """Get API key from environment, skip if not available."""
        from dotenv import load_dotenv
        load_dotenv()
        key = os.getenv("OPENAI_API_KEY")
        if not key or key == "paste-your-key-here":
            pytest.skip("OPENAI_API_KEY not set - skipping LLM integration test")
        return key

    def test_llm_generate_suggestion(self, client, api_key):
        """Test generating a suggestion with a real LLM call."""
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        response = client.post(
            f"/generate/{session_id}/{thread_id}",
            data={
                "provider": "openai",
                "api_key": api_key,
            },
        )

        assert response.status_code == 200, f"Generate failed: {response.text[:200]}"

        suggestion = session["suggestions"].get(thread_id)
        assert suggestion is not None, "Suggestion not stored in session"
        assert suggestion.get("revised_text"), "Suggestion has no revised_text"
        assert len(suggestion["revised_text"]) > 10, "Revised text suspiciously short"
        assert suggestion.get("revised_text_html"), "Suggestion has no revised_text_html"

    def test_llm_accept_suggestion(self, client, api_key):
        """Test accepting a generated suggestion."""
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        response = client.post(
            f"/generate/{session_id}/{thread_id}",
            data={"provider": "openai", "api_key": api_key},
        )
        assert response.status_code == 200

        response = client.post(f"/accept/{session_id}/{thread_id}")
        assert response.status_code == 200
        assert session["thread_status"].get(thread_id) == ThreadStatus.ACCEPTED

    def test_llm_export_after_accept(self, client, api_key):
        """Test full flow: generate → accept → export."""
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        response = client.post(
            f"/generate/{session_id}/{thread_id}",
            data={"provider": "openai", "api_key": api_key},
        )
        assert response.status_code == 200

        response = client.post(f"/accept/{session_id}/{thread_id}")
        assert response.status_code == 200

        response = client.post(
            f"/export/{session_id}",
            data={
                "insert_tracked_changes": "true",
                "author": "Stet Integration Test",
            },
        )
        assert response.status_code == 200, f"Export failed: {response.status_code}"

        content = response.content
        assert len(content) > 1000, "Exported file suspiciously small"

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                names = zf.namelist()
                assert "word/document.xml" in names
                assert "word/comments.xml" in names
                assert "[Content_Types].xml" in names

                doc_xml = zf.read("word/document.xml").decode("utf-8")
                assert doc_xml.startswith("<?xml")
                assert "</w:document>" in doc_xml
                assert "[CITATION_" not in doc_xml
                assert "w:ins" in doc_xml or "w:del" in doc_xml
        finally:
            os.unlink(tmp_path)


class TestExportWithoutLLM:
    """Test export mechanics without needing an LLM call (uses mock suggestion)."""

    def test_export_with_mock_suggestion(self, client):
        """Test export with a manually injected suggestion."""
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        thread = session["model"].comments.threads[thread_id]
        anchor = thread.root.anchor
        target_para_id = anchor.para_id if anchor else None
        assert target_para_id, "Thread has no anchor"

        para = session["model"].body.get_element_by_para_id(target_para_id)
        original_text = para.plain_text

        mock_revised = original_text.replace(".", ". [INTEGRATION TEST EDIT].", 1)
        session["suggestions"][thread_id] = {
            "revised_text": mock_revised,
            "revised_text_html": f"<p>{mock_revised}</p>",
            "response": "Mock suggestion for testing",
            "target_para_id": target_para_id,
            "all_target_para_ids": [target_para_id],
        }

        response = client.post(f"/accept/{session_id}/{thread_id}")
        assert response.status_code == 200
        assert session["thread_status"][thread_id] == ThreadStatus.ACCEPTED

        response = client.post(
            f"/export/{session_id}",
            data={
                "insert_tracked_changes": "true",
                "author": "Integration Test",
            },
        )
        assert response.status_code == 200

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                assert "</w:document>" in doc_xml
                assert "[CITATION_" not in doc_xml
                assert "INTEGRATION TEST EDIT" in doc_xml
        finally:
            os.unlink(tmp_path)

    def test_export_without_track_changes(self, client):
        """Test export without tracked changes still produces valid DOCX."""
        session_id = upload_docx(client)
        session = sessions[session_id]
        thread_id = get_first_thread_id(session)

        thread = session["model"].comments.threads[thread_id]
        target_para_id = thread.root.anchor.para_id
        para = session["model"].body.get_element_by_para_id(target_para_id)
        original_text = para.plain_text

        mock_revised = original_text + " EDIT TEST."
        session["suggestions"][thread_id] = {
            "revised_text": mock_revised,
            "revised_text_html": f"<p>{mock_revised}</p>",
            "response": "Mock suggestion for integration test",
            "target_para_id": target_para_id,
            "all_target_para_ids": [target_para_id],
        }

        response = client.post(f"/accept/{session_id}/{thread_id}")
        assert response.status_code == 200

        response = client.post(
            f"/export/{session_id}",
            data={"author": "Integration Test"},
        )
        assert response.status_code == 200

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                assert "</w:document>" in doc_xml
                assert "[CITATION_" not in doc_xml
                comments_xml = zf.read("word/comments.xml").decode("utf-8")
                assert "Integration Test" in comments_xml or "Mock suggestion" in comments_xml
        finally:
            os.unlink(tmp_path)
