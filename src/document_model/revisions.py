"""
Track changes (revision) data structures for the Document Model.

Handles both existing revisions in the document and new revisions created by Stet.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Any

from .paragraph import RunFormatting, RevisionType


@dataclass
class Revision:
    """
    A single tracked change.
    
    Represents an insertion, deletion, or formatting change tracked in the document.
    """
    revision_id: str                    # w:id in the XML
    revision_type: RevisionType
    
    # Location
    para_id: str                        # Paragraph containing this revision
    start_offset: int                   # Character offset (in paragraph)
    end_offset: int                     # Character offset (in paragraph)
    
    # Content
    text: str = ""                      # Inserted text or deleted text
    formatting: Optional[RunFormatting] = None  # For insertions with formatting
    original_formatting: Optional[RunFormatting] = None  # For formatting changes
    
    # Metadata
    author: str = ""
    timestamp: Optional[datetime] = None
    
    # Thread tracking (for thread-aware revision context)
    thread_id: Optional[str] = None        # Which comment thread initiated this revision
    
    # State
    is_accepted: bool = False
    is_rejected: bool = False
    
    @property
    def length(self) -> int:
        """Length of the text affected by this revision."""
        return len(self.text)
    
    @property
    def is_pending(self) -> bool:
        """Is this revision still pending (not accepted or rejected)?"""
        return not self.is_accepted and not self.is_rejected
    
    def shift(self, offset: int, after_position: int) -> None:
        """
        Shift revision positions after an edit.
        
        Args:
            offset: Amount to shift (positive for insert, negative for delete)
            after_position: Only shift positions >= this value
        """
        if self.start_offset >= after_position:
            self.start_offset = max(0, self.start_offset + offset)
        if self.end_offset >= after_position:
            self.end_offset = max(self.start_offset, self.end_offset + offset)
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'revision_id': self.revision_id,
            'revision_type': self.revision_type.value,
            'para_id': self.para_id,
            'start_offset': self.start_offset,
            'end_offset': self.end_offset,
            'text': self.text,
            'formatting': self.formatting.to_dict() if self.formatting else None,
            'original_formatting': self.original_formatting.to_dict() if self.original_formatting else None,
            'author': self.author,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'thread_id': self.thread_id,
            'is_accepted': self.is_accepted,
            'is_rejected': self.is_rejected,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Revision':
        """Deserialize from dictionary."""
        from .paragraph import RunFormatting
        formatting = None
        if data.get('formatting'):
            formatting = RunFormatting.from_dict(data['formatting'])
        original_formatting = None
        if data.get('original_formatting'):
            original_formatting = RunFormatting.from_dict(data['original_formatting'])
        timestamp = None
        if data.get('timestamp'):
            timestamp = datetime.fromisoformat(data['timestamp'])
        return cls(
            revision_id=data.get('revision_id', ''),
            revision_type=RevisionType(data.get('revision_type', 'insertion')),
            para_id=data.get('para_id', ''),
            start_offset=data.get('start_offset', 0),
            end_offset=data.get('end_offset', 0),
            text=data.get('text', ''),
            formatting=formatting,
            original_formatting=original_formatting,
            author=data.get('author', ''),
            timestamp=timestamp,
            thread_id=data.get('thread_id'),
            is_accepted=data.get('is_accepted', False),
            is_rejected=data.get('is_rejected', False),
        )


@dataclass
class RevisionStore:
    """
    Manages tracked changes (insertions, deletions, formatting changes).
    
    Handles both:
    - Existing revisions already in the document
    - New revisions created by Stet
    """
    # All revisions by revision_id
    revisions: Dict[str, Revision] = field(default_factory=dict)
    
    # Index by paragraph for fast lookup
    _by_para_id: Dict[str, List[Revision]] = field(default_factory=dict)
    
    # Index by thread_id for fast lookup
    _by_thread_id: Dict[str, List[Revision]] = field(default_factory=dict)
    
    # ID generator state
    _next_revision_id: int = 0
    
    # Settings
    track_changes_enabled: bool = True
    default_author: str = "Stet"
    
    def _generate_revision_id(self) -> str:
        """Generate the next revision ID."""
        self._next_revision_id += 1
        return str(self._next_revision_id)
    
    def _ensure_starts_after_existing(self) -> None:
        """Ensure our ID counter starts after any existing revision IDs."""
        for rev_id in self.revisions.keys():
            try:
                existing_id = int(rev_id)
                if existing_id >= self._next_revision_id:
                    self._next_revision_id = existing_id + 1
            except ValueError:
                pass
    
    def add_revision(self, revision: Revision) -> None:
        """
        Add a revision to the store.
        
        Updates indices for fast lookup.
        """
        self.revisions[revision.revision_id] = revision
        
        # Update paragraph index
        if revision.para_id not in self._by_para_id:
            self._by_para_id[revision.para_id] = []
        self._by_para_id[revision.para_id].append(revision)
        
        # Update thread index
        if revision.thread_id:
            if revision.thread_id not in self._by_thread_id:
                self._by_thread_id[revision.thread_id] = []
            self._by_thread_id[revision.thread_id].append(revision)
        
        # Update ID counter if needed
        try:
            rev_id = int(revision.revision_id)
            if rev_id >= self._next_revision_id:
                self._next_revision_id = rev_id + 1
        except ValueError:
            pass
    
    def add_insertion(
        self,
        para_id: str,
        position: int,
        text: str,
        author: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        formatting: Optional[RunFormatting] = None,
        thread_id: Optional[str] = None
    ) -> Revision:
        """
        Record a text insertion as a tracked change.
        
        Args:
            para_id: Paragraph where insertion occurs
            position: Character offset where text is inserted
            text: The inserted text
            author: Author of the change (uses default_author if not provided)
            timestamp: When the change was made (uses now if not provided)
            formatting: Formatting for the inserted text
            thread_id: Comment thread that initiated this revision
            
        Returns:
            The created Revision
        """
        revision = Revision(
            revision_id=self._generate_revision_id(),
            revision_type=RevisionType.INSERTION,
            para_id=para_id,
            start_offset=position,
            end_offset=position + len(text),
            text=text,
            formatting=formatting,
            author=author or self.default_author,
            timestamp=timestamp or datetime.now(),
            thread_id=thread_id
        )
        self.add_revision(revision)
        return revision
    
    def add_deletion(
        self,
        para_id: str,
        start: int,
        end: int,
        original_text: str,
        author: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        thread_id: Optional[str] = None
    ) -> Revision:
        """
        Record a text deletion as a tracked change.
        
        Args:
            para_id: Paragraph where deletion occurs
            start: Start character offset
            end: End character offset
            original_text: The text being deleted
            author: Author of the change (uses default_author if not provided)
            timestamp: When the change was made (uses now if not provided)
            thread_id: Comment thread that initiated this revision
            
        Returns:
            The created Revision
        """
        revision = Revision(
            revision_id=self._generate_revision_id(),
            revision_type=RevisionType.DELETION,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
            text=original_text,
            author=author or self.default_author,
            timestamp=timestamp or datetime.now(),
            thread_id=thread_id
        )
        self.add_revision(revision)
        return revision
    
    def add_formatting_change(
        self,
        para_id: str,
        start: int,
        end: int,
        new_formatting: RunFormatting,
        original_formatting: RunFormatting,
        author: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        thread_id: Optional[str] = None
    ) -> Revision:
        """
        Record a formatting change as a tracked change.
        
        Args:
            para_id: Paragraph where formatting changes
            start: Start character offset
            end: End character offset
            new_formatting: The new formatting
            original_formatting: The original formatting (for undo)
            author: Author of the change
            timestamp: When the change was made
            thread_id: Comment thread that initiated this revision
            
        Returns:
            The created Revision
        """
        revision = Revision(
            revision_id=self._generate_revision_id(),
            revision_type=RevisionType.FORMATTING,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
            formatting=new_formatting,
            original_formatting=original_formatting,
            author=author or self.default_author,
            timestamp=timestamp or datetime.now(),
            thread_id=thread_id
        )
        self.add_revision(revision)
        return revision
    
    def get_revision(self, revision_id: str) -> Optional[Revision]:
        """Get a revision by its ID."""
        return self.revisions.get(revision_id)
    
    def get_revisions_in_paragraph(self, para_id: str) -> List[Revision]:
        """Get all revisions affecting a paragraph."""
        return self._by_para_id.get(para_id, [])
    
    def get_pending_revisions(self) -> List[Revision]:
        """Get all revisions that are not yet accepted or rejected."""
        return [r for r in self.revisions.values() if r.is_pending]
    
    def get_revisions_by_author(self, author: str) -> List[Revision]:
        """Get all revisions by a specific author."""
        return [r for r in self.revisions.values() if r.author == author]
    
    def get_revisions_by_thread(self, thread_id: str) -> List[Revision]:
        """Get all revisions created by a specific comment thread."""
        return self._by_thread_id.get(thread_id, [])
    
    def get_revisions_excluding_thread(self, thread_id: str) -> List[Revision]:
        """Get all revisions NOT created by a specific comment thread."""
        return [r for r in self.revisions.values() if r.thread_id != thread_id]
    
    def get_revisions_for_paragraph_excluding_thread(
        self, 
        para_id: str, 
        thread_id: str
    ) -> List[Revision]:
        """Get revisions for a paragraph, excluding those from a specific thread."""
        para_revisions = self._by_para_id.get(para_id, [])
        return [r for r in para_revisions if r.thread_id != thread_id]
    
    def accept_revision(self, revision_id: str) -> bool:
        """
        Accept a revision (make it permanent).
        
        Returns True if successful, False if revision not found.
        """
        revision = self.get_revision(revision_id)
        if not revision:
            return False
        
        revision.is_accepted = True
        revision.is_rejected = False
        return True
    
    def reject_revision(self, revision_id: str) -> bool:
        """
        Reject a revision (undo the change).
        
        Returns True if successful, False if revision not found.
        """
        revision = self.get_revision(revision_id)
        if not revision:
            return False
        
        revision.is_rejected = True
        revision.is_accepted = False
        return True
    
    def accept_all(self) -> int:
        """Accept all pending revisions. Returns count of accepted revisions."""
        count = 0
        for revision in self.revisions.values():
            if revision.is_pending:
                revision.is_accepted = True
                count += 1
        return count
    
    def reject_all(self) -> int:
        """Reject all pending revisions. Returns count of rejected revisions."""
        count = 0
        for revision in self.revisions.values():
            if revision.is_pending:
                revision.is_rejected = True
                count += 1
        return count
    
    @property
    def revision_count(self) -> int:
        """Total number of revisions."""
        return len(self.revisions)
    
    @property
    def pending_count(self) -> int:
        """Number of pending revisions."""
        return sum(1 for r in self.revisions.values() if r.is_pending)
    
    def get_max_revision_id(self) -> int:
        """Get the maximum revision ID currently in use."""
        max_id = 0
        for rev_id in self.revisions.keys():
            try:
                id_num = int(rev_id)
                max_id = max(max_id, id_num)
            except ValueError:
                pass
        return max_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'revisions': {k: v.to_dict() for k, v in self.revisions.items()},
            '_next_revision_id': self._next_revision_id,
            'track_changes_enabled': self.track_changes_enabled,
            'default_author': self.default_author,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RevisionStore':
        """Deserialize from dictionary."""
        store = cls()
        store._next_revision_id = data.get('_next_revision_id', 0)
        store.track_changes_enabled = data.get('track_changes_enabled', True)
        store.default_author = data.get('default_author', 'Stet')
        # Deserialize revisions
        for rev_id, rev_data in data.get('revisions', {}).items():
            revision = Revision.from_dict(rev_data)
            store.revisions[rev_id] = revision
            # Update paragraph index
            if revision.para_id not in store._by_para_id:
                store._by_para_id[revision.para_id] = []
            store._by_para_id[revision.para_id].append(revision)
            # Update thread index
            if revision.thread_id:
                if revision.thread_id not in store._by_thread_id:
                    store._by_thread_id[revision.thread_id] = []
                store._by_thread_id[revision.thread_id].append(revision)
        return store
