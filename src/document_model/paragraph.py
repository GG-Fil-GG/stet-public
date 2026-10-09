"""
Paragraph and Run data structures for the Document Model.

These represent the content elements of a Word document.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum


class RevisionType(Enum):
    """Type of tracked change."""
    INSERTION = "insertion"      # <w:ins>
    DELETION = "deletion"        # <w:del>
    FORMATTING = "formatting"    # <w:rPrChange>
    MOVE_FROM = "move_from"      # <w:moveFrom>
    MOVE_TO = "move_to"          # <w:moveTo>


@dataclass
class RunFormatting:
    """
    Run-level formatting properties.
    
    These map to <w:rPr> elements in Word XML.
    """
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    
    font_name: Optional[str] = None
    font_size: Optional[float] = None    # Points
    color: Optional[str] = None          # Hex color (e.g., "FF0000")
    highlight: Optional[str] = None      # Highlight color name
    
    # For future expansion
    custom_properties: Dict[str, Any] = field(default_factory=dict)
    
    def __eq__(self, other: object) -> bool:
        """Check formatting equality (ignoring custom_properties for simplicity)."""
        if not isinstance(other, RunFormatting):
            return False
        return (
            self.bold == other.bold and
            self.italic == other.italic and
            self.underline == other.underline and
            self.strike == other.strike and
            self.superscript == other.superscript and
            self.subscript == other.subscript and
            self.font_name == other.font_name and
            self.font_size == other.font_size and
            self.color == other.color and
            self.highlight == other.highlight
        )
    
    def is_empty(self) -> bool:
        """Check if this represents no formatting (all defaults)."""
        return (
            not self.bold and
            not self.italic and
            not self.underline and
            not self.strike and
            not self.superscript and
            not self.subscript and
            self.font_name is None and
            self.font_size is None and
            self.color is None and
            self.highlight is None
        )
    
    def copy(self) -> 'RunFormatting':
        """Create a copy of this formatting."""
        return RunFormatting(
            bold=self.bold,
            italic=self.italic,
            underline=self.underline,
            strike=self.strike,
            superscript=self.superscript,
            subscript=self.subscript,
            font_name=self.font_name,
            font_size=self.font_size,
            color=self.color,
            highlight=self.highlight,
            custom_properties=dict(self.custom_properties)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'bold': self.bold,
            'italic': self.italic,
            'underline': self.underline,
            'strike': self.strike,
            'superscript': self.superscript,
            'subscript': self.subscript,
            'font_name': self.font_name,
            'font_size': self.font_size,
            'color': self.color,
            'highlight': self.highlight,
            'custom_properties': self.custom_properties,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RunFormatting':
        """Deserialize from dictionary."""
        return cls(
            bold=data.get('bold', False),
            italic=data.get('italic', False),
            underline=data.get('underline', False),
            strike=data.get('strike', False),
            superscript=data.get('superscript', False),
            subscript=data.get('subscript', False),
            font_name=data.get('font_name'),
            font_size=data.get('font_size'),
            color=data.get('color'),
            highlight=data.get('highlight'),
            custom_properties=data.get('custom_properties', {}),
        )
    
    def to_html(self, text: str) -> str:
        """
        Wrap text in HTML tags based on formatting.
        
        Order matters for proper nesting:
        - Outer: subscript/superscript (structural)
        - Middle: underline, strike
        - Inner: bold, italic (emphasis)
        
        Args:
            text: The plain text to wrap
            
        Returns:
            HTML string with appropriate formatting tags
        """
        import html as html_module
        result = html_module.escape(text)
        
        # Apply formatting from innermost to outermost
        if self.bold:
            result = f'<b>{result}</b>'
        if self.italic:
            result = f'<i>{result}</i>'
        if self.underline:
            result = f'<u>{result}</u>'
        if self.strike:
            result = f'<s>{result}</s>'
        if self.superscript:
            result = f'<sup>{result}</sup>'
        if self.subscript:
            result = f'<sub>{result}</sub>'
        
        return result
    
    def to_formatting_set(self) -> set:
        """
        Convert formatting to a set of format identifiers.
        
        Used for comparing formatting between original and revised text.
        
        Returns:
            Set of strings like {'bold', 'italic', 'subscript'}
        """
        result = set()
        if self.bold:
            result.add('bold')
        if self.italic:
            result.add('italic')
        if self.underline:
            result.add('underline')
        if self.strike:
            result.add('strike')
        if self.superscript:
            result.add('superscript')
        if self.subscript:
            result.add('subscript')
        return result


@dataclass
class Run:
    """
    A run of text with uniform formatting.
    
    In Word, formatting changes require run boundaries. A paragraph like:
    "Hello WORLD today" (where WORLD is bold) has 3 runs.
    """
    # Content
    text: str
    
    # Formatting
    formatting: RunFormatting = field(default_factory=RunFormatting)
    style_id: Optional[str] = None  # Character style reference
    
    # Position within paragraph (computed during parsing, updated on edits)
    start_offset: int = 0   # Character offset in paragraph
    end_offset: int = 0     # Character offset in paragraph
    
    # Track change context (if this run is inside w:ins or w:del)
    revision_type: Optional[RevisionType] = None
    revision_id: Optional[str] = None
    
    # Original XML (for elements we don't fully parse)
    _raw_xml: Optional[str] = None
    
    def __post_init__(self):
        """Ensure end_offset is set correctly if not provided."""
        if self.end_offset == 0 and self.text:
            self.end_offset = self.start_offset + len(self.text)
    
    @property
    def length(self) -> int:
        """Length of this run's text."""
        return len(self.text)
    
    def is_deleted(self) -> bool:
        """Is this run part of a deletion (track change)?"""
        return self.revision_type == RevisionType.DELETION
    
    def is_inserted(self) -> bool:
        """Is this run part of an insertion (track change)?"""
        return self.revision_type == RevisionType.INSERTION
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'text': self.text,
            'formatting': self.formatting.to_dict(),
            'style_id': self.style_id,
            'start_offset': self.start_offset,
            'end_offset': self.end_offset,
            'revision_type': self.revision_type.value if self.revision_type else None,
            'revision_id': self.revision_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Run':
        """Deserialize from dictionary."""
        revision_type = None
        if data.get('revision_type'):
            revision_type = RevisionType(data['revision_type'])
        return cls(
            text=data.get('text', ''),
            formatting=RunFormatting.from_dict(data.get('formatting', {})),
            style_id=data.get('style_id'),
            start_offset=data.get('start_offset', 0),
            end_offset=data.get('end_offset', 0),
            revision_type=revision_type,
            revision_id=data.get('revision_id'),
        )
    
    def to_html(self) -> str:
        """
        Generate HTML for this run with formatting applied.
        
        Returns:
            HTML string with text wrapped in appropriate tags
        """
        return self.formatting.to_html(self.text)


