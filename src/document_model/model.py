"""
Core Document Model data structures.

DocumentModel is the single source of truth for document state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Iterator, Set, Union, TYPE_CHECKING, Any

from .paragraph import Paragraph, Run
from .comments import CommentStore, Comment
from .revisions import RevisionStore
from .edits import DocumentEdit, EditType
from .utils import generate_valid_para_id, generate_hex_id

if TYPE_CHECKING:
    from .paragraph import RunFormatting


# Type alias for elements that can appear in the document body
BodyElement = Union[Paragraph, 'Table']


@dataclass
class Table:
    """
    A table in the document.
    
    Tables contain rows, which contain cells, which contain paragraphs.
    This is a simplified representation - full table support will be added later.
    """
    rows: List[List[Paragraph]] = field(default_factory=list)  # rows × cells × paragraphs
    index: int = 0  # Position in body.elements
    
    @property
    def row_count(self) -> int:
        """Number of rows in the table."""
        return len(self.rows)
    
    @property
    def col_count(self) -> int:
        """Number of columns (based on first row)."""
        return len(self.rows[0]) if self.rows else 0
    
    def get_cell(self, row: int, col: int) -> Optional[Paragraph]:
        """Get the paragraph in a specific cell."""
        if 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            return self.rows[row][col]
        return None
    
    def iter_paragraphs(self) -> Iterator[Paragraph]:
        """Iterate over all paragraphs in the table."""
        for row in self.rows:
            for cell in row:
                yield cell
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'type': 'table',
            'rows': [[cell.to_dict() for cell in row] for row in self.rows],
            'index': self.index,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Table':
        """Deserialize from dictionary."""
        return cls(
            rows=[[Paragraph.from_dict(cell) for cell in row] for row in data.get('rows', [])],
            index=data.get('index', 0),
        )


@dataclass
class DocumentProperties:
    """
    Document metadata and properties.
    """
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[str] = None
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    
    # Custom properties
    custom: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'title': self.title,
            'author': self.author,
            'subject': self.subject,
            'keywords': self.keywords,
            'created': self.created.isoformat() if self.created else None,
            'modified': self.modified.isoformat() if self.modified else None,
            'custom': self.custom,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentProperties':
        """Deserialize from dictionary."""
        created = None
        if data.get('created'):
            created = datetime.fromisoformat(data['created'])
        modified = None
        if data.get('modified'):
            modified = datetime.fromisoformat(data['modified'])
        return cls(
            title=data.get('title'),
            author=data.get('author'),
            subject=data.get('subject'),
            keywords=data.get('keywords'),
            created=created,
            modified=modified,
            custom=data.get('custom', {}),
        )


@dataclass
class StyleStore:
    """
    Manages document styles.
    
    Simplified for now - full style support will be added later.
    """
    styles: Dict[str, Dict] = field(default_factory=dict)  # style_id → style properties
    
    def get_style(self, style_id: str) -> Optional[Dict]:
        """Get a style by ID."""
        return self.styles.get(style_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {'styles': self.styles}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StyleStore':
        """Deserialize from dictionary."""
        return cls(styles=data.get('styles', {}))


@dataclass
class DocumentBody:
    """
    The document body containing all content elements.
    
    Elements are stored in document order. Each element knows its position.
    """
    elements: List[BodyElement] = field(default_factory=list)
    
    # Index for fast para_id lookup
    _para_id_index: Dict[str, Paragraph] = field(default_factory=dict)
    
    def add_element(self, element: BodyElement) -> None:
        """Add an element to the body and update indices."""
        element.index = len(self.elements)
        self.elements.append(element)
        
        # Update index
        if isinstance(element, Paragraph):
            self._para_id_index[element.para_id] = element
        elif isinstance(element, Table):
            for para in element.iter_paragraphs():
                self._para_id_index[para.para_id] = para
    
    def insert_element_at(self, index: int, element: BodyElement) -> None:
        """
        Insert an element at a specific position in the body.
        
        Args:
            index: Position to insert at (0 = beginning, len = end)
            element: The element to insert
        """
        # Clamp index to valid range
        index = max(0, min(index, len(self.elements)))
        
        # Insert the element
        self.elements.insert(index, element)
        
        # Update indices for all elements from insertion point onwards
        for i in range(index, len(self.elements)):
            self.elements[i].index = i
        
        # Update para_id index
        if isinstance(element, Paragraph):
            self._para_id_index[element.para_id] = element
        elif isinstance(element, Table):
            for para in element.iter_paragraphs():
                self._para_id_index[para.para_id] = para
    
    def remove_element(self, para_id: str) -> Optional[BodyElement]:
        """
        Remove a paragraph from the body by its para_id.
        
        Note: For table cells, this removes the entire table (not just the cell).
        To remove a table cell, use table-specific methods.
        
        Args:
            para_id: The paragraph ID to remove
            
        Returns:
            The removed element, or None if not found
        """
        # Find the element to remove
        element_to_remove = None
        remove_index = -1
        
        for i, element in enumerate(self.elements):
            if isinstance(element, Paragraph) and element.para_id == para_id:
                element_to_remove = element
                remove_index = i
                break
            elif isinstance(element, Table):
                # Check if para_id is in this table
                for para in element.iter_paragraphs():
                    if para.para_id == para_id:
                        # For now, we don't support removing individual table cells
                        # The caller should handle table cell removal separately
                        return None
        
        if element_to_remove is None:
            return None
        
        # Remove from elements list
        self.elements.pop(remove_index)
        
        # Update indices for all elements after removal point
        for i in range(remove_index, len(self.elements)):
            self.elements[i].index = i
        
        # Remove from para_id index
        if isinstance(element_to_remove, Paragraph):
            self._para_id_index.pop(element_to_remove.para_id, None)
        
        return element_to_remove
    
    def get_element_index(self, para_id: str) -> int:
        """
        Get the index of an element in self.elements by its para_id.
        
        For paragraphs: returns the index in elements list.
        For table cells: returns the index of the containing table.
        
        Args:
            para_id: The paragraph ID to find
            
        Returns:
            Index in elements list, or -1 if not found
        """
        for i, element in enumerate(self.elements):
            if isinstance(element, Paragraph) and element.para_id == para_id:
                return i
            elif isinstance(element, Table):
                for para in element.iter_paragraphs():
                    if para.para_id == para_id:
                        return i  # Return the table's index
        return -1
    
    def get_element_by_para_id(self, para_id: str) -> Optional[Paragraph]:
        """Find paragraph by its paragraph ID."""
        return self._para_id_index.get(para_id)
    
    def get_element_at_index(self, index: int) -> Optional[BodyElement]:
        """Get element at a specific index."""
        if 0 <= index < len(self.elements):
            return self.elements[index]
        return None
    
    def get_elements_in_range(self, start_idx: int, end_idx: int) -> List[BodyElement]:
        """Get elements by index range (for context expansion)."""
        start = max(0, start_idx)
        end = min(len(self.elements), end_idx)
        return self.elements[start:end]
    
    def iter_paragraphs(self) -> Iterator[Paragraph]:
        """Iterate over all paragraphs (including those in tables)."""
        for element in self.elements:
            if isinstance(element, Paragraph):
                yield element
            elif isinstance(element, Table):
                yield from element.iter_paragraphs()
    
    def get_paragraph_index(self, para_id: str) -> int:
        """
        Get the index of a paragraph in the flat paragraph list.
        
        Returns -1 if not found.
        """
        idx = 0
        for para in self.iter_paragraphs():
            if para.para_id == para_id:
                return idx
            idx += 1
        return -1
    
    def get_paragraph_at_flat_index(self, flat_index: int) -> Optional[Paragraph]:
        """Get paragraph at a flat index (across all elements including tables)."""
        idx = 0
        for para in self.iter_paragraphs():
            if idx == flat_index:
                return para
            idx += 1
        return None
    
    @property
    def paragraph_count(self) -> int:
        """Total number of paragraphs (including in tables)."""
        return sum(1 for _ in self.iter_paragraphs())
    
    @property
    def element_count(self) -> int:
        """Number of top-level elements."""
        return len(self.elements)
    
    def rebuild_index(self) -> None:
        """Rebuild the para_id index (call after bulk modifications)."""
        self._para_id_index.clear()
        for element in self.elements:
            if isinstance(element, Paragraph):
                self._para_id_index[element.para_id] = element
            elif isinstance(element, Table):
                for para in element.iter_paragraphs():
                    self._para_id_index[para.para_id] = para
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        elements_data = []
        for element in self.elements:
            if isinstance(element, Paragraph):
                data = element.to_dict()
                data['type'] = 'paragraph'
                elements_data.append(data)
            elif isinstance(element, Table):
                elements_data.append(element.to_dict())
        return {'elements': elements_data}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentBody':
        """Deserialize from dictionary."""
        body = cls()
        for elem_data in data.get('elements', []):
            if elem_data.get('type') == 'table':
                element = Table.from_dict(elem_data)
            else:
                element = Paragraph.from_dict(elem_data)
            body.add_element(element)
        return body


@dataclass
class DocumentModel:
    """
    The single source of truth for document state.
    
    All modifications go through this model. Export serializes this back to DOCX.
    """
    # Document identity
    source_path: Optional[Path] = None    # Original file path
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    # Content structure
    body: DocumentBody = field(default_factory=DocumentBody)
    
    # Comments system (our primary focus)
    comments: CommentStore = field(default_factory=CommentStore)
    
    # Track changes
    revisions: RevisionStore = field(default_factory=RevisionStore)
    
    # Styles and formatting
    styles: StyleStore = field(default_factory=StyleStore)
    
    # Metadata
    properties: DocumentProperties = field(default_factory=DocumentProperties)
    
    # State tracking
    is_dirty: bool = False  # Has unsaved changes
    _plain_edited_para_ids: Set[str] = field(default_factory=set)
    
    def get_paragraph(self, para_id: str) -> Optional[Paragraph]:
        """Get a paragraph by its para_id."""
        return self.body.get_element_by_para_id(para_id)
    
    def apply_edit(self, edit: DocumentEdit) -> bool:
        """
        Apply an edit to the document.
        
        This is the main entry point for modifications. It:
        1. Validates the edit
        2. Modifies the paragraph content (or structure for INSERT/DELETE_PARAGRAPH)
        3. Updates comment anchors
        4. Optionally creates a tracked change
        
        Args:
            edit: The edit to apply
            
        Returns:
            True if successful, False otherwise
        """
        edit.validate()
        
        # Handle structural edits (paragraph insert/delete) separately
        if edit.edit_type == EditType.INSERT_PARAGRAPH:
            return self._apply_insert_paragraph(edit)
        elif edit.edit_type == EditType.DELETE_PARAGRAPH:
            return self._apply_delete_paragraph(edit)
        
        # Standard within-paragraph edits
        paragraph = self.get_paragraph(edit.para_id)
        if not paragraph:
            return False
        
        # Calculate the offset change for anchor adjustment
        offset_change = edit.net_length_change
        edit_position = edit.start_offset
        
        # Apply the edit based on type
        if edit.edit_type == EditType.INSERT:
            paragraph.insert_text(edit.start_offset, edit.text, edit.formatting)
            if edit.track_change:
                self.revisions.add_insertion(
                    para_id=edit.para_id,
                    position=edit.start_offset,
                    text=edit.text,
                    author=edit.author,
                    timestamp=edit.timestamp,
                    formatting=edit.formatting,
                    thread_id=edit.thread_id
                )
        
        elif edit.edit_type == EditType.DELETE:
            deleted_text = paragraph.delete_text(edit.start_offset, edit.end_offset)
            if edit.track_change:
                self.revisions.add_deletion(
                    para_id=edit.para_id,
                    start=edit.start_offset,
                    end=edit.end_offset,
                    original_text=deleted_text,
                    author=edit.author,
                    timestamp=edit.timestamp,
                    thread_id=edit.thread_id
                )
        
        elif edit.edit_type == EditType.REPLACE:
            deleted_text = paragraph.delete_text(edit.start_offset, edit.end_offset)
            paragraph.insert_text(edit.start_offset, edit.text, edit.formatting)
            if edit.track_change:
                self.revisions.add_deletion(
                    para_id=edit.para_id,
                    start=edit.start_offset,
                    end=edit.end_offset,
                    original_text=deleted_text,
                    author=edit.author,
                    timestamp=edit.timestamp,
                    thread_id=edit.thread_id
                )
                self.revisions.add_insertion(
                    para_id=edit.para_id,
                    position=edit.start_offset,
                    text=edit.text,
                    author=edit.author,
                    timestamp=edit.timestamp,
                    formatting=edit.formatting,
                    thread_id=edit.thread_id
                )
        
        elif edit.edit_type == EditType.FORMAT:
            # Formatting changes don't modify text content
            # The actual formatting change would be applied to runs
            # For now, just record the revision
            if edit.track_change and edit.formatting:
                self.revisions.add_formatting_change(
                    para_id=edit.para_id,
                    start=edit.start_offset,
                    end=edit.end_offset,
                    new_formatting=edit.formatting,
                    original_formatting=edit.formatting,  # Would need to capture original
                    author=edit.author,
                    timestamp=edit.timestamp,
                    thread_id=edit.thread_id
                )
        
        # Adjust comment anchors in this paragraph
        if offset_change != 0:
            self._adjust_anchors(edit.para_id, edit_position, offset_change)
        
        if not edit.track_change and edit.edit_type in (
            EditType.INSERT, EditType.DELETE, EditType.REPLACE
        ):
            self._plain_edited_para_ids.add(edit.para_id)
        
        self.is_dirty = True
        self.modified_at = datetime.now()
        
        return True
    
    def _adjust_anchors(self, para_id: str, position: int, offset: int) -> None:
        """
        Adjust comment anchors after an edit.
        
        Args:
            para_id: The paragraph that was edited
            position: Character position where the edit occurred
            offset: Amount of shift (positive for insert, negative for delete)
        """
        for comment in self.comments.comments.values():
            if not comment.anchor:
                continue
            
            anchor = comment.anchor
            
            # Check if this edit affects the anchor's START paragraph
            if anchor.para_id == para_id:
                # For multi-paragraph anchors, only adjust start_offset (not end_offset)
                # because end_offset is relative to end_para_id
                if anchor.spans_paragraphs:
                    if anchor.start_offset > position:
                        anchor.start_offset = max(0, anchor.start_offset + offset)
                else:
                    # Single paragraph anchor - use standard shift
                    anchor.shift(offset, position)
            
            # Check if this edit affects the anchor's END paragraph (for multi-paragraph anchors)
            elif anchor.end_para_id and anchor.end_para_id == para_id:
                # For multi-paragraph anchors, end_offset is relative to end_para_id
                # Only shift end_offset if it's after the edit position
                if anchor.end_offset > position:
                    anchor.end_offset = max(0, anchor.end_offset + offset)
    
    def _apply_insert_paragraph(self, edit: DocumentEdit) -> bool:
        """
        Apply an INSERT_PARAGRAPH edit.
        
        Creates a new paragraph and inserts it at the specified position.
        
        Args:
            edit: The edit with INSERT_PARAGRAPH type
            
        Returns:
            True if successful, False otherwise
        """
        # Get all existing IDs for uniqueness check
        existing_para_ids = set(p.para_id for p in self.body.iter_paragraphs())
        existing_text_ids = set()  # text_ids are not easily accessible, generate fresh
        
        # Generate para_id if not provided
        new_para_id = edit.new_para_id
        if not new_para_id:
            new_para_id = generate_valid_para_id(existing_para_ids)
        
        # Generate text_id (always generated, no constraint on first char)
        new_text_id = generate_hex_id(existing_text_ids)
        
        # Create the new paragraph
        new_paragraph = Paragraph(
            para_id=new_para_id,
            text_id=new_text_id,
            runs=[Run(text=edit.text)] if edit.text else [],
            index=0  # Will be set by insert_element_at
        )
        
        # Determine insertion position
        # before_para_id takes precedence over after_para_id
        if edit.before_para_id:
            # Insert before the specified paragraph
            before_index = self.body.get_element_index(edit.before_para_id)
            if before_index < 0:
                return False  # Reference paragraph not found
            insert_index = before_index  # Insert at same position, pushing existing down
        elif edit.after_para_id:
            # Insert after the specified paragraph
            after_index = self.body.get_element_index(edit.after_para_id)
            if after_index < 0:
                return False  # Reference paragraph not found
            insert_index = after_index + 1
        else:
            # Insert at beginning
            insert_index = 0
        
        # Insert the paragraph
        self.body.insert_element_at(insert_index, new_paragraph)
        
        # Track the change if requested
        if edit.track_change:
            # Record as an insertion revision
            # The entire paragraph content is marked as inserted
            self.revisions.add_insertion(
                para_id=new_para_id,
                position=0,
                text=edit.text,
                author=edit.author,
                timestamp=edit.timestamp,
                thread_id=edit.thread_id
            )
        
        self.is_dirty = True
        self.modified_at = datetime.now()
        
        return True
    
    def _apply_delete_paragraph(self, edit: DocumentEdit) -> bool:
        """
        Apply a DELETE_PARAGRAPH edit.
        
        Removes a paragraph and migrates any anchors pointing to it.
        
        Args:
            edit: The edit with DELETE_PARAGRAPH type
            
        Returns:
            True if successful, False otherwise
        """
        # Get the paragraph to delete
        paragraph = self.get_paragraph(edit.para_id)
        if not paragraph:
            return False
        
        # Get the paragraph's text before deletion (for revision tracking)
        original_text = paragraph.plain_text
        
        # Migrate anchors before deletion
        self._migrate_anchors_for_deleted_paragraph(edit.para_id)
        
        # Remove the paragraph
        removed = self.body.remove_element(edit.para_id)
        if not removed:
            return False
        
        # Track the change if requested
        if edit.track_change:
            # Record as a deletion revision
            # The entire paragraph content is marked as deleted
            self.revisions.add_deletion(
                para_id=edit.para_id,
                start=0,
                end=len(original_text),
                original_text=original_text,
                author=edit.author,
                timestamp=edit.timestamp,
                thread_id=edit.thread_id
            )
        
        self.is_dirty = True
        self.modified_at = datetime.now()
        
        return True
    
    def _migrate_anchors_for_deleted_paragraph(self, para_id: str) -> None:
        """
        Migrate comment anchors when a paragraph is deleted.
        
        For single-paragraph anchors on the deleted paragraph:
        - Migrate to the nearest adjacent paragraph (prefer next, then previous)
        - Set offsets to start of next or end of previous
        
        For multi-paragraph anchors:
        - If start paragraph is deleted: move start to next paragraph
        - If end paragraph is deleted: move end to previous paragraph
        - If both start and end are deleted: collapse to nearest remaining paragraph
        
        Args:
            para_id: ID of the paragraph being deleted
        """
        # Find adjacent paragraphs
        paragraphs = list(self.body.iter_paragraphs())
        deleted_idx = -1
        for i, p in enumerate(paragraphs):
            if p.para_id == para_id:
                deleted_idx = i
                break
        
        if deleted_idx < 0:
            return  # Paragraph not found, nothing to migrate
        
        # Find next and previous paragraphs
        prev_para = paragraphs[deleted_idx - 1] if deleted_idx > 0 else None
        next_para = paragraphs[deleted_idx + 1] if deleted_idx < len(paragraphs) - 1 else None
        
        for comment in self.comments.comments.values():
            if not comment.anchor:
                continue
            
            anchor = comment.anchor
            
            if anchor.spans_paragraphs:
                # Multi-paragraph anchor
                start_deleted = anchor.para_id == para_id
                end_deleted = anchor.end_para_id == para_id
                
                if start_deleted and end_deleted:
                    # Both start and end are the same deleted paragraph (shouldn't happen for multi-para)
                    # Migrate entire anchor to nearest paragraph
                    if next_para:
                        anchor.para_id = next_para.para_id
                        anchor.end_para_id = next_para.para_id
                        anchor.start_offset = 0
                        anchor.end_offset = 0
                    elif prev_para:
                        anchor.para_id = prev_para.para_id
                        anchor.end_para_id = prev_para.para_id
                        anchor.start_offset = len(prev_para.plain_text)
                        anchor.end_offset = len(prev_para.plain_text)
                elif start_deleted:
                    # Start paragraph deleted - move start to next paragraph
                    if next_para:
                        anchor.para_id = next_para.para_id
                        anchor.start_offset = 0
                    # If next_para is None, the anchor becomes invalid
                    # but end_para_id should still exist
                elif end_deleted:
                    # End paragraph deleted - move end to previous paragraph
                    if prev_para:
                        anchor.end_para_id = prev_para.para_id
                        anchor.end_offset = len(prev_para.plain_text)
                    # If prev_para is None, try to collapse to start paragraph
                    elif anchor.para_id != para_id:
                        # Collapse to single-paragraph anchor at start
                        start_para = self.get_paragraph(anchor.para_id)
                        if start_para:
                            anchor.end_para_id = None
                            anchor.end_offset = len(start_para.plain_text)
            else:
                # Single-paragraph anchor on deleted paragraph
                if anchor.para_id == para_id:
                    if next_para:
                        # Migrate to start of next paragraph
                        anchor.para_id = next_para.para_id
                        anchor.start_offset = 0
                        anchor.end_offset = 0
                    elif prev_para:
                        # Migrate to end of previous paragraph
                        anchor.para_id = prev_para.para_id
                        anchor.start_offset = len(prev_para.plain_text)
                        anchor.end_offset = len(prev_para.plain_text)
                    # If neither exists, anchor becomes orphaned (document would be empty)
    
    def split_paragraph(
        self,
        para_id: str,
        split_position: int,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Split a paragraph at a given position.
        
        The text after split_position is moved to a new paragraph.
        
        Args:
            para_id: ID of the paragraph to split
            split_position: Character position where to split
            author: Author of the change
            track_change: Whether to create tracked changes
            thread_id: Comment thread that initiated this change
            
        Returns:
            ID of the new paragraph (containing text after split), or None if failed
        """
        paragraph = self.get_paragraph(para_id)
        if not paragraph:
            return None
        
        original_text = paragraph.plain_text
        
        # Validate split position
        if split_position <= 0 or split_position >= len(original_text):
            return None  # Can't split at very beginning or end
        
        # Get text for new paragraph
        text_before = original_text[:split_position]
        text_after = original_text[split_position:]
        
        # Generate IDs for new paragraph
        existing_para_ids = set(p.para_id for p in self.body.iter_paragraphs())
        existing_text_ids = set()  # text_ids are not easily accessible, generate fresh
        new_para_id = generate_valid_para_id(existing_para_ids)
        new_text_id = generate_hex_id(existing_text_ids)
        
        # Migrate anchors BEFORE modifying paragraphs
        self._migrate_anchors_for_split_paragraph(para_id, split_position, new_para_id)
        
        # Modify original paragraph - remove text after split
        # We do this by replacing the entire text with text_before
        paragraph.runs = [Run(text=text_before)] if text_before else []
        paragraph.invalidate_cache()  # Clear cached plain_text
        
        # Create new paragraph with text_after
        new_paragraph = Paragraph(
            para_id=new_para_id,
            text_id=new_text_id,
            runs=[Run(text=text_after)] if text_after else [],
            index=0  # Will be set by insert_element_at
        )
        
        # Insert new paragraph after original
        original_index = self.body.get_element_index(para_id)
        self.body.insert_element_at(original_index + 1, new_paragraph)
        
        # Track changes if requested
        if track_change:
            # The split creates a revision showing the paragraph was modified
            # Note: Word doesn't have a native "split" revision, so we represent it
            # as a deletion of the split-off text from the original paragraph
            self.revisions.add_deletion(
                para_id=para_id,
                start=split_position,
                end=len(original_text),
                original_text=text_after,
                author=author,
                timestamp=datetime.now(),
                thread_id=thread_id
            )
            # And an insertion of the new paragraph
            self.revisions.add_insertion(
                para_id=new_para_id,
                position=0,
                text=text_after,
                author=author,
                timestamp=datetime.now(),
                thread_id=thread_id
            )
        
        self.is_dirty = True
        self.modified_at = datetime.now()
        
        return new_para_id
    
    def _migrate_anchors_for_split_paragraph(
        self,
        para_id: str,
        split_position: int,
        new_para_id: str
    ) -> None:
        """
        Migrate comment anchors when a paragraph is split.
        
        Rules (using exclusive end convention):
        - Anchors entirely before split (end_offset <= split_position): stay in A, no change
        - Anchors entirely after split (start_offset >= split_position): migrate to B, 
          adjust offsets by subtracting split_position
        - Anchors spanning split (start_offset < split_position < end_offset): 
          convert to multi-paragraph anchor with end_para_id = B
        
        Args:
            para_id: ID of the paragraph being split
            split_position: Character position where the split occurs
            new_para_id: ID of the new paragraph (containing text after split)
        """
        for comment in self.comments.comments.values():
            if not comment.anchor:
                continue
            
            anchor = comment.anchor
            
            # Only process anchors on the paragraph being split
            # Handle single-paragraph anchors
            if anchor.para_id == para_id and not anchor.spans_paragraphs:
                if anchor.end_offset <= split_position:
                    # Entirely before split - no change needed
                    pass
                elif anchor.start_offset >= split_position:
                    # Entirely after split - migrate to new paragraph
                    anchor.para_id = new_para_id
                    anchor.start_offset -= split_position
                    anchor.end_offset -= split_position
                else:
                    # Spans the split point - convert to multi-paragraph anchor
                    anchor.end_para_id = new_para_id
                    anchor.end_offset = anchor.end_offset - split_position
                    # start_offset stays the same (relative to original paragraph)
            
            # Handle multi-paragraph anchors where start is in the split paragraph
            elif anchor.para_id == para_id and anchor.spans_paragraphs:
                if anchor.start_offset >= split_position:
                    # Start is after split - move start to new paragraph
                    anchor.para_id = new_para_id
                    anchor.start_offset -= split_position
                # If start is before split, it stays in original paragraph
            
            # Handle multi-paragraph anchors where end is in the split paragraph
            elif anchor.end_para_id == para_id:
                if anchor.end_offset <= split_position:
                    # End is before split - stays in original paragraph, no change
                    pass
                else:
                    # End is after split - move end to new paragraph
                    anchor.end_para_id = new_para_id
                    anchor.end_offset -= split_position
    
    def merge_paragraphs(
        self,
        para_id_a: str,
        para_id_b: str,
        author: str = "Stet",
        track_change: bool = True,
        thread_id: Optional[str] = None
    ) -> bool:
        """
        Merge two adjacent paragraphs into one.
        
        The content of paragraph B is appended to paragraph A, and B is deleted.
        
        Args:
            para_id_a: ID of the first paragraph (will contain merged content)
            para_id_b: ID of the second paragraph (will be deleted)
            author: Author of the change
            track_change: Whether to create tracked changes
            thread_id: Comment thread that initiated this change
            
        Returns:
            True if successful, False otherwise
        """
        para_a = self.get_paragraph(para_id_a)
        para_b = self.get_paragraph(para_id_b)
        
        if not para_a or not para_b:
            return False
        
        # Verify they are adjacent
        idx_a = self.body.get_element_index(para_id_a)
        idx_b = self.body.get_element_index(para_id_b)
        
        if idx_b != idx_a + 1:
            return False  # Not adjacent
        
        # Get texts before merge
        text_a = para_a.plain_text
        text_b = para_b.plain_text
        len_a = len(text_a)
        
        # Migrate anchors BEFORE modifying paragraphs
        self._migrate_anchors_for_merge(para_id_a, para_id_b, len_a)
        
        # Append B's content to A
        # Simple approach: combine runs
        if para_b.runs:
            para_a.runs.extend(para_b.runs)
        para_a.invalidate_cache()  # Clear cached plain_text
        
        # Remove paragraph B
        self.body.remove_element(para_id_b)
        
        # Track changes if requested
        if track_change:
            # Represent as: B's text was deleted from B and inserted into A
            self.revisions.add_deletion(
                para_id=para_id_b,
                start=0,
                end=len(text_b),
                original_text=text_b,
                author=author,
                timestamp=datetime.now(),
                thread_id=thread_id
            )
            self.revisions.add_insertion(
                para_id=para_id_a,
                position=len_a,
                text=text_b,
                author=author,
                timestamp=datetime.now(),
                thread_id=thread_id
            )
        
        self.is_dirty = True
        self.modified_at = datetime.now()
        
        return True
    
    def _migrate_anchors_for_merge(
        self,
        para_id_a: str,
        para_id_b: str,
        len_a: int
    ) -> None:
        """
        Migrate comment anchors when two paragraphs are merged (B into A).
        
        Anchors on paragraph B are migrated to paragraph A with offsets
        adjusted by adding len_a (the length of A's text before merge).
        
        Args:
            para_id_a: ID of the paragraph receiving content
            para_id_b: ID of the paragraph being merged into A
            len_a: Length of paragraph A's text before merge
        """
        for comment in self.comments.comments.values():
            if not comment.anchor:
                continue
            
            anchor = comment.anchor
            
            # Handle single-paragraph anchors on B
            if anchor.para_id == para_id_b and not anchor.spans_paragraphs:
                # Migrate to A with adjusted offsets
                anchor.para_id = para_id_a
                anchor.start_offset += len_a
                anchor.end_offset += len_a
            
            # Handle multi-paragraph anchors
            elif anchor.spans_paragraphs:
                # If start is in B, move to A
                if anchor.para_id == para_id_b:
                    anchor.para_id = para_id_a
                    anchor.start_offset += len_a
                
                # If end is in B, move to A
                if anchor.end_para_id == para_id_b:
                    anchor.end_para_id = para_id_a
                    anchor.end_offset += len_a
                
                # Check if anchor now starts and ends in same paragraph
                if anchor.para_id == anchor.end_para_id:
                    # Collapse to single-paragraph anchor
                    anchor.end_para_id = None
    
    def add_reply(
        self,
        parent_comment_id: str,
        text: str,
        author: str,
        timestamp: Optional[datetime] = None
    ) -> Optional[Comment]:
        """
        Add a reply to an existing comment thread.
        
        Convenience method that delegates to CommentStore.
        
        Args:
            parent_comment_id: The comment to reply to
            text: Reply text
            author: Author name
            timestamp: When the reply was created (defaults to now)
            
        Returns:
            The new Comment, or None if parent not found
        """
        reply = self.comments.add_reply(
            parent_comment_id=parent_comment_id,
            text=text,
            author=author,
            timestamp=timestamp or datetime.now()
        )
        if reply:
            self.is_dirty = True
            self.modified_at = datetime.now()
        return reply
    
    def add_comment(
        self,
        para_id: str,
        start: int,
        end: int,
        text: str,
        author: str,
        timestamp: Optional[datetime] = None
    ) -> Comment:
        """
        Add a new root comment anchored to a [start, end) range in a paragraph.
        
        Convenience method that delegates to CommentStore. Validates the target
        paragraph exists and the range falls within its text.
        
        Args:
            para_id: The document paragraph to anchor to
            start: Highlight start offset (inclusive) into the paragraph's raw text
            end: Highlight end offset (exclusive)
            text: Comment text
            author: Author name
            timestamp: When the comment was created (defaults to now)
        
        Returns:
            The new root Comment
        
        Raises:
            ValueError: If the paragraph is missing or the range is invalid
        """
        paragraph = self.get_paragraph(para_id)
        if paragraph is None:
            raise ValueError(f"Paragraph not found: {para_id}")
        
        text_len = len(paragraph.raw_text)
        if not (0 <= start <= end <= text_len):
            raise ValueError(
                f"Invalid comment range [{start}, {end}) for paragraph {para_id} "
                f"(length {text_len})"
            )
        
        comment = self.comments.add_comment_at(
            para_id=para_id,
            start=start,
            end=end,
            text=text,
            author=author,
            timestamp=timestamp or datetime.now(),
        )
        self.is_dirty = True
        self.modified_at = datetime.now()
        return comment
    
    def remove_comment(self, comment_id: str) -> bool:
        """
        Remove a comment (and, for a root, its whole thread).
        
        Convenience method that delegates to CommentStore.
        
        Returns:
            True if a comment was removed, False if the id was unknown.
        """
        removed = self.comments.remove_comment(comment_id)
        if removed:
            self.is_dirty = True
            self.modified_at = datetime.now()
        return removed
    
    def get_thread(self, thread_id: str):
        """Get a comment thread by ID."""
        return self.comments.get_thread(thread_id)
    
    def get_unresolved_threads(self):
        """Get all unresolved comment threads."""
        return self.comments.get_unresolved_threads()
    
    def get_context_paragraphs(
        self,
        para_id: str,
        before: int = 2,
        after: int = 2
    ) -> List[Paragraph]:
        """
        Get paragraphs around a target paragraph for context.
        
        Args:
            para_id: The target paragraph's ID
            before: Number of paragraphs to include before
            after: Number of paragraphs to include after
            
        Returns:
            List of paragraphs in order, including the target
        """
        target_idx = self.body.get_paragraph_index(para_id)
        if target_idx < 0:
            return []
        
        result = []
        start = max(0, target_idx - before)
        end = target_idx + after + 1
        
        current_idx = 0
        for para in self.body.iter_paragraphs():
            if start <= current_idx < end:
                result.append(para)
            current_idx += 1
            if current_idx >= end:
                break
        
        return result
    
    @property
    def paragraph_count(self) -> int:
        """Total number of paragraphs in the document."""
        return self.body.paragraph_count
    
    @property
    def comment_count(self) -> int:
        """Total number of comments."""
        return self.comments.comment_count
    
    @property
    def thread_count(self) -> int:
        """Number of comment threads."""
        return self.comments.thread_count
    
    @property
    def revision_count(self) -> int:
        """Number of tracked changes."""
        return self.revisions.revision_count
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the entire model to a dictionary.
        
        This enables session persistence by converting the model to JSON-compatible format.
        """
        return {
            'source_path': str(self.source_path) if self.source_path else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
            'body': self.body.to_dict(),
            'comments': self.comments.to_dict(),
            'revisions': self.revisions.to_dict(),
            'styles': self.styles.to_dict(),
            'properties': self.properties.to_dict(),
            'is_dirty': self.is_dirty,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentModel':
        """
        Deserialize a model from a dictionary.
        
        Args:
            data: Dictionary from to_dict()
            
        Returns:
            Reconstructed DocumentModel
        """
        created_at = None
        if data.get('created_at'):
            created_at = datetime.fromisoformat(data['created_at'])
        modified_at = None
        if data.get('modified_at'):
            modified_at = datetime.fromisoformat(data['modified_at'])
        source_path = None
        if data.get('source_path'):
            source_path = Path(data['source_path'])
        
        model = cls(
            source_path=source_path,
            created_at=created_at,
            modified_at=modified_at,
            body=DocumentBody.from_dict(data.get('body', {})),
            comments=CommentStore.from_dict(data.get('comments', {})),
            revisions=RevisionStore.from_dict(data.get('revisions', {})),
            styles=StyleStore.from_dict(data.get('styles', {})),
            properties=DocumentProperties.from_dict(data.get('properties', {})),
            is_dirty=data.get('is_dirty', False),
        )
        return model
