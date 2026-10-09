"""
Workflow Integration Tests.

Tests the complete workflow: upload → generate → accept → export
using the DOM model with session utilities.
"""

import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.document_model import (
    DocumentModel,
    DocumentSerializer,
    parse_docx,
    DocumentEdit,
    EditType,
)
from src.session_utils import (
    create_session_from_model,
    get_model_from_session,
    is_dom_session,
    convert_dom_thread_for_llm,
    build_paragraph_cache_from_model,
    build_thread_target_indices_from_model,
)
from tests.test_support import SYNTHETIC_TEST_DATA_DIR


class TestCompleteWorkflow:
    """Tests simulating the complete application workflow."""
    
    @pytest.fixture
    def test_docx_path(self):
        """Get path to test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return path
    
    def test_upload_workflow(self, test_docx_path):
        """
        Test upload workflow: parse document and create session.
        
        Simulates what happens in the /upload endpoint.
        """
        # Parse document (like in upload endpoint)
        model = parse_docx(test_docx_path)
        
        # Verify we have the expected data
        assert model is not None
        assert model.paragraph_count > 0
        
        # Create session from model
        session = create_session_from_model(
            session_id="test-session",
            filename="test.docx",
            filepath=str(test_docx_path),
            output_dir=Path("/tmp"),
            model=model
        )
        
        # Verify session structure
        assert is_dom_session(session)
        assert get_model_from_session(session) is model
        
        # Get legacy-compatible threads
        threads = []
        for dom_thread in model.comments.threads.values():
            legacy_thread = convert_dom_thread_for_llm(dom_thread, model)
            threads.append(legacy_thread)
        
        assert isinstance(threads, list)
        
        # Get paragraph cache and indices
        paragraph_cache = build_paragraph_cache_from_model(model)
        thread_target_indices = build_thread_target_indices_from_model(model)
        
        assert isinstance(paragraph_cache, list)
        assert isinstance(thread_target_indices, dict)
        
        # Verify thread structure
        for thread in threads:
            assert thread.thread_id
            assert len(thread.comments) > 0
    
    def test_context_generation_workflow(self, test_docx_path):
        """
        Test context generation for LLM.
        
        Simulates what happens before calling generate_suggestion.
        """
        model = parse_docx(test_docx_path)
        
        if not model.thread_count:
            pytest.skip("No threads in test document")
        
        # Get first thread
        thread_id = list(model.comments.threads.keys())[0]
        dom_thread = model.comments.get_thread(thread_id)
        
        # Get context from the model
        root_anchor = dom_thread.root.anchor
        if root_anchor:
            para = model.body.get_element_by_para_id(root_anchor.para_id)
            if para:
                target_text = para.plain_text
                assert target_text  # Should have some context
    
    def test_accept_workflow(self, test_docx_path):
        """
        Test accept workflow: apply edit directly to model.
        
        Simulates what happens in the /accept endpoint.
        """
        model = parse_docx(test_docx_path)
        
        if not model.thread_count:
            pytest.skip("No threads in test document")
        
        # Get thread and para_id
        thread_id = list(model.comments.threads.keys())[0]
        dom_thread = model.comments.get_thread(thread_id)
        
        root_anchor = dom_thread.root.anchor
        if not root_anchor:
            pytest.skip("Thread has no anchor")
        
        para_id = root_anchor.para_id
        para = model.body.get_element_by_para_id(para_id)
        if not para:
            pytest.skip("Paragraph not found")
        
        original_text = para.plain_text
        revised_text = "This is the revised text accepted by the user."
        
        # Apply edit to model (like /accept does for DOM sessions)
        edit = DocumentEdit(
            edit_type=EditType.REPLACE,
            para_id=para_id,
            start_offset=0,
            end_offset=len(original_text),
            text=revised_text,
            author="Stet",
            track_change=True
        )
        model.apply_edit(edit)
        
        # Verify the revision is applied
        updated_para = model.body.get_element_by_para_id(para_id)
        assert updated_para.plain_text == revised_text
    
    def test_export_workflow_with_reply(self, test_docx_path, tmp_path):
        """
        Test export workflow: add reply and export.
        
        Simulates what happens in the /export endpoint.
        """
        model = parse_docx(test_docx_path)
        
        if not model.thread_count:
            pytest.skip("No threads in test document")
        
        thread_id = list(model.comments.threads.keys())[0]
        original_comment_count = model.comment_count
        
        # Add reply (like export would do)
        reply = model.add_reply(
            parent_comment_id=thread_id,
            text="Thank you for your feedback. We have addressed your comment.",
            author="Stet",
            timestamp=datetime.now(timezone.utc)
        )
        
        assert reply is not None
        
        # Export document
        output_path = tmp_path / "exported.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True)
        
        # Verify export
        assert output_path.exists()
        
        # Re-parse and verify reply was added
        model2 = parse_docx(output_path)
        assert model2.comment_count == original_comment_count + 1
    
    def test_full_workflow_simulation(self, test_docx_path, tmp_path):
        """
        Test complete workflow: upload → accept revision → add reply → export.
        
        Full simulation of the application workflow using DOM model.
        """
        # === UPLOAD ===
        model = parse_docx(test_docx_path)
        
        if not model.thread_count:
            pytest.skip("No threads in test document")
        
        # Get legacy-compatible threads and caches
        threads = [
            convert_dom_thread_for_llm(t, model) 
            for t in model.comments.threads.values()
        ]
        thread = threads[0]
        
        paragraph_cache = build_paragraph_cache_from_model(model)
        thread_target_indices = build_thread_target_indices_from_model(model)
        
        print(f"Uploaded: {len(threads)} threads, {len(paragraph_cache)} paragraphs")
        
        # === GENERATE (simulated) ===
        thread_id = thread.thread_id
        dom_thread = model.comments.get_thread(thread_id)
        root_anchor = dom_thread.root.anchor
        
        target_text = ""
        para_id = None
        if root_anchor:
            para_id = root_anchor.para_id
            para = model.body.get_element_by_para_id(para_id)
            if para:
                target_text = para.plain_text
        
        # Simulated LLM response
        revised_text = f"[REVISED] {target_text}" if target_text else "[REVISED] Sample revision"
        response_text = "Thank you for your comment. We have revised the text accordingly."
        
        print(f"Generated suggestion for thread {thread_id}")
        
        # === ACCEPT ===
        if para_id and target_text:
            edit = DocumentEdit(
                edit_type=EditType.REPLACE,
                para_id=para_id,
                start_offset=0,
                end_offset=len(target_text),
                text=revised_text,
                author="Stet",
                track_change=True
            )
            model.apply_edit(edit)
            print(f"Accepted revision for para_id {para_id}")
        
        # Verify revision is reflected
        if para_id:
            updated_para = model.body.get_element_by_para_id(para_id)
            if updated_para:
                assert updated_para.plain_text == revised_text
        
        # === EXPORT ===
        # Add reply
        model.add_reply(
            parent_comment_id=thread_id,
            text=response_text,
            author="Stet"
        )
        
        # Export with tracked changes
        output_path = tmp_path / "final_output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(
            model,
            output_path,
            include_track_changes=True,
            preserve_original=True
        )
        
        assert output_path.exists()
        print(f"Exported to {output_path}")
        
        # Verify the output
        model2 = parse_docx(output_path)
        
        # Reply should be added
        assert model2.comment_count >= model.comment_count


class TestMultipleThreadsWorkflow:
    """Tests workflow with multiple threads."""
    
    @pytest.fixture
    def multi_thread_docx(self):
        """Get a document with multiple threads."""
        # Use a file that has multiple comment threads
        for filename in ["test.docx", "test_comment_chain.docx", "reply_test.docx"]:
            path = SYNTHETIC_TEST_DATA_DIR / filename
            if path.exists():
                model = parse_docx(path)
                if model.thread_count >= 2:
                    return path
        pytest.skip("No multi-thread test document found")
    
    def test_process_multiple_threads(self, multi_thread_docx, tmp_path):
        """Test processing multiple threads in sequence."""
        model = parse_docx(multi_thread_docx)
        
        thread_ids = list(model.comments.threads.keys())[:3]  # Process up to 3 threads
        
        # Process each thread
        for thread_id in thread_ids:
            dom_thread = model.comments.get_thread(thread_id)
            root_anchor = dom_thread.root.anchor
            
            # Simulate acceptance
            if root_anchor:
                para_id = root_anchor.para_id
                para = model.body.get_element_by_para_id(para_id)
                if para:
                    original_text = para.plain_text
                    revised_text = f"[REVISED] {original_text}"
                    
                    edit = DocumentEdit(
                        edit_type=EditType.REPLACE,
                        para_id=para_id,
                        start_offset=0,
                        end_offset=len(original_text),
                        text=revised_text,
                        author="Stet",
                        track_change=True
                    )
                    model.apply_edit(edit)
            
            # Add reply
            model.add_reply(
                parent_comment_id=thread_id,
                text=f"Reply to thread {thread_id}",
                author="Stet"
            )
        
        # Export
        output_path = tmp_path / "multi_thread_output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True)
        
        assert output_path.exists()
        
        # Verify
        model2 = parse_docx(output_path)
        # Should have more comments (replies added)
        assert model2.comment_count >= model.comment_count


class TestParagraphSplitWorkflow:
    """Tests for paragraph split/merge workflows (Phase 6 feature)."""
    
    @pytest.fixture
    def test_docx_path(self):
        """Get path to test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return path
    
    def test_paragraph_split_basic(self, test_docx_path, tmp_path):
        """
        Test paragraph split: single paragraph → two paragraphs.
        
        Simulates what happens when LLM or user splits a paragraph.
        """
        from src.document_model.plain_text import apply_revision_from_plain_text
        
        model = parse_docx(test_docx_path)
        
        # Get a paragraph to split
        paragraphs = list(model.body.iter_paragraphs())
        if len(paragraphs) < 2:
            pytest.skip("Need at least 2 paragraphs")
        
        # Use a paragraph in the middle (not first/last)
        para = paragraphs[min(5, len(paragraphs) - 1)]
        para_id = para.para_id
        original_text = para.plain_text
        original_para_count = model.paragraph_count
        
        # Split into two paragraphs
        if len(original_text) > 50:
            split_point = len(original_text) // 2
            revised_text = original_text[:split_point] + "\n\n" + original_text[split_point:]
        else:
            revised_text = "First part of paragraph.\n\nSecond part of paragraph."
        
        # Apply the split
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text=revised_text,
            author="Stet",
            track_changes=True
        )
        
        assert len(edits) > 0, "Should have generated edits"
        
        # Verify paragraph count increased
        new_para_count = model.paragraph_count
        assert new_para_count > original_para_count, "Should have more paragraphs after split"
        
        # Export and verify
        output_path = tmp_path / "split_output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True, include_track_changes=True)
        
        assert output_path.exists()
        
        # Re-parse and verify structure
        model2 = parse_docx(output_path)
        assert model2.paragraph_count == new_para_count
    
    def test_paragraph_split_with_field_codes(self, test_docx_path, tmp_path):
        """
        Test paragraph split preserves field codes (citations).
        
        When a paragraph with [CITATION_1] is split, the field code
        should be correctly restored in whichever paragraph it ends up in.
        """
        from src.document_model.plain_text import apply_revision_from_plain_text
        
        model = parse_docx(test_docx_path)
        
        # Find a paragraph with field codes
        para_with_field_codes = None
        for para in model.body.iter_paragraphs():
            if para.field_codes:
                para_with_field_codes = para
                break
        
        if not para_with_field_codes:
            pytest.skip("No paragraphs with field codes in test document")
        
        para_id = para_with_field_codes.para_id
        original_text = para_with_field_codes.plain_text
        field_codes = para_with_field_codes.field_codes.copy()
        
        # Verify we have a placeholder in the text
        has_placeholder = any(p in original_text for p in field_codes.keys())
        if not has_placeholder:
            pytest.skip("Field code placeholder not in paragraph text")
        
        # Find the placeholder position
        placeholder = list(field_codes.keys())[0]
        placeholder_pos = original_text.find(placeholder)
        
        # Split BEFORE the placeholder (so it ends up in second paragraph)
        if placeholder_pos > 20:
            split_point = placeholder_pos - 10
            revised_text = original_text[:split_point].strip() + "\n\n" + original_text[split_point:].strip()
        else:
            # Split AFTER the placeholder
            split_point = placeholder_pos + len(placeholder) + 10
            if split_point < len(original_text):
                revised_text = original_text[:split_point].strip() + "\n\n" + original_text[split_point:].strip()
            else:
                pytest.skip("Paragraph too short to split around field code")
        
        # Apply the split
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para_id],
            revised_text=revised_text,
            author="Stet",
            track_changes=True
        )
        
        assert len(edits) > 0
        
        # Export
        output_path = tmp_path / "field_code_split.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True, include_track_changes=True)
        
        assert output_path.exists()
        
        # Verify output can be parsed (basic validity check)
        model2 = parse_docx(output_path)
        assert model2 is not None
    
    def test_paragraph_merge(self, test_docx_path, tmp_path):
        """
        Test paragraph merge: two paragraphs → single paragraph.
        """
        from src.document_model.plain_text import apply_revision_from_plain_text
        
        model = parse_docx(test_docx_path)
        
        # Get two consecutive paragraphs
        paragraphs = list(model.body.iter_paragraphs())
        if len(paragraphs) < 3:
            pytest.skip("Need at least 3 paragraphs for merge test")
        
        # Use paragraphs in the middle
        idx = min(5, len(paragraphs) - 2)
        para1 = paragraphs[idx]
        para2 = paragraphs[idx + 1]
        
        original_para_count = model.paragraph_count
        
        # Merge: combine texts without paragraph break
        merged_text = para1.plain_text + " " + para2.plain_text
        
        # Apply the merge (revising both paragraphs into one)
        edits = apply_revision_from_plain_text(
            model=model,
            para_ids=[para1.para_id, para2.para_id],
            revised_text=merged_text,
            author="Stet",
            track_changes=True
        )
        
        # Verify paragraph count decreased
        new_para_count = model.paragraph_count
        assert new_para_count < original_para_count, "Should have fewer paragraphs after merge"
        
        # Export and verify
        output_path = tmp_path / "merge_output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True, include_track_changes=True)
        
        assert output_path.exists()


class TestErrorHandling:
    """Tests for error handling in workflow."""
    
    def test_nonexistent_thread(self):
        """Test handling of nonexistent thread."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        
        model = parse_docx(path)
        
        # Try to get nonexistent thread
        thread = model.comments.get_thread("nonexistent_thread_999")
        
        # Should return None, not crash
        assert thread is None
    
    def test_export_without_modifications(self, tmp_path):
        """Test export without any modifications."""
        path = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        
        model = parse_docx(path)
        original_para_count = model.paragraph_count
        original_comment_count = model.comment_count
        
        # Export without changes
        output_path = tmp_path / "unchanged.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, preserve_original=True)
        
        # Should preserve everything
        model2 = parse_docx(output_path)
        assert model2.paragraph_count == original_para_count
        assert model2.comment_count == original_comment_count
