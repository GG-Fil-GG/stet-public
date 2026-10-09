"""
Comment system data structures for the Document Model.

Handles the complexity of Word's 4-file comment system:
- comments.xml: Comment content
- commentsExtended.xml: Threading (paraIdParent)
- commentsIds.xml: Durable IDs
- commentsExtensible.xml: UTC timestamps
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Set

from .utils import generate_valid_para_id, generate_hex_id, generate_comment_id


def _normalize_datetime_for_sort(dt: Optional[datetime]) -> datetime:
    """
    Normalize a datetime for safe comparison/sorting.
    
    Handles the case where some datetimes are offset-aware (have timezone info)
    and others are offset-naive. Python can't compare these directly.
    
    Returns a naive datetime in UTC for offset-aware dates, or the original
    for naive dates. Returns datetime.min if dt is None.
    """
    if dt is None:
        return datetime.min
    
    # If offset-aware, convert to naive UTC
    if dt.tzinfo is not None:
        # Replace timezone info, effectively treating it as naive
        return dt.replace(tzinfo=None)
    
    return dt


@dataclass
class CommentParagraph:
    """
    A paragraph within a comment's content.
    
    Comments can contain multiple paragraphs with their own formatting.
    """
    para_id: str          # Each paragraph in a comment has its own paraId
    text: str
    # Could add formatting later if needed
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'para_id': self.para_id,
            'text': self.text,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CommentParagraph':
        """Deserialize from dictionary."""
        return cls(
            para_id=data.get('para_id', ''),
            text=data.get('text', ''),
        )


@dataclass
class CommentAnchor:
    """
    Defines where a comment is anchored in the document.
    
    In document.xml, this corresponds to:
    - <w:commentRangeStart w:id="X"/>
    - ... text ...
    - <w:commentRangeEnd w:id="X"/>
    - <w:commentReference w:id="X"/>
    
    We store this as character offsets for easier manipulation.
    """
    comment_id: str
    
    # Location (paragraph-relative)
    para_id: str              # Paragraph containing the anchor start
    start_offset: int         # Character offset where highlight starts
    end_offset: int           # Character offset where highlight ends
    
    # For multi-paragraph anchors (rare but possible)
    end_para_id: Optional[str] = None  # If anchor spans paragraphs
    
    @property
    def is_collapsed(self) -> bool:
        """Is this a zero-width anchor (cursor position)?"""
        return self.start_offset == self.end_offset and self.end_para_id is None
    
    @property
    def spans_paragraphs(self) -> bool:
        """Does this anchor span multiple paragraphs?"""
        return self.end_para_id is not None and self.end_para_id != self.para_id
    
    def shift(self, offset: int, after_position: int) -> None:
        """
        Shift anchor positions after an edit.
        
        Called when text is inserted/deleted before or within the anchor.
        
        Args:
            offset: Amount to shift (positive for insert, negative for delete)
            after_position: Only shift positions > this value
                           (positions AT the edit point are NOT shifted)
        
        Note: For REPLACE operations, the anchor start AT the edit position
        should NOT shift, only the end (and positions after).
        """
        # Start only shifts if AFTER the edit position (not at it)
        if self.start_offset > after_position:
            self.start_offset = max(0, self.start_offset + offset)
        # End shifts if AT or AFTER the edit position
        if self.end_offset > after_position:
            self.end_offset = max(self.start_offset, self.end_offset + offset)
    
    def contains_offset(self, offset: int) -> bool:
        """Check if a character offset falls within this anchor."""
        return self.start_offset <= offset < self.end_offset
    
    def copy(self) -> 'CommentAnchor':
        """Create a copy of this anchor."""
        return CommentAnchor(
            comment_id=self.comment_id,
            para_id=self.para_id,
            start_offset=self.start_offset,
            end_offset=self.end_offset,
            end_para_id=self.end_para_id
        )
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'comment_id': self.comment_id,
            'para_id': self.para_id,
            'start_offset': self.start_offset,
            'end_offset': self.end_offset,
            'end_para_id': self.end_para_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CommentAnchor':
        """Deserialize from dictionary."""
        return cls(
            comment_id=data.get('comment_id', ''),
            para_id=data.get('para_id', ''),
            start_offset=data.get('start_offset', 0),
            end_offset=data.get('end_offset', 0),
            end_para_id=data.get('end_para_id'),
        )


@dataclass
class Comment:
    """
    A single comment in the document.
    
    Maps to <w:comment> in comments.xml plus related entries in the
    auxiliary comment XML files.
    
    ID Constraints (validated 2026-02-16):
    - para_id: First char MUST be 0-7 (Word rejects 8-F as signed int overflow)
    - text_id, durable_id, rsid: NO constraint (full 0-F range works)
    - comment_id: Integer, no specific constraint
    """
    # Primary identity (from comments.xml)
    comment_id: str           # w:id attribute (integer as string)
    para_id: str              # w14:paraId (8-char hex, first char 0-7!)
    
    # Content
    text: str                 # Plain text of comment
    paragraphs: List[CommentParagraph] = field(default_factory=list)
    
    # Metadata
    author: str = ""
    author_initials: str = ""
    date: Optional[datetime] = None         # Local time (from w:date)
    date_utc: Optional[datetime] = None     # UTC time (from commentsExtensible.xml)
    
    # Threading (from commentsExtended.xml)
    parent_para_id: Optional[str] = None    # w15:paraIdParent - None if root comment
    is_resolved: bool = False               # w15:done
    
    # Durable identity (from commentsIds.xml)
    durable_id: str = ""                    # w16cid:durableId (no constraint)
    
    # Additional IDs
    text_id: str = ""                       # w14:textId (no constraint)
    rsid: str = ""                          # w:rsidR (no constraint)
    
    # Anchor in document (from document.xml)
    anchor: Optional[CommentAnchor] = None
    
    @property
    def is_root(self) -> bool:
        """Is this a root comment (not a reply)?"""
        return self.parent_para_id is None
    
    @property
    def is_reply(self) -> bool:
        """Is this a reply to another comment?"""
        return self.parent_para_id is not None
    
    def __hash__(self):
        """Allow using Comment in sets."""
        return hash(self.comment_id)
    
    def __eq__(self, other):
        """Equality based on comment_id."""
        if not isinstance(other, Comment):
            return False
        return self.comment_id == other.comment_id
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'comment_id': self.comment_id,
            'para_id': self.para_id,
            'text': self.text,
            'paragraphs': [p.to_dict() for p in self.paragraphs],
            'author': self.author,
            'author_initials': self.author_initials,
            'date': self.date.isoformat() if self.date else None,
            'date_utc': self.date_utc.isoformat() if self.date_utc else None,
            'parent_para_id': self.parent_para_id,
            'is_resolved': self.is_resolved,
            'durable_id': self.durable_id,
            'text_id': self.text_id,
            'rsid': self.rsid,
            'anchor': self.anchor.to_dict() if self.anchor else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Comment':
        """Deserialize from dictionary."""
        date = None
        if data.get('date'):
            date = datetime.fromisoformat(data['date'])
        date_utc = None
        if data.get('date_utc'):
            date_utc = datetime.fromisoformat(data['date_utc'])
        anchor = None
        if data.get('anchor'):
            anchor = CommentAnchor.from_dict(data['anchor'])
        return cls(
            comment_id=data.get('comment_id', ''),
            para_id=data.get('para_id', ''),
            text=data.get('text', ''),
            paragraphs=[CommentParagraph.from_dict(p) for p in data.get('paragraphs', [])],
            author=data.get('author', ''),
            author_initials=data.get('author_initials', ''),
            date=date,
            date_utc=date_utc,
            parent_para_id=data.get('parent_para_id'),
            is_resolved=data.get('is_resolved', False),
            durable_id=data.get('durable_id', ''),
            text_id=data.get('text_id', ''),
            rsid=data.get('rsid', ''),
            anchor=anchor,
        )


@dataclass
class CommentThread:
    """
    A thread of comments (root + replies).
    
    Convenience structure for working with comment threads.
    Word uses FLAT threading: all replies point to the root's paraId,
    not to each other (no nested replies).
    """
    thread_id: str                # Same as root comment's comment_id
    root: Comment                 # The original comment
    replies: List[Comment] = field(default_factory=list)
    
    @property
    def all_comments(self) -> List[Comment]:
        """All comments in thread order (root first, then replies by date)."""
        return [self.root] + self.replies
    
    @property
    def latest_comment(self) -> Comment:
        """Most recent comment in thread."""
        return self.replies[-1] if self.replies else self.root
    
    @property
    def reply_count(self) -> int:
        """Number of replies in this thread."""
        return len(self.replies)
    
    @property
    def is_resolved(self) -> bool:
        """Is this thread marked as resolved?"""
        return self.root.is_resolved
    
    def get_anchor_text(self, paragraph_text: str) -> str:
        """
        Get the text this thread's anchor highlights.
        
        Args:
            paragraph_text: The full text of the anchored paragraph
            
        Returns:
            The highlighted portion of the text
        """
        if self.root.anchor:
            return paragraph_text[self.root.anchor.start_offset:self.root.anchor.end_offset]
        return ""
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'thread_id': self.thread_id,
            'root': self.root.to_dict(),
            'replies': [r.to_dict() for r in self.replies],
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CommentThread':
        """Deserialize from dictionary."""
        return cls(
            thread_id=data.get('thread_id', ''),
            root=Comment.from_dict(data.get('root', {})),
            replies=[Comment.from_dict(r) for r in data.get('replies', [])],
        )


@dataclass
class CommentStore:
    """
    Manages all comments and their relationships.
    
    Handles the complexity of Word's 4-file comment system and provides
    a clean interface for working with comments and threads.
    """
    # All comments by comment_id
    comments: Dict[str, Comment] = field(default_factory=dict)
    
    # Threading structure (thread_id → CommentThread)
    threads: Dict[str, CommentThread] = field(default_factory=dict)
    
    # Index by para_id for fast lookup
    _by_para_id: Dict[str, Comment] = field(default_factory=dict)
    
    # ID tracking for collision avoidance
    _existing_para_ids: Set[str] = field(default_factory=set)
    _existing_durable_ids: Set[str] = field(default_factory=set)
    _existing_text_ids: Set[str] = field(default_factory=set)
    _existing_comment_ids: Set[int] = field(default_factory=set)
    _existing_rsids: Set[str] = field(default_factory=set)
    
    def add_comment(self, comment: Comment) -> None:
        """
        Add a comment to the store.
        
        Also updates threading relationships and indices.
        """
        self.comments[comment.comment_id] = comment
        self._by_para_id[comment.para_id] = comment
        
        # Track IDs for collision avoidance
        self._existing_para_ids.add(comment.para_id)
        if comment.durable_id:
            self._existing_durable_ids.add(comment.durable_id)
        if comment.text_id:
            self._existing_text_ids.add(comment.text_id)
        if comment.rsid:
            self._existing_rsids.add(comment.rsid)
        try:
            self._existing_comment_ids.add(int(comment.comment_id))
        except ValueError:
            pass
        
        # Update threading
        if comment.is_root:
            self.threads[comment.comment_id] = CommentThread(
                thread_id=comment.comment_id,
                root=comment
            )
        else:
            # Find the thread this reply belongs to
            parent = self._by_para_id.get(comment.parent_para_id)
            if parent:
                thread = self.get_thread_for_comment(parent.comment_id)
                if thread:
                    thread.replies.append(comment)
                    # Sort replies by date
                    thread.replies.sort(key=lambda c: _normalize_datetime_for_sort(c.date))
    
    def get_comment(self, comment_id: str) -> Optional[Comment]:
        """Get comment by its w:id."""
        return self.comments.get(comment_id)
    
    def get_comment_by_para_id(self, para_id: str) -> Optional[Comment]:
        """Get comment by its paraId."""
        return self._by_para_id.get(para_id)
    
    def get_thread(self, thread_id: str) -> Optional[CommentThread]:
        """Get thread by thread_id (same as root comment_id)."""
        return self.threads.get(thread_id)
    
    def get_thread_for_comment(self, comment_id: str) -> Optional[CommentThread]:
        """Find the thread a comment belongs to."""
        comment = self.get_comment(comment_id)
        if not comment:
            return None
        
        if comment.is_root:
            return self.threads.get(comment.comment_id)
        
        # It's a reply - find the root via parent_para_id
        parent = self._by_para_id.get(comment.parent_para_id)
        if parent:
            # In flat threading, parent is always the root
            return self.threads.get(parent.comment_id)
        
        return None
    
    def get_comments_for_paragraph(self, para_id: str) -> List[Comment]:
        """Get all comments anchored to a paragraph."""
        return [
            c for c in self.comments.values()
            if c.anchor and c.anchor.para_id == para_id
        ]
    
    def get_unresolved_threads(self) -> List[CommentThread]:
        """Get all threads that are not resolved."""
        return [t for t in self.threads.values() if not t.is_resolved]
    
    def get_resolved_threads(self) -> List[CommentThread]:
        """Get all threads that are resolved."""
        return [t for t in self.threads.values() if t.is_resolved]
    
    def add_reply(
        self,
        parent_comment_id: str,
        text: str,
        author: str,
        timestamp: datetime,
        author_initials: Optional[str] = None
    ) -> Optional[Comment]:
        """
        Add a reply to an existing comment.
        
        Handles all the complexity:
        - Generates new IDs (comment_id, para_id, durable_id, text_id, rsid)
        - CRITICAL: para_id must use constrained generation (first char 0-7)
        - Other hex IDs (durable_id, text_id, rsid) can use full 0-F range
        - Sets up threading relationship (paraIdParent points to ROOT)
        
        Note: Replies do NOT have anchors in document.xml. They are only
        linked to their parent via paraIdParent in commentsExtended.xml.
        
        Args:
            parent_comment_id: The comment_id to reply to
            text: The reply text
            author: Author name
            timestamp: When the reply was created
            author_initials: Author initials (derived from author if not provided)
            
        Returns:
            The new Comment, or None if parent not found
        """
        thread = self.get_thread_for_comment(parent_comment_id)
        if not thread:
            return None
        
        # Generate IDs with collision checking
        new_comment_id = generate_comment_id(self._existing_comment_ids)
        new_para_id = generate_valid_para_id(self._existing_para_ids)
        new_durable_id = generate_hex_id(self._existing_durable_ids)
        new_text_id = generate_hex_id(self._existing_text_ids)
        new_rsid = generate_hex_id(self._existing_rsids)
        
        # IMPORTANT: Replies do NOT have anchors in document.xml
        # They are only linked via paraIdParent in commentsExtended.xml
        # So we leave anchor as None for replies
        new_anchor = None
        
        # Create initials if not provided
        if not author_initials:
            parts = author.split()
            author_initials = ''.join(p[0].upper() for p in parts if p)
        
        # Create the reply comment
        reply = Comment(
            comment_id=new_comment_id,
            para_id=new_para_id,
            text=text,
            paragraphs=[CommentParagraph(para_id=new_para_id, text=text)],
            author=author,
            author_initials=author_initials,
            date=timestamp,
            date_utc=timestamp,  # Assuming timestamp is already UTC or local as appropriate
            parent_para_id=thread.root.para_id,  # FLAT threading: always point to root
            is_resolved=False,
            durable_id=new_durable_id,
            text_id=new_text_id,
            rsid=new_rsid,
            anchor=new_anchor
        )
        
        self.add_comment(reply)
        return reply
    
    def add_comment_at(
        self,
        para_id: str,
        start: int,
        end: int,
        text: str,
        author: str,
        timestamp: datetime,
        author_initials: Optional[str] = None
    ) -> Comment:
        """
        Add a NEW root comment anchored to a character range in a paragraph.

        Creates a single-comment thread. The anchor highlights the precise
        [start, end) character range within ``para_id`` (a document body
        paragraph). Generates all required IDs.

        Args:
            para_id: The document paragraph the comment anchors to.
            start: Character offset where the highlight starts (inclusive).
            end: Character offset where the highlight ends (exclusive).
            text: The comment text.
            author: Author name.
            timestamp: When the comment was created.
            author_initials: Initials (derived from author if not provided).

        Returns:
            The new root Comment.
        """
        new_comment_id = generate_comment_id(self._existing_comment_ids)
        new_para_id = generate_valid_para_id(self._existing_para_ids)
        new_durable_id = generate_hex_id(self._existing_durable_ids)
        new_text_id = generate_hex_id(self._existing_text_ids)
        new_rsid = generate_hex_id(self._existing_rsids)

        if not author_initials:
            parts = author.split()
            author_initials = ''.join(p[0].upper() for p in parts if p)

        # Anchor references the target document paragraph (para_id), while the
        # comment's own paragraph (new_para_id) lives in comments.xml.
        anchor = CommentAnchor(
            comment_id=new_comment_id,
            para_id=para_id,
            start_offset=start,
            end_offset=end,
        )

        comment = Comment(
            comment_id=new_comment_id,
            para_id=new_para_id,
            text=text,
            paragraphs=[CommentParagraph(para_id=new_para_id, text=text)],
            author=author,
            author_initials=author_initials,
            date=timestamp,
            date_utc=timestamp,
            parent_para_id=None,  # root comment
            is_resolved=False,
            durable_id=new_durable_id,
            text_id=new_text_id,
            rsid=new_rsid,
            anchor=anchor,
        )

        self.add_comment(comment)
        return comment

    def remove_comment(self, comment_id: str) -> bool:
        """
        Remove a comment from the store.

        Removing a ROOT comment removes the entire thread (root + all replies);
        removing a REPLY removes only that reply. Mirrors Word's behavior.

        Returns:
            True if a comment was removed, False if the id was unknown.
        """
        comment = self.comments.get(comment_id)
        if comment is None:
            return False

        def _forget(c: Comment) -> None:
            self.comments.pop(c.comment_id, None)
            if self._by_para_id.get(c.para_id) is c:
                del self._by_para_id[c.para_id]

        if comment.is_root:
            thread = self.threads.get(comment_id)
            if thread:
                for reply in list(thread.replies):
                    _forget(reply)
            _forget(comment)
            self.threads.pop(comment_id, None)
        else:
            thread = self.get_thread_for_comment(comment_id)
            _forget(comment)
            if thread:
                thread.replies = [r for r in thread.replies if r.comment_id != comment_id]

        return True

    def resolve_thread(self, thread_id: str) -> bool:
        """
        Mark a thread as resolved.
        
        Returns True if successful, False if thread not found.
        """
        thread = self.get_thread(thread_id)
        if not thread:
            return False
        thread.root.is_resolved = True
        return True
    
    def unresolve_thread(self, thread_id: str) -> bool:
        """
        Mark a thread as unresolved.
        
        Returns True if successful, False if thread not found.
        """
        thread = self.get_thread(thread_id)
        if not thread:
            return False
        thread.root.is_resolved = False
        return True
    
    @property
    def comment_count(self) -> int:
        """Total number of comments (including replies)."""
        return len(self.comments)
    
    @property
    def thread_count(self) -> int:
        """Number of comment threads (root comments only)."""
        return len(self.threads)
    
    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            'comments': {k: v.to_dict() for k, v in self.comments.items()},
            'threads': {k: v.to_dict() for k, v in self.threads.items()},
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'CommentStore':
        """Deserialize from dictionary.
        
        Threads are wired to reference the same Comment objects stored in
        store.comments, so mutating a comment via either path stays
        consistent.
        """
        store = cls()
        # Deserialize comments
        for comment_id, comment_data in data.get('comments', {}).items():
            comment = Comment.from_dict(comment_data)
            store.comments[comment_id] = comment
            store._by_para_id[comment.para_id] = comment
            # Track IDs
            store._existing_para_ids.add(comment.para_id)
            if comment.durable_id:
                store._existing_durable_ids.add(comment.durable_id)
            if comment.text_id:
                store._existing_text_ids.add(comment.text_id)
            if comment.rsid:
                store._existing_rsids.add(comment.rsid)
            try:
                store._existing_comment_ids.add(int(comment.comment_id))
            except ValueError:
                pass
        # Build threads from the already-deserialized Comment instances
        for thread_id, thread_data in data.get('threads', {}).items():
            root_id = thread_data.get('root', {}).get('comment_id', '')
            root = store.comments.get(root_id)
            if root is None:
                continue
            reply_ids = [
                r.get('comment_id', '') for r in thread_data.get('replies', [])
            ]
            replies = [
                store.comments[rid] for rid in reply_ids
                if rid in store.comments
            ]
            store.threads[thread_id] = CommentThread(
                thread_id=thread_id,
                root=root,
                replies=replies,
            )
        return store
