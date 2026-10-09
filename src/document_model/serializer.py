"""
DocumentSerializer - Serialize DocumentModel back to DOCX.

Thin orchestrator: ZIP lifecycle and document.xml coordination.
Implementation details live in serializer_*.py mixins.
"""

import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Optional

import html

logger = logging.getLogger(__name__)

from .model import DocumentModel
from .paragraph import Paragraph, RunFormatting
from .serializer_common import _sanitize_for_xml
from .serializer_comments import SerializerCommentsMixin
from .serializer_field_codes import SerializerFieldCodesMixin
from .serializer_formatting import SerializerFormattingMixin
from .serializer_revisions import SerializerRevisionsMixin

class DocumentSerializer(
    SerializerFieldCodesMixin,
    SerializerFormattingMixin,
    SerializerCommentsMixin,
    SerializerRevisionsMixin,
):
    """Serializes a DocumentModel back to DOCX."""

    """
    Serializes a DocumentModel back to DOCX.
    
    Strategy:
    1. Copy original DOCX as base (preserve unknown elements)
    2. Use string manipulation for XML updates (preserves namespaces)
    3. Write comment XML files with proper threading
    4. Insert revision markup into document.xml
    """
    
    # XML namespaces
    NS = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
        'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
        'w16cid': 'http://schemas.microsoft.com/office/word/2016/wordml/cid',
        'w16cex': 'http://schemas.microsoft.com/office/word/2018/wordml/cex',
    }
    
    NS_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    NS_W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
    NS_W15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
    NS_W16CID = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'
    NS_W16CEX = '{http://schemas.microsoft.com/office/word/2018/wordml/cex}'
    
    def __init__(self):
        """Initialize the serializer."""
        # Formatting info for track changes (set during serialize())
        self._formatting_info: Dict[str, str] = {}
        # Comments present in the source DOCX but absent from the model are
        # treated as removed and stripped from every comment part. Populated
        # per-serialize by _compute_removed_comments().
        self._removed_comment_ids: set = set()
        self._removed_para_ids: set = set()
        self._removed_durable_ids: set = set()
    
    def serialize(
        self,
        model: DocumentModel,
        output_path: Path,
        include_track_changes: bool = True,
        preserve_original: bool = True,
        formatting_info: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Serialize DocumentModel to DOCX file.
        
        Args:
            model: The DocumentModel to serialize
            output_path: Path where the output .docx will be written
            include_track_changes: Whether to include track change markup
            preserve_original: If True, use original DOCX as template
            formatting_info: Optional dict mapping para_id to revised_text_html.
                            Used for generating rPrChange on EQUAL text with
                            different formatting, and for applying formatting
                            to INSERT text.
            
        Raises:
            FileNotFoundError: If source_path not set and preserve_original=True
            ValueError: If model has no source_path when needed
        """
        # Store formatting info for use by _apply_diff_to_paragraph
        self._formatting_info = formatting_info or {}
        if preserve_original and not model.source_path:
            raise ValueError("Cannot preserve original: model has no source_path")
        
        if preserve_original and not model.source_path.exists():
            raise FileNotFoundError(f"Source file not found: {model.source_path}")
        
        output_path = Path(output_path)
        
        # Use a temp file for atomic write
        temp_path = output_path.with_suffix('.docx.tmp')
        
        try:
            with zipfile.ZipFile(model.source_path, 'r') as zin:
                # Determine which comments were removed (present in source, gone
                # from the model) so each comment part can strip them.
                self._compute_removed_comments(zin, model)
                with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                    # Process each item in the original archive
                    for item in zin.namelist():
                        if item == 'word/document.xml':
                            # Update document.xml with changes
                            original_xml = zin.read(item).decode('utf-8')
                            modified_xml = self._serialize_document_xml(
                                model, original_xml, include_track_changes
                            )
                            zout.writestr(item, modified_xml.encode('utf-8'))
                            
                        elif item == 'word/comments.xml':
                            # Generate comments.xml from model
                            original_xml = zin.read(item).decode('utf-8')
                            modified_xml = self._serialize_comments_xml(model, original_xml)
                            zout.writestr(item, modified_xml.encode('utf-8'))
                            
                        elif item == 'word/commentsExtended.xml':
                            # Generate commentsExtended.xml (threading)
                            original_xml = zin.read(item).decode('utf-8')
                            modified_xml = self._serialize_comments_extended_xml(model, original_xml)
                            zout.writestr(item, modified_xml.encode('utf-8'))
                            
                        elif item == 'word/commentsIds.xml':
                            # Generate commentsIds.xml (durable IDs)
                            original_xml = zin.read(item).decode('utf-8')
                            modified_xml = self._serialize_comments_ids_xml(model, original_xml)
                            zout.writestr(item, modified_xml.encode('utf-8'))
                            
                        elif item == 'word/commentsExtensible.xml':
                            # Generate commentsExtensible.xml (UTC timestamps)
                            # Need commentsIds.xml to map para_id to durable_id
                            original_xml = zin.read(item).decode('utf-8')
                            comments_ids_xml = zin.read('word/commentsIds.xml').decode('utf-8') if 'word/commentsIds.xml' in zin.namelist() else ''
                            modified_xml = self._serialize_comments_extensible_xml(model, original_xml, comments_ids_xml)
                            zout.writestr(item, modified_xml.encode('utf-8'))
                            
                        else:
                            # Copy other files unchanged
                            zout.writestr(item, zin.read(item))
            
            # Atomic move
            shutil.move(str(temp_path), str(output_path))
            
        except Exception:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise
    
    def _serialize_document_xml(
        self,
        model: DocumentModel,
        original_xml: str,
        include_track_changes: bool
    ) -> str:
        """
        Update document.xml with paragraph changes and comment anchors.
        
        Args:
            model: The DocumentModel
            original_xml: Original document.xml content
            include_track_changes: Whether to include revision markup
            
        Returns:
            Modified document.xml content
        """
        modified_xml = original_xml
        
        # Insert track changes if enabled and there are pending revisions
        if include_track_changes and model.revisions.pending_count > 0:
            modified_xml = self._serialize_revisions(model, modified_xml)
        
        # Apply plain edits (paragraphs modified without track changes)
        modified_xml = self._serialize_plain_edits(model, modified_xml)
        
        # Update/insert comment anchors
        modified_xml = self._serialize_comment_anchors(model, modified_xml)
        
        return modified_xml
    
    def _serialize_plain_edits(self, model: DocumentModel, doc_xml: str) -> str:
        """
        Write plain (non-tracked) edits to document.xml.
        
        Processes only paragraphs explicitly edited with track_change=False
        (tracked via model._plain_edited_para_ids). Replaces their run content
        in-place, preserving paragraph properties and comment anchors.
        """
        if not model._plain_edited_para_ids:
            return doc_xml
        
        modified_xml = doc_xml
        
        for paragraph in model.body.iter_paragraphs():
            if paragraph.para_id not in model._plain_edited_para_ids:
                continue
            
            # Must handle both <w:p ...>...</w:p> and self-closing <w:p .../>
            para_pattern = re.compile(
                r'(<w:p\s[^>]*w14:paraId="' + paragraph.para_id + r'"[^>]*)(/>\s*|>(.*?)</w:p>)',
                re.DOTALL
            )
            match = para_pattern.search(modified_xml)
            if not match:
                continue
            
            if match.group(2).startswith('/'):
                # Self-closing paragraph — no content to replace
                continue
            
            para_content = match.group(3) or ''
            
            # Rebuild the paragraph body from model runs.
            # Preserve <w:pPr> (paragraph properties) and comment anchors.
            ppr_match = re.search(r'<w:pPr\b[^>]*>.*?</w:pPr>', para_content, re.DOTALL)
            ppr_xml = ppr_match.group(0) if ppr_match else ''
            
            comment_anchors = self._extract_comment_anchor_elements(para_content)
            
            runs_xml = self._build_runs_xml_from_model(paragraph)
            
            new_content = ppr_xml + comment_anchors + runs_xml
            new_para = match.group(1) + '>' + new_content + '</w:p>'
            modified_xml = (
                modified_xml[:match.start()]
                + new_para
                + modified_xml[match.end():]
            )
        
        return modified_xml
    
    def _extract_comment_anchor_elements(self, para_content: str) -> str:
        """
        Extract comment range start/end markers and comment references
        from paragraph XML content, preserving their order.
        """
        anchor_pattern = re.compile(
            r'<w:commentRangeStart\b[^/]*/>'
            r'|<w:commentRangeEnd\b[^/]*/>'
            r'|<w:r\b[^>]*>\s*<w:rPr>.*?</w:rPr>\s*<w:commentReference\b[^/]*/>\s*</w:r>',
            re.DOTALL
        )
        return ''.join(m.group(0) for m in anchor_pattern.finditer(para_content))
    
    def _build_runs_xml_from_model(self, paragraph: Paragraph) -> str:
        """
        Build Word XML run elements from a Paragraph's current runs.
        
        Generates <w:r> elements with <w:rPr> for formatting and <w:t> for
        text content. Field codes are restored from the paragraph's field_codes
        dict if present.
        """
        parts = []
        for run in paragraph.runs:
            if run.is_deleted():
                continue
            
            text = run.text
            if not text:
                continue
            
            safe_text = _sanitize_for_xml(html.escape(text, quote=False))
            
            rpr = self._build_rpr_xml(run.formatting)
            
            preserve = ' xml:space="preserve"' if text != text.strip() else ''
            parts.append(f'<w:r>{rpr}<w:t{preserve}>{safe_text}</w:t></w:r>')
        
        result = ''.join(parts)
        
        if paragraph.field_codes:
            result = self._restore_field_codes(result, paragraph.field_codes)
        
        return result
    
    def _build_rpr_xml(self, formatting: RunFormatting) -> str:
        """Build <w:rPr> XML from a RunFormatting object. Returns empty string if no formatting."""
        if formatting.is_empty():
            return ''
        
        props = []
        if formatting.bold:
            props.append('<w:b/>')
        if formatting.italic:
            props.append('<w:i/>')
        if formatting.underline:
            props.append('<w:u w:val="single"/>')
        if formatting.strike:
            props.append('<w:strike/>')
        if formatting.superscript:
            props.append('<w:vertAlign w:val="superscript"/>')
        if formatting.subscript:
            props.append('<w:vertAlign w:val="subscript"/>')
        if formatting.font_name:
            safe_name = _sanitize_for_xml(html.escape(formatting.font_name, quote=True))
            props.append(f'<w:rFonts w:ascii="{safe_name}" w:hAnsi="{safe_name}"/>')
        if formatting.font_size is not None:
            half_points = int(formatting.font_size * 2)
            props.append(f'<w:sz w:val="{half_points}"/>')
        if formatting.color:
            props.append(f'<w:color w:val="{formatting.color}"/>')
        if formatting.highlight:
            props.append(f'<w:highlight w:val="{formatting.highlight}"/>')
        
        if not props:
            return ''
        return '<w:rPr>' + ''.join(props) + '</w:rPr>'
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in Word format."""
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # =========================================================================
    # Field Code Handling (EndNote, Zotero, etc.)
    # =========================================================================
    
