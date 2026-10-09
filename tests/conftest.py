"""
Pytest configuration and shared fixtures.

Committed synthetic test documents live in test_data/synthetic/.
Local-only manuscripts live in test_data/local/ (gitignored).
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from src.routes.state import sessions
from tests.test_support import (
    SYNTHETIC_TEST_DATA_DIR,
    LOCAL_TEST_DATA_DIR,
    TEST_DOCX,
    DUMMY_DOCX,
    REPLY_TEST_DOCX,
    TEST_COMMENT_CHAIN_DOCX,
    TEST_TC_IN_RANGE_DOCX,
    SAMPLE_XLSX,
    upload_docx,
    get_first_thread_id,
    require_synthetic_file,
)


# =============================================================================
# PATH FIXTURES
# =============================================================================

@pytest.fixture
def project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def test_data_dir(project_root) -> Path:
    """Root test_data directory."""
    return project_root / "test_data"


@pytest.fixture
def synthetic_test_data_dir(test_data_dir) -> Path:
    """Committed synthetic test documents."""
    return test_data_dir / "synthetic"


@pytest.fixture
def local_test_data_dir(test_data_dir) -> Path:
    """Gitignored local-only test documents."""
    return test_data_dir / "local"


@pytest.fixture
def test_docx_path(synthetic_test_data_dir) -> Path:
    """Primary synthetic test document."""
    path = synthetic_test_data_dir / "test.docx"
    require_synthetic_file(path)
    return path


@pytest.fixture
def dummy_docx_path(synthetic_test_data_dir) -> Path:
    path = synthetic_test_data_dir / "dummy.docx"
    require_synthetic_file(path)
    return path


@pytest.fixture
def reply_test_docx_path(synthetic_test_data_dir) -> Path:
    path = synthetic_test_data_dir / "reply_test.docx"
    require_synthetic_file(path)
    return path


@pytest.fixture
def temp_dir():
    """Create a temporary directory that's cleaned up after the test."""
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
# APP / SESSION FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def clean_sessions():
    """Clear in-memory sessions before and after each test."""
    sessions.clear()
    yield
    sessions.clear()


@pytest.fixture
def client():
    """FastAPI TestClient for route tests."""
    return TestClient(app)


# =============================================================================
# SAMPLE DATA FIXTURES
# =============================================================================

@pytest.fixture
def sample_paragraph_cache():
    """Sample paragraph cache for testing context extraction."""
    return [
        {"para_id": "p1", "text": "First paragraph.", "type": "paragraph"},
        {"para_id": "p2", "text": "Second paragraph with more content.", "type": "paragraph"},
        {"para_id": "p3", "text": "Third paragraph - this is the target.", "type": "paragraph"},
        {"para_id": "p4", "text": "Fourth paragraph after target.", "type": "paragraph"},
        {"para_id": "p5", "text": "Fifth paragraph.", "type": "paragraph"},
    ]


@pytest.fixture
def sample_table_paragraph_cache():
    """Sample paragraph cache with table rows for testing table handling."""
    return [
        {"para_id": "p1", "text": "Before table.", "type": "paragraph"},
        {
            "para_id": "t1r1",
            "text": "Cell A | Cell B | Cell C",
            "type": "table_row",
            "row_number": 1,
            "total_rows": 3,
            "col_count": 3,
            "cells": [
                {"para_id": "c1", "text": "Cell A"},
                {"para_id": "c2", "text": "Cell B"},
                {"para_id": "c3", "text": "Cell C"},
            ]
        },
        {
            "para_id": "t1r2",
            "text": "Cell D | Cell E | Cell F",
            "type": "table_row",
            "row_number": 2,
            "total_rows": 3,
            "col_count": 3,
            "cells": [
                {"para_id": "c4", "text": "Cell D"},
                {"para_id": "c5", "text": "Cell E"},
                {"para_id": "c6", "text": "Cell F"},
            ]
        },
        {
            "para_id": "t1r3",
            "text": "Cell G | Cell H | Cell I",
            "type": "table_row",
            "row_number": 3,
            "total_rows": 3,
            "col_count": 3,
            "cells": [
                {"para_id": "c7", "text": "Cell G"},
                {"para_id": "c8", "text": "Cell H"},
                {"para_id": "c9", "text": "Cell I"},
            ]
        },
        {"para_id": "p2", "text": "After table.", "type": "paragraph"},
    ]


@pytest.fixture
def sample_thread_target_indices():
    """Sample thread target indices mapping thread_id to (start_idx, end_idx)."""
    return {
        "thread1": (2, 2),
        "thread2": (1, 3),
    }


@pytest.fixture
def sample_session(sample_paragraph_cache, sample_thread_target_indices):
    """Sample session dict for testing."""
    return {
        "paragraph_cache": sample_paragraph_cache,
        "thread_target_indices": sample_thread_target_indices,
        "accepted_revisions": {},
        "suggestions": {},
        "thread_status": {"thread1": "pending", "thread2": "pending"},
    }


@pytest.fixture
def sample_comment_thread():
    """Sample CommentThread-like dict for testing."""
    return {
        "thread_id": "test_thread_1",
        "comments": [
            {
                "id": "1",
                "author": "Reviewer",
                "date": "2024-01-15T10:30:00Z",
                "text": "Please clarify this statement.",
                "para_id": "p3",
            }
        ],
        "referenced_text": "Third paragraph - this is the target.",
        "exact_text": "this is the target",
        "exact_text_occurrence": 1,
    }


# =============================================================================
# DOCX TEST FILE FIXTURES
# =============================================================================

@pytest.fixture
def available_docx_files(synthetic_test_data_dir):
    """All committed synthetic DOCX files."""
    return list(synthetic_test_data_dir.glob("*.docx"))


@pytest.fixture
def sample_docx_path(test_docx_path):
    """Alias for the primary synthetic test document."""
    return test_docx_path


# =============================================================================
# MOCK LLM FIXTURES
# =============================================================================

@pytest.fixture
def mock_llm_response():
    """Sample LLM response for testing."""
    return {
        "revised_text": "This is the revised paragraph with improvements.",
        "response": "Thank you for pointing this out. I have clarified the statement.",
        "rationale": "The original text was ambiguous about the measurement.",
    }


@pytest.fixture
def mock_chat_response():
    """Sample chat response for testing."""
    return {
        "revised_text": "Updated revision based on feedback.",
        "response": "I've updated the response as requested.",
        "chat_response": "I understand your concern. I've made the changes you requested.",
    }
