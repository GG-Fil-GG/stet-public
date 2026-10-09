"""
Document Object Model for DOCX files.

This module provides a DOM-like representation of Word documents,
serving as the single source of truth for document state.

Main classes:
- DocumentModel: The root container for a document
- Paragraph, Run, RunFormatting: Content elements
- Comment, CommentStore, CommentThread: Comment system
- Revision, RevisionStore: Track changes
- DocumentEdit: Edit operations
"""

# Core model
from .model import (
    DocumentModel,
    DocumentBody,
    DocumentProperties,
    StyleStore,
    Table,
)

# Paragraph and formatting
from .paragraph import (
    Paragraph,
    Run,
    RunFormatting,
    ParagraphProperties,
    RevisionType,
)

# Comments
from .comments import (
    Comment,
    CommentStore,
    CommentThread,
    CommentAnchor,
    CommentParagraph,
)

# Revisions (track changes)
from .revisions import (
    Revision,
    RevisionStore,
)

# Edits
from .edits import (
    DocumentEdit,
    EditType,
)

# Utilities
from .utils import (
    generate_valid_para_id,
    generate_hex_id,
    generate_comment_id,
    is_valid_para_id,
    is_valid_hex_id,
)

# Parser
from .parser import (
    DocumentParser,
    parse_docx,
)

# Plain text view
from .plain_text import (
    PlainTextView,
    PlainTextViewBuilder,
    TextScope,
    DOMPosition,
    PreservedRegion,
    CommentRange,
    get_context_for_thread,
)

# Serializer
from .serializer import DocumentSerializer

__all__ = [
    # Core model
    'DocumentModel',
    'DocumentBody',
    'DocumentProperties',
    'StyleStore',
    'Table',
    
    # Paragraph
    'Paragraph',
    'Run',
    'RunFormatting',
    'ParagraphProperties',
    
    # Comments
    'Comment',
    'CommentStore',
    'CommentThread',
    'CommentAnchor',
    'CommentParagraph',
    
    # Revisions
    'Revision',
    'RevisionStore',
    
    # Edits
    'DocumentEdit',
    'EditType',
    
    # Utilities
    'generate_valid_para_id',
    'generate_hex_id',
    'generate_comment_id',
    'is_valid_para_id',
    'is_valid_hex_id',
    
    # Parser
    'DocumentParser',
    'parse_docx',
    
    # Plain text view
    'PlainTextView',
    'PlainTextViewBuilder',
    'TextScope',
    'DOMPosition',
    'PreservedRegion',
    'CommentRange',
    'get_context_for_thread',
    
    # Serializer
    'DocumentSerializer',
]
