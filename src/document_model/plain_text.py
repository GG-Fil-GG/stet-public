"""
PlainTextView - Bidirectional mapping between DOM and plain text.

This is the KEY abstraction for LLM integration:
1. Convert DOM → plain text (for sending to LLM)
2. Track position mapping for converting back
3. Track comment ranges in plain text coordinates
4. Support preserved regions (citations, field codes)
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from .model import DocumentModel
    from .paragraph import Paragraph
    from .edits import DocumentEdit


class ScopeType(Enum):
    """How to define the scope of text to include."""
    PARA_IDS = "para_ids"           # Specific paragraph IDs
    INDEX_RANGE = "index_range"     # Range by index
    THREAD = "thread"               # Around a comment thread


@dataclass
class TextScope:
    """
    Defines what content to include in a PlainTextView.
    """
    # Method 1: Specific paragraph IDs
    para_ids: Optional[List[str]] = None
    
    # Method 2: Range by paragraph index
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    
    # Method 3: Context around a thread
    thread_id: Optional[str] = None
    context_before: int = 2
    context_after: int = 2
    
    # What to include
    include_deleted_text: bool = False   # Include text in <w:del>?
    include_tables: bool = True
    skip_ghost_paragraphs: bool = True   # Skip paragraphs with only deleted content
    
    @classmethod
    def from_para_ids(cls, para_ids: List[str], **kwargs) -> 'TextScope':
        """Create scope from specific paragraph IDs."""
        return cls(para_ids=para_ids, **kwargs)
    
    @classmethod
    def from_range(cls, start: int, end: int, **kwargs) -> 'TextScope':
        """Create scope from index range."""
        return cls(start_index=start, end_index=end, **kwargs)
    
    @classmethod
    def from_thread(
        cls, 
        thread_id: str, 
        before: int = 2, 
        after: int = 2,
        **kwargs
    ) -> 'TextScope':
        """Create scope centered on a comment thread."""
        return cls(
            thread_id=thread_id,
            context_before=before,
            context_after=after,
            **kwargs
        )


@dataclass
class DOMPosition:
    """
    A position in the DOM.
    
    Used for bidirectional mapping between plain text and DOM.
    """
    para_id: str
    para_index: int              # Index in body.elements (or flat paragraph list)
    char_offset: int             # Character offset in paragraph's plain text
    
    def __eq__(self, other):
        if not isinstance(other, DOMPosition):
            return False
        return (self.para_id == other.para_id and 
                self.para_index == other.para_index and
                self.char_offset == other.char_offset)
    
    def __hash__(self):
        return hash((self.para_id, self.para_index, self.char_offset))


@dataclass
class PreservedRegion:
    """
    A region that should be preserved verbatim (not modified by LLM).
    
    Used for citations, field codes, etc.
    """
    start_offset: int            # In plain text
    end_offset: int
    placeholder: str             # What we replace it with for LLM (e.g., "[CITATION]")
    original_content: str        # The actual content to preserve
    region_type: str             # 'citation', 'field_code', etc.


@dataclass
class CommentRange:
    """
    A comment's range in plain text coordinates.
    """
    comment_id: str
    start_offset: int
    end_offset: int
    text: str                    # The text the comment references
    
    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset


@dataclass
class PlainTextView:
    """
    A plain text representation of document content with bidirectional mapping.
    
    This is the KEY abstraction for LLM integration:
    1. Convert DOM → plain text (for sending to LLM)
    2. LLM returns edited plain text
    3. Diff the texts to find changes
    4. Map changes back to DOM positions
    5. Apply edits to DOM with proper anchor adjustment
    
    Note: Position mapping is stored as a list where index = character position.
    For efficiency with large texts, we only store positions at paragraph boundaries
    and compute within-paragraph positions on demand.
    """
    # The plain text
    text: str
    
    # Scope of what's included
    scope: TextScope
    
    # Paragraphs included (in order)
    paragraphs: List['Paragraph'] = field(default_factory=list)
    
    # Paragraph boundaries in plain text: [(start_offset, end_offset, para_id), ...]
    paragraph_boundaries: List[Tuple[int, int, str]] = field(default_factory=list)
    
    # Comment ranges in plain text coordinates
    comment_ranges: Dict[str, CommentRange] = field(default_factory=dict)
    
    # Preserved regions (citations, field codes)
    preserved_regions: List[PreservedRegion] = field(default_factory=list)
    
    # Paragraph separator (used when joining paragraphs)
    _paragraph_separator: str = "\n\n"
    
    def dom_to_plain(self, para_id: str, char_offset: int) -> int:
        """
        Convert DOM position to plain text position.
        
        Args:
            para_id: The paragraph ID
            char_offset: Character offset within the paragraph
            
        Returns:
            Character offset in the plain text, or -1 if not found
        """
        for start, end, pid in self.paragraph_boundaries:
            if pid == para_id:
                # Found the paragraph, add the offset
                return min(start + char_offset, end)
        return -1
    
    def plain_to_dom(self, plain_offset: int) -> Optional[DOMPosition]:
        """
        Convert plain text position to DOM position.
        
        Args:
            plain_offset: Character offset in plain text
            
        Returns:
            DOMPosition or None if offset is invalid
        """
        if plain_offset < 0 or plain_offset > len(self.text):
            return None
        
        for i, (start, end, para_id) in enumerate(self.paragraph_boundaries):
            if start <= plain_offset <= end:
                return DOMPosition(
                    para_id=para_id,
                    para_index=i,
                    char_offset=plain_offset - start
                )
        
        # If past all boundaries, return position at end of last paragraph
        if self.paragraph_boundaries:
            start, end, para_id = self.paragraph_boundaries[-1]
            return DOMPosition(
                para_id=para_id,
                para_index=len(self.paragraph_boundaries) - 1,
                char_offset=end - start
            )
        
        return None
    
    def get_paragraph_text(self, para_id: str) -> Optional[str]:
        """Get the plain text for a specific paragraph."""
        for start, end, pid in self.paragraph_boundaries:
            if pid == para_id:
                return self.text[start:end]
        return None
    
    def get_comment_range_text(self, comment_id: str) -> Optional[str]:
        """Get the plain text that a comment references."""
        if comment_id in self.comment_ranges:
            return self.comment_ranges[comment_id].text
        return None
    
    def get_context_parts(self) -> Tuple[str, str, str]:
        """
        Split the text into before, target, and after parts.
        
        Only works for thread-based scopes.
        
        Returns:
            Tuple of (context_before, target, context_after)
        """
        if not self.scope.thread_id:
            return "", self.text, ""
        
        # Find the thread's anchor paragraph
        thread = None
        if hasattr(self, '_model') and self._model:
            thread = self._model.comments.get_thread(self.scope.thread_id)
        
        if not thread or not thread.root.anchor:
            return "", self.text, ""
        
        anchor_para_id = thread.root.anchor.para_id
        
        # Find boundaries
        before_parts = []
        target_parts = []
        after_parts = []
        found_target = False
        passed_target = False
        
        for start, end, para_id in self.paragraph_boundaries:
            para_text = self.text[start:end]
            
            if para_id == anchor_para_id:
                found_target = True
                target_parts.append(para_text)
            elif not found_target:
                before_parts.append(para_text)
            else:
                if not passed_target:
                    passed_target = True
                after_parts.append(para_text)
        
        return (
            self._paragraph_separator.join(before_parts),
            self._paragraph_separator.join(target_parts) if target_parts else self.text,
            self._paragraph_separator.join(after_parts)
        )
    
    @property
    def paragraph_count(self) -> int:
        """Number of paragraphs in this view."""
        return len(self.paragraph_boundaries)
    
    @property 
    def char_count(self) -> int:
        """Total character count."""
        return len(self.text)
    
    def compute_edits(
        self,
        revised_text: str,
        author: str = "Stet",
        track_changes: bool = True
    ) -> List['DocumentEdit']:
        """
        Compute DOM edits from revised text.
        
        This is the key method for LLM integration:
        1. Diff the original text vs revised text
        2. Map diff operations to DOM positions
        3. Return DocumentEdit objects that can be applied to DocumentModel
        
        Args:
            revised_text: The revised text (from LLM)
            author: Author name for tracked changes
            track_changes: Whether to create tracked changes
            
        Returns:
            List of DocumentEdit objects in application order
        """
        from src.diff_utils import compute_diff, DiffOperation
        from .edits import DocumentEdit, EditType
        
        edits = []
        
        # Compute word-level diff
        diff_result = compute_diff(self.text, revised_text)
        
        if not diff_result.has_changes:
            return edits
        
        # Track current position in original text
        original_offset = 0
        
        for op in diff_result.operations:
            if op.op == DiffOperation.EQUAL:
                # No change, just advance the offset
                original_offset += len(op.text)
            
            elif op.op == DiffOperation.DELETE:
                # Map the deletion to DOM position
                dom_pos = self.plain_to_dom(original_offset)
                if dom_pos:
                    edit = DocumentEdit.delete(
                        para_id=dom_pos.para_id,
                        start=dom_pos.char_offset,
                        end=dom_pos.char_offset + len(op.text),
                        author=author,
                        track_change=track_changes
                    )
                    edits.append(edit)
                
                # Advance past the deleted text
                original_offset += len(op.text)
            
            elif op.op == DiffOperation.INSERT:
                # Map the insertion to DOM position
                dom_pos = self.plain_to_dom(original_offset)
                if dom_pos:
                    edit = DocumentEdit.insert(
                        para_id=dom_pos.para_id,
                        position=dom_pos.char_offset,
                        text=op.text,
                        author=author,
                        track_change=track_changes
                    )
                    edits.append(edit)
                # Note: insert doesn't advance original_offset
        
        return edits
    
    def compute_edits_for_paragraph(
        self,
        para_id: str,
        original_para_text: str,
        revised_para_text: str,
        author: str = "Stet",
        track_changes: bool = True
    ) -> List['DocumentEdit']:
        """
        Compute edits for a single paragraph replacement.
        
        This is a simpler method when you know exactly which paragraph
        is being edited (common case for single-paragraph revisions).
        
        Args:
            para_id: The paragraph being edited
            original_para_text: Original text of the paragraph
            revised_para_text: Revised text of the paragraph
            author: Author name for tracked changes
            track_changes: Whether to create tracked changes
            
        Returns:
            List of DocumentEdit objects
        """
        from src.diff_utils import compute_diff, DiffOperation
        from .edits import DocumentEdit, EditType
        
        edits = []
        
        # Compute diff
        diff_result = compute_diff(original_para_text, revised_para_text)
        
        if not diff_result.has_changes:
            return edits
        
        # Track current position in original text
        original_offset = 0
        
        for op in diff_result.operations:
            if op.op == DiffOperation.EQUAL:
                original_offset += len(op.text)
            
            elif op.op == DiffOperation.DELETE:
                edit = DocumentEdit.delete(
                    para_id=para_id,
                    start=original_offset,
                    end=original_offset + len(op.text),
                    author=author,
                    track_change=track_changes
                )
                edits.append(edit)
                original_offset += len(op.text)
            
            elif op.op == DiffOperation.INSERT:
                edit = DocumentEdit.insert(
                    para_id=para_id,
                    position=original_offset,
                    text=op.text,
                    author=author,
                    track_change=track_changes
                )
                edits.append(edit)
        
        return edits

class PlainTextViewBuilder:
    """
    Builder for constructing PlainTextView from a DocumentModel.
    
    Usage:
        builder = PlainTextViewBuilder(model)
        view = builder.build_for_thread(thread_id, context_before=2, context_after=2)
        
        # Or for specific paragraphs
        view = builder.build_for_paragraphs([para_id1, para_id2])
    """
    
    def __init__(self, model: 'DocumentModel'):
        """
        Initialize builder with a DocumentModel.
        
        Args:
            model: The document model to build views from
        """
        self.model = model
    
    def build(self, scope: TextScope) -> PlainTextView:
        """
        Build a PlainTextView for the given scope.
        
        Args:
            scope: Defines what content to include
            
        Returns:
            A PlainTextView with position mapping
        """
        # Determine which paragraphs to include
        paragraphs = self._get_paragraphs_for_scope(scope)
        
        # Build the plain text with position tracking
        text_parts = []
        boundaries = []
        current_offset = 0
        
        for para in paragraphs:
            para_text = para.plain_text if not scope.include_deleted_text else para.full_text
            
            if scope.skip_ghost_paragraphs and not para_text.strip():
                continue
            
            start_offset = current_offset
            end_offset = start_offset + len(para_text)
            
            text_parts.append(para_text)
            boundaries.append((start_offset, end_offset, para.para_id))
            
            current_offset = end_offset + len("\n\n")  # Account for separator
        
        # Join with paragraph separator
        full_text = "\n\n".join(text_parts)
        
        # Build comment ranges
        comment_ranges = self._build_comment_ranges(scope, boundaries, full_text)
        
        view = PlainTextView(
            text=full_text,
            scope=scope,
            paragraphs=paragraphs,
            paragraph_boundaries=boundaries,
            comment_ranges=comment_ranges
        )
        
        # Store reference to model for context parts
        view._model = self.model
        
        return view
    
    def build_for_thread(
        self,
        thread_id: str,
        context_before: int = 2,
        context_after: int = 2,
        accepted_revisions: Optional[Dict[str, str]] = None,
        ref_start_offset: int = 0,
        ref_end_offset: int = 0
    ) -> PlainTextView:
        """
        Build a PlainTextView centered on a comment thread.
        
        This is the main method for LLM integration.
        
        Args:
            thread_id: The thread to center on
            context_before: Paragraphs to include before target
            context_after: Paragraphs to include after target
            accepted_revisions: Dict of para_id -> revised text to apply
            ref_start_offset: Expand target start (negative = more paragraphs above)
            ref_end_offset: Expand target end (positive = more paragraphs below)
            
        Returns:
            PlainTextView with context
        """
        thread = self.model.comments.get_thread(thread_id)
        if not thread or not thread.root.anchor:
            # Return empty view
            return PlainTextView(
                text="",
                scope=TextScope.from_thread(thread_id),
                paragraphs=[],
                paragraph_boundaries=[],
                comment_ranges={}
            )
        
        # Find target paragraph index
        anchor_para_id = thread.root.anchor.para_id
        target_idx = self.model.body.get_paragraph_index(anchor_para_id)
        
        if target_idx < 0:
            return PlainTextView(
                text="",
                scope=TextScope.from_thread(thread_id),
                paragraphs=[],
                paragraph_boundaries=[],
                comment_ranges={}
            )
        
        # Calculate expanded range
        expanded_start = max(0, target_idx + ref_start_offset)
        expanded_end = min(
            self.model.body.paragraph_count - 1,
            target_idx + ref_end_offset
        )
        
        # Calculate full range including context
        full_start = max(0, expanded_start - context_before)
        full_end = min(
            self.model.body.paragraph_count - 1,
            expanded_end + context_after
        )
        
        # Get paragraphs
        paragraphs = []
        for i, para in enumerate(self.model.body.iter_paragraphs()):
            if full_start <= i <= full_end:
                paragraphs.append(para)
        
        # Build text with position tracking, applying revisions
        text_parts = []
        boundaries = []
        current_offset = 0
        
        # Track which paragraphs are before/target/after
        before_end_idx = expanded_start - full_start
        target_end_idx = before_end_idx + (expanded_end - expanded_start + 1)
        
        all_target_para_ids = []
        
        for local_idx, para in enumerate(paragraphs):
            # Get text (apply revision if available)
            if accepted_revisions and para.para_id in accepted_revisions:
                para_text = accepted_revisions[para.para_id]
            else:
                para_text = para.plain_text
            
            if not para_text.strip():
                continue
            
            start_offset = current_offset
            end_offset = start_offset + len(para_text)
            
            text_parts.append(para_text)
            boundaries.append((start_offset, end_offset, para.para_id))
            
            # Track target para IDs
            if before_end_idx <= local_idx < target_end_idx:
                all_target_para_ids.append(para.para_id)
            
            current_offset = end_offset + 2  # +2 for "\n\n"
        
        full_text = "\n\n".join(text_parts)
        
        # Build comment ranges
        scope = TextScope.from_thread(thread_id, context_before, context_after)
        comment_ranges = self._build_comment_ranges(scope, boundaries, full_text)
        
        view = PlainTextView(
            text=full_text,
            scope=scope,
            paragraphs=paragraphs,
            paragraph_boundaries=boundaries,
            comment_ranges=comment_ranges
        )
        view._model = self.model
        view._target_para_ids = all_target_para_ids
        view._target_para_id = anchor_para_id
        
        return view
    
    def build_for_paragraphs(
        self,
        para_ids: List[str],
        accepted_revisions: Optional[Dict[str, str]] = None
    ) -> PlainTextView:
        """
        Build a PlainTextView for specific paragraphs.
        
        Args:
            para_ids: List of paragraph IDs to include
            accepted_revisions: Dict of para_id -> revised text to apply
            
        Returns:
            PlainTextView for the specified paragraphs
        """
        paragraphs = []
        for para_id in para_ids:
            para = self.model.get_paragraph(para_id)
            if para:
                paragraphs.append(para)
        
        # Build text
        text_parts = []
        boundaries = []
        current_offset = 0
        
        for para in paragraphs:
            if accepted_revisions and para.para_id in accepted_revisions:
                para_text = accepted_revisions[para.para_id]
            else:
                para_text = para.plain_text
            
            if not para_text.strip():
                continue
            
            start_offset = current_offset
            end_offset = start_offset + len(para_text)
            
            text_parts.append(para_text)
            boundaries.append((start_offset, end_offset, para.para_id))
            
            current_offset = end_offset + 2
        
        full_text = "\n\n".join(text_parts)
        
        scope = TextScope.from_para_ids(para_ids)
        comment_ranges = self._build_comment_ranges(scope, boundaries, full_text)
        
        view = PlainTextView(
            text=full_text,
            scope=scope,
            paragraphs=paragraphs,
            paragraph_boundaries=boundaries,
            comment_ranges=comment_ranges
        )
        view._model = self.model
        
        return view
    
    def _get_paragraphs_for_scope(self, scope: TextScope) -> List['Paragraph']:
        """Get paragraphs matching the scope."""
        if scope.para_ids:
            # Specific paragraph IDs
            paragraphs = []
            for para_id in scope.para_ids:
                para = self.model.get_paragraph(para_id)
                if para:
                    paragraphs.append(para)
            return paragraphs
        
        elif scope.start_index is not None and scope.end_index is not None:
            # Index range
            paragraphs = []
            for i, para in enumerate(self.model.body.iter_paragraphs()):
                if scope.start_index <= i <= scope.end_index:
                    paragraphs.append(para)
            return paragraphs
        
        elif scope.thread_id:
            # Thread-based scope - handled by build_for_thread
            thread = self.model.comments.get_thread(scope.thread_id)
            if not thread or not thread.root.anchor:
                return []
            
            anchor_para_id = thread.root.anchor.para_id
            target_idx = self.model.body.get_paragraph_index(anchor_para_id)
            
            if target_idx < 0:
                return []
            
            start_idx = max(0, target_idx - scope.context_before)
            end_idx = min(
                self.model.body.paragraph_count - 1,
                target_idx + scope.context_after
            )
            
            paragraphs = []
            for i, para in enumerate(self.model.body.iter_paragraphs()):
                if start_idx <= i <= end_idx:
                    paragraphs.append(para)
            return paragraphs
        
        # Default: all paragraphs
        return list(self.model.body.iter_paragraphs())
    
    def _build_comment_ranges(
        self,
        scope: TextScope,
        boundaries: List[Tuple[int, int, str]],
        full_text: str
    ) -> Dict[str, CommentRange]:
        """Build comment range mappings for the view."""
        comment_ranges = {}
        
        # Build para_id -> (start, end) mapping
        para_boundaries = {pid: (start, end) for start, end, pid in boundaries}
        
        # Map each comment's anchor to plain text coordinates
        for comment in self.model.comments.comments.values():
            if not comment.anchor:
                continue
            
            anchor_para_id = comment.anchor.para_id
            if anchor_para_id not in para_boundaries:
                continue
            
            para_start, para_end = para_boundaries[anchor_para_id]
            
            # Calculate plain text offsets
            start_offset = para_start + comment.anchor.start_offset
            end_offset = para_start + comment.anchor.end_offset
            
            # Clamp to paragraph boundaries
            start_offset = max(para_start, min(start_offset, para_end))
            end_offset = max(start_offset, min(end_offset, para_end))
            
            # Extract the text
            text = full_text[start_offset:end_offset] if start_offset < len(full_text) else ""
            
            comment_ranges[comment.comment_id] = CommentRange(
                comment_id=comment.comment_id,
                start_offset=start_offset,
                end_offset=end_offset,
                text=text
            )
        
        return comment_ranges


def get_context_for_thread(
    model: 'DocumentModel',
    thread_id: str,
    context_before: int = 2,
    context_after: int = 2,
    accepted_revisions: Optional[Dict[str, str]] = None,
    ref_start_offset: int = 0,
    ref_end_offset: int = 0
) -> Tuple[str, str, str, Optional[str], Optional[List[str]]]:
    """
    Get context text for a thread, compatible with legacy LLM handler interface.
    
    This is the main entry point for integrating with the LLM handler.
    
    Args:
        model: The DocumentModel
        thread_id: Thread to get context for
        context_before: Paragraphs before target
        context_after: Paragraphs after target
        accepted_revisions: Dict of para_id -> revised text
        ref_start_offset: Expand target start (negative)
        ref_end_offset: Expand target end (positive)
        
    Returns:
        Tuple of (context_before, target_text, context_after, target_para_id, all_target_para_ids)
    """
    builder = PlainTextViewBuilder(model)
    view = builder.build_for_thread(
        thread_id=thread_id,
        context_before=context_before,
        context_after=context_after,
        accepted_revisions=accepted_revisions,
        ref_start_offset=ref_start_offset,
        ref_end_offset=ref_end_offset
    )
    
    if not view.text:
        return "", "", "", None, None
    
    # Split into before/target/after based on boundaries
    thread = model.comments.get_thread(thread_id)
    if not thread or not thread.root.anchor:
        return "", view.text, "", None, None
    
    # Get target para IDs from view
    target_para_ids = getattr(view, '_target_para_ids', [])
    target_para_id = getattr(view, '_target_para_id', None)
    
    if not target_para_ids:
        return "", view.text, "", target_para_id, None
    
    # Split text by finding target paragraph boundaries
    before_parts = []
    target_parts = []
    after_parts = []
    
    in_target = False
    passed_target = False
    
    for start, end, para_id in view.paragraph_boundaries:
        para_text = view.text[start:end]
        
        if para_id in target_para_ids:
            in_target = True
            target_parts.append(para_text)
        elif in_target and para_id not in target_para_ids:
            in_target = False
            passed_target = True
            after_parts.append(para_text)
        elif passed_target:
            after_parts.append(para_text)
        else:
            before_parts.append(para_text)
    
    return (
        "\n\n".join(before_parts),
        "\n\n".join(target_parts),
        "\n\n".join(after_parts),
        target_para_id,
        target_para_ids if target_para_ids else None
    )

from .plain_text_edits import (
    _align_gap,
    _align_paragraphs,
    _compute_within_paragraph_edits,
    _reorder_edits_for_safe_application,
    apply_revision_from_plain_text,
    compute_structural_edits,
)

__all__ = [
    'ScopeType',
    'TextScope',
    'DOMPosition',
    'PreservedRegion',
    'CommentRange',
    'PlainTextView',
    'PlainTextViewBuilder',
    'get_context_for_thread',
    'compute_structural_edits',
    'apply_revision_from_plain_text',
    '_reorder_edits_for_safe_application',
    '_compute_within_paragraph_edits',
    '_align_paragraphs',
    '_align_gap',
]
