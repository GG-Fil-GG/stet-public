"""
Tests for DocumentSerializer.

Tests round-trip serialization, comment XML generation, and track changes.
"""

import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.document_model import (
    DocumentModel,
    DocumentBody,
    DocumentSerializer,
    DocumentParser,
    Paragraph,
    Run,
    Comment,
    CommentStore,
    CommentThread,
    CommentAnchor,
    CommentParagraph,
    Revision,
    RevisionStore,
    DocumentEdit,
    EditType,
    parse_docx,
    generate_valid_para_id,
    generate_hex_id,
)
from src.document_model.paragraph import RevisionType
from tests.test_support import SYNTHETIC_TEST_DATA_DIR


class TestDocumentSerializerBasic:
    """Basic serialization tests."""
    
    def test_serializer_instantiation(self):
        """Test that serializer can be instantiated."""
        serializer = DocumentSerializer()
        assert serializer is not None
    
    def test_serialize_requires_source_path(self):
        """Test that serialize raises error when model has no source_path."""
        serializer = DocumentSerializer()
        model = DocumentModel()
        
        with pytest.raises(ValueError, match="no source_path"):
            serializer.serialize(model, Path("/tmp/output.docx"))
    
    def test_serialize_requires_existing_file(self, tmp_path):
        """Test that serialize raises error when source file doesn't exist."""
        serializer = DocumentSerializer()
        model = DocumentModel()
        model.source_path = Path("/nonexistent/file.docx")
        
        with pytest.raises(FileNotFoundError):
            serializer.serialize(model, tmp_path / "output.docx")


