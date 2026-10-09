"""Tests for Phase 2: Multi-paragraph edit support (same count)."""

import pytest
from dataclasses import field
from typing import List, Optional

from src.document_model import DocumentModel, DocumentBody, Paragraph, Run, DocumentEdit, EditType
from src.document_model.comments import Comment, CommentAnchor, CommentThread, CommentStore
from src.session_utils import build_thread_target_indices_from_model


def create_multi_paragraph_model(para_texts: List[str]) -> DocumentModel:
    """Create a DocumentModel with multiple paragraphs."""
    model = DocumentModel(
        source_path=None,
        body=DocumentBody()
    )
    
    for i, text in enumerate(para_texts):
        para = Paragraph(
            para_id=f"PARA{i:04d}",
            text_id=f"TEXT{i:04d}",
            runs=[Run(text=text)]
        )
        model.body.add_element(para)
    
    return model


class TestMultiParagraphDetection:
    """Test detection of multi-paragraph vs table revisions."""
    
    def test_multi_paragraph_detected_correctly(self):
        """Multiple para_ids without pipe character should be multi-paragraph."""
        all_target_para_ids = ["PARA0001", "PARA0002"]
        revised_text = "First paragraph revised.\n\nSecond paragraph revised."
        
        is_table = '|' in revised_text
        is_multi = len(all_target_para_ids) > 1 and not is_table
        
        assert is_multi is True
        assert is_table is False
    
    def test_table_revision_detected_correctly(self):
        """Multiple para_ids with pipe character should be table revision."""
        all_target_para_ids = ["CELL0001", "CELL0002"]
        revised_text = "| Cell 1 | Cell 2 |"
        
        is_table = '|' in revised_text
        is_multi = len(all_target_para_ids) > 1 and not is_table
        
        assert is_table is True
        assert is_multi is False
    
    def test_single_paragraph_detected_correctly(self):
        """Single para_id should not be multi-paragraph."""
        all_target_para_ids = ["PARA0001"]
        revised_text = "Single paragraph revised."
        
        is_table = '|' in revised_text
        is_multi = len(all_target_para_ids) > 1 and not is_table
        
        assert is_multi is False
        assert is_table is False


class TestMultiParagraphParsing:
    """Test parsing of multi-paragraph revised text."""
    
    def test_parse_two_paragraphs(self):
        """Two paragraphs separated by double newline."""
        revised_text = "First paragraph revised.\n\nSecond paragraph revised."
        paragraphs = revised_text.split('\n\n')
        
        assert len(paragraphs) == 2
        assert paragraphs[0] == "First paragraph revised."
        assert paragraphs[1] == "Second paragraph revised."
    
    def test_parse_three_paragraphs(self):
        """Three paragraphs separated by double newlines."""
        revised_text = "First para.\n\nSecond para.\n\nThird para."
        paragraphs = revised_text.split('\n\n')
        
        assert len(paragraphs) == 3
        assert paragraphs[0] == "First para."
        assert paragraphs[1] == "Second para."
        assert paragraphs[2] == "Third para."
    
    def test_paragraphs_with_internal_newlines(self):
        """Paragraphs can contain single newlines without splitting."""
        revised_text = "First line\ncontinued.\n\nSecond paragraph."
        paragraphs = revised_text.split('\n\n')
        
        assert len(paragraphs) == 2
        assert paragraphs[0] == "First line\ncontinued."
        assert paragraphs[1] == "Second paragraph."
    
    def test_whitespace_handling(self):
        """Leading/trailing whitespace should be stripped from paragraphs."""
        revised_text = "  First para.  \n\n  Second para.  "
        paragraphs = [p.strip() for p in revised_text.split('\n\n')]
        
        assert paragraphs[0] == "First para."
        assert paragraphs[1] == "Second para."


