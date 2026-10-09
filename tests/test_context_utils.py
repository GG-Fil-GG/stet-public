"""
Tests for src/context_utils.py

Tests for paragraph context extraction and table handling functions.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.context_utils import (
    highlight_cell_in_row,
    parse_table_row,
    parse_markdown_table,
    group_consecutive_table_rows,
    create_paragraph_entry,
    get_context_paragraphs,
    compute_table_diff_cells,
)


# =============================================================================
# HIGHLIGHT_CELL_IN_ROW TESTS
# =============================================================================

class TestHighlightCellInRow:
    """Tests for highlight_cell_in_row function."""
    
    def test_exact_match(self):
        """Test highlighting exact text match."""
        result = highlight_cell_in_row("Cell A | Cell B | Cell C", "Cell B")
        assert "<mark>Cell B</mark>" in result
    
    def test_no_match(self):
        """Test when search text is not found."""
        result = highlight_cell_in_row("Cell A | Cell B | Cell C", "Cell X")
        assert "<mark>" not in result
        assert result == "Cell A | Cell B | Cell C"
    
    def test_empty_inputs(self):
        """Test handling of empty inputs."""
        assert highlight_cell_in_row("", "search") == ""
        assert highlight_cell_in_row("text", "") == "text"
        assert highlight_cell_in_row("", "") == ""
    
    def test_occurrence_parameter(self):
        """Test highlighting specific occurrence."""
        row = "A | B | A | C"
        # First occurrence
        result1 = highlight_cell_in_row(row, "A", occurrence=1)
        assert result1.index("<mark>A</mark>") < result1.index(" | B")
        
    def test_whitespace_normalization(self):
        """Test that whitespace variations are handled."""
        row = "Name1,  Name2 | Value"
        result = highlight_cell_in_row(row, "Name1, Name2")
        # Should find match despite extra space
        assert "<mark>" in result


# =============================================================================
# PARSE_TABLE_ROW TESTS
# =============================================================================

class TestParseTableRow:
    """Tests for parse_table_row function."""
    
    def test_basic_row(self):
        """Test parsing basic pipe-separated row."""
        result = parse_table_row("Cell A | Cell B | Cell C")
        assert result == ["Cell A", "Cell B", "Cell C"]
    
    def test_with_leading_trailing_pipes(self):
        """Test parsing row with leading/trailing pipes."""
        result = parse_table_row("| Cell A | Cell B |")
        assert result == ["Cell A", "Cell B"]
    
    def test_strips_whitespace(self):
        """Test that cell values are stripped."""
        result = parse_table_row("  Cell A  |  Cell B  ")
        assert result == ["Cell A", "Cell B"]
    
    def test_empty_row(self):
        """Test handling empty row."""
        result = parse_table_row("")
        assert result == [""]
    
    def test_single_cell(self):
        """Test single cell row."""
        result = parse_table_row("Single Cell")
        assert result == ["Single Cell"]


# =============================================================================
# PARSE_MARKDOWN_TABLE TESTS
# =============================================================================

class TestParseMarkdownTable:
    """Tests for parse_markdown_table function."""
    
    def test_basic_table(self):
        """Test parsing basic markdown table."""
        markdown = """
| Header 1 | Header 2 |
|----------|----------|
| Cell A   | Cell B   |
| Cell C   | Cell D   |
"""
        result = parse_markdown_table(markdown)
        assert len(result) == 3  # Header + 2 data rows
        assert result[0] == ["Header 1", "Header 2"]
        assert result[1] == ["Cell A", "Cell B"]
        assert result[2] == ["Cell C", "Cell D"]
    
    def test_skips_separator_lines(self):
        """Test that separator lines are skipped."""
        markdown = """| H1 | H2 |