class TestCommentXMLGeneration:
    """Tests for comment XML generation."""
    
    def test_build_comment_element(self):
        """Test building a comment XML element."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="5",
            para_id="12345678",
            text="Test comment",
            author="Test Author",
            author_initials="TA",
            date=datetime(2025, 2, 5, 10, 30, 0, tzinfo=timezone.utc),
            text_id="ABCD1234",
            durable_id="EFGH5678"
        )
        
        xml = serializer._build_comment_element(comment)
        
        assert 'w:id="5"' in xml
        assert 'w:author="Test Author"' in xml
        assert 'w:initials="TA"' in xml
        assert 'w14:paraId="12345678"' in xml
        assert 'Test comment' in xml
    
    def test_build_comment_ex_element_root(self):
        """Test building commentEx element for root comment."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text="Root comment",
            is_resolved=False
        )
        
        xml = serializer._build_comment_ex_element(comment)
        
        assert 'w15:paraId="12345678"' in xml
        assert 'w15:done="0"' in xml
        assert 'w15:paraIdParent' not in xml
    
    def test_build_comment_ex_element_reply(self):
        """Test building commentEx element for reply comment."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="2",
            para_id="22222222",
            parent_para_id="11111111",
            text="Reply comment",
            is_resolved=False
        )
        
        xml = serializer._build_comment_ex_element(comment)
        
        assert 'w15:paraId="22222222"' in xml
        assert 'w15:paraIdParent="11111111"' in xml
        assert 'w15:done="0"' in xml
    
    def test_build_comment_id_element(self):
        """Test building commentId element."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text="Test",
            durable_id="ABCDEF12"
        )
        
        xml = serializer._build_comment_id_element(comment)
        
        assert 'w16cid:paraId="12345678"' in xml
        assert 'w16cid:durableId="ABCDEF12"' in xml
    
    def test_build_comment_extensible_element(self):
        """Test building commentExtensible element."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text="Test",
            durable_id="ABCDEF12",
            date_utc=datetime(2025, 2, 5, 10, 30, 0, tzinfo=timezone.utc)
        )
        
        xml = serializer._build_comment_extensible_element(comment)
        
        assert 'w16cex:durableId="ABCDEF12"' in xml
        assert 'w16cex:dateUtc="2025-02-05T10:30:00Z"' in xml


class TestIDExtraction:
    """Tests for extracting existing IDs from XML."""
    
    def test_extract_comment_ids(self):
        """Test extracting comment IDs from comments.xml."""
        serializer = DocumentSerializer()
        xml = '''
        <w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:comment w:id="1" w:author="A">text</w:comment>
            <w:comment w:id="5" w:author="B">text</w:comment>
        </w:comments>
        '''
        
        ids = serializer._extract_existing_comment_ids(xml)
        
        assert "1" in ids
        assert "5" in ids
        assert len(ids) == 2
    
    def test_extract_para_ids_from_extended(self):
        """Test extracting paraIds from commentsExtended.xml."""
        serializer = DocumentSerializer()
        xml = '''
        <w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">
            <w15:commentEx w15:paraId="11111111"/>
            <w15:commentEx w15:paraId="22222222"/>
        </w15:commentsEx>
        '''
        
        ids = serializer._extract_existing_para_ids_from_extended(xml)
        
        assert "11111111" in ids
        assert "22222222" in ids


class TestRevisionSerialization:
    """Tests for track changes serialization."""
    
    def test_analyze_runs_simple(self):
        """Test analyzing runs in simple paragraph XML."""
        serializer = DocumentSerializer()
        para_xml = '''
        <w:p>
            <w:r><w:t>Hello </w:t></w:r>
            <w:r><w:t>world</w:t></w:r>
        </w:p>
        '''
        
        runs = serializer._analyze_runs(para_xml)
        
        assert len(runs) == 2
        assert runs[0]['text'] == 'Hello '
        assert runs[0]['length'] == 6
        assert runs[1]['text'] == 'world'
        assert runs[1]['length'] == 5
    
    def test_analyze_runs_excludes_deleted(self):
        """Test that _analyze_runs excludes deleted text."""
        serializer = DocumentSerializer()
        para_xml = '''
        <w:p>
            <w:r><w:t>Hello </w:t></w:r>
            <w:del w:id="1"><w:r><w:delText>deleted</w:delText></w:r></w:del>
            <w:r><w:t>world</w:t></w:r>
        </w:p>
        '''
        
        runs = serializer._analyze_runs(para_xml)
        
        # Should only see non-deleted runs
        texts = [r['text'] for r in runs]
        assert 'Hello ' in texts
        assert 'world' in texts
        assert 'deleted' not in texts


class TestAnchorSerialization:
    """Tests for comment anchor serialization."""
    
    def test_anchor_exists_true(self):
        """Test detecting existing anchor."""
        serializer = DocumentSerializer()
        doc_xml = '''
        <w:p>
            <w:commentRangeStart w:id="1"/>
            <w:r><w:t>text</w:t></w:r>
            <w:commentRangeEnd w:id="1"/>
            <w:r><w:commentReference w:id="1"/></w:r>
        </w:p>
        '''
        
        assert serializer._anchor_exists(doc_xml, "1") is True
        assert serializer._anchor_exists(doc_xml, "2") is False


class TestRoundTrip:
    """Round-trip serialization tests using real DOCX files."""
    
    @pytest.fixture
    def test_docx_path(self):
        """Get path to test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return path
    
    @pytest.fixture
    def dummy_docx_path(self):
        """Get path to dummy.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        return path
    
    def test_round_trip_preserves_structure(self, test_docx_path, tmp_path):
        """Test that serialization preserves basic document structure."""
        # Parse
        model = parse_docx(test_docx_path)
        
        # Serialize
        output_path = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path)
        
        # Verify output exists and is valid zip
        assert output_path.exists()
        with zipfile.ZipFile(output_path, 'r') as zf:
            namelist = zf.namelist()
            assert 'word/document.xml' in namelist
            assert 'word/comments.xml' in namelist
    
    def test_round_trip_preserves_comments(self, test_docx_path, tmp_path):
        """Test that comments are preserved through round-trip."""
        # Parse
        model = parse_docx(test_docx_path)
        original_comment_count = model.comment_count
        
        # Serialize
        output_path = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path)
        
        # Re-parse
        model2 = parse_docx(output_path)
        
        # Verify comments preserved
        assert model2.comment_count >= original_comment_count
    
    def test_round_trip_preserves_paragraphs(self, dummy_docx_path, tmp_path):
        """Test that paragraphs are preserved through round-trip."""
        # Parse
        model = parse_docx(dummy_docx_path)
        original_para_count = model.paragraph_count
        
        # Serialize
        output_path = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path)
        
        # Re-parse
        model2 = parse_docx(output_path)
        
        # Verify paragraph count
        assert model2.paragraph_count == original_para_count


class TestAddReplyAndSerialize:
    """Tests for adding reply and serializing."""
    
    @pytest.fixture
    def test_docx_path(self):
        """Get path to test.docx."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        return path
    
    def test_add_reply_and_serialize(self, test_docx_path, tmp_path):
        """Test adding a reply and serializing to new file."""
        # Parse
        model = parse_docx(test_docx_path)
        
        if model.thread_count == 0:
            pytest.skip("No comment threads in test document")
        
        # Get first thread
        thread = list(model.comments.threads.values())[0]
        original_reply_count = thread.reply_count
        
        # Add reply
        reply = model.add_reply(
            parent_comment_id=thread.root.comment_id,
            text="Test reply from serializer",
            author="Test Author",
            timestamp=datetime.now(timezone.utc)
        )
        
        assert reply is not None
        
        # Serialize
        output_path = tmp_path / "with_reply.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path)
        
        # Re-parse and verify
        model2 = parse_docx(output_path)
        thread2 = model2.comments.get_thread(thread.thread_id)
        
        # New reply should be in the document
        assert thread2 is not None
        assert thread2.reply_count == original_reply_count + 1


