"""
Tests for thread-aware revision tracking (Phase 1).

These tests verify:
1. thread_id is properly attached to DocumentEdit and Revision
2. RevisionStore correctly indexes and filters by thread
3. Session stores thread original text correctly
4. Paragraph cache correctly excludes thread's own changes
"""

import pytest
from datetime import datetime
from pathlib import Path

from src.document_model import (
    DocumentModel, Paragraph, Run, RunFormatting,
    CommentStore, RevisionStore, DocumentEdit, EditType
)
from src.document_model.revisions import Revision
from src.document_model.paragraph import RevisionType
from src.session_utils import (
    create_session_from_model,
    store_thread_original_text,
    get_text_excluding_thread,
    clear_thread_original_text,
    get_paragraph_text_for_llm,
    build_paragraph_cache_for_thread,
    build_paragraph_cache_from_model,
)


class TestDocumentEditThreadId:
    """Test thread_id field in DocumentEdit."""
    
    def test_edit_has_thread_id_field(self):
        """DocumentEdit should have thread_id field."""
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="para1",
            start_offset=0,
            text="Hello",
            thread_id="thread1"
        )
        assert edit.thread_id == "thread1"
    
    def test_edit_thread_id_defaults_to_none(self):
        """thread_id should default to None."""
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="para1",
            start_offset=0,
            text="Hello"
        )
        assert edit.thread_id is None
    
    def test_factory_methods_accept_thread_id(self):
        """Factory methods should accept thread_id parameter."""
        insert = DocumentEdit.insert("para1", 0, "text", thread_id="t1")
        assert insert.thread_id == "t1"
        
        delete = DocumentEdit.delete("para1", 0, 5, thread_id="t2")
        assert delete.thread_id == "t2"
        
        replace = DocumentEdit.replace("para1", 0, 5, "new", thread_id="t3")
        assert replace.thread_id == "t3"
        
        fmt = DocumentEdit.format_change(
            "para1", 0, 5, RunFormatting(bold=True), thread_id="t4"
        )
        assert fmt.thread_id == "t4"


class TestRevisionThreadId:
    """Test thread_id field in Revision."""
    
    def test_revision_has_thread_id_field(self):
        """Revision should have thread_id field."""
        revision = Revision(
            revision_id="1",
            revision_type=RevisionType.INSERTION,
            para_id="para1",
            start_offset=0,
            end_offset=5,
            text="Hello",
            thread_id="thread1"
        )
        assert revision.thread_id == "thread1"
    
    def test_revision_thread_id_defaults_to_none(self):
        """thread_id should default to None."""
        revision = Revision(
            revision_id="1",
            revision_type=RevisionType.INSERTION,
            para_id="para1",
            start_offset=0,
            end_offset=5,
            text="Hello"
        )
        assert revision.thread_id is None
    
    def test_revision_serialization_includes_thread_id(self):
        """thread_id should be included in serialization."""
        revision = Revision(
            revision_id="1",
            revision_type=RevisionType.INSERTION,
            para_id="para1",
            start_offset=0,
            end_offset=5,
            text="Hello",
            thread_id="thread1"
        )
        data = revision.to_dict()
        assert data["thread_id"] == "thread1"
        
        restored = Revision.from_dict(data)
        assert restored.thread_id == "thread1"
    
    def test_revision_serialization_handles_none_thread_id(self):
        """None thread_id should serialize correctly."""
        revision = Revision(
            revision_id="1",
            revision_type=RevisionType.INSERTION,
            para_id="para1",
            start_offset=0,
            end_offset=5,
            text="Hello"
        )
        data = revision.to_dict()
        assert data["thread_id"] is None
        
        restored = Revision.from_dict(data)
        assert restored.thread_id is None