@dataclass
class ParagraphProperties:
    """
    Paragraph-level formatting properties.
    
    These map to <w:pPr> elements in Word XML.
    """
    alignment: Optional[str] = None      # left, center, right, justify
    indent_left: Optional[float] = None  # Points
    indent_right: Optional[float] = None
    indent_first: Optional[float] = None
    spacing_before: Optional[float] = None
    spacing_after: Optional[float] = None
    line_spacing: Optional[float] = None
    
    # For future expansion
    custom_properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'alignment': self.alignment,
            'indent_left': self.indent_left,
            'indent_right': self.indent_right,
            'indent_first': self.indent_first,
            'spacing_before': self.spacing_before,
            'spacing_after': self.spacing_after,
            'line_spacing': self.line_spacing,
            'custom_properties': self.custom_properties,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ParagraphProperties':
        """Deserialize from dictionary."""
        return cls(
            alignment=data.get('alignment'),
            indent_left=data.get('indent_left'),
            indent_right=data.get('indent_right'),
            indent_first=data.get('indent_first'),
            spacing_before=data.get('spacing_before'),
            spacing_after=data.get('spacing_after'),
            line_spacing=data.get('line_spacing'),
            custom_properties=data.get('custom_properties', {}),
        )


@dataclass
class Paragraph:
    """
    A document paragraph.
    
    Key insight: We track character positions within the paragraph to enable
    plain text ↔ DOM mapping and anchor management.
    """
    # Identity
    para_id: str          # w14:paraId (8-char hex, first char MUST be 0-7)
    text_id: str          # w14:textId (8-char hex, no constraint)
    
    # Content
    runs: List[Run] = field(default_factory=list)
    
    # Formatting
    properties: ParagraphProperties = field(default_factory=ParagraphProperties)
    style_id: Optional[str] = None  # Reference to named style (e.g., "Heading1")
    
    # Position in document
    index: int = 0  # Position in body.elements
    
    # Field codes (EndNote citations, etc.) - extracted at parse time
    # Maps placeholder (e.g., "[CITATION_1]") -> original field code XML
    field_codes: Dict[str, str] = field(default_factory=dict)
    
    # Raw text extracted from runs (before placeholder injection)
    # Used to map placeholders back to their display text locations
    _raw_text: Optional[str] = None
    
    # Cached computed properties (invalidated on edit)
    _plain_text: Optional[str] = None
    _char_count: Optional[int] = None
    
    @property
    def plain_text(self) -> str:
        """
        Get concatenated plain text of all runs (excluding deleted text).
        
        If field_codes are present, returns text with placeholders (e.g., [CITATION_1])
        instead of the field code display text (e.g., [1]).
        """
        if self._plain_text is None:
            # Get raw text from runs
            raw = ''.join(
                run.text for run in self.runs 
                if not run.is_deleted()
            )
            self._raw_text = raw
            
            # Apply field code placeholders if present
            # Replace ALL occurrences of each display text with its placeholder.
            # This ensures consistency between model text and serializer's original text,
            # even when LLM adds new citations that look like "[1]".
            if self.field_codes:
                text_with_placeholders = raw
                for placeholder, field_xml in self.field_codes.items():
                    display_text = self._extract_field_display_text(field_xml)
                    if display_text and display_text in text_with_placeholders:
                        text_with_placeholders = text_with_placeholders.replace(
                            display_text, placeholder
                        )
                self._plain_text = text_with_placeholders
            else:
                self._plain_text = raw
        return self._plain_text
    
    def _extract_field_display_text(self, field_xml: str) -> str:
        """
        Extract the visible display text from a field code XML fragment.
        
        For EndNote citations, this is typically something like "[1]" or "(Author 2023)".
        The display text is in <w:t> elements between the field code markers.
        """
        import re
        # Find all text content within the field code
        text_matches = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', field_xml)
        return ''.join(text_matches)
    
    @property
    def raw_text(self) -> str:
        """Get raw text without placeholder substitution (for export)."""
        if self._raw_text is None:
            # Trigger plain_text to compute _raw_text
            _ = self.plain_text
        return self._raw_text or ''
    
    def to_html(self, include_deleted: bool = False) -> str:
        """
        Generate HTML representation of the paragraph with formatting.
        
        Concatenates HTML from all runs, applying character-level formatting
        (bold, italic, underline, super/subscript) via HTML tags.
        
        Args:
            include_deleted: If True, include deleted text (for debugging)
            
        Returns:
            HTML string with formatted text
        """
        parts = []
        for run in self.runs:
            if run.is_deleted() and not include_deleted:
                continue
            parts.append(run.to_html())
        return ''.join(parts)
    
    def to_display_html(self) -> str:
        """
        Generate HTML for UI display, with field code placeholders converted.
        
        Similar to to_html() but replaces [CITATION_X] placeholders with
        their original display text (e.g., [1]).
        
        Returns:
            HTML string suitable for UI display
        """
        html = self.to_html()
        
        # Convert placeholders back to display text
        if self.field_codes:
            html = self.get_display_text(html)
        
        return html
    
    def get_display_text(self, text_with_placeholders: str) -> str:
        """
        Convert placeholders back to display text for UI display.
        
        Args:
            text_with_placeholders: Text containing [CITATION_X] placeholders
            
        Returns:
            Text with placeholders replaced by original display text (e.g., [1])
        """
        result = text_with_placeholders
        for placeholder, field_xml in self.field_codes.items():
            display_text = self._extract_field_display_text(field_xml)
            if display_text and placeholder in result:
                result = result.replace(placeholder, display_text)
        return result
    
    @property
    def full_text(self) -> str:
        """Get concatenated plain text of all runs (including deleted text)."""
        return ''.join(run.text for run in self.runs)
    
    @property
    def char_count(self) -> int:
        """Total character count (excluding deleted text)."""
        if self._char_count is None:
            self._char_count = len(self.plain_text)
        return self._char_count
    
    def get_run_at_offset(self, char_offset: int) -> Tuple[Optional[Run], int]:
        """
        Find the run containing a character offset.
        
        Args:
            char_offset: Character position in the paragraph's plain text
            
        Returns:
            Tuple of (run, offset_within_run) or (None, -1) if not found
        """
        current_offset = 0
        for run in self.runs:
            if run.is_deleted():
                continue
            run_length = len(run.text)
            if current_offset <= char_offset < current_offset + run_length:
                return (run, char_offset - current_offset)
            current_offset += run_length
        return (None, -1)
    
    def invalidate_cache(self) -> None:
        """Clear cached computed properties after modification."""
        self._plain_text = None
        self._raw_text = None
        self._char_count = None
    
    def recalculate_run_offsets(self) -> None:
        """Recalculate start_offset and end_offset for all runs."""
        current_offset = 0
        for run in self.runs:
            run.start_offset = current_offset
            run.end_offset = current_offset + len(run.text)
            current_offset = run.end_offset
        self.invalidate_cache()
    
    def insert_text(self, offset: int, text: str, formatting: Optional[RunFormatting] = None) -> None:
        """
        Insert text at a character offset.
        
        Args:
            offset: Character position to insert at
            text: Text to insert
            formatting: Formatting for the new text (uses run's formatting if None)
        """
        if not text:
            return
            
        run, offset_in_run = self.get_run_at_offset(offset)
        
        if run is None:
            # Insert at end
            new_run = Run(
                text=text,
                formatting=formatting or RunFormatting(),
                start_offset=self.char_count
            )
            self.runs.append(new_run)
        elif offset_in_run == 0:
            # Insert at beginning of run
            if formatting is None or formatting == run.formatting:
                run.text = text + run.text
            else:
                # Insert new run before
                run_idx = self.runs.index(run)
                new_run = Run(text=text, formatting=formatting)
                self.runs.insert(run_idx, new_run)
        elif offset_in_run == len(run.text):
            # Insert at end of run
            if formatting is None or formatting == run.formatting:
                run.text = run.text + text
            else:
                # Insert new run after
                run_idx = self.runs.index(run)
                new_run = Run(text=text, formatting=formatting)
                self.runs.insert(run_idx + 1, new_run)
        else:
            # Split the run
            run_idx = self.runs.index(run)
            before_text = run.text[:offset_in_run]
            after_text = run.text[offset_in_run:]
            
            run.text = before_text
            
            if formatting is None or formatting == run.formatting:
                # Same formatting, just insert text
                new_run = Run(text=text + after_text, formatting=run.formatting.copy())
            else:
                # Different formatting, create two new runs
                new_run = Run(text=text, formatting=formatting)
                after_run = Run(text=after_text, formatting=run.formatting.copy())
                self.runs.insert(run_idx + 1, new_run)
                self.runs.insert(run_idx + 2, after_run)
                self.recalculate_run_offsets()
                return
            
            self.runs.insert(run_idx + 1, new_run)
        
        self.recalculate_run_offsets()
    
    def delete_text(self, start: int, end: int) -> str:
        """
        Delete text between start and end offsets.
        
        Args:
            start: Start character offset
            end: End character offset
            
        Returns:
            The deleted text
        """
        if start >= end or start < 0:
            return ""
        
        deleted_text = self.plain_text[start:end]
        
        # Find affected runs and modify them
        runs_to_remove = []
        current_offset = 0
        
        for run in self.runs:
            if run.is_deleted():
                continue
                
            run_start = current_offset
            run_end = current_offset + len(run.text)
            
            if run_end <= start:
                # Run is entirely before deletion
                current_offset = run_end
                continue
            elif run_start >= end:
                # Run is entirely after deletion
                break
            elif run_start >= start and run_end <= end:
                # Run is entirely within deletion
                runs_to_remove.append(run)
            elif run_start < start and run_end > end:
                # Deletion is entirely within this run
                delete_start = start - run_start
                delete_end = end - run_start
                run.text = run.text[:delete_start] + run.text[delete_end:]
            elif run_start < start:
                # Deletion starts within this run
                delete_start = start - run_start
                run.text = run.text[:delete_start]
            elif run_end > end:
                # Deletion ends within this run
                delete_end = end - run_start
                run.text = run.text[delete_end:]
            
            current_offset = run_end
        
        for run in runs_to_remove:
            self.runs.remove(run)
        
        self.recalculate_run_offsets()
        return deleted_text
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'para_id': self.para_id,
            'text_id': self.text_id,
            'runs': [run.to_dict() for run in self.runs],
            'properties': self.properties.to_dict(),
            'style_id': self.style_id,
            'index': self.index,
            'field_codes': self.field_codes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Paragraph':
        """Deserialize from dictionary."""
        para = cls(
            para_id=data.get('para_id', ''),
            text_id=data.get('text_id', ''),
            runs=[Run.from_dict(r) for r in data.get('runs', [])],
            properties=ParagraphProperties.from_dict(data.get('properties', {})),
            style_id=data.get('style_id'),
            index=data.get('index', 0),
            field_codes=data.get('field_codes', {}),
        )
        return para