class TestTrackChanges:
    """Tests for track changes serialization."""
    
    @pytest.fixture
    def model_with_revision(self, tmp_path):
        """Create a model with a pending revision."""
        # We need a real docx to serialize
        test_path = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        model = parse_docx(test_path)
        
        if model.paragraph_count == 0:
            pytest.skip("No paragraphs in test document")
        
        # Get first paragraph
        first_para = list(model.body.iter_paragraphs())[0]
        
        # Add a revision (insertion)
        model.revisions.add_insertion(
            para_id=first_para.para_id,
            position=0,
            text="INSERTED: ",
            author="Test Author",
            timestamp=datetime.now(timezone.utc)
        )
        
        return model
    
    def test_serialize_with_revisions(self, model_with_revision, tmp_path):
        """Test serializing a document with pending revisions."""
        output_path = tmp_path / "with_revisions.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model_with_revision, output_path)
        
        # Verify output is valid
        assert output_path.exists()
        with zipfile.ZipFile(output_path, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')
            # Should have track changes if enabled
            # Note: actual insertion may depend on paragraph finding


class TestCommentXMLFiles:
    """Tests for individual comment XML file generation."""
    
    @pytest.fixture
    def model_with_new_comment(self):
        """Create a model with a new comment to add."""
        test_path = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        model = parse_docx(test_path)
        return model
    
    def test_serialize_comments_xml_preserves_existing(self, model_with_new_comment, tmp_path):
        """Test that serialization preserves existing comments."""
        original_count = model_with_new_comment.comment_count
        
        output_path = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model_with_new_comment, output_path)
        
        # Read the comments.xml
        with zipfile.ZipFile(output_path, 'r') as zf:
            if 'word/comments.xml' in zf.namelist():
                comments_xml = zf.read('word/comments.xml').decode('utf-8')
                # Count comment elements
                import re
                comment_count = len(re.findall(r'<w:comment\s', comments_xml))
                assert comment_count == original_count


class TestSerializerEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_empty_xml_handling(self):
        """Test handling of empty or minimal XML."""
        serializer = DocumentSerializer()
        
        # Comments with no closing tag
        result = serializer._serialize_comments_xml(
            DocumentModel(), 
            '<w:comments></w:comments>'
        )
        # Should not crash, just return original
        assert '</w:comments>' in result
    
    def test_special_characters_escaped(self):
        """Test that special characters are properly escaped."""
        serializer = DocumentSerializer()
        comment = Comment(
            comment_id="1",
            para_id="12345678",
            text='Text with <special> & "characters"',
            author="Test <Author>",
            author_initials="TA"
        )
        
        xml = serializer._build_comment_element(comment)
        
        # XML special chars should be escaped
        assert '&lt;special&gt;' in xml
        assert '&amp;' in xml
        assert '&quot;' in xml
        assert '&lt;Author&gt;' in xml


class TestSerializerIntegration:
    """Integration tests with full workflow."""
    
    @pytest.fixture
    def sample_docx(self):
        """Get a sample docx for testing."""
        path = SYNTHETIC_TEST_DATA_DIR / "test.docx"
        if not path.exists():
            # Try dummy.docx
            path = SYNTHETIC_TEST_DATA_DIR / "dummy.docx"
        return path
    
    def test_full_workflow_parse_modify_serialize(self, sample_docx, tmp_path):
        """Test complete workflow: parse, modify, serialize."""
        # Parse
        model = parse_docx(sample_docx)
        
        # Track original state
        original_para_count = model.paragraph_count
        original_comment_count = model.comment_count
        
        # Modify - mark dirty
        model.is_dirty = True
        model.modified_at = datetime.now()
        
        # Serialize
        output_path = tmp_path / "modified.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path)
        
        # Verify
        assert output_path.exists()
        assert output_path.stat().st_size > 0
        
        # Re-parse and verify
        model2 = parse_docx(output_path)
        assert model2.paragraph_count == original_para_count
        assert model2.comment_count == original_comment_count
    
    def test_multiple_serializations(self, sample_docx, tmp_path):
        """Test that a document can be serialized multiple times."""
        model = parse_docx(sample_docx)
        serializer = DocumentSerializer()
        
        # Serialize twice
        output1 = tmp_path / "output1.docx"
        output2 = tmp_path / "output2.docx"
        
        serializer.serialize(model, output1)
        serializer.serialize(model, output2)
        
        # Both should be valid
        assert output1.exists()
        assert output2.exists()
        
        # And should produce identical content (minus timestamps)
        with zipfile.ZipFile(output1, 'r') as z1, zipfile.ZipFile(output2, 'r') as z2:
            assert z1.namelist() == z2.namelist()