|---|---|
| A | B |"""
        result = parse_markdown_table(markdown)
        assert len(result) == 2  # Header + 1 data row
    
    def test_empty_string(self):
        """Test handling empty input."""
        result = parse_markdown_table("")
        assert result == []
    
    def test_no_pipes(self):
        """Test input without pipes."""
        result = parse_markdown_table("No pipes here")
        assert result == []


# =============================================================================
# GROUP_CONSECUTIVE_TABLE_ROWS TESTS
# =============================================================================

class TestGroupConsecutiveTableRows:
    """Tests for group_consecutive_table_rows function."""
    
    def test_empty_list(self):
        """Test handling empty input."""
        result = group_consecutive_table_rows([])
        assert result == []
    
    def test_no_table_rows(self):
        """Test list with no table rows."""
        paragraphs = [
            {"type": "paragraph", "text": "Para 1"},
            {"type": "paragraph", "text": "Para 2"},
        ]
        result = group_consecutive_table_rows(paragraphs)
        assert len(result) == 2
        assert result[0]["type"] == "paragraph"
        assert result[1]["type"] == "paragraph"
    
    def test_consecutive_table_rows(self):
        """Test grouping consecutive table rows."""
        paragraphs = [
            {"type": "table_row", "row_number": 1, "total_rows": 3, "text": "Row 1"},
            {"type": "table_row", "row_number": 2, "total_rows": 3, "text": "Row 2"},
            {"type": "table_row", "row_number": 3, "total_rows": 3, "text": "Row 3"},
        ]
        result = group_consecutive_table_rows(paragraphs)
        
        assert len(result) == 1  # All rows grouped into one table_group
        assert result[0]["type"] == "table_group"
        assert len(result[0]["rows"]) == 3
        assert result[0]["continues_above"] == False  # row_number 1 is first
        assert result[0]["continues_below"] == False  # row 3 of 3
    
    def test_mixed_paragraphs_and_tables(self):
        """Test mixed content - paragraphs and table rows."""
        paragraphs = [
            {"type": "paragraph", "text": "Before table"},
            {"type": "table_row", "row_number": 1, "total_rows": 2, "text": "Row 1"},
            {"type": "table_row", "row_number": 2, "total_rows": 2, "text": "Row 2"},
            {"type": "paragraph", "text": "After table"},
        ]
        result = group_consecutive_table_rows(paragraphs)
        
        assert len(result) == 3
        assert result[0]["type"] == "paragraph"
        assert result[1]["type"] == "table_group"
        assert len(result[1]["rows"]) == 2
        assert result[2]["type"] == "paragraph"
    
    def test_continues_above_below_flags(self):
        """Test that continues_above/below flags are set correctly."""
        # Partial table (rows 2-3 of 4)
        paragraphs = [
            {"type": "table_row", "row_number": 2, "total_rows": 4, "text": "Row 2"},
            {"type": "table_row", "row_number": 3, "total_rows": 4, "text": "Row 3"},
        ]
        result = group_consecutive_table_rows(paragraphs)
        
        assert result[0]["continues_above"] == True  # Row 2 is not first
        assert result[0]["continues_below"] == True  # Row 3 is not last (4 total)


# =============================================================================
# CREATE_PARAGRAPH_ENTRY TESTS
# =============================================================================

class TestCreateParagraphEntry:
    """Tests for create_paragraph_entry function."""
    
    def test_regular_paragraph(self):
        """Test creating entry for regular paragraph."""
        para = {"para_id": "p1", "text": "Test text", "type": "paragraph"}
        result = create_paragraph_entry(para, {})
        
        assert result["text"] == "Test text"
        assert result["para_id"] == "p1"
        assert result["is_revised"] == False
        assert result["type"] == "paragraph"
    
    def test_paragraph_with_revision(self):
        """Test that accepted revisions are applied."""
        para = {"para_id": "p1", "text": "Original text", "type": "paragraph"}
        accepted = {"p1": "Revised text"}
        result = create_paragraph_entry(para, accepted)
        
        assert result["text"] == "Revised text"
        assert result["is_revised"] == True
    
    def test_table_row(self):
        """Test creating entry for table row."""
        para = {
            "para_id": "t1",
            "type": "table_row",
            "row_number": 1,
            "total_rows": 3,
            "cells": [
                {"para_id": "c1", "text": "Cell A"},
                {"para_id": "c2", "text": "Cell B"},
            ]
        }
        result = create_paragraph_entry(para, {})
        
        assert result["type"] == "table_row"
        assert result["text"] == "Cell A | Cell B"
        assert len(result["cells"]) == 2
        assert result["row_number"] == 1
        assert result["total_rows"] == 3
    
    def test_table_row_with_cell_revision(self):
        """Test table row with revised cell content."""
        para = {
            "para_id": "t1",
            "type": "table_row",
            "row_number": 1,
            "total_rows": 1,
            "cells": [
                {"para_id": "c1", "text": "Original"},
                {"para_id": "c2", "text": "Cell B"},
            ]
        }
        accepted = {"c1": "Revised"}
        result = create_paragraph_entry(para, accepted)
        
        assert "Revised | Cell B" == result["text"]
        assert result["is_revised"] == True
        assert result["cells"][0]["is_revised"] == True
        assert result["cells"][1]["is_revised"] == False
    
    def test_paragraph_with_html_revision(self):
        """Test that HTML in accepted_revisions is used for formatted_html and stripped for text."""
        para = {"para_id": "p1", "text": "Original text", "type": "paragraph"}
        # accepted_revisions now stores HTML (source of truth)
        accepted = {"p1": "<strong>Revised</strong> text with <em>formatting</em>"}
        result = create_paragraph_entry(para, accepted)
        
        # text should be plain (HTML stripped)
        assert result["text"] == "Revised text with formatting"
        # formatted_html should preserve the HTML
        assert result["formatted_html"] == "<strong>Revised</strong> text with <em>formatting</em>"
        assert result["is_revised"] == True
    
    def test_table_cell_with_html_revision(self):
        """Test table row cell with HTML in accepted_revisions."""
        para = {
            "para_id": "t1",
            "type": "table_row",
            "row_number": 1,
            "total_rows": 1,
            "cells": [
                {"para_id": "c1", "text": "Original"},
                {"para_id": "c2", "text": "Cell B"},
            ]
        }
        # HTML revision for cell c1
        accepted = {"c1": "<strong>Bold</strong> cell"}
        result = create_paragraph_entry(para, accepted)
        
        # Plain text display should have HTML stripped
        assert result["text"] == "Bold cell | Cell B"
        # But the cell's formatted_html should have the HTML
        assert result["cells"][0]["formatted_html"] == "<strong>Bold</strong> cell"
        assert result["cells"][0]["text"] == "Bold cell"
        assert result["is_revised"] == True


# =============================================================================
# GET_CONTEXT_PARAGRAPHS TESTS
# =============================================================================

class TestGetContextParagraphs:
    """Tests for get_context_paragraphs function."""
    
    def test_basic_context_extraction(self, sample_session):
        """Test basic context extraction around target."""
        settings = {"before_count": 2, "after_count": 2}
        result = get_context_paragraphs(sample_session, "thread1", settings)
        
        assert "before" in result
        assert "target" in result
        assert "after" in result
    
    def test_unknown_thread_id(self, sample_session):
        """Test with unknown thread ID returns empty lists."""
        settings = {"before_count": 2, "after_count": 2}
        result = get_context_paragraphs(sample_session, "unknown_thread", settings)
        
        assert result["before"] == []
        assert result["target"] == []
        assert result["after"] == []
    
    def test_before_count_respected(self, sample_session):
        """Test that before_count setting is respected."""
        settings = {"before_count": 1, "after_count": 0}
        result = get_context_paragraphs(sample_session, "thread1", settings)
        
        # Thread1 targets index 2, so before should have max 1 paragraph
        assert len(result["before"]) <= 1
    
    def test_after_count_respected(self, sample_session):
        """Test that after_count setting is respected."""
        settings = {"before_count": 0, "after_count": 1}
        result = get_context_paragraphs(sample_session, "thread1", settings)
        
        assert len(result["after"]) <= 1
    
    def test_ref_offset_adjustments(self, sample_session):
        """Test reference offset adjustments."""
        settings = {
            "before_count": 0, 
            "after_count": 0,
            "ref_start_offset": -1,  # Include one paragraph before
            "ref_end_offset": 1,     # Include one paragraph after
        }
        result = get_context_paragraphs(sample_session, "thread1", settings)
        
        # Target should include more paragraphs due to offsets
        assert len(result["target"]) >= 1
    
    def test_accepted_revisions_applied(self, sample_session):
        """Test that accepted revisions are shown in context."""
        sample_session["accepted_revisions"]["p3"] = "Revised paragraph text"
        settings = {"before_count": 0, "after_count": 0}
        result = get_context_paragraphs(sample_session, "thread1", settings)
        
        # Target paragraph should show revised text
        if result["target"]:
            target = result["target"][0]
            if target.get("type") != "table_group":
                assert target["is_revised"] == True
                assert target["text"] == "Revised paragraph text"
    
    def test_table_rows_grouped(self, sample_table_paragraph_cache):
        """Test that consecutive table rows are grouped."""
        session = {
            "paragraph_cache": sample_table_paragraph_cache,
            "thread_target_indices": {"thread1": (1, 3)},  # Table rows
            "accepted_revisions": {},
        }
        settings = {"before_count": 1, "after_count": 1}
        result = get_context_paragraphs(session, "thread1", settings)
        
        # Table rows in target should be grouped
        target_types = [item.get("type") for item in result["target"]]
        assert "table_group" in target_types or all(t == "table_row" for t in target_types)


# =============================================================================
# COMPUTE_TABLE_DIFF_CELLS TESTS
# =============================================================================

class TestComputeTableDiffCells:
    """Tests for compute_table_diff_cells function."""
    
    @staticmethod
    def mock_compute_diff(orig, rev):
        """Simple mock diff that returns a result-like object."""
        class MockResult:
            def __init__(self, orig, rev):
                self.original = orig
                self.revised = rev
        return MockResult(orig, rev)
    
    @staticmethod
    def mock_diff_to_html(result):
        """Simple mock that shows changes."""
        if result.original == result.revised:
            return result.revised
        elif not result.original:
            return f'<ins>{result.revised}</ins>'
        elif not result.revised:
            return f'<del>{result.original}</del>'
        else:
            return f'<del>{result.original}</del><ins>{result.revised}</ins>'
    
    def test_identical_rows(self):
        """Test when original and revised are identical."""
        original = [["A", "B", "C"]]
        revised = [["A", "B", "C"]]
        
        result = compute_table_diff_cells(
            original, revised, 
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert len(result) == 1
        assert len(result[0]) == 3
        assert all(cell['changed'] == False for cell in result[0])
        assert result[0][0]['html'] == "A"
        assert result[0][1]['html'] == "B"
        assert result[0][2]['html'] == "C"
    
    def test_single_cell_changed(self):
        """Test when only one cell changes."""
        original = [["A", "B", "C"]]
        revised = [["A", "X", "C"]]
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert result[0][0]['changed'] == False
        assert result[0][1]['changed'] == True
        assert result[0][2]['changed'] == False
        assert "<del>B</del><ins>X</ins>" in result[0][1]['html']
    
    def test_row_added(self):
        """Test when a new row is added."""
        original = [["A", "B"]]
        revised = [["A", "B"], ["C", "D"]]
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert len(result) == 2
        # First row unchanged
        assert result[0][0]['changed'] == False
        # Second row is new
        assert result[1][0]['added'] == True
        assert result[1][1]['added'] == True
    
    def test_row_deleted(self):
        """Test when a row is deleted."""
        original = [["A", "B"], ["C", "D"]]
        revised = [["A", "B"]]
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert len(result) == 2
        # First row unchanged
        assert result[0][0]['changed'] == False
        # Second row is deleted
        assert result[1][0]['deleted'] == True
        assert result[1][1]['deleted'] == True
    
    def test_multiple_rows_multiple_changes(self):
        """Test multiple rows with multiple changes."""
        original = [["A1", "B1", "C1"], ["A2", "B2", "C2"]]
        revised = [["A1", "X1", "C1"], ["A2", "B2", "Y2"]]
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        # Row 1: only middle cell changed
        assert result[0][0]['changed'] == False
        assert result[0][1]['changed'] == True
        assert result[0][2]['changed'] == False
        
        # Row 2: only last cell changed
        assert result[1][0]['changed'] == False
        assert result[1][1]['changed'] == False
        assert result[1][2]['changed'] == True
    
    def test_empty_original(self):
        """Test with empty original (all additions)."""
        original = []
        revised = [["A", "B"]]
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert len(result) == 1
        assert result[0][0]['added'] == True
        assert result[0][1]['added'] == True
    
    def test_empty_revised(self):
        """Test with empty revised (all deletions)."""
        original = [["A", "B"]]
        revised = []
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        assert len(result) == 1
        assert result[0][0]['deleted'] == True
        assert result[0][1]['deleted'] == True
    
    def test_unequal_column_counts(self):
        """Test handling rows with different column counts."""
        original = [["A", "B", "C"]]
        revised = [["A", "B"]]  # One less column
        
        result = compute_table_diff_cells(
            original, revised,
            self.mock_compute_diff, self.mock_diff_to_html
        )
        
        # Should handle gracefully - 3 columns (max)
        assert len(result[0]) == 3
        # Third column: original had "C", revised has empty
        assert result[0][2]['changed'] == True
