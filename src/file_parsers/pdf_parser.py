"""
PDF Parser for extracting text and tables from PDF documents.

Uses pdfplumber for reliable text and table extraction.
"""

import pdfplumber
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PDFPage:
    """Represents extracted content from a single PDF page."""
    page_number: int  # 1-indexed
    text: str
    tables: List[List[List[str]]]  # List of tables, each table is rows of cells
    
    def to_markdown(self, include_page_header: bool = True) -> str:
        """Convert page content to markdown format."""
        parts = []
        
        if include_page_header:
            parts.append(f"--- Page {self.page_number} ---")
        
        # Add text content
        if self.text.strip():
            parts.append(self.text.strip())
        
        # Add tables in markdown format
        for i, table in enumerate(self.tables):
            if table and len(table) > 0:
                parts.append(self._table_to_markdown(table, i + 1))
        
        return "\n\n".join(parts)
    
    def _table_to_markdown(self, table: List[List[str]], table_num: int) -> str:
        """Convert a table to markdown format."""
        if not table or len(table) == 0:
            return ""
        
        lines = [f"[Table {table_num} on page {self.page_number}]"]
        
        # Clean up cells - replace None with empty string, strip whitespace
        cleaned_table = []
        for row in table:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    # Replace newlines with spaces, strip whitespace
                    cleaned_row.append(str(cell).replace("\n", " ").strip())
            cleaned_table.append(cleaned_row)
        
        if not cleaned_table:
            return ""
        
        # Determine column widths (minimum 3 for markdown)
        num_cols = max(len(row) for row in cleaned_table)
        col_widths = [3] * num_cols
        
        for row in cleaned_table:
            for i, cell in enumerate(row):
                if i < num_cols:
                    col_widths[i] = max(col_widths[i], len(cell))
        
        # Build markdown table
        for row_idx, row in enumerate(cleaned_table):
            # Pad row to have correct number of columns
            while len(row) < num_cols:
                row.append("")
            
            # Format cells with proper padding
            cells = [cell.ljust(col_widths[i]) for i, cell in enumerate(row)]
            lines.append("| " + " | ".join(cells) + " |")
            
            # Add separator after header row
            if row_idx == 0:
                separators = ["-" * col_widths[i] for i in range(num_cols)]
                lines.append("| " + " | ".join(separators) + " |")
        
        return "\n".join(lines)


@dataclass
class PDFParseResult:
    """Result of parsing a PDF document."""
    filename: str
    total_pages: int
    pages: List[PDFPage]
    error: Optional[str] = None
    
    @property
    def pages_extracted(self) -> int:
        """Number of pages actually extracted."""
        return len(self.pages)
    
    def to_markdown(self, include_page_headers: bool = True) -> str:
        """Convert all extracted content to markdown."""
        if self.error:
            return f"[Error parsing PDF: {self.error}]"
        
        parts = [f"=== PDF: {self.filename} (pages {self._page_range_str()}) ==="]
        
        for page in self.pages:
            parts.append(page.to_markdown(include_page_headers))
        
        return "\n\n".join(parts)
    
    def _page_range_str(self) -> str:
        """Generate a string representation of extracted page numbers."""
        if not self.pages:
            return "none"
        
        page_nums = [p.page_number for p in self.pages]
        
        # Simple case: contiguous range
        if page_nums == list(range(page_nums[0], page_nums[-1] + 1)):
            if len(page_nums) == 1:
                return str(page_nums[0])
            return f"{page_nums[0]}-{page_nums[-1]}"
        
        # Non-contiguous: list them
        return ", ".join(str(n) for n in page_nums)
    
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int:
        """Estimate token count based on character count."""
        total_chars = sum(len(page.to_markdown()) for page in self.pages)
        return int(total_chars / chars_per_token)


