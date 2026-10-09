"""
Document Parser - Parse DOCX files into DocumentModel.

Uses a hybrid approach:
- python-docx for standard document structure (when possible)
- lxml for direct XML access (comments, track changes, comment anchors)

This parser focuses on comments and their relationships. Full document
structure parsing will be expanded in future phases.
"""

import logging
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

from lxml import etree

from .model import DocumentModel, DocumentBody, Table
from .paragraph import Paragraph, Run, RunFormatting, RevisionType
from .comments import Comment, CommentStore, CommentAnchor, CommentParagraph
from .revisions import RevisionStore
from .utils import is_valid_para_id


# XML Namespaces used in DOCX
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'w16cid': 'http://schemas.microsoft.com/office/word/2016/wordml/cid',
    'w16': 'http://schemas.microsoft.com/office/word/2018/wordml',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
}

# Namespace URIs for attribute access
NS_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NS_W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
NS_W15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
NS_W16CID = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'


@dataclass
class AnchorPosition:
    """Temporary structure for tracking anchor positions during parsing."""
    para_id: str
    para_index: int
    char_offset: int


class DocumentParser:
    """
    Parse DOCX files into DocumentModel.
    
    This parser extracts:
    - Document paragraphs with their para_ids and text
    - Comments from comments.xml
    - Threading relationships from commentsExtended.xml
    - Durable IDs from commentsIds.xml
    - UTC timestamps from commentsExtensible.xml (if present)
    - Comment anchors from document.xml
    """
    
    def __init__(self, docx_path: str | Path):
        """
        Initialize parser with path to DOCX file.
        
        Args:
            docx_path: Path to the .docx file
        """
        self.docx_path = Path(docx_path)
        if not self.docx_path.exists():
            raise FileNotFoundError(f"DOCX file not found: {docx_path}")
        self._field_code_counter = 0
    
    def parse(self) -> DocumentModel:
        """
        Parse the DOCX file into a DocumentModel.
        
        Returns:
            A fully populated DocumentModel
        """
        model = DocumentModel(
            source_path=self.docx_path,
            created_at=datetime.now()
        )
        
        with zipfile.ZipFile(self.docx_path, 'r') as zf:
            # Parse document structure
            self._parse_document_body(zf, model)
            
            # Parse comments (if present)
            if 'word/comments.xml' in zf.namelist():
                self._parse_comments(zf, model)
                self._parse_comment_anchors(zf, model)
        
        return model
    
    def _parse_document_body(self, zf: zipfile.ZipFile, model: DocumentModel) -> None:
        """
        Parse document.xml to extract paragraphs and tables.
        
        Builds the document body structure with proper para_ids and text content.
        """
        doc_xml = zf.read('word/document.xml')
        doc_root = etree.fromstring(doc_xml)
        
        body = doc_root.find('.//w:body', NS)
        if body is None:
            return
        
        # Track which paragraphs are inside tables
        table_para_ids: Set[str] = set()
        for table in body.findall('.//w:tbl', NS):
            for para in table.findall('.//w:p', NS):
                para_id = para.get(f'{NS_W14}paraId')
                if para_id:
                    table_para_ids.add(para_id)
        
        # Walk body children in order
        for child in body:
            tag_name = etree.QName(child).localname
            
            if tag_name == 'tbl':
                self._parse_table(child, model)
            elif tag_name == 'p':
                para_id = child.get(f'{NS_W14}paraId')
                if para_id and para_id in table_para_ids:
                    continue  # Skip table paragraphs at body level
                self._parse_paragraph(child, model)
    
    def _parse_paragraph(self, para_elem, model: DocumentModel) -> Optional[Paragraph]:
        """
        Parse a single paragraph element.
        
        Extracts:
        - para_id and text_id
        - Runs with text and formatting
        - Handles track changes (w:ins, w:del)
        - Field codes (EndNote citations, etc.)
        """
        para_id = para_elem.get(f'{NS_W14}paraId', '')
        text_id = para_elem.get(f'{NS_W14}textId', '')
        
        if not para_id:
            # Generate a placeholder ID if missing
            para_id = f"NOID{model.body.element_count:04d}"
        
        # Extract field codes from the paragraph XML before processing runs
        field_codes = self._extract_field_codes_from_element(para_elem)
        
        runs = []
        current_offset = 0
        
        # Process all children, handling runs, insertions, deletions
        for child in para_elem:
            tag_name = etree.QName(child).localname
            
            if tag_name == 'r':
                run = self._parse_run(child, current_offset)
                if run:
                    runs.append(run)
                    current_offset += len(run.text)
            
            elif tag_name == 'ins':
                # Track change insertion - extract runs inside
                for run_elem in child.findall('w:r', NS):
                    run = self._parse_run(run_elem, current_offset, RevisionType.INSERTION)
                    if run:
                        runs.append(run)
                        current_offset += len(run.text)
            
            elif tag_name == 'del':
                # Track change deletion - extract runs but mark as deleted
                for run_elem in child.findall('w:r', NS):
                    run = self._parse_run(run_elem, current_offset, RevisionType.DELETION)
                    if run:
                        runs.append(run)
                        # Don't advance offset for deleted text
            
            elif tag_name == 'hyperlink':
                # Extract runs from hyperlinks
                for run_elem in child.findall('w:r', NS):
                    run = self._parse_run(run_elem, current_offset)
                    if run:
                        runs.append(run)
                        current_offset += len(run.text)
        
        paragraph = Paragraph(
            para_id=para_id,
            text_id=text_id,
            runs=runs,
            index=model.body.element_count,
            field_codes=field_codes
        )
        
        if field_codes:
            logger.debug("Paragraph %s: Found %d field code(s)", para_id, len(field_codes))
        
        model.body.add_element(paragraph)
        return paragraph
    
    def _parse_run(
        self, 
        run_elem, 
        start_offset: int,
        revision_type: Optional[RevisionType] = None
    ) -> Optional[Run]:
        """
        Parse a single run element.
        
        Extracts text content and formatting.
        """
        text_parts = []
        
        for t_elem in run_elem.findall('.//w:t', NS):
            if t_elem.text:
                text_parts.append(t_elem.text)
        # Deleted runs (inside <w:del>) carry their text in <w:delText>, not
        # <w:t>. Capture it so tracked deletions survive into the model (and can
        # be rendered struck-through); plain_text/offsets still exclude deleted
        # runs, and the serializer skips them, so round-tripping is unaffected.
        for del_elem in run_elem.findall('.//w:delText', NS):
            if del_elem.text:
                text_parts.append(del_elem.text)
        
        text = ''.join(text_parts)
        if not text:
            return None
        
        # Parse formatting
        formatting = self._parse_run_formatting(run_elem)
        
        return Run(
            text=text,
            formatting=formatting,
            start_offset=start_offset,
            end_offset=start_offset + len(text),
            revision_type=revision_type
        )
    
    def _parse_run_formatting(self, run_elem) -> RunFormatting:
        """Parse run properties (w:rPr) into RunFormatting."""
        formatting = RunFormatting()
        
        rPr = run_elem.find('w:rPr', NS)
        if rPr is None:
            return formatting
        
        # Bold
        if rPr.find('w:b', NS) is not None:
            formatting.bold = True
        
        # Italic
        if rPr.find('w:i', NS) is not None:
            formatting.italic = True
        
        # Underline
        if rPr.find('w:u', NS) is not None:
            formatting.underline = True
        
        # Strikethrough
        if rPr.find('w:strike', NS) is not None:
            formatting.strike = True
        
        # Superscript/Subscript
        vertAlign = rPr.find('w:vertAlign', NS)
        if vertAlign is not None:
            val = vertAlign.get(f'{NS_W}val', '')
            if val == 'superscript':
                formatting.superscript = True
            elif val == 'subscript':
                formatting.subscript = True
        
        # Font size
        sz = rPr.find('w:sz', NS)
        if sz is not None:
            val = sz.get(f'{NS_W}val', '')
            if val and val.isdigit():
                # Word stores font size in half-points
                formatting.font_size = int(val) / 2.0
        
        return formatting
    
    def _extract_field_codes_from_element(self, para_elem) -> Dict[str, str]:
        """
        Extract field codes (EndNote citations, etc.) from a paragraph element.
        
        Field codes in Word XML span multiple runs:
          <w:fldChar w:fldCharType="begin"/> ... <w:fldChar w:fldCharType="end"/>
        
        EndNoteXML citations use nested field codes (EN.CITE wraps EN.CITE.DATA).
        We use a stack-based approach to capture only outermost field codes,
        keeping the entire nested structure as a single unit.
        
        Returns:
            Dict mapping placeholder (e.g., "[CITATION_1]") to original field code XML
        """
        para_xml = etree.tostring(para_elem, encoding='unicode')
        
        begin_count = para_xml.count('w:fldCharType="begin"')
        end_count = para_xml.count('w:fldCharType="end"')
        
        if begin_count != end_count:
            return {}
        
        if begin_count == 0:
            return {}
        
        field_codes: Dict[str, str] = {}
        
        # Stack-based approach: track nesting depth to capture outermost field codes
        field_code_ranges: List[Tuple[int, int]] = []
        stack: List[int] = []
        
        for match in re.finditer(r'<w:fldChar[^>]*w:fldCharType="(begin|end)"', para_xml):
            marker_type = match.group(1)
            if marker_type == "begin":
                run_start = para_xml.rfind('<w:r', 0, match.start())
                if run_start != -1:
                    stack.append(run_start)
            elif marker_type == "end":
                run_end = para_xml.find('</w:r>', match.end())
                if run_end != -1 and stack:
                    run_end += len('</w:r>')
                    begin_run_start = stack.pop()
                    if not stack:
                        field_code_ranges.append((begin_run_start, run_end))
        
        if stack:
            return {}
        
        for begin_pos, end_pos in field_code_ranges:
            if begin_pos < end_pos:
                field_xml = para_xml[begin_pos:end_pos]
                
                self._field_code_counter += 1
                placeholder = f"[CITATION_{self._field_code_counter}]"
                
                field_codes[placeholder] = field_xml
                
                display_text = self._extract_field_display_text(field_xml)
                logger.debug("Found field code: '%s' -> %s", display_text, placeholder)
        
        return field_codes
    
    def _extract_field_display_text(self, field_xml: str) -> str:
        """
        Extract the visible display text from a field code XML fragment.
        
        For EndNote citations, this is typically something like "[1]" or "(Author 2023)".
        """
        # Find all text content within the field code (in <w:t> elements)
        text_matches = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', field_xml)
        return ''.join(text_matches)
    
    def _parse_table(self, table_elem, model: DocumentModel) -> None:
        """
        Parse a table element.
        
        Tables are represented as a list of rows, where each row contains
        cell paragraphs.
        """
        rows = []
        
        for row_elem in table_elem.findall('w:tr', NS):
            row_cells = []
            for cell_elem in row_elem.findall('w:tc', NS):
                # Get first paragraph in cell (simplified)
                first_para = cell_elem.find('w:p', NS)
                if first_para is not None:
                    para_id = first_para.get(f'{NS_W14}paraId', '')
                    text_id = first_para.get(f'{NS_W14}textId', '')
                    
                    # Extract cell text
                    text_parts = []
                    for t_elem in cell_elem.findall('.//w:t', NS):
                        if t_elem.text:
                            text_parts.append(t_elem.text)
                    
                    cell_para = Paragraph(
                        para_id=para_id or f"CELL{model.body.element_count:04d}",
                        text_id=text_id,
                        runs=[Run(text=' '.join(text_parts))] if text_parts else []
                    )
                    row_cells.append(cell_para)
            
            if row_cells:
                rows.append(row_cells)
        
        if rows:
            table = Table(rows=rows, index=model.body.element_count)
            model.body.add_element(table)
    
    def _parse_comments(self, zf: zipfile.ZipFile, model: DocumentModel) -> None:
        """
        Parse all comment-related XML files.
        
        This handles Word's 4-file comment system:
        - comments.xml: Comment content and basic metadata
        - commentsExtended.xml: Threading (paraIdParent) and resolved status
        - commentsIds.xml: Durable IDs
        - commentsExtensible.xml: UTC timestamps
        """
        # Step 1: Parse comments.xml for basic comment data
        comments_xml = zf.read('word/comments.xml')
        comments_root = etree.fromstring(comments_xml)
        
        # Temporary storage for building relationships
        comment_data: Dict[str, Comment] = {}
        para_id_to_comment: Dict[str, Comment] = {}
        
        for comment_elem in comments_root.findall('.//w:comment', NS):
            comment_id = comment_elem.get(f'{NS_W}id')
            if not comment_id:
                continue
            
            # Basic metadata
            author = comment_elem.get(f'{NS_W}author', 'Unknown')
            initials = comment_elem.get(f'{NS_W}initials', '')
            date_str = comment_elem.get(f'{NS_W}date', '')
            
            # Parse date
            date = None
            if date_str:
                try:
                    date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except ValueError:
                    pass
            
            # Extract comment text and para_id
            text_parts = []
            comment_para_id = ''
            
            # Find all paragraphs in comment (multi-paragraph comments use LAST para_id)
            comment_paras = comment_elem.findall('.//w:p', NS)
            for para in comment_paras:
                para_id = para.get(f'{NS_W14}paraId')
                if para_id:
                    comment_para_id = para_id  # Will end up with LAST para's ID
            
            # Extract text
            for t_elem in comment_elem.findall('.//w:t', NS):
                if t_elem.text:
                    text_parts.append(t_elem.text)
            
            text = ''.join(text_parts)
            
            # Create comment object
            comment = Comment(
                comment_id=comment_id,
                para_id=comment_para_id,
                text=text,
                author=author,
                author_initials=initials,
                date=date
            )
            
            comment_data[comment_id] = comment
            if comment_para_id:
                para_id_to_comment[comment_para_id] = comment
        
        # Step 2: Parse commentsExtended.xml for threading and resolved status
        if 'word/commentsExtended.xml' in zf.namelist():
            self._parse_comments_extended(zf, comment_data, para_id_to_comment)
        
        # Step 3: Parse commentsIds.xml for durable IDs
        if 'word/commentsIds.xml' in zf.namelist():
            self._parse_comments_ids(zf, para_id_to_comment)
        
        # Step 4: Parse commentsExtensible.xml for UTC timestamps
        if 'word/commentsExtensible.xml' in zf.namelist():
            self._parse_comments_extensible(zf, para_id_to_comment)
        
        # Add all comments to model's CommentStore
        for comment in comment_data.values():
            model.comments.add_comment(comment)
    
    def _parse_comments_extended(
        self, 
        zf: zipfile.ZipFile,
        comment_data: Dict[str, Comment],
        para_id_to_comment: Dict[str, Comment]
    ) -> None:
        """
        Parse commentsExtended.xml for threading and resolved status.
        
        This file contains:
        - w15:paraId: Links to comment's para_id
        - w15:paraIdParent: Parent comment's para_id (for threading)
        - w15:done: Resolved status (0 or 1)
        """
        extended_xml = zf.read('word/commentsExtended.xml')
        extended_root = etree.fromstring(extended_xml)
        
        # Build mapping: w15:paraId -> comment (using positional fallback)
        w15_para_id_to_comment: Dict[str, Comment] = {}
        comments_list = list(comment_data.values())
        
        comment_ex_elems = [
            elem for elem in extended_root.iter() 
            if etree.QName(elem).localname == 'commentEx'
        ]
        
        for i, comment_ex in enumerate(comment_ex_elems):
            w15_para_id = comment_ex.get(f'{NS_W15}paraId')
            if not w15_para_id:
                continue
            
            # Try to match by paraId first (w15:paraId should match w14:paraId)
            if w15_para_id in para_id_to_comment:
                w15_para_id_to_comment[w15_para_id] = para_id_to_comment[w15_para_id]
            elif i < len(comments_list):
                # Fallback to positional matching
                w15_para_id_to_comment[w15_para_id] = comments_list[i]
        
        # Now process threading and resolved status
        for comment_ex in comment_ex_elems:
            w15_para_id = comment_ex.get(f'{NS_W15}paraId')
            para_id_parent = comment_ex.get(f'{NS_W15}paraIdParent')
            done = comment_ex.get(f'{NS_W15}done', '0')
            
            if not w15_para_id:
                continue
            
            comment = w15_para_id_to_comment.get(w15_para_id)
            if not comment:
                continue
            
            # Set resolved status
            comment.is_resolved = (done == '1')
            
            # Set parent relationship (flat threading: parent is always root)
            if para_id_parent:
                parent_comment = w15_para_id_to_comment.get(para_id_parent)
                if parent_comment:
                    comment.parent_para_id = parent_comment.para_id
    
    def _parse_comments_ids(
        self, 
        zf: zipfile.ZipFile,
        para_id_to_comment: Dict[str, Comment]
    ) -> None:
        """
        Parse commentsIds.xml for durable IDs.
        
        Durable IDs persist across document saves and are used for
        cross-document comment tracking.
        """
        ids_xml = zf.read('word/commentsIds.xml')
        ids_root = etree.fromstring(ids_xml)
        
        for comment_id_elem in ids_root.iter():
            if etree.QName(comment_id_elem).localname == 'commentId':
                # commentsIds.xml uses w16cid namespace for both paraId and durableId
                para_id = comment_id_elem.get(f'{NS_W16CID}paraId')
                durable_id = comment_id_elem.get(f'{NS_W16CID}durableId')
                
                if para_id and durable_id:
                    comment = para_id_to_comment.get(para_id)
                    if comment:
                        comment.durable_id = durable_id
    
    def _parse_comments_extensible(
        self, 
        zf: zipfile.ZipFile,
        para_id_to_comment: Dict[str, Comment]
    ) -> None:
        """
        Parse commentsExtensible.xml for UTC timestamps.
        
        This file contains accurate UTC timestamps (the w:date in comments.xml
        is local time).
        """
        try:
            extensible_xml = zf.read('word/commentsExtensible.xml')
            extensible_root = etree.fromstring(extensible_xml)
            
            for comment_ext in extensible_root.iter():
                if etree.QName(comment_ext).localname == 'commentExtensible':
                    para_id = comment_ext.get(f'{NS_W15}paraId')
                    date_utc_str = comment_ext.get(f'{NS_W16}dateUtc')
                    
                    if para_id and date_utc_str:
                        comment = para_id_to_comment.get(para_id)
                        if comment:
                            try:
                                comment.date_utc = datetime.fromisoformat(
                                    date_utc_str.replace('Z', '+00:00')
                                )
                            except ValueError:
                                pass
        except Exception:
            # commentsExtensible.xml is optional and may have issues
            pass
    
    def _parse_comment_anchors(self, zf: zipfile.ZipFile, model: DocumentModel) -> None:
        """
        Parse comment anchors from document.xml.
        
        Finds commentRangeStart/commentRangeEnd pairs and maps them to
        character positions within paragraphs.
        """
        doc_xml = zf.read('word/document.xml')
        doc_root = etree.fromstring(doc_xml)
        
        # Build para_id -> paragraph mapping
        para_id_to_para: Dict[str, Paragraph] = {}
        for para in model.body.iter_paragraphs():
            para_id_to_para[para.para_id] = para
        
        # Find all comment ranges
        # Structure: track (comment_id -> start_info, end_info)
        comment_ranges: Dict[str, Dict] = {}
        
        all_paras = doc_root.findall('.//w:p', NS)
        
        for para_elem in all_paras:
            para_id = para_elem.get(f'{NS_W14}paraId', '')
            if not para_id or para_id not in para_id_to_para:
                continue
            
            paragraph = para_id_to_para[para_id]
            
            # Track character position as we walk through elements
            char_pos = 0
            
            for child in para_elem.iter():
                tag_name = etree.QName(child).localname
                
                if tag_name == 'commentRangeStart':
                    comment_id = child.get(f'{NS_W}id')
                    if comment_id:
                        if comment_id not in comment_ranges:
                            comment_ranges[comment_id] = {}
                        comment_ranges[comment_id]['start_para_id'] = para_id
                        comment_ranges[comment_id]['start_offset'] = char_pos
                
                elif tag_name == 'commentRangeEnd':
                    comment_id = child.get(f'{NS_W}id')
                    if comment_id:
                        if comment_id not in comment_ranges:
                            comment_ranges[comment_id] = {}
                        comment_ranges[comment_id]['end_para_id'] = para_id
                        comment_ranges[comment_id]['end_offset'] = char_pos
                
                elif tag_name == 't':
                    # Only count text in non-deleted runs
                    parent = child.getparent()
                    if parent is not None:
                        grandparent = parent.getparent()
                        # Skip text inside w:del
                        if grandparent is not None and etree.QName(grandparent).localname == 'del':
                            continue
                    if child.text:
                        char_pos += len(child.text)
        
        # Create anchors for comments
        for comment_id, range_info in comment_ranges.items():
            comment = model.comments.get_comment(comment_id)
            if not comment:
                continue
            
            start_para_id = range_info.get('start_para_id')
            start_offset = range_info.get('start_offset', 0)
            end_para_id = range_info.get('end_para_id')
            end_offset = range_info.get('end_offset', 0)
            
            if start_para_id:
                anchor = CommentAnchor(
                    comment_id=comment_id,
                    para_id=start_para_id,
                    start_offset=start_offset,
                    end_offset=end_offset if end_para_id == start_para_id else start_offset,
                    end_para_id=end_para_id if end_para_id != start_para_id else None
                )
                comment.anchor = anchor


def parse_docx(docx_path: str | Path) -> DocumentModel:
    """
    Convenience function to parse a DOCX file.
    
    Args:
        docx_path: Path to the .docx file
        
    Returns:
        A populated DocumentModel
    """
    parser = DocumentParser(docx_path)
    return parser.parse()
