"""
LLM-compatible adapter types and DOM-to-LLM conversion.

These classes provide the interface that LLMHandler expects for comment
threads. They adapt DOM model data to a simpler structure.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.document_model import DocumentModel
    from src.document_model.comments import CommentThread as DOMCommentThread


@dataclass
class CommentContext:
    """
    A comment in a format compatible with LLMHandler.

    Adapter type — not the same as document_model.comments.Comment.
    """
    id: str
    author: str
    date: str
    text: str
    para_id: str = ""
    comment_para_id: str = ""
    is_resolved: bool = False
    has_anchor: bool = True
    is_on_deleted_text: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThreadContext:
    """
    A comment thread in a format compatible with LLMHandler.

    Adapter type — not the same as document_model.comments.CommentThread.
    """
    thread_id: str
    comments: List[CommentContext] = field(default_factory=list)
    referenced_text: Optional[str] = None
    exact_text: Optional[str] = None
    exact_text_occurrence: int = 1
    paragraph_text: Optional[str] = None
    section: Optional[str] = None
    is_resolved: bool = False
    has_anchor: bool = True
    is_on_deleted_text: bool = False

    def to_dict(self) -> dict:
        return {
            'thread_id': self.thread_id,
            'comments': [c.to_dict() for c in self.comments],
            'referenced_text': self.referenced_text,
            'exact_text': self.exact_text,
            'exact_text_occurrence': self.exact_text_occurrence,
            'paragraph_text': self.paragraph_text,
            'section': self.section,
            'is_resolved': self.is_resolved,
            'has_anchor': self.has_anchor,
            'is_on_deleted_text': self.is_on_deleted_text
        }


def convert_dom_thread_for_llm(
    dom_thread: 'DOMCommentThread',
    model: 'DocumentModel'
) -> ThreadContext:
    """
    Convert a DOM CommentThread to a ThreadContext for LLMHandler.

    Args:
        dom_thread: The DOM CommentThread to convert
        model: The DocumentModel containing the thread

    Returns:
        A ThreadContext object compatible with LLMHandler
    """
    comments = []
    all_comments = dom_thread.all_comments  # root + replies

    for dom_comment in all_comments:
        comment = CommentContext(
            id=dom_comment.comment_id,
            author=dom_comment.author,
            date=dom_comment.date.isoformat() if dom_comment.date else "",
            text=dom_comment.text,
            para_id=dom_comment.anchor.para_id if dom_comment.anchor else "",
            comment_para_id=dom_comment.para_id,
            is_resolved=dom_comment.is_resolved,
            has_anchor=dom_comment.anchor is not None,
        )
        comments.append(comment)

    referenced_text = ""
    exact_text = ""
    paragraph_text = ""

    root_anchor = dom_thread.root.anchor
    if root_anchor:
        para = model.body.get_element_by_para_id(root_anchor.para_id)
        if para:
            paragraph_text = para.plain_text
            raw = para.raw_text
            exact_text = raw[root_anchor.start_offset:root_anchor.end_offset]
            referenced_text = f"[{exact_text}] in [{raw}]"

    is_on_deleted_text = False
    if root_anchor:
        para = model.body.get_element_by_para_id(root_anchor.para_id)
        if para and hasattr(para, 'runs'):
            from src.document_model import RevisionType
            current_pos = 0
            for run in para.runs:
                run_end = current_pos + len(run.text)
                if (run.revision_type == RevisionType.DELETION and
                    current_pos < root_anchor.end_offset and
                    run_end > root_anchor.start_offset):
                    is_on_deleted_text = True
                    break
                current_pos = run_end

    return ThreadContext(
        thread_id=dom_thread.thread_id,
        comments=comments,
        referenced_text=referenced_text,
        exact_text=exact_text,
        exact_text_occurrence=1,
        paragraph_text=paragraph_text,
        section=None,
        is_resolved=dom_thread.is_resolved,
        has_anchor=root_anchor is not None,
        is_on_deleted_text=is_on_deleted_text,
    )
