"""
Tests for session management functionality.

Tests the session cleanup/deletion endpoints.
"""

import pytest
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.routes.sessions import (
    get_session_folders,
    delete_session_folder,
)


class TestGetSessionFolders:
    """Tests for get_session_folders function."""
    
    def test_empty_sessions_dir(self, tmp_path):
        """Test when sessions directory is empty."""
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            folders = get_session_folders()
            assert folders == []
    
    def test_sessions_dir_not_exists(self, tmp_path):
        """Test when sessions directory doesn't exist."""
        non_existent = tmp_path / "does_not_exist"
        with patch('src.routes.sessions.get_sessions_dir', return_value=non_existent):
            folders = get_session_folders()
            assert folders == []
    
    def test_single_session_folder(self, tmp_path):
        """Test with a single session folder."""
        # Create a session folder with a file
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        (session_dir / "session.json").write_text('{"test": true}')
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            folders = get_session_folders()
            
            assert len(folders) == 1
            assert folders[0]['name'] == 'test_session'
            assert folders[0]['has_session_file'] == True
            assert folders[0]['size_mb'] >= 0
    
    def test_multiple_session_folders(self, tmp_path):
        """Test with multiple session folders."""
        # Create multiple session folders
        for name in ['session_a', 'session_b', 'session_c']:
            session_dir = tmp_path / name
            session_dir.mkdir()
            (session_dir / "data.txt").write_text("test data")
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            folders = get_session_folders()
            
            assert len(folders) == 3
            names = [f['name'] for f in folders]
            assert 'session_a' in names
            assert 'session_b' in names
            assert 'session_c' in names
    
    def test_folders_sorted_by_name(self, tmp_path):
        """Test that folders are sorted alphabetically by name."""
        for name in ['zebra', 'apple', 'mango']:
            (tmp_path / name).mkdir()
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            folders = get_session_folders()
            
            names = [f['name'] for f in folders]
            assert names == ['apple', 'mango', 'zebra']
    
    def test_ignores_files_in_sessions_dir(self, tmp_path):
        """Test that files in the sessions directory are ignored (only folders)."""
        (tmp_path / "some_file.txt").write_text("not a session")
        session_dir = tmp_path / "real_session"
        session_dir.mkdir()
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            folders = get_session_folders()
            
            assert len(folders) == 1
            assert folders[0]['name'] == 'real_session'


class TestDeleteSessionFolder:
    """Tests for delete_session_folder function."""
    
    def test_delete_existing_session(self, tmp_path):
        """Test deleting an existing session folder."""
        session_dir = tmp_path / "to_delete"
        session_dir.mkdir()
        (session_dir / "session.json").write_text('{}')
        (session_dir / "data.txt").write_text('test')
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            result = delete_session_folder("to_delete")
            
            assert result == True
            assert not session_dir.exists()
    
    def test_delete_nonexistent_session(self, tmp_path):
        """Test deleting a session that doesn't exist."""
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            result = delete_session_folder("nonexistent")
            
            assert result == False
    
    def test_delete_removes_from_memory(self, tmp_path):
        """Test that deleting a session removes it from in-memory dict."""
        from src.routes.sessions import sessions
        
        session_dir = tmp_path / "memory_test"
        session_dir.mkdir()
        
        # Add to in-memory sessions
        sessions["memory_test"] = {"test": True}
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            result = delete_session_folder("memory_test")
            
            assert result == True
            assert "memory_test" not in sessions
    
    def test_delete_nested_content(self, tmp_path):
        """Test that deleting removes all nested content."""
        session_dir = tmp_path / "nested"
        session_dir.mkdir()
        
        # Create nested structure
        llm_dir = session_dir / "llm"
        llm_dir.mkdir()
        (llm_dir / "thread_1.json").write_text('{}')
        (llm_dir / "thread_2.json").write_text('{}')
        
        attachments_dir = session_dir / "attachments"
        attachments_dir.mkdir()
        (attachments_dir / "file.pdf").write_text('fake pdf')
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            result = delete_session_folder("nested")
            
            assert result == True
            assert not session_dir.exists()
            assert not llm_dir.exists()
            assert not attachments_dir.exists()


class TestSessionEndpoints:
    """Tests for session management API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create a test client."""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_list_sessions_empty(self, client, tmp_path):
        """Test listing sessions when empty."""
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            response = client.get("/sessions/list")
            
            assert response.status_code == 200
            data = response.json()
            assert data['count'] == 0
            assert data['sessions'] == []
            assert data['total_size_mb'] == 0
    
    def test_list_sessions_with_data(self, client, tmp_path):
        """Test listing sessions with existing data."""
        # Create some sessions
        (tmp_path / "session1").mkdir()
        (tmp_path / "session2").mkdir()
        (tmp_path / "session1" / "session.json").write_text('{}')
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            response = client.get("/sessions/list")
            
            assert response.status_code == 200
            data = response.json()
            assert data['count'] == 2
    
    def test_delete_session_success(self, client, tmp_path):
        """Test deleting a specific session."""
        session_dir = tmp_path / "delete_me"
        session_dir.mkdir()
        (session_dir / "data.txt").write_text("test")
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            response = client.delete("/session/delete_me")
            
            assert response.status_code == 200
            data = response.json()
            assert data['success'] == True
            assert not session_dir.exists()
    
    def test_delete_session_not_found(self, client, tmp_path):
        """Test deleting a session that doesn't exist."""
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            response = client.delete("/session/nonexistent")
            
            assert response.status_code == 404
            data = response.json()
            assert data['success'] == False
    
    def test_delete_all_sessions(self, client, tmp_path):
        """Test deleting all sessions."""
        # Create multiple sessions
        (tmp_path / "session1").mkdir()
        (tmp_path / "session2").mkdir()
        (tmp_path / "session3").mkdir()
        
        with patch('src.routes.sessions.get_sessions_dir', return_value=tmp_path):
            response = client.delete("/sessions/all")
            
            assert response.status_code == 200
            data = response.json()
            assert data['success'] == True
            assert data['deleted'] == 3
            
            # Verify all deleted
            assert len(list(tmp_path.iterdir())) == 0
