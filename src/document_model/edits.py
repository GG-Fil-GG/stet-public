"""
Edit operation data structures for the Document Model.

These represent changes to be applied to the document.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum

from .paragraph import RunFormatting


class EditType(Enum):
    """Type of edit operation."""
    INSERT = "insert"                     # Insert new text within a paragraph
    DELETE = "delete"                     # Delete existing text within a paragraph
    REPLACE = "replace"                   # Delete + Insert (common case)
    FORMAT = "format"                     # Change formatting only (no text change)
    INSERT_PARAGRAPH = "insert_paragraph" # Insert a new paragraph (structural change)
    DELETE_PARAGRAPH = "delete_paragraph" # Delete an entire paragraph (structural change)


@dataclass
class DocumentEdit:
    """
    A single edit operation to apply to the document.
    
    Edits are computed from PlainTextView.apply_edit() and then
    applied to DocumentModel.apply_edit().
    
    The edit workflow:
    1. LLM returns revised plain text
    2. Diff original vs revised to identify changes
    3. Map changes to DOM positions via PlainTextView
    4. Create DocumentEdit objects
    5. Apply edits to DocumentModel (updates anchors automatically)
    
    For structural edits (INSERT_PARAGRAPH, DELETE_PARAGRAPH):
    - INSERT_PARAGRAPH: Creates a new paragraph after `after_para_id`
    - DELETE_PARAGRAPH: Removes the paragraph with `para_id`
    """
    edit_type: EditType
    
    # Location
    para_id: str                           # Paragraph to edit (or to delete for DELETE_PARAGRAPH)
    start_offset: int = 0                  # Character offset where edit begins
    end_offset: int = 0                    # Character offset where edit ends (for delete/replace)
    
    # Content
    text: str = ""                         # New text (for insert/replace/insert_paragraph)
    formatting: Optional[RunFormatting] = None  # Formatting for inserted text
    
    # Structural edit fields
    after_para_id: Optional[str] = None    # For INSERT_PARAGRAPH: insert after this paragraph
                                           # None means insert at beginning of document
    before_para_id: Optional[str] = None   # For INSERT_PARAGRAPH: insert before this paragraph
                                           # Takes precedence over after_para_id if both set
    new_para_id: Optional[str] = None      # For INSERT_PARAGRAPH: ID for the new paragraph
                                           # Will be generated if not provided
    
    # Metadata
    author: str = "Stet"
    timestamp: Optional[datetime] = None
    
    # Thread tracking (for thread-aware revision context)
    thread_id: Optional[str] = None        # Which comment thread initiated this edit
    
    # Options
    track_change: bool = True              # Create tracked change or direct edit?
    
    def __post_init__(self):
        """Set default values."""
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.edit_type == EditType.INSERT:
            self.end_offset = self.start_offset
    
    @property
    def is_insert(self) -> bool:
        """Is this an insertion?"""
        return self.edit_type == EditType.INSERT
    
    @property
    def is_delete(self) -> bool:
        """Is this a deletion?"""
        return self.edit_type == EditType.DELETE
    
    @property
    def is_replace(self) -> bool:
        """Is this a replacement?"""
        return self.edit_type == EditType.REPLACE
    
    @property
    def is_format(self) -> bool:
        """Is this a formatting change?"""
        return self.edit_type == EditType.FORMAT
    
    @property
    def deletion_length(self) -> int:
        """Length of text being deleted (0 for pure inserts)."""
        return max(0, self.end_offset - self.start_offset)
    
    @property
    def insertion_length(self) -> int:
        """Length of text being inserted (0 for pure deletes)."""
        return len(self.text)
    
    @property
    def net_length_change(self) -> int:
        """
        Net change in paragraph length after this edit.
        
        Positive = paragraph gets longer
        Negative = paragraph gets shorter
        """
        return self.insertion_length - self.deletion_length
    
    @classmethod
    def insert(
        cls,
        para_id: str,
        position: int,
        text: str,
        author: str = "Stet",
        track_change: bool = True,
        formatting: Optional[RunFormatting] = None,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create an insertion edit.
        
        Args:
            para_id: Paragraph to insert into
            position: Character offset to insert at
            text: Text to insert
            author: Author of the change
            track_change: Whether to create a tracked change
            formatting: Formatting for the inserted text
            thread_id: Comment thread that initiated this edit
        """
        return cls(
            edit_type=EditType.INSERT,
            para_id=para_id,
            start_offset=position,
            end_offset=position,
            text=text,
            author=author,
            track_change=track_change,
            formatting=formatting,
            thread_id=thread_id
        )
    
    @classmethod
    def delete(
        cls,
        para_id: str,
        start: int,
        end: int,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create a deletion edit.
        
        Args:
            para_id: Paragraph to delete from
            start: Start character offset
            end: End character offset
            author: Author of the change
            track_change: Whether to create a tracked change
            thread_id: Comment thread that initiated this edit
        """
        return cls(
            edit_type=EditType.DELETE,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
            text="",
            author=author,
            track_change=track_change,
            thread_id=thread_id
        )
    
    @classmethod
    def replace(
        cls,
        para_id: str,
        start: int,
        end: int,
        new_text: str,
        author: str = "Stet",
        track_change: bool = True,
        formatting: Optional[RunFormatting] = None,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create a replacement edit (delete + insert).
        
        Args:
            para_id: Paragraph to modify
            start: Start character offset of text to replace
            end: End character offset of text to replace
            new_text: New text to insert
            author: Author of the change
            track_change: Whether to create a tracked change
            formatting: Formatting for the new text
            thread_id: Comment thread that initiated this edit
        """
        return cls(
            edit_type=EditType.REPLACE,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
            text=new_text,
            author=author,
            track_change=track_change,
            formatting=formatting,
            thread_id=thread_id
        )
    
    @classmethod
    def format_change(
        cls,
        para_id: str,
        start: int,
        end: int,
        formatting: RunFormatting,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create a formatting-only edit.
        
        Args:
            para_id: Paragraph to modify
            start: Start character offset
            end: End character offset
            formatting: New formatting to apply
            author: Author of the change
            track_change: Whether to create a tracked change
            thread_id: Comment thread that initiated this edit
        """
        return cls(
            edit_type=EditType.FORMAT,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
            text="",
            formatting=formatting,
            author=author,
            track_change=track_change,
            thread_id=thread_id
        )
    
    @classmethod
    def insert_paragraph(
        cls,
        text: str,
        after_para_id: Optional[str] = None,
        before_para_id: Optional[str] = None,
        new_para_id: Optional[str] = None,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create an edit to insert a new paragraph.
        
        Args:
            text: Text content for the new paragraph
            after_para_id: Insert after this paragraph (None = beginning of document)
            before_para_id: Insert before this paragraph (takes precedence if both set)
            new_para_id: ID for the new paragraph (will be generated if not provided)
            author: Author of the change
            track_change: Whether to create a tracked change
            thread_id: Comment thread that initiated this edit
            
        Returns:
            DocumentEdit for inserting a paragraph
        """
        return cls(
            edit_type=EditType.INSERT_PARAGRAPH,
            para_id=new_para_id or "",  # Will be generated if empty
            start_offset=0,
            end_offset=0,
            text=text,
            after_para_id=after_para_id,
            before_para_id=before_para_id,
            new_para_id=new_para_id,
            author=author,
            track_change=track_change,
            thread_id=thread_id
        )
    
    @classmethod
    def delete_paragraph(
        cls,
        para_id: str,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> 'DocumentEdit':
        """
        Create an edit to delete an entire paragraph.
        
        Args:
            para_id: ID of the paragraph to delete
            author: Author of the change
            track_change: Whether to create a tracked change
            thread_id: Comment thread that initiated this edit
            
        Returns:
            DocumentEdit for deleting a paragraph
        """
        return cls(
            edit_type=EditType.DELETE_PARAGRAPH,
            para_id=para_id,
            start_offset=0,
            end_offset=0,
            text="",
            author=author,
            track_change=track_change,
            thread_id=thread_id
        )
    
    @property
    def is_structural(self) -> bool:
        """Is this a structural change (paragraph insert/delete)?"""
        return self.edit_type in (EditType.INSERT_PARAGRAPH, EditType.DELETE_PARAGRAPH)
    
    def validate(self) -> bool:
        """
        Validate this edit for basic correctness.
        
        Returns True if valid, raises ValueError if not.
        """
        # Structural edits have different validation rules
        if self.edit_type == EditType.INSERT_PARAGRAPH:
            # INSERT_PARAGRAPH doesn't require para_id (it will be generated)
            # but does require text (can be empty string for empty paragraph)
            return True
        
        if self.edit_type == EditType.DELETE_PARAGRAPH:
            if not self.para_id:
                raise ValueError("DELETE_PARAGRAPH requires para_id")
            return True
        
        # Standard within-paragraph edits
        if not self.para_id:
            raise ValueError("para_id is required")
        
        if self.start_offset < 0:
            raise ValueError("start_offset cannot be negative")
        
        if self.end_offset < self.start_offset:
            raise ValueError("end_offset cannot be less than start_offset")
        
        if self.edit_type in (EditType.INSERT, EditType.REPLACE) and not self.text:
            if self.edit_type == EditType.INSERT:
                raise ValueError("INSERT edit requires text")
            # REPLACE with empty text is effectively DELETE - that's OK
        
        if self.edit_type == EditType.DELETE and self.start_offset == self.end_offset:
            raise ValueError("DELETE edit requires non-zero range")
        
        if self.edit_type == EditType.FORMAT and self.formatting is None:
            raise ValueError("FORMAT edit requires formatting")
        
        return True
