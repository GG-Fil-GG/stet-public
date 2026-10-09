"""
DOCX Parser for extracting text and tables from Word documents.

Extracts document content organized by sections/headings.
Converts tables to markdown format.
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET


# Word XML namespaces
NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
}


@dataclass
class DocxSection:
    """Represents a section of the document (heading + content)."""
    heading: Optional[str]  # None for content before first heading
    heading_level: int  # 0 for no heading, 1-9 for heading levels
    paragraphs: List[str]
    tables: List[List[List[str]]]  # List of tables, each table is rows of cells
    
    def to_markdown(self) -> str:
        """Convert section to markdown format."""
        parts = []
        
        # Add heading
        if self.heading:
            prefix = "#" * min(self.heading_level, 6)  # Markdown supports h1-h6
            parts.append(f"{prefix} {self.heading}")
        
        # Add paragraphs
        for para in self.paragraphs:
            if para.strip():
                parts.append(para.strip())
        
        # Add tables
        for i, table in enumerate(self.tables):
            if table and len(table) > 0:
                parts.append(self._table_to_markdown(table))
        
        return "\n\n".join(parts)
    
    def _table_to_markdown(self, table: List[List[str]]) -> str:
        """Convert a table to markdown format."""
        if not table or len(table) == 0:
            return ""
        
        lines = []
        
        # Clean up cells
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
        
        # Determine column count
        num_cols = max(len(row) for row in cleaned_table)
        
        # Build markdown table
        for row_idx, row in enumerate(cleaned_table):
            # Pad row to have correct number of columns
            while len(row) < num_cols:
                row.append("")
            
            lines.append("| " + " | ".join(row) + " |")
            
            # Add separator after header row
            if row_idx == 0:
                lines.append("| " + " | ".join(["---"] * num_cols) + " |")
        
        return "\n".join(lines)


@dataclass
class DocxParseResult:
    """Result of parsing a DOCX document."""
    filename: str
    sections: List[DocxSection]
    error: Optional[str] = None
    
    @property
    def section_count(self) -> int:
        """Number of sections."""
        return len(self.sections)
    
    @property
    def paragraph_count(self) -> int:
        """Total paragraphs across all sections."""
        return sum(len(s.paragraphs) for s in self.sections)
    
    @property
    def table_count(self) -> int:
        """Total tables across all sections."""
        return sum(len(s.tables) for s in self.sections)
    
    def to_markdown(self) -> str:
        """Convert all sections to markdown format."""
        if self.error:
            return f"[Error parsing DOCX: {self.error}]"
        
        parts = [f"=== Document: {self.filename} ==="]
        
        for section in self.sections:
            section_md = section.to_markdown()
            if section_md.strip():
                parts.append(section_md)
        
        return "\n\n".join(parts)
    
    def get_token_estimate(self, chars_per_token: float = 4.0) -> int:
        """Estimate token count based on character count."""
        total_chars = len(self.to_markdown())
        return int(total_chars / chars_per_token)


class DocxParser:
    """Parser for extracting text and tables from DOCX documents."""
    
    # Heading style prefixes that indicate heading levels
    HEADING_STYLES = {
        'Heading1': 1, 'Heading 1': 1, 'heading 1': 1,
        'Heading2': 2, 'Heading 2': 2, 'heading 2': 2,
        'Heading3': 3, 'Heading 3': 3, 'heading 3': 3,
        'Heading4': 4, 'Heading 4': 4, 'heading 4': 4,
        'Heading5': 5, 'Heading 5': 5, 'heading 5': 5,
        'Heading6': 6, 'Heading 6': 6, 'heading 6': 6,
        'Title': 1, 'Subtitle': 2,
    }
    
    def __init__(self):
        pass
    
    def parse(self, file_path: str) -> DocxParseResult:
        """
        Parse a DOCX file and extract text organized by sections.
        
        Args:
            file_path: Path to the DOCX file
        
        Returns:
            DocxParseResult with extracted content
        """
        file_path = Path(file_path)
        filename = file_path.name
        
        try:
            with zipfile.ZipFile(file_path, 'r') as docx:
                # Read document.xml
                if 'word/document.xml' not in docx.namelist():
                    return DocxParseResult(
                        filename=filename,
                        sections=[],
                        error="Invalid DOCX: missing document.xml"
                    )
                
                doc_xml = docx.read('word/document.xml')
                root = ET.fromstring(doc_xml)
                
                # Read styles.xml for heading detection
                styles_map = {}
                if 'word/styles.xml' in docx.namelist():
                    styles_xml = docx.read('word/styles.xml')
                    styles_map = self._parse_styles(styles_xml)
                
                # Extract content
                sections = self._extract_sections(root, styles_map)
                
                return DocxParseResult(
                    filename=filename,
                    sections=sections
                )
                
        except zipfile.BadZipFile:
            return DocxParseResult(
                filename=filename,
                sections=[],
                error="Invalid DOCX file (not a valid ZIP archive)"
            )
        except Exception as e:
            return DocxParseResult(
                filename=filename,
                sections=[],
                error=str(e)
            )
    
    def _parse_styles(self, styles_xml: bytes) -> Dict[str, int]:
        """Parse styles.xml to map style IDs to heading levels."""
        styles_map = {}
        
        try:
            root = ET.fromstring(styles_xml)
            
            for style in root.findall('.//w:style', NAMESPACES):
                style_id = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId', '')
                style_name_elem = style.find('w:name', NAMESPACES)
                
                if style_name_elem is not None:
                    style_name = style_name_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                    
                    # Check if this is a heading style
                    for heading_name, level in self.HEADING_STYLES.items():
                        if heading_name.lower() in style_name.lower() or heading_name.lower() in style_id.lower():
                            styles_map[style_id] = level
                            break
        except Exception:
            pass  # Silently ignore style parsing errors
        
        return styles_map
    
    def _extract_sections(self, root: ET.Element, styles_map: Dict[str, int]) -> List[DocxSection]:
        """Extract document content organized by sections."""
        sections = []
        current_section = DocxSection(
            heading=None,
            heading_level=0,
            paragraphs=[],
            tables=[]
        )
        
        # Find body element
        body = root.find('.//w:body', NAMESPACES)
        if body is None:
            return sections
        
        for elem in body:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag == 'p':
                # Paragraph
                text = self._extract_paragraph_text(elem)
                heading_level = self._get_heading_level(elem, styles_map)
                
                if heading_level > 0 and text.strip():
                    # This is a heading - start a new section
                    if current_section.paragraphs or current_section.tables or current_section.heading:
                        sections.append(current_section)
                    
                    current_section = DocxSection(
                        heading=text.strip(),
                        heading_level=heading_level,
                        paragraphs=[],
                        tables=[]
                    )
                elif text.strip():
                    # Regular paragraph
                    current_section.paragraphs.append(text)
            
            elif tag == 'tbl':
                # Table
                table = self._extract_table(elem)
                if table:
                    current_section.tables.append(table)
        
        # Add final section
        if current_section.paragraphs or current_section.tables or current_section.heading:
            sections.append(current_section)
        
        return sections
    
    def _get_heading_level(self, para: ET.Element, styles_map: Dict[str, int]) -> int:
        """Determine if a paragraph is a heading and its level."""
        # Check paragraph style
        pPr = para.find('w:pPr', NAMESPACES)
        if pPr is not None:
            pStyle = pPr.find('w:pStyle', NAMESPACES)
            if pStyle is not None:
                style_id = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                
                # Check style map first
                if style_id in styles_map:
                    return styles_map[style_id]
                
                # Check known heading style patterns
                for heading_name, level in self.HEADING_STYLES.items():
                    if heading_name.lower() in style_id.lower():
                        return level
            
            # Check outline level
            outlineLvl = pPr.find('w:outlineLvl', NAMESPACES)
            if outlineLvl is not None:
                try:
                    level = int(outlineLvl.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '-1'))
                    if 0 <= level <= 8:
                        return level + 1  # Convert 0-based to 1-based
                except ValueError:
                    pass
        
        return 0  # Not a heading
    
    def _extract_paragraph_text(self, para: ET.Element) -> str:
        """Extract text content from a paragraph element."""
        text_parts = []
        
        for elem in para.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag == 't':
                # Text element
                if elem.text:
                    text_parts.append(elem.text)
            elif tag == 'tab':
                text_parts.append('\t')
            elif tag == 'br':
                text_parts.append('\n')
        
        return ''.join(text_parts)
    
    def _extract_table(self, tbl: ET.Element) -> List[List[str]]:
        """Extract table content as a list of rows."""
        rows = []
        
        for tr in tbl.findall('.//w:tr', NAMESPACES):
            row = []
            for tc in tr.findall('.//w:tc', NAMESPACES):
                cell_text = self._extract_cell_text(tc)
                row.append(cell_text)
            if row:
                rows.append(row)
        
        return rows
    
    def _extract_cell_text(self, tc: ET.Element) -> str:
        """Extract text from a table cell."""
        text_parts = []
        
        for para in tc.findall('.//w:p', NAMESPACES):
            para_text = self._extract_paragraph_text(para)
            if para_text.strip():
                text_parts.append(para_text.strip())
        
        return ' '.join(text_parts)
    
    def get_document_info(self, file_path: str) -> Dict[str, Any]:
        """
        Get basic info about a DOCX without fully parsing it.
        
        Returns:
            Dict with 'paragraph_count', 'table_count', 'has_headings'
        """
        try:
            result = self.parse(file_path)
            return {
                'paragraph_count': result.paragraph_count,
                'table_count': result.table_count,
                'section_count': result.section_count,
                'has_error': result.error is not None
            }
        except Exception as e:
            return {
                'paragraph_count': 0,
                'table_count': 0,
                'section_count': 0,
                'has_error': True,
                'error': str(e)
            }
