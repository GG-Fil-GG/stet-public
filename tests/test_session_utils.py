"""
Tests for session utilities with DOM model support.

Tests the Phase 6+ session management that uses DocumentModel
as the single source of truth.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.session_utils import (
    create_session_from_model,
    serialize_session_for_save,
    deserialize_session_data,
    save_session_to_file,
    load_session_from_file,
    merge_loaded_session,
    get_model_from_session,
    is_dom_session,
    get_threads_from_session,
)
from src.document_model import DocumentModel, parse_docx
from src.constants import ThreadStatus
from tests.test_support import SYNTHETIC_TEST_DATA_DIR

class TestCreateSessionFromModel:
    """Tests for create_session_from_model()."""
    
    @pytest.fixture
    def sample_model(self):
        """Get a parsed model from test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return parse_docx(path)
    
    def test_creates_session_structure(self, sample_model):
        """Test that session has required structure."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        assert "model" in session
        assert "suggestions" in session
        assert "thread_status" in session
        assert "chat_history" in session
        assert session["filename"] == "test.docx"
    
    def test_thread_status_initialized(self, sample_model):
        """Test that thread statuses are initialized."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        # All threads should have PENDING status
        for status in session["thread_status"].values():
            assert status == ThreadStatus.PENDING
    
    def test_model_stored(self, sample_model):
        """Test that model is stored in session."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        assert session["model"] is sample_model


class TestSessionSerialization:
    """Tests for session serialization/deserialization."""
    
    @pytest.fixture
    def sample_model(self):
        """Get a parsed model from test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return parse_docx(path)
    
    @pytest.fixture
    def dom_session(self, sample_model):
        """Create a DOM-based session."""
        return create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
    
    def test_serialize_dom_session(self, dom_session):
        """Test serializing a DOM session."""
        serialized = serialize_session_for_save(dom_session)

        assert "model_data" in serialized
        assert serialized["version"] == "dom_v2"  # Updated for refactored architecture
        assert "original_model_data" in serialized  # Now stores original model instead of caches
        assert serialized.get("accepted_revisions") == {}  # Present but empty in DOM sessions
    
    def test_serialize_produces_json_compatible(self, dom_session):
        """Test that serialized data is JSON-compatible."""
        serialized = serialize_session_for_save(dom_session)
        
        # Should not raise
        json_str = json.dumps(serialized)
        assert json_str is not None
    
    def test_deserialize_dom_session(self, dom_session, sample_model):
        """Test deserializing a DOM session."""
        serialized = serialize_session_for_save(dom_session)
        deserialized = deserialize_session_data(serialized)

        assert "model" in deserialized
        assert deserialized["version"] == "dom_v2"  # Updated for refactored architecture
        assert "original_model_data" in deserialized  # Now stores original model
        assert deserialized["model"].paragraph_count == sample_model.paragraph_count
    
    def test_round_trip_preserves_data(self, dom_session, sample_model):
        """Test that serialization round-trip preserves data."""
        # Add some suggestions
        thread_ids = list(dom_session["thread_status"].keys())
        if thread_ids:
            dom_session["suggestions"][thread_ids[0]] = {
                "revised_text": "Test revision",
                "response": "Test response",
                "rationale": "Test rationale",
            }
            dom_session["thread_status"][thread_ids[0]] = ThreadStatus.ACCEPTED
        
        # Serialize and deserialize
        serialized = serialize_session_for_save(dom_session)
        deserialized = deserialize_session_data(serialized)
        
        # Check model
        assert deserialized["model"].paragraph_count == sample_model.paragraph_count
        assert deserialized["model"].comment_count == sample_model.comment_count
        
        # Check thread data in threads dict (will be merged later)
        if thread_ids:
            assert thread_ids[0] in serialized["threads"]
            thread_data = serialized["threads"][thread_ids[0]]
            assert thread_data["revised_text"] == "Test revision"
            assert thread_data["status"] == "accepted"


class TestFilePersistence:
    """Tests for file-based session persistence."""
    
    @pytest.fixture
    def sample_model(self):
        """Get a parsed model from test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return parse_docx(path)
    
    def test_save_and_load_dom_session(self, sample_model):
        """Test saving and loading a DOM session to file."""
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            
            # Create session
            session = create_session_from_model(
                session_id="test123",
                filename="test.docx",
                filepath="/tmp/test.docx",
                output_dir=output_dir,
                model=sample_model
            )
            
            # Save
            assert save_session_to_file(session, output_dir)
            
            # Load
            loaded = load_session_from_file(output_dir)
            
            assert loaded is not None
            assert "model" in loaded
            assert loaded["model"].paragraph_count == sample_model.paragraph_count


class TestSessionHelpers:
    """Tests for session helper functions."""
    
    @pytest.fixture
    def sample_model(self):
        """Get a parsed model from test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return parse_docx(path)
    
    def test_is_dom_session_true(self, sample_model):
        """Test is_dom_session returns True for DOM session."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        assert is_dom_session(session) is True
    
    def test_is_dom_session_false(self):
        """Test is_dom_session returns False for legacy session."""
        legacy_session = {
            "threads": [],
            "paragraph_cache": [],
            "model": None,
        }
        
        assert is_dom_session(legacy_session) is False
    
    def test_get_model_from_session(self, sample_model):
        """Test get_model_from_session returns model."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        result = get_model_from_session(session)
        assert result is sample_model
    
    def test_get_threads_from_dom_session(self, sample_model):
        """Test get_threads_from_session with DOM session."""
        session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        threads = get_threads_from_session(session)
        assert len(threads) == sample_model.comments.thread_count


class TestMergeLoadedSession:
    """Tests for merge_loaded_session with DOM support."""
    
    @pytest.fixture
    def sample_model(self):
        """Get a parsed model from test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return parse_docx(path)
    
    def test_merge_restores_model(self, sample_model):
        """Test that merge restores the model."""
        # Create fresh session
        fresh_session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        # Create loaded data with model
        loaded_data = {
            "model": sample_model,
            "threads": {},
            "context_settings": {"test": True},
        }
        
        valid_thread_ids = set(sample_model.comments.threads.keys())
        result = merge_loaded_session(fresh_session, loaded_data, valid_thread_ids)
        
        assert result["model"] is sample_model
        assert result["context_settings"] == {"test": True}
    
    def test_merge_restores_thread_status(self, sample_model):
        """Test that merge restores thread statuses."""
        fresh_session = create_session_from_model(
            session_id="test123",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp/output"),
            model=sample_model
        )
        
        thread_ids = list(sample_model.comments.threads.keys())
        loaded_data = {
            "model": sample_model,
            "threads": {},
        }
        
        if thread_ids:
            loaded_data["threads"][thread_ids[0]] = {
                "status": "accepted",
                "revised_text": "Test",
                "response": "Response",
            }
        
        result = merge_loaded_session(fresh_session, loaded_data, set(thread_ids))
        
        if thread_ids:
            assert result["thread_status"][thread_ids[0]] == ThreadStatus.ACCEPTED
            assert result["suggestions"][thread_ids[0]]["revised_text"] == "Test"