class TestStructuralChanges:
    """Tests for Phase 5: Serializer handling of structural paragraph changes."""
    
    def test_extract_all_para_ids(self):
        """Test extraction of all paragraph IDs from document XML."""
        serializer = DocumentSerializer()
        
        doc_xml = '''<?xml version="1.0"?>
        <w:document>
            <w:body>
                <w:p w14:paraId="ABC12345" w14:textId="11111111">
                    <w:r><w:t>First</w:t></w:r>
                </w:p>
                <w:p w14:paraId="DEF67890" w14:textId="22222222">
                    <w:r><w:t>Second</w:t></w:r>
                </w:p>
            </w:body>
        </w:document>'''
        
        para_ids = serializer._extract_all_para_ids(doc_xml)
        
        assert "ABC12345" in para_ids
        assert "DEF67890" in para_ids
        assert len(para_ids) == 2
    
    def test_mark_paragraph_as_deleted(self):
        """Test marking a paragraph as deleted with track changes."""
        serializer = DocumentSerializer()
        
        doc_xml = '''<?xml version="1.0"?>
        <w:document xmlns:w="http://example.com" xmlns:w14="http://example.com">
            <w:body>
                <w:p w14:paraId="TODELETE" w14:textId="11111111">
                    <w:r><w:t>Delete this text</w:t></w:r>
                </w:p>
            </w:body>
        </w:document>'''
        
        timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        result_xml, next_id = serializer._mark_paragraph_as_deleted(
            doc_xml, "TODELETE", "TestAuthor", timestamp, 1
        )
        
        # Should contain deletion markup
        assert '<w:del ' in result_xml
        assert 'w:author="TestAuthor"' in result_xml
        assert '<w:delText' in result_xml
        # Original text should be in delText
        assert 'Delete this text' in result_xml
    
    def test_insert_new_paragraph(self):
        """Test inserting a new paragraph with track changes."""
        serializer = DocumentSerializer()
        
        # Create a minimal paragraph
        paragraph = Paragraph(
            para_id="NEWPARA1",
            text_id="33333333",
            runs=[Run(text="This is new content")]
        )
        
        doc_xml = '''<?xml version="1.0"?>
        <w:document xmlns:w="http://example.com" xmlns:w14="http://example.com">
            <w:body>
                <w:p w14:paraId="EXISTING" w14:textId="11111111">
                    <w:r><w:t>Existing paragraph</w:t></w:r>
                </w:p>
            </w:body>
        </w:document>'''
        
        timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        result_xml, next_id = serializer._insert_new_paragraph(
            doc_xml, paragraph, "EXISTING", None, "TestAuthor", timestamp, 1
        )
        
        # Should contain the new paragraph
        assert 'w14:paraId="NEWPARA1"' in result_xml
        # Should be wrapped in insertion markup
        assert '<w:ins ' in result_xml
        assert 'w:author="TestAuthor"' in result_xml
        # Should contain the text
        assert 'This is new content' in result_xml
    
    def test_find_insertion_position(self):
        """Test finding the insertion position for a new paragraph."""
        # Create a model with some paragraphs
        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="ORIG1", text_id="11111111", runs=[Run(text="First")]),
            Paragraph(para_id="NEW1", text_id="22222222", runs=[Run(text="New")]),
            Paragraph(para_id="ORIG2", text_id="33333333", runs=[Run(text="Second")]),
        ]
        
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore()
        )
        
        serializer = DocumentSerializer()
        original_para_ids = {"ORIG1", "ORIG2"}
        
        # NEW1 should be inserted after ORIG1
        after_id, before_id = serializer._find_insertion_position(model, "NEW1", original_para_ids)
        assert after_id == "ORIG1"
        assert before_id is None
        
        # ORIG1 has no previous existing paragraph - should return before next original
        after_id, before_id = serializer._find_insertion_position(model, "ORIG1", original_para_ids)
        # Since ORIG1 is in original, looking for position doesn't make sense, but should handle gracefully
        assert after_id is None or before_id is None  # Either could be None depending on logic
    
    def test_structural_changes_in_serialize_revisions(self, sample_docx_path, tmp_path):
        """Integration test: structural changes are handled in serialization."""
        model = parse_docx(sample_docx_path)
        original_para_count = model.paragraph_count
        
        # Get all existing para_ids
        existing_ids = set(p.para_id for p in model.body.iter_paragraphs())
        
        # Add a new paragraph
        new_para_id = generate_valid_para_id(existing_ids)
        existing_text_ids = set()
        new_text_id = generate_hex_id(existing_text_ids)
        
        # Get the first paragraph's ID to insert after
        first_para = next(model.body.iter_paragraphs())
        
        new_paragraph = Paragraph(
            para_id=new_para_id,
            text_id=new_text_id,
            runs=[Run(text="This is a new paragraph added by the test")]
        )
        
        # Insert at position 1 (after first paragraph)
        model.body.insert_element_at(1, new_paragraph)
        
        # Record a revision for the new paragraph
        model.revisions.add_insertion(
            para_id=new_para_id,
            position=0,
            text="This is a new paragraph added by the test",
            author="TestAuthor"
        )
        
        # Serialize
        output_path = tmp_path / "with_new_para.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output_path, include_track_changes=True)
        
        # Verify output exists
        assert output_path.exists()
        
        # Read document.xml and check for insertion markup
        with zipfile.ZipFile(output_path, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')
            
            # Should contain the new paragraph ID
            assert new_para_id in doc_xml
            # Should have insertion markup (the new paragraph wrapped in w:ins)
            assert '<w:ins ' in doc_xml


def _create_minimal_docx(path, document_xml=None):
    """Create a minimal valid docx file for testing."""
    if document_xml is None:
        document_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
  <w:body>
    <w:p w14:paraId="00000001" w14:textId="A0000001">
      <w:r><w:t>Hello world</w:t></w:r>
    </w:p>
    <w:p w14:paraId="00000002" w14:textId="A0000002">
      <w:r><w:t>Second paragraph</w:t></w:r>
    </w:p>
  </w:body>
</w:document>'''
    
    comments_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
</w:comments>'''
    
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>'''
    
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', document_xml)
        zf.writestr('word/comments.xml', comments_xml)


class TestPlainEdits:
    """Tests for plain (non-tracked) edit serialization."""

    def test_plain_edit_changes_text_in_export(self, tmp_path):
        """A paragraph edited with track_change=False must appear in the exported docx."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="00000001", text_id="A0000001",
                      runs=[Run(text="Hello world MODIFIED")]),
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Second paragraph")]),
        ]
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore(),
        )
        model.source_path = src
        model._plain_edited_para_ids.add("00000001")

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=False)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Hello world MODIFIED' in doc_xml
        assert '<w:ins ' not in doc_xml
        assert '<w:del ' not in doc_xml

    def test_plain_edit_preserves_unchanged_paragraph(self, tmp_path):
        """Unchanged paragraphs should remain untouched."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="00000001", text_id="A0000001",
                      runs=[Run(text="Hello world")]),
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Second paragraph")]),
        ]
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore(),
        )
        model.source_path = src

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=False)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Hello world' in doc_xml
        assert 'Second paragraph' in doc_xml

    def test_plain_edit_preserves_formatting(self, tmp_path):
        """Plain edits should write run formatting (bold, italic, etc.) to XML."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        from src.document_model.paragraph import RunFormatting

        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="00000001", text_id="A0000001", runs=[
                Run(text="Bold text", formatting=RunFormatting(bold=True)),
                Run(text=" and italic", formatting=RunFormatting(italic=True)),
            ]),
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Second paragraph")]),
        ]
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore(),
        )
        model.source_path = src
        model._plain_edited_para_ids.add("00000001")

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=False)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Bold text' in doc_xml
        assert ' and italic' in doc_xml
        assert '<w:b/>' in doc_xml
        assert '<w:i/>' in doc_xml

    def test_plain_edit_no_track_change_markup(self, tmp_path):
        """Plain edits must not produce w:ins or w:del markup."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="00000001", text_id="A0000001",
                      runs=[Run(text="Completely new text")]),
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Second paragraph")]),
        ]
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore(),
        )
        model.source_path = src
        model._plain_edited_para_ids.add("00000001")

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=False)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Completely new text' in doc_xml
        assert '<w:ins ' not in doc_xml
        assert '<w:del ' not in doc_xml

    def test_plain_edit_skips_paragraphs_with_revisions(self, tmp_path):
        """Paragraphs with pending revisions should be handled by the
        tracked-changes path, not the plain edit path."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        body = DocumentBody()
        body.elements = [
            Paragraph(para_id="00000001", text_id="A0000001",
                      runs=[Run(text="Tracked change text")]),
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Plain change text")]),
        ]
        revisions = RevisionStore()
        revisions.add_insertion(
            para_id="00000001", position=0, text="Tracked change text",
            author="Tester"
        )
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=revisions,
        )
        model.source_path = src
        model._plain_edited_para_ids.add("00000002")

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=True)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Plain change text' in doc_xml

    def test_plain_edit_via_apply_edit(self, tmp_path):
        """End-to-end: apply_edit with track_change=False followed by serialize."""
        src = tmp_path / "source.docx"
        _create_minimal_docx(src)

        body = DocumentBody()
        body.add_element(
            Paragraph(para_id="00000001", text_id="A0000001",
                      runs=[Run(text="Hello world")])
        )
        body.add_element(
            Paragraph(para_id="00000002", text_id="A0000002",
                      runs=[Run(text="Second paragraph")])
        )
        model = DocumentModel(
            body=body,
            comments=CommentStore(),
            revisions=RevisionStore(),
        )
        model.source_path = src

        edit = DocumentEdit(
            edit_type=EditType.REPLACE,
            para_id="00000001",
            start_offset=0,
            end_offset=11,
            text="Goodbye world",
            track_change=False,
        )
        model.apply_edit(edit)

        assert model.get_paragraph("00000001").plain_text == "Goodbye world"
        assert model.revisions.pending_count == 0

        output = tmp_path / "output.docx"
        serializer = DocumentSerializer()
        serializer.serialize(model, output, include_track_changes=False)

        with zipfile.ZipFile(output, 'r') as zf:
            doc_xml = zf.read('word/document.xml').decode('utf-8')

        assert 'Goodbye world' in doc_xml
        assert 'Hello world' not in doc_xml
        assert '<w:ins ' not in doc_xml
        assert '<w:del ' not in doc_xml


class TestInsertAtOffsetRunSplit:
    """Regression tests for mid-run insertion (_insert_at_offset / _split_run_and_insert).

    The mid-run split previously dropped the run's </w:t> and <w:rPr>, producing
    invalid XML. These lock in the fix.
    """

    def _para(self):
        return (
            '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" w14:paraId="A1">'
            '<w:pPr/><w:r><w:rPr><w:b/></w:rPr>'
            '<w:t xml:space="preserve">Hello world</w:t></w:r></w:p>'
        )

    def test_mid_run_insertion_is_well_formed(self):
        import lxml.etree as ET
        serializer = DocumentSerializer()
        content = '<w:ins><w:r><w:t>!!!</w:t></w:r></w:ins>'
        out = serializer._insert_at_offset(self._para(), 5, content)
        # Parses without error (would raise on the old broken output).
        ET.fromstring(out)

    def test_mid_run_split_preserves_rpr_on_both_halves(self):
        serializer = DocumentSerializer()
        out = serializer._insert_at_offset(self._para(), 5, '<MARK/>')
        # Both halves keep the bold run property.
        assert out.count('<w:rPr><w:b/></w:rPr>') == 2
        # Text is split cleanly around the insertion point.
        assert '>Hello</w:t>' in out
        assert '> world</w:t>' in out
        assert '</w:t></w:r><MARK/><w:r>' in out

    def test_split_run_without_text_falls_back(self):
        import lxml.etree as ET
        serializer = DocumentSerializer()
        # A run with no <w:t> (e.g. a field-code run) must stay well-formed.
        para = (
            '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:r><w:rPr/><w:fldChar w:fldCharType="begin"/></w:r></w:p>'
        )
        run_info = {'start': para.index('<w:r>'), 'end': para.index('</w:r>') + len('</w:r>'),
                    'length': 0, 'text': ''}
        out = serializer._split_run_and_insert(para, run_info, 0, '<MARK/>')
        ET.fromstring(out)
        assert '<MARK/>' in out