class TestRevisionStoreThreadTracking:
    """Test RevisionStore thread tracking methods."""
    
    def test_add_insertion_with_thread_id(self):
        """add_insertion should accept and store thread_id."""
        store = RevisionStore()
        rev = store.add_insertion(
            para_id="para1",
            position=0,
            text="Hello",
            thread_id="thread1"
        )
        assert rev.thread_id == "thread1"
    
    def test_add_deletion_with_thread_id(self):
        """add_deletion should accept and store thread_id."""
        store = RevisionStore()
        rev = store.add_deletion(
            para_id="para1",
            start=0,
            end=5,
            original_text="Hello",
            thread_id="thread1"
        )
        assert rev.thread_id == "thread1"
    
    def test_add_formatting_change_with_thread_id(self):
        """add_formatting_change should accept and store thread_id."""
        store = RevisionStore()
        rev = store.add_formatting_change(
            para_id="para1",
            start=0,
            end=5,
            new_formatting=RunFormatting(bold=True),
            original_formatting=RunFormatting(),
            thread_id="thread1"
        )
        assert rev.thread_id == "thread1"
    
    def test_get_revisions_by_thread(self):
        """get_revisions_by_thread should return revisions for a specific thread."""
        store = RevisionStore()
        store.add_insertion("para1", 0, "Hello", thread_id="thread1")
        store.add_insertion("para1", 5, " World", thread_id="thread1")
        store.add_insertion("para2", 0, "Other", thread_id="thread2")
        store.add_insertion("para3", 0, "No thread")  # No thread_id
        
        thread1_revs = store.get_revisions_by_thread("thread1")
        assert len(thread1_revs) == 2
        assert all(r.thread_id == "thread1" for r in thread1_revs)
        
        thread2_revs = store.get_revisions_by_thread("thread2")
        assert len(thread2_revs) == 1
        
        thread3_revs = store.get_revisions_by_thread("thread3")
        assert len(thread3_revs) == 0
    
    def test_get_revisions_excluding_thread(self):
        """get_revisions_excluding_thread should return all except given thread."""
        store = RevisionStore()
        store.add_insertion("para1", 0, "Hello", thread_id="thread1")
        store.add_insertion("para2", 0, "World", thread_id="thread2")
        store.add_insertion("para3", 0, "Other")  # No thread_id
        
        excluded = store.get_revisions_excluding_thread("thread1")
        assert len(excluded) == 2
        assert all(r.thread_id != "thread1" for r in excluded)
    
    def test_get_revisions_for_paragraph_excluding_thread(self):
        """Should filter by both paragraph and thread."""
        store = RevisionStore()
        store.add_insertion("para1", 0, "A", thread_id="thread1")
        store.add_insertion("para1", 1, "B", thread_id="thread2")
        store.add_insertion("para2", 0, "C", thread_id="thread1")
        
        # Para1, excluding thread1 -> should only get thread2's revision
        result = store.get_revisions_for_paragraph_excluding_thread("para1", "thread1")
        assert len(result) == 1
        assert result[0].thread_id == "thread2"
    
    def test_thread_index_rebuilt_on_deserialize(self):
        """Thread index should be rebuilt when deserializing."""
        store = RevisionStore()
        store.add_insertion("para1", 0, "Hello", thread_id="thread1")
        store.add_insertion("para1", 5, " World", thread_id="thread2")
        
        # Serialize and restore
        data = store.to_dict()
        restored = RevisionStore.from_dict(data)
        
        # Thread index should work
        thread1_revs = restored.get_revisions_by_thread("thread1")
        assert len(thread1_revs) == 1
        assert thread1_revs[0].text == "Hello"


class TestDocumentModelApplyEdit:
    """Test that DocumentModel.apply_edit passes thread_id to revisions."""
    
    def create_simple_model(self):
        """Create a simple model with one paragraph."""
        para = Paragraph(para_id="para1", text_id="text1", runs=[Run(text="Hello World")])
        model = DocumentModel()
        model.body.add_element(para)
        return model
    
    def test_apply_edit_creates_revision_with_thread_id(self):
        """apply_edit should create revisions with the edit's thread_id."""
        model = self.create_simple_model()
        
        edit = DocumentEdit.insert("para1", 0, "New ", thread_id="thread1")
        model.apply_edit(edit)
        
        revisions = model.revisions.get_revisions_by_thread("thread1")
        assert len(revisions) == 1
        assert revisions[0].text == "New "