class TestMultiParagraphEdit:
    """Test applying edits to multiple paragraphs."""
    
    def test_two_paragraph_revision_applies_to_both(self):
        """Two-paragraph revision should apply separate edits to both paragraphs."""
        model = create_multi_paragraph_model([
            "Original first paragraph.",
            "Original second paragraph."
        ])
        
        # Simulate multi-paragraph revision
        all_target_para_ids = ["PARA0000", "PARA0001"]
        revised_text = "Revised first paragraph.\n\nRevised second paragraph."
        revised_paragraphs = revised_text.split('\n\n')
        thread_id = "thread_1"
        
        # Apply edits (mimicking the /accept endpoint logic)
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(revised_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                model.apply_edit(edit)
        
        # Verify both paragraphs were updated
        para1 = model.get_paragraph("PARA0000")
        para2 = model.get_paragraph("PARA0001")
        
        assert para1.plain_text == "Revised first paragraph."
        assert para2.plain_text == "Revised second paragraph."
    
    def test_three_paragraph_revision(self):
        """Three-paragraph revision should apply to all three paragraphs."""
        model = create_multi_paragraph_model([
            "Original A.",
            "Original B.",
            "Original C."
        ])
        
        all_target_para_ids = ["PARA0000", "PARA0001", "PARA0002"]
        revised_text = "Revised A.\n\nRevised B.\n\nRevised C."
        revised_paragraphs = revised_text.split('\n\n')
        thread_id = "thread_1"
        
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(revised_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                model.apply_edit(edit)
        
        assert model.get_paragraph("PARA0000").plain_text == "Revised A."
        assert model.get_paragraph("PARA0001").plain_text == "Revised B."
        assert model.get_paragraph("PARA0002").plain_text == "Revised C."
    
    def test_fewer_revised_paragraphs_than_targets(self):
        """If fewer revised paragraphs than targets, extras keep original."""
        model = create_multi_paragraph_model([
            "Original A.",
            "Original B.",
            "Original C."
        ])
        
        all_target_para_ids = ["PARA0000", "PARA0001", "PARA0002"]
        # Only 2 revised paragraphs for 3 targets
        revised_text = "Revised A.\n\nRevised B."
        revised_paragraphs = revised_text.split('\n\n')
        thread_id = "thread_1"
        
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para:
                original_text = para.plain_text
                if i < len(revised_paragraphs):
                    revised = revised_paragraphs[i].strip()
                else:
                    revised = original_text  # Keep original
                
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised,
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                model.apply_edit(edit)
        
        assert model.get_paragraph("PARA0000").plain_text == "Revised A."
        assert model.get_paragraph("PARA0001").plain_text == "Revised B."
        assert model.get_paragraph("PARA0002").plain_text == "Original C."  # Kept original


class TestMultiParagraphThreadTracking:
    """Test that multi-paragraph edits correctly track thread_id."""
    
    def test_revisions_track_thread_id(self):
        """Each revision in multi-paragraph edit should track the thread_id."""
        model = create_multi_paragraph_model([
            "Original A.",
            "Original B."
        ])
        
        all_target_para_ids = ["PARA0000", "PARA0001"]
        revised_text = "Revised A.\n\nRevised B."
        revised_paragraphs = revised_text.split('\n\n')
        thread_id = "thread_42"
        
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(revised_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id=thread_id
                )
                model.apply_edit(edit)
        
        # Check revisions have correct thread_id
        thread_revisions = model.revisions.get_revisions_by_thread(thread_id)
        assert len(thread_revisions) > 0
        
        for revision in thread_revisions:
            assert revision.thread_id == thread_id
    
    def test_different_threads_different_paragraphs(self):
        """Different threads can modify different paragraphs."""
        model = create_multi_paragraph_model([
            "Original A.",
            "Original B.",
            "Original C."
        ])
        
        # Thread 1 modifies first two paragraphs
        thread1_para_ids = ["PARA0000", "PARA0001"]
        thread1_text = "Thread1 A.\n\nThread1 B."
        thread1_paragraphs = thread1_text.split('\n\n')
        
        for i, para_id in enumerate(thread1_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(thread1_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=thread1_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id="thread_1"
                )
                model.apply_edit(edit)
        
        # Thread 2 modifies third paragraph
        para = model.get_paragraph("PARA0002")
        original_text = para.plain_text
        edit = DocumentEdit(
            edit_type=EditType.REPLACE,
            para_id="PARA0002",
            start_offset=0,
            end_offset=len(original_text),
            text="Thread2 C.",
            author="Stet",
            track_change=True,
            thread_id="thread_2"
        )
        model.apply_edit(edit)
        
        # Verify content
        assert model.get_paragraph("PARA0000").plain_text == "Thread1 A."
        assert model.get_paragraph("PARA0001").plain_text == "Thread1 B."
        assert model.get_paragraph("PARA0002").plain_text == "Thread2 C."
        
        # Verify thread tracking
        thread1_revisions = model.revisions.get_revisions_by_thread("thread_1")
        thread2_revisions = model.revisions.get_revisions_by_thread("thread_2")
        
        assert len(thread1_revisions) > 0
        assert len(thread2_revisions) > 0
        
        for rev in thread1_revisions:
            assert rev.thread_id == "thread_1"
        for rev in thread2_revisions:
            assert rev.thread_id == "thread_2"


class TestMultiParagraphWithFormatting:
    """Test multi-paragraph edits preserve paragraph structure."""
    
    def test_paragraph_count_preserved(self):
        """Multi-paragraph edit should preserve the number of paragraphs."""
        model = create_multi_paragraph_model([
            "Para 1 original.",
            "Para 2 original.",
            "Para 3 original."
        ])
        
        initial_count = len(list(model.body.elements))
        
        # Apply multi-paragraph revision
        all_target_para_ids = ["PARA0000", "PARA0001", "PARA0002"]
        revised_text = "Para 1 revised.\n\nPara 2 revised.\n\nPara 3 revised."
        revised_paragraphs = revised_text.split('\n\n')
        
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(revised_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id="thread_1"
                )
                model.apply_edit(edit)
        
        final_count = len(list(model.body.elements))
        assert final_count == initial_count  # Same number of paragraphs
    
    def test_para_ids_preserved(self):
        """Multi-paragraph edit should preserve paragraph IDs."""
        model = create_multi_paragraph_model([
            "Original A.",
            "Original B."
        ])
        
        original_para_ids = ["PARA0000", "PARA0001"]
        
        # Apply multi-paragraph revision
        all_target_para_ids = ["PARA0000", "PARA0001"]
        revised_text = "Revised A.\n\nRevised B."
        revised_paragraphs = revised_text.split('\n\n')
        
        for i, para_id in enumerate(all_target_para_ids):
            para = model.get_paragraph(para_id)
            if para and i < len(revised_paragraphs):
                original_text = para.plain_text
                edit = DocumentEdit(
                    edit_type=EditType.REPLACE,
                    para_id=para_id,
                    start_offset=0,
                    end_offset=len(original_text),
                    text=revised_paragraphs[i].strip(),
                    author="Stet",
                    track_change=True,
                    thread_id="thread_1"
                )
                model.apply_edit(edit)
        
        # Verify para_ids are still accessible
        for para_id in original_para_ids:
            para = model.get_paragraph(para_id)
            assert para is not None
            assert para.para_id == para_id


class TestMultiParagraphAnchorDetection:
    """Test detection of multi-paragraph comment anchors."""
    
    def _create_model_with_comment(self, para_texts: List[str], 
                                    anchor_start_para_idx: int, 
                                    anchor_end_para_idx: int = None) -> DocumentModel:
        """Create a model with paragraphs and a comment anchored to them."""
        model = create_multi_paragraph_model(para_texts)
        
        # Get para_ids
        para_ids = [f"PARA{i:04d}" for i in range(len(para_texts))]
        start_para_id = para_ids[anchor_start_para_idx]
        end_para_id = para_ids[anchor_end_para_idx] if anchor_end_para_idx is not None else None
        
        # Create a comment with anchor
        comment = Comment(
            comment_id="0",
            para_id="C0000000",  # Comment's own para_id (different from anchor para_id)
            author="Reviewer",
            text="Test comment"
        )
        
        # Create anchor - end_para_id is None for single-paragraph, different for multi
        anchor = CommentAnchor(
            comment_id="0",
            para_id=start_para_id,
            start_offset=0,
            end_offset=10,
            end_para_id=end_para_id if end_para_id != start_para_id else None
        )
        comment.anchor = anchor
        
        # Create thread and add to model
        thread = CommentThread(thread_id="0", root=comment)
        model.comments.threads["0"] = thread
        
        return model
    
    def test_single_paragraph_anchor_returns_same_start_end(self):
        """Single-paragraph anchor should have start_idx == end_idx."""
        model = self._create_model_with_comment(
            ["Para A", "Para B", "Para C"],
            anchor_start_para_idx=1,  # Anchored to Para B only
            anchor_end_para_idx=None
        )
        
        indices = build_thread_target_indices_from_model(model)
        
        assert "0" in indices
        start_idx, end_idx = indices["0"]
        assert start_idx == 1
        assert end_idx == 1  # Same as start
    
    def test_multi_paragraph_anchor_returns_range(self):
        """Multi-paragraph anchor should return (start_idx, end_idx) covering all paragraphs."""
        model = self._create_model_with_comment(
            ["Para A", "Para B", "Para C", "Para D"],
            anchor_start_para_idx=1,  # Start at Para B
            anchor_end_para_idx=2     # End at Para C
        )
        
        indices = build_thread_target_indices_from_model(model)
        
        assert "0" in indices
        start_idx, end_idx = indices["0"]
        assert start_idx == 1  # Para B
        assert end_idx == 2    # Para C
    
    def test_multi_paragraph_anchor_three_paragraphs(self):
        """Anchor spanning three paragraphs."""
        model = self._create_model_with_comment(
            ["Para 0", "Para 1", "Para 2", "Para 3", "Para 4"],
            anchor_start_para_idx=1,  # Start at Para 1
            anchor_end_para_idx=3     # End at Para 3
        )
        
        indices = build_thread_target_indices_from_model(model)
        
        assert "0" in indices
        start_idx, end_idx = indices["0"]
        assert start_idx == 1  # Para 1
        assert end_idx == 3    # Para 3
    
    def test_anchor_at_document_start_and_end(self):
        """Anchor from first to last paragraph."""
        model = self._create_model_with_comment(
            ["First", "Middle", "Last"],
            anchor_start_para_idx=0,
            anchor_end_para_idx=2
        )
        
        indices = build_thread_target_indices_from_model(model)
        
        assert "0" in indices
        start_idx, end_idx = indices["0"]
        assert start_idx == 0
        assert end_idx == 2


class TestMultiParagraphAnchorAdjustment:
    """Test anchor adjustment when editing paragraphs in multi-paragraph anchors."""
    
    def _create_model_with_multi_para_anchor(self, para_texts: list, start_idx: int, end_idx: int, anchor_offsets: tuple = (0, 10)):
        """Create a model with a comment anchor spanning multiple paragraphs."""
        from src.document_model.model import DocumentModel
        from src.document_model.paragraph import Paragraph, Run
        from src.document_model.comments import Comment, CommentThread, CommentAnchor
        
        model = DocumentModel(source_path=None)
        
        for i, text in enumerate(para_texts):
            para_id = f"P{i:08d}"
            para = Paragraph(para_id=para_id, text_id=f"T{i:08d}", runs=[Run(text=text)])
            model.body.add_element(para)
        
        paragraphs = list(model.body.iter_paragraphs())
        start_para_id = paragraphs[start_idx].para_id
        end_para_id = paragraphs[end_idx].para_id if end_idx != start_idx else None
        
        comment = Comment(
            comment_id="0",
            para_id="C0000000",
            author="Reviewer",
            text="Multi-para comment"
        )
        
        anchor = CommentAnchor(
            comment_id="0",
            para_id=start_para_id,
            start_offset=anchor_offsets[0],
            end_offset=anchor_offsets[1],
            end_para_id=end_para_id
        )
        comment.anchor = anchor
        
        thread = CommentThread(thread_id="0", root=comment)
        model.comments.threads["0"] = thread
        model.comments.comments["0"] = comment
        
        return model
    
    def test_edit_start_paragraph_shifts_start_offset(self):
        """When editing the START paragraph, start_offset should shift."""
        from src.document_model.edits import DocumentEdit, EditType
        
        model = self._create_model_with_multi_para_anchor(
            ["Intro paragraph", "Methods paragraph"],
            start_idx=0,
            end_idx=1,
            anchor_offsets=(5, 20)  # start_offset=5 in Intro, end_offset=20 in Methods
        )
        
        anchor = model.comments.comments["0"].anchor
        original_start = anchor.start_offset
        
        # Insert text at the beginning of Intro (position 0)
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="P00000000",
            start_offset=0,
            text="New: "
        )
        model.apply_edit(edit)
        
        # start_offset should shift by 5 (len("New: "))
        assert anchor.start_offset == original_start + 5
    
    def test_edit_end_paragraph_shifts_end_offset(self):
        """When editing the END paragraph, end_offset should shift."""
        from src.document_model.edits import DocumentEdit, EditType
        
        model = self._create_model_with_multi_para_anchor(
            ["Intro paragraph", "Methods paragraph"],
            start_idx=0,
            end_idx=1,
            anchor_offsets=(0, 20)  # end_offset=20 in Methods
        )
        
        anchor = model.comments.comments["0"].anchor
        original_end = anchor.end_offset
        
        # Insert text at position 10 in Methods (before end_offset=20)
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="P00000001",  # Methods paragraph
            start_offset=10,
            text="inserted "
        )
        model.apply_edit(edit)
        
        # end_offset should shift by 9 (len("inserted "))
        assert anchor.end_offset == original_end + 9
    
    def test_edit_end_paragraph_does_not_shift_start_offset(self):
        """Editing END paragraph should not affect start_offset (which is in START paragraph)."""
        from src.document_model.edits import DocumentEdit, EditType
        
        model = self._create_model_with_multi_para_anchor(
            ["Intro paragraph", "Methods paragraph"],
            start_idx=0,
            end_idx=1,
            anchor_offsets=(5, 20)
        )
        
        anchor = model.comments.comments["0"].anchor
        original_start = anchor.start_offset
        
        # Insert text in Methods paragraph
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="P00000001",
            start_offset=0,
            text="Added: "
        )
        model.apply_edit(edit)
        
        # start_offset should NOT change
        assert anchor.start_offset == original_start
    
    def test_edit_start_paragraph_does_not_shift_end_offset_in_end_para(self):
        """Editing START paragraph should not affect end_offset (which is in END paragraph)."""
        from src.document_model.edits import DocumentEdit, EditType
        
        model = self._create_model_with_multi_para_anchor(
            ["Intro paragraph", "Methods paragraph"],
            start_idx=0,
            end_idx=1,
            anchor_offsets=(0, 20)
        )
        
        anchor = model.comments.comments["0"].anchor
        original_end = anchor.end_offset
        
        # Insert text in Intro paragraph
        edit = DocumentEdit(
            edit_type=EditType.INSERT,
            para_id="P00000000",
            start_offset=0,
            text="Added: "
        )
        model.apply_edit(edit)
        
        # end_offset should NOT change (it's in the END paragraph)
        assert anchor.end_offset == original_end