class PDFParser:
    """Parser for extracting text and tables from PDF documents."""
    
    DEFAULT_MAX_PAGES = 10
    
    def __init__(self):
        pass
    
    def get_page_count(self, file_path: str) -> int:
        """Get the total number of pages in a PDF without fully parsing it."""
        try:
            with pdfplumber.open(file_path) as pdf:
                return len(pdf.pages)
        except Exception as e:
            raise ValueError(f"Could not read PDF: {str(e)}")
    
    def parse(
        self,
        file_path: str,
        page_range: Optional[Tuple[int, int]] = None,
        max_pages: Optional[int] = None
    ) -> PDFParseResult:
        """
        Parse a PDF and extract text and tables.
        
        Args:
            file_path: Path to the PDF file
            page_range: Optional tuple of (start_page, end_page), 1-indexed inclusive
                       If None, extracts from page 1 up to max_pages
            max_pages: Maximum number of pages to extract. Defaults to DEFAULT_MAX_PAGES.
                      Ignored if page_range is specified.
        
        Returns:
            PDFParseResult with extracted content
        """
        file_path = Path(file_path)
        filename = file_path.name
        
        if max_pages is None:
            max_pages = self.DEFAULT_MAX_PAGES
        
        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                
                # Determine which pages to extract
                if page_range:
                    start_page, end_page = page_range
                    # Validate range
                    start_page = max(1, min(start_page, total_pages))
                    end_page = max(start_page, min(end_page, total_pages))
                    pages_to_extract = list(range(start_page - 1, end_page))  # Convert to 0-indexed
                else:
                    # Default: first max_pages pages
                    pages_to_extract = list(range(min(max_pages, total_pages)))
                
                # Extract content from each page
                extracted_pages = []
                for page_idx in pages_to_extract:
                    page = pdf.pages[page_idx]
                    page_content = self._extract_page_content(page, page_idx + 1)
                    extracted_pages.append(page_content)
                
                return PDFParseResult(
                    filename=filename,
                    total_pages=total_pages,
                    pages=extracted_pages
                )
                
        except Exception as e:
            return PDFParseResult(
                filename=filename,
                total_pages=0,
                pages=[],
                error=str(e)
            )
    
    def _extract_page_content(self, page: Any, page_number: int) -> PDFPage:
        """Extract text and tables from a single page."""
        # Extract text
        text = page.extract_text() or ""
        
        # Extract tables
        tables = []
        try:
            raw_tables = page.extract_tables()
            if raw_tables:
                for table in raw_tables:
                    if table and len(table) > 0:
                        tables.append(table)
        except Exception:
            # Table extraction can fail on some pages - that's OK
            pass
        
        return PDFPage(
            page_number=page_number,
            text=text,
            tables=tables
        )
    
    def parse_pages_string(self, pages_str: str, total_pages: int) -> List[int]:
        """
        Parse a page selection string into a list of page numbers.
        
        Supports formats like:
        - "1-10" (range)
        - "1, 5, 10" (specific pages)
        - "1-5, 10, 15-20" (mixed)
        
        Args:
            pages_str: String specifying pages
            total_pages: Total pages in the document
        
        Returns:
            List of 1-indexed page numbers
        """
        pages = set()
        
        # Split by comma
        parts = [p.strip() for p in pages_str.split(",")]
        
        for part in parts:
            if not part:
                continue
            
            if "-" in part:
                # Range
                try:
                    start, end = part.split("-", 1)
                    start = int(start.strip())
                    end = int(end.strip())
                    # Clamp to valid range
                    start = max(1, min(start, total_pages))
                    end = max(start, min(end, total_pages))
                    pages.update(range(start, end + 1))
                except ValueError:
                    continue
            else:
                # Single page
                try:
                    page = int(part)
                    if 1 <= page <= total_pages:
                        pages.add(page)
                except ValueError:
                    continue
        
        return sorted(pages)
    
    def parse_selected_pages(
        self,
        file_path: str,
        pages_str: str,
        max_pages: Optional[int] = None
    ) -> PDFParseResult:
        """
        Parse specific pages from a PDF based on a page selection string.
        
        Args:
            file_path: Path to the PDF file
            pages_str: String specifying pages (e.g., "1-10" or "1, 5, 10-15")
            max_pages: Maximum pages to extract (applied after parsing pages_str)
        
        Returns:
            PDFParseResult with extracted content
        """
        file_path = Path(file_path)
        filename = file_path.name
        
        if max_pages is None:
            max_pages = self.DEFAULT_MAX_PAGES
        
        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                
                # Parse page selection
                selected_pages = self.parse_pages_string(pages_str, total_pages)
                
                # Apply max_pages limit
                if len(selected_pages) > max_pages:
                    selected_pages = selected_pages[:max_pages]
                
                # Extract content from selected pages
                extracted_pages = []
                for page_num in selected_pages:
                    page = pdf.pages[page_num - 1]  # Convert to 0-indexed
                    page_content = self._extract_page_content(page, page_num)
                    extracted_pages.append(page_content)
                
                return PDFParseResult(
                    filename=filename,
                    total_pages=total_pages,
                    pages=extracted_pages
                )
                
        except Exception as e:
            return PDFParseResult(
                filename=filename,
                total_pages=0,
                pages=[],
                error=str(e)
            )