class TestSessionThreadOriginalText:
    """Test session-level thread original text storage."""
    
    def create_test_session(self):
        """Create a test session with a simple model."""
        para = Paragraph(para_id="para1", text_id="text1", runs=[Run(text="Original text")])
        model = DocumentModel()
        model.body.add_element(para)
        session = create_session_from_model(
            session_id="test",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp"),
            model=model
        )
        return session, model
    
    def test_session_has_thread_original_text(self):
        """Session should have thread_original_text dict."""
        session, _ = self.create_test_session()
        assert "thread_original_text" in session
        assert session["thread_original_text"] == {}
    
    def test_store_thread_original_text(self):
        """store_thread_original_text should store original text."""
        session, _ = self.create_test_session()
        
        store_thread_original_text(session, "thread1", "para1", "Original text")
        
        assert session["thread_original_text"]["thread1"]["para1"] == "Original text"
    
    def test_store_thread_original_text_only_first(self):
        """Should only store the first original text (not overwrite)."""
        session, _ = self.create_test_session()
        
        store_thread_original_text(session, "thread1", "para1", "First")
        store_thread_original_text(session, "thread1", "para1", "Second")
        
        # Should still be "First"
        assert session["thread_original_text"]["thread1"]["para1"] == "First"
    
    def test_get_text_excluding_thread(self):
        """get_text_excluding_thread should return stored original text."""
        session, _ = self.create_test_session()
        
        store_thread_original_text(session, "thread1", "para1", "Original text")
        
        result = get_text_excluding_thread(session, "para1", "thread1")
        assert result == "Original text"
    
    def test_get_text_excluding_thread_returns_none_if_not_stored(self):
        """Should return None if thread hasn't modified the paragraph."""
        session, _ = self.create_test_session()
        
        result = get_text_excluding_thread(session, "para1", "thread1")
        assert result is None
    
    def test_clear_thread_original_text(self):
        """clear_thread_original_text should remove thread's stored data."""
        session, _ = self.create_test_session()
        
        store_thread_original_text(session, "thread1", "para1", "Original")
        assert "thread1" in session["thread_original_text"]
        
        clear_thread_original_text(session, "thread1")
        assert "thread1" not in session["thread_original_text"]
    
    def test_get_paragraph_text_for_llm_uses_stored(self):
        """get_paragraph_text_for_llm should use stored original if available."""
        session, model = self.create_test_session()
        
        # Store original text
        store_thread_original_text(session, "thread1", "para1", "Original text")
        
        # Modify the model
        para = model.get_paragraph("para1")
        para.runs = [Run(text="Modified text")]
        
        # Should return stored original, not current model text
        result = get_paragraph_text_for_llm(session, "para1", "thread1")
        assert result == "Original text"
    
    def test_get_paragraph_text_for_llm_uses_current_if_not_stored(self):
        """get_paragraph_text_for_llm should use current text if not stored."""
        session, model = self.create_test_session()
        
        # Don't store original text
        result = get_paragraph_text_for_llm(session, "para1", "thread1")
        assert result == "Original text"  # Current model text


