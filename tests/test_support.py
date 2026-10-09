"""Shared paths and helpers for tests."""

from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent
TEST_DATA_DIR = PROJECT_ROOT / "test_data"
SYNTHETIC_TEST_DATA_DIR = TEST_DATA_DIR / "synthetic"
LOCAL_TEST_DATA_DIR = TEST_DATA_DIR / "local"

TEST_DOCX = SYNTHETIC_TEST_DATA_DIR / "test.docx"
DUMMY_DOCX = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
REPLY_TEST_DOCX = SYNTHETIC_TEST_DATA_DIR / "reply_test.docx"
TEST_COMMENT_CHAIN_DOCX = SYNTHETIC_TEST_DATA_DIR / "test_comment_chain.docx"
TEST_TC_IN_RANGE_DOCX = SYNTHETIC_TEST_DATA_DIR / "test_tc_in_range.docx"
# Minimal fixture with EndNote-style citation fields (fldChar/instrText/fldData)
# and an en-dash year range — added in M9e to cover the field-code edit path that
# real manuscripts exercise but earlier fixtures did not.
CITATION_FIELD_DOCX = SYNTHETIC_TEST_DATA_DIR / "citation_field.docx"
SAMPLE_XLSX = SYNTHETIC_TEST_DATA_DIR / "attachments" / "adsl.xlsx"
SAMPLE_RTF = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.rtf"
SAMPLE_PPTX = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.pptx"
SAMPLE_TXT = SYNTHETIC_TEST_DATA_DIR / "attachments" / "sample.txt"


def require_synthetic_file(path: Path) -> Path:
    """Return path or fail fast if a committed synthetic fixture is missing."""
    if not path.exists():
        raise FileNotFoundError(f"Committed synthetic fixture missing: {path}")
    return path


def upload_docx(client: TestClient, docx_path: Path | None = None, filename: str | None = None) -> str:
    """Upload a docx via POST /upload and return the session_id."""
    from src.routes.state import sessions

    path = require_synthetic_file(docx_path or TEST_DOCX)
    upload_name = filename or path.name

    with open(path, "rb") as f:
        response = client.post(
            "/upload",
            files={
                "file": (
                    upload_name,
                    f,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200, f"Upload failed: {response.status_code} {response.text[:200]}"
    assert len(sessions) == 1, "Expected exactly one session after upload"
    return list(sessions.keys())[0]


def get_first_thread_id(session: dict) -> str:
    """Return the first thread id from a session's DOM model."""
    model = session["model"]
    return list(model.comments.threads.keys())[0]