class TestBuildParagraphCacheForThread:
    """Test thread-aware paragraph cache building."""
    
    def create_test_session_with_paragraphs(self):
        """Create session with multiple paragraphs."""
        para1 = Paragraph(para_id="para1", text_id="text1", runs=[Run(text="Paragraph 1")])
        para2 = Paragraph(para_id="para2", text_id="text2", runs=[Run(text="Paragraph 2")])
        para3 = Paragraph(para_id="para3", text_id="text3", runs=[Run(text="Paragraph 3")])
        
        model = DocumentModel()
        model.body.add_element(para1)
        model.body.add_element(para2)
        model.body.add_element(para3)
        
        session = create_session_from_model(
            session_id="test",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp"),
            model=model
        )
        return session, model
    
    def test_cache_without_thread_changes(self):
        """Cache should match normal cache when no thread changes stored."""
        session, model = self.create_test_session_with_paragraphs()
        
        normal_cache = build_paragraph_cache_from_model(model)
        thread_cache = build_paragraph_cache_for_thread(session, "thread1")
        
        assert len(thread_cache) == len(normal_cache)
        for i in range(len(thread_cache)):
            assert thread_cache[i]["text"] == normal_cache[i]["text"]
    
    def test_cache_with_thread_changes_overrides_text(self):
        """Cache should use stored original text for modified paragraphs."""
        session, model = self.create_test_session_with_paragraphs()
        
        # Store original text for thread1's modification of para2
        store_thread_original_text(session, "thread1", "para2", "Original Para 2")
        
        # Modify the model (simulating accepted edit)
        para2 = model.get_paragraph("para2")
        para2.runs = [Run(text="Modified Para 2")]
        
        # Build thread-aware cache
        thread_cache = build_paragraph_cache_for_thread(session, "thread1")
        
        # Para1 and Para3 should have current text
        assert thread_cache[0]["text"] == "Paragraph 1"
        assert thread_cache[2]["text"] == "Paragraph 3"
        
        # Para2 should have stored original text
        assert thread_cache[1]["text"] == "Original Para 2"
    
    def test_different_thread_sees_current_text(self):
        """Different thread should see current model text (including changes)."""
        session, model = self.create_test_session_with_paragraphs()
        
        # Store original text for thread1's modification of para2
        store_thread_original_text(session, "thread1", "para2", "Original Para 2")
        
        # Modify the model (simulating accepted edit)
        para2 = model.get_paragraph("para2")
        para2.runs = [Run(text="Modified Para 2")]
        # Clear cached plain_text since we modified runs directly
        para2._plain_text = None
        
        # Thread2 should see the modified text (current model state)
        thread2_cache = build_paragraph_cache_for_thread(session, "thread2")
        assert thread2_cache[1]["text"] == "Modified Para 2"


class TestMultipleThreadScenario:
    """Test scenarios with multiple threads modifying the same paragraph."""
    
    def create_session(self):
        """Create a session with one paragraph."""
        para = Paragraph(para_id="para1", text_id="text1", runs=[Run(text="Original")])
        model = DocumentModel()
        model.body.add_element(para)
        
        session = create_session_from_model(
            session_id="test",
            filename="test.docx",
            filepath="/tmp/test.docx",
            output_dir=Path("/tmp"),
            model=model
        )
        return session, model
    
    def test_thread_a_then_thread_b(self):
        """
        Simulate: Thread A accepts, Thread B accepts, Thread A regenerates.
        
        Thread A's stored original = "Original"
        After A's edit: "Modified by A"
        Thread B's stored original = "Modified by A"
        After B's edit: "Modified by A and B"
        
        When Thread A regenerates, it should see "Original" (its stored original).
        When Thread B regenerates, it should see "Modified by A" (its stored original).
        """
        session, model = self.create_session()
        para = model.get_paragraph("para1")
        
        # Thread A accepts
        store_thread_original_text(session, "threadA", "para1", "Original")
        para.runs = [Run(text="Modified by A")]
        
        # Thread B accepts (sees Thread A's changes as the baseline)
        store_thread_original_text(session, "threadB", "para1", "Modified by A")
        para.runs = [Run(text="Modified by A and B")]
        
        # Thread A regenerates - should see "Original"
        cacheA = build_paragraph_cache_for_thread(session, "threadA")
        assert cacheA[0]["text"] == "Original"
        
        # Thread B regenerates - should see "Modified by A"
        cacheB = build_paragraph_cache_for_thread(session, "threadB")
        assert cacheB[0]["text"] == "Modified by A"
