# Document Model (DOM) Architecture Design

> **Status: reference document.** Drafted Feb 2026 as the DOM architecture spec. The architecture it describes is in place. Some line counts, file paths, and "deprecated files" references predate the Tier 1 cleanup (post-2026-05-23) and may be stale — **the code under `src/document_model/` is the source of truth.** Use this doc for the design rationale and the validated Word behaviors; verify any concrete numbers against the current codebase.

## Overview

This document outlines the architecture for a Document Object Model that will serve as the single source of truth for DOCX documents in Stet. The design prioritizes:

1. **Full fidelity** - Preserve all document structure through round-trips
2. **Position mapping** - Bidirectional mapping between DOM and plain text
3. **Comment threading** - First-class support for threaded comments
4. **Track changes** - Awareness of existing and new tracked changes
5. **Extensibility** - Room for future features without architectural changes

## Validated Findings (from XML Assumption Tests)

Before designing the DOM, we validated key assumptions about how Word handles DOCX files.
These tests were conducted on 2026-02-16 using Microsoft Word for Mac.

### Comment Threading Requirements

| Requirement | Status | Evidence |
|-------------|--------|----------|
| `comments.xml` entry | **Required** | Comment content must exist here |
| `commentsExtended.xml` entry with `paraIdParent` | **Required** | Threading relationship |
| `commentsIds.xml` entry with `durableId` | **Required for threading** | Without this, reply shows as standalone |
| `commentsExtensible.xml` entry | **Required for threading** | UTC timestamp linked via durableId |
| Anchor in `document.xml` | **Required** | Without anchor, reply is invisible |

### Threading Model

**Word uses FLAT threading**: All replies point to the root comment's `paraId`, not to each other.

```xml
<!-- commentsExtended.xml -->
<w15:commentEx w15:paraId="ROOT_PARA_ID" w15:done="0"/>
<w15:commentEx w15:paraId="REPLY1_PARA_ID" w15:paraIdParent="ROOT_PARA_ID" w15:done="0"/>
<w15:commentEx w15:paraId="REPLY2_PARA_ID" w15:paraIdParent="ROOT_PARA_ID" w15:done="0"/>
<w15:commentEx w15:paraId="REPLY3_PARA_ID" w15:paraIdParent="ROOT_PARA_ID" w15:done="0"/>
```

### Reply Anchor Structure

Word nests reply anchors at the same starting position as the parent:

```xml
<w:commentRangeStart w:id="0"/>  <!-- Root -->
<w:commentRangeStart w:id="1"/>  <!-- Reply 1 - same start position -->
<w:commentRangeStart w:id="2"/>  <!-- Reply 2 - same start position -->
... referenced text ...
<w:commentRangeEnd w:id="0"/>
<w:commentReference w:id="0"/>
<w:commentRangeEnd w:id="1"/>
<w:commentReference w:id="1"/>
<w:commentRangeEnd w:id="2"/>
<w:commentReference w:id="2"/>
```

### Other Validated Behaviors

| Behavior | Result |
|----------|--------|
| Ordering in `commentsExtended.xml` | Does NOT matter |
| Track changes inside comment range | Works correctly |
| Zero-width anchors | Work for threading |
| Overlapping anchor ranges | Work correctly |

### ID Constraints (Critical Discovery)

Validated 2026-02-16 through systematic testing:

| ID Type | Constraint | Reason |
|---------|------------|--------|
| `w14:paraId` | **First char must be 0-7** | Word interprets as signed 32-bit int |
| `w14:textId` | None (full 0-F range) | Tested with invalid first char - works |
| `w16cid:durableId` | None (full 0-F range) | Tested with invalid first char - works |
| `w:rsidR` | None (full 0-F range) | Tested with invalid first char - works |
| `w:id` (comment) | None (any unique integer) | Random IDs work for threading |

**Why paraId has this constraint**: Word appears to validate paraId as a non-negative signed 32-bit integer. Values 0x80000000+ (first char 8-F) are negative and rejected. See `docs/word_threading_specification.md` for full details.

### Areas Still Needing Validation

See "Open Questions" section at the end of this document.

---

## Architecture Approach: Hybrid (Option 4)

We use a **layered hybrid approach**:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Stet Application Layer                       │
│         (UI, LLM integration, business logic)                   │
├─────────────────────────────────────────────────────────────────┤
│                    Document Model (Our DOM)                      │
│    DocumentModel, Paragraph, Run, Comment, TrackChange, etc.    │
├─────────────────────────────────────────────────────────────────┤
│                      Parsing/Serialization                       │
│  ┌─────────────────────┐    ┌────────────────────────────────┐  │
│  │     python-docx     │    │   lxml (direct XML handling)   │  │
│  │  - Document structure│    │  - comments.xml                │  │
│  │  - Paragraphs/Runs   │    │  - commentsExtended.xml        │  │
│  │  - Tables            │    │  - commentsIds.xml             │  │
│  │  - Styles            │    │  - commentsExtensible.xml      │  │
│  │                      │    │  - Comment anchors in doc.xml  │  │
│  └─────────────────────┘    │  - Track change elements       │  │
│                              └────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                         OPC Package                              │
│              (ZIP archive with XML parts)                        │
└─────────────────────────────────────────────────────────────────┘
```

**Rationale**: python-docx handles standard document structure well but may strip/corrupt custom XML. We use it for what it's good at (paragraphs, tables, styles) and handle comments/track-changes ourselves via lxml for full control.

---

## Core Data Structures

### 1. DocumentModel (Root)

The top-level container for the entire document state.

```python
@dataclass
class DocumentModel:
    """
    The single source of truth for document state.
    
    All modifications go through this model. Export serializes this back to DOCX.
    """
    # Document identity
    source_path: Path                    # Original file path
    created_at: datetime
    modified_at: datetime
    
    # Content structure
    body: DocumentBody                   # Main document content
    
    # Comments system (our primary focus)
    comments: CommentStore               # All comments and threading
    
    # Track changes
    revisions: RevisionStore             # Existing + new track changes
    
    # Styles and formatting
    styles: StyleStore                   # Named styles (Heading1, Normal, etc.)
    
    # Metadata
    properties: DocumentProperties       # Author, title, etc.
    
    # State tracking
    is_dirty: bool = False               # Has unsaved changes
    
    def get_plain_text_view(self, scope: TextScope) -> PlainTextView:
        """Get plain text representation with position mapping."""
        
    def apply_edit(self, edit: DocumentEdit) -> None:
        """Apply an edit, updating all affected anchors and positions."""
        
    def to_docx(self, output_path: Path) -> None:
        """Serialize back to DOCX file."""
```

### 2. DocumentBody

The main content container.

```python
@dataclass
class DocumentBody:
    """
    The document body containing all content elements.
    
    Elements are stored in document order. Each element knows its position.
    """
    elements: List[BodyElement]          # Paragraphs, tables, etc. in order
    
    def get_element_by_para_id(self, para_id: str) -> Optional[BodyElement]:
        """Find element by its paragraph ID."""
        
    def get_elements_in_range(self, start_idx: int, end_idx: int) -> List[BodyElement]:
        """Get elements by index range (for context expansion)."""
        
    def iter_paragraphs(self) -> Iterator[Paragraph]:
        """Iterate over all paragraphs (including those in tables)."""
```

### 3. Paragraph

A single paragraph with runs and anchors.

```python
@dataclass
class Paragraph:
    """
    A document paragraph.
    
    Key insight: We track character positions within the paragraph to enable
    plain text ↔ DOM mapping and anchor management.
    """
    # Identity
    para_id: str                         # w14:paraId (8-char hex, first char MUST be 0-7)
    text_id: str                         # w14:textId (8-char hex, no constraint)
    
    # Content
    runs: List[Run]                      # Text runs in order
    
    # Formatting
    properties: ParagraphProperties      # Alignment, spacing, indentation, etc.
    style_id: Optional[str]              # Reference to named style
    
    # Position in document
    index: int                           # Position in body.elements
    
    # Computed properties (cached, invalidated on edit)
    _plain_text: Optional[str] = None
    _char_count: Optional[int] = None
    
    @property
    def plain_text(self) -> str:
        """Get concatenated plain text of all runs."""
        if self._plain_text is None:
            self._plain_text = ''.join(run.text for run in self.runs)
        return self._plain_text
    
    @property
    def char_count(self) -> int:
        """Total character count."""
        return len(self.plain_text)
    
    def get_run_at_offset(self, char_offset: int) -> Tuple[Run, int]:
        """
        Find the run containing a character offset.
        
        Returns: (run, offset_within_run)
        """
        
    def invalidate_cache(self) -> None:
        """Clear cached computed properties after modification."""
        self._plain_text = None
        self._char_count = None
```

### 4. Run

A span of text with consistent formatting.

```python
@dataclass
class Run:
    """
    A run of text with uniform formatting.
    
    In Word, formatting changes require run boundaries. A paragraph like:
    "Hello WORLD today" (where WORLD is bold) has 3 runs.
    """
    # Content
    text: str                            # The actual text
    
    # Formatting
    formatting: RunFormatting            # Bold, italic, etc.
    style_id: Optional[str]              # Character style reference
    
    # Position within paragraph (computed during parsing, updated on edits)
    start_offset: int                    # Character offset in paragraph
    end_offset: int                      # Character offset in paragraph
    
    # Track change context (if this run is inside w:ins or w:del)
    revision_type: Optional[RevisionType] = None  # 'insertion', 'deletion', None
    revision_id: Optional[str] = None
    
    # Original XML (for elements we don't fully parse)
    _raw_xml: Optional[str] = None       # Preserved for round-trip fidelity


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
    color: Optional[str] = None          # Hex color
    highlight: Optional[str] = None      # Highlight color
    
    # For future expansion
    custom_properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_word_xml(self) -> str:
        """Generate <w:rPr> XML."""
        
    @classmethod
    def from_word_xml(cls, rPr_element) -> 'RunFormatting':
        """Parse from <w:rPr> element."""
```

---

## Comments System

### 5. CommentStore

Central manager for all comments.

```python
@dataclass
class CommentStore:
    """
    Manages all comments and their relationships.
    
    Handles the complexity of Word's 4-file comment system:
    - comments.xml: Comment content
    - commentsExtended.xml: Threading (paraIdParent)
    - commentsIds.xml: Durable IDs
    - commentsExtensible.xml: UTC timestamps
    """
    # All comments by ID
    comments: Dict[str, Comment] = field(default_factory=dict)
    
    # Threading structure
    threads: Dict[str, CommentThread] = field(default_factory=dict)
    
    # ID generators (for new comments)
    # Note: comment_id is an integer (no constraint)
    # Note: para_id MUST have first char 0-7 (use generate_valid_para_id())
    # Note: durable_id, text_id, rsid have NO constraint (full 0-F range OK)
    _next_comment_id: int = 0
    
    def get_comment(self, comment_id: str) -> Optional[Comment]:
        """Get comment by its w:id."""
        
    def get_thread(self, thread_id: str) -> Optional[CommentThread]:
        """Get thread (root comment + all replies)."""
        
    def get_thread_for_comment(self, comment_id: str) -> Optional[CommentThread]:
        """Find the thread a comment belongs to."""
        
    def add_reply(
        self,
        parent_comment_id: str,
        text: str,
        author: str,
        timestamp: datetime
    ) -> Comment:
        """
        Add a reply to an existing comment.
        
        Handles all the complexity:
        - Generates new IDs (comment_id, para_id, durable_id, text_id, rsid)
        - CRITICAL: para_id must use constrained generation (first char 0-7)
        - Other hex IDs (durable_id, text_id, rsid) can use full 0-F range
        - Sets up threading relationship (paraIdParent points to ROOT)
        - Creates anchor matching parent's anchor
        """
        
    def get_comments_for_paragraph(self, para_id: str) -> List[Comment]:
        """Get all comments anchored to a paragraph."""
```

### 6. Comment

A single comment (either root or reply).

```python
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
    comment_id: str                      # w:id attribute (integer as string)
    para_id: str                         # w14:paraId (8-char hex, first char 0-7!)
    
    # Content
    text: str                            # Plain text of comment
    paragraphs: List[CommentParagraph]   # Full structure (for complex comments)
    
    # Metadata
    author: str
    author_initials: str
    date: datetime                       # Local time (from w:date)
    date_utc: Optional[datetime]         # UTC time (from commentsExtensible.xml)
    
    # Threading (from commentsExtended.xml)
    parent_para_id: Optional[str]        # w15:paraIdParent - None if root comment
    is_resolved: bool                    # w15:done
    
    # Durable identity (from commentsIds.xml)
    durable_id: str                      # w16cid:durableId (no constraint)
    
    # Anchor in document (from document.xml)
    anchor: CommentAnchor
    
    @property
    def is_root(self) -> bool:
        """Is this a root comment (not a reply)?"""
        return self.parent_para_id is None
    
    @property
    def is_reply(self) -> bool:
        """Is this a reply to another comment?"""
        return self.parent_para_id is not None


@dataclass
class CommentThread:
    """
    A thread of comments (root + replies).
    
    Convenience structure for working with comment threads.
    """
    thread_id: str                       # Same as root comment's comment_id
    root: Comment                        # The original comment
    replies: List[Comment]               # All replies in chronological order
    
    @property
    def all_comments(self) -> List[Comment]:
        """All comments in thread order."""
        return [self.root] + self.replies
    
    @property
    def latest_comment(self) -> Comment:
        """Most recent comment in thread."""
        return self.replies[-1] if self.replies else self.root
```

### 7. CommentAnchor

Where a comment points in the document.

```python
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
    para_id: str                         # Paragraph containing the anchor
    start_offset: int                    # Character offset where highlight starts
    end_offset: int                      # Character offset where highlight ends
    
    # For multi-paragraph anchors (rare but possible)
    end_para_id: Optional[str] = None    # If anchor spans paragraphs
    
    @property
    def is_collapsed(self) -> bool:
        """Is this a zero-width anchor (cursor position)?"""
        return self.start_offset == self.end_offset
    
    @property
    def spans_paragraphs(self) -> bool:
        """Does this anchor span multiple paragraphs?"""
        return self.end_para_id is not None and self.end_para_id != self.para_id
    
    def shift(self, offset: int, after_position: int) -> None:
        """
        Shift anchor positions after an edit.
        
        Called when text is inserted/deleted before or within the anchor.
        """
        if self.start_offset >= after_position:
            self.start_offset += offset
        if self.end_offset >= after_position:
            self.end_offset += offset
    
    def get_anchored_text(self, paragraph: Paragraph) -> str:
        """Get the text this anchor highlights."""
        return paragraph.plain_text[self.start_offset:self.end_offset]
```

---

## Track Changes (Revisions)

### 8. RevisionStore

Manager for tracked changes.

```python
@dataclass
class RevisionStore:
    """
    Manages tracked changes (insertions, deletions, formatting changes).
    
    Handles both:
    - Existing revisions already in the document
    - New revisions created by Stet
    """
    revisions: Dict[str, Revision] = field(default_factory=dict)
    
    # ID generator
    _next_revision_id: int = 0
    
    # Settings
    track_changes_enabled: bool = True
    default_author: str = "Stet"
    
    def add_insertion(
        self,
        para_id: str,
        position: int,
        text: str,
        author: str,
        timestamp: datetime,
        formatting: Optional[RunFormatting] = None
    ) -> Revision:
        """Record a text insertion."""
        
    def add_deletion(
        self,
        para_id: str,
        start: int,
        end: int,
        original_text: str,
        author: str,
        timestamp: datetime
    ) -> Revision:
        """Record a text deletion."""
        
    def get_revisions_in_paragraph(self, para_id: str) -> List[Revision]:
        """Get all revisions affecting a paragraph."""
        
    def accept_revision(self, revision_id: str) -> None:
        """Accept a revision (make it permanent)."""
        
    def reject_revision(self, revision_id: str) -> None:
        """Reject a revision (undo the change)."""


@dataclass
class Revision:
    """
    A single tracked change.
    """
    revision_id: str                     # w:id in the XML
    revision_type: RevisionType          # insertion, deletion, formatting
    
    # Location
    para_id: str
    start_offset: int
    end_offset: int
    
    # Content
    text: str                            # Inserted text or deleted text
    formatting: Optional[RunFormatting]  # For insertions with formatting
    
    # Metadata
    author: str
    timestamp: datetime
    
    # State
    is_accepted: bool = False
    is_rejected: bool = False


class RevisionType(Enum):
    INSERTION = "insertion"              # <w:ins>
    DELETION = "deletion"                # <w:del>
    FORMATTING = "formatting"            # <w:rPrChange>
    MOVE_FROM = "move_from"              # <w:moveFrom>
    MOVE_TO = "move_to"                  # <w:moveTo>
```

---

## Plain Text Mapping

### 9. PlainTextView

The bridge between DOM and plain text.

```python
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
    """
    # The plain text
    text: str
    
    # Scope of what's included
    scope: TextScope
    
    # Position mapping: plain_text_index → DOMPosition
    # Stored as a list where index = character position in plain text
    position_map: List[DOMPosition]
    
    # Reverse mapping for efficiency: (para_id, offset) → plain_text_index
    _reverse_map: Dict[Tuple[str, int], int] = field(default_factory=dict)
    
    # Comment ranges in plain text coordinates
    comment_ranges: Dict[str, Tuple[int, int]]  # comment_id → (start, end)
    
    # Markers for special content (preserved but not sent to LLM)
    preserved_regions: List[PreservedRegion]    # Citations, field codes, etc.
    
    def dom_to_plain(self, para_id: str, offset: int) -> int:
        """Convert DOM position to plain text position."""
        
    def plain_to_dom(self, plain_offset: int) -> DOMPosition:
        """Convert plain text position to DOM position."""
        
    def apply_edit(
        self,
        original_text: str,
        revised_text: str
    ) -> List[DocumentEdit]:
        """
        Given original and revised plain text, compute DOM-level edits.
        
        Uses diff algorithm to find changes, then maps back to DOM positions.
        Returns a list of edits that can be applied to DocumentModel.
        """
        
    def get_comment_range_text(self, comment_id: str) -> str:
        """Get the plain text that a comment references."""
        start, end = self.comment_ranges[comment_id]
        return self.text[start:end]


@dataclass
class DOMPosition:
    """
    A position in the DOM.
    """
    para_id: str
    para_index: int                      # Index in body.elements
    char_offset: int                     # Character offset in paragraph
    run_index: int                       # Which run
    char_in_run: int                     # Offset within run


@dataclass
class TextScope:
    """
    Defines what content to include in a PlainTextView.
    """
    # Which paragraphs to include
    para_ids: List[str]                  # Specific paragraphs
    # OR
    start_index: Optional[int] = None    # Range of paragraphs
    end_index: Optional[int] = None
    
    # What to include
    include_deleted_text: bool = False   # Include text in <w:del>?
    include_tables: bool = True
    
    # Markers to insert
    mark_comment_ranges: bool = True     # Add markers like [COMMENT_START:0]


@dataclass  
class PreservedRegion:
    """
    A region that should be preserved verbatim (not modified by LLM).
    
    Used for citations, field codes, etc.
    """
    start_offset: int                    # In plain text
    end_offset: int
    placeholder: str                     # What we replace it with for LLM
    original_content: str                # The actual content to preserve
    region_type: str                     # 'citation', 'field_code', etc.
```

---

## Edit Operations

### 10. DocumentEdit

Represents a change to apply.

```python
@dataclass
class DocumentEdit:
    """
    A single edit operation to apply to the document.
    
    Edits are computed from PlainTextView.apply_edit() and then
    applied to DocumentModel.apply_edit().
    """
    edit_type: EditType
    
    # Location
    para_id: str
    start_offset: int
    end_offset: int                      # For deletions/replacements
    
    # Content
    text: str                            # New text (for insert/replace)
    formatting: Optional[RunFormatting]  # Formatting for inserted text
    
    # Metadata
    author: str
    timestamp: datetime
    
    # Options
    track_change: bool = True            # Create tracked change or direct edit?


class EditType(Enum):
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"                  # DELETE + INSERT
    FORMAT = "format"                    # Change formatting only
```

---

## Parsing and Serialization

### 11. DocumentParser

Parses DOCX into DocumentModel.

```python
class DocumentParser:
    """
    Parses a DOCX file into a DocumentModel.
    
    Uses python-docx for document structure, lxml for comments/revisions.
    """
    
    def parse(self, docx_path: Path) -> DocumentModel:
        """
        Parse a DOCX file into a DocumentModel.
        
        Steps:
        1. Open as ZIP archive
        2. Use python-docx to parse document structure
        3. Use lxml to parse comment XML files
        4. Use lxml to extract revision markup from document.xml
        5. Build position mappings
        6. Construct and return DocumentModel
        """
        
    def _parse_document_structure(self, docx) -> DocumentBody:
        """Parse paragraphs, tables, runs using python-docx."""
        
    def _parse_comments(self, zip_archive) -> CommentStore:
        """
        Parse all 4 comment XML files using lxml.
        
        - word/comments.xml → Comment content
        - word/commentsExtended.xml → Threading (paraIdParent)
        - word/commentsIds.xml → Durable IDs
        - word/commentsExtensible.xml → UTC timestamps
        """
        
    def _parse_comment_anchors(self, document_xml) -> Dict[str, CommentAnchor]:
        """
        Parse comment anchors from document.xml.
        
        Extracts commentRangeStart/End positions and converts to character offsets.
        """
        
    def _parse_revisions(self, document_xml) -> RevisionStore:
        """Parse existing track changes from document.xml."""


class DocumentSerializer:
    """
    Serializes a DocumentModel back to DOCX.
    
    The tricky part: we need to merge our changes back into the original
    DOCX structure without breaking anything python-docx doesn't understand.
    """
    
    def serialize(self, model: DocumentModel, output_path: Path) -> None:
        """
        Serialize DocumentModel to DOCX file.
        
        Strategy:
        1. Copy original DOCX as base
        2. Use python-docx to update document structure
        3. Use lxml to directly update comment XML files
        4. Use lxml to insert revision markup into document.xml
        5. Save the modified ZIP archive
        """
        
    def _serialize_comments(self, model: DocumentModel, zip_archive) -> None:
        """
        Write all 4 comment XML files.
        
        This is done with lxml for full control over the XML structure.
        """
        
    def _serialize_comment_anchors(
        self,
        model: DocumentModel,
        document_xml: bytes
    ) -> bytes:
        """
        Insert/update comment anchors in document.xml.
        
        Converts character offsets back to XML positions.
        """
        
    def _serialize_revisions(
        self,
        model: DocumentModel,
        document_xml: bytes
    ) -> bytes:
        """Insert track change markup into document.xml."""
```

---

## Usage Example

```python
# 1. Parse document
parser = DocumentParser()
model = parser.parse(Path("input.docx"))

# 2. Get context for a comment
comment = model.comments.get_comment("0")
thread = model.comments.get_thread_for_comment("0")
anchor_para = model.body.get_element_by_para_id(comment.anchor.para_id)

# 3. Create plain text view for LLM
view = model.get_plain_text_view(TextScope(
    para_ids=[anchor_para.para_id],
    include_deleted_text=False
))

# 4. Send to LLM, get revised text
original_text = view.text
revised_text = llm.generate_revision(original_text, comment.text)

# 5. Compute and apply edits
edits = view.apply_edit(original_text, revised_text)
for edit in edits:
    edit.author = "Stet"
    edit.track_change = True
    model.apply_edit(edit)  # This updates anchors automatically

# 6. Add reply comment
model.comments.add_reply(
    parent_comment_id=comment.comment_id,
    text="I've revised this text as suggested.",
    author="Stet",
    timestamp=datetime.now()
)

# 7. Export
serializer = DocumentSerializer()
serializer.serialize(model, Path("output.docx"))
```

---

## Future Extensibility

This architecture supports future features:

| Feature | How it fits |
|---------|-------------|
| **Multi-paragraph edits** | PlainTextView can span multiple paragraphs |
| **Existing track changes** | RevisionStore already tracks them |
| **Accept/reject revisions** | RevisionStore.accept/reject methods |
| **Formatting changes** | RevisionType.FORMATTING + RunFormatting |
| **Images/shapes** | Add ImageElement, ShapeElement to BodyElement types |
| **Headers/footers** | Add HeaderModel, FooterModel to DocumentModel |
| **Footnotes/endnotes** | Similar structure to comments |
| **Multiple comment selections** | CommentAnchor supports multi-paragraph |
| **Collaborative editing** | Each edit tracks author/timestamp |

---

## File Organization

Suggested module structure:

```
src/
├── document_model/
│   ├── __init__.py
│   ├── model.py              # DocumentModel, DocumentBody
│   ├── paragraph.py          # Paragraph, Run, RunFormatting
│   ├── comments.py           # CommentStore, Comment, CommentAnchor
│   ├── revisions.py          # RevisionStore, Revision
│   ├── plain_text.py         # PlainTextView, TextScope, DOMPosition
│   ├── edits.py              # DocumentEdit, EditType
│   ├── parser.py             # DocumentParser
│   ├── serializer.py         # DocumentSerializer
│   └── utils.py              # ID generators, XML helpers
```

### ID Generation Utilities (utils.py)

All ID generators check for collisions with existing IDs. While collision probability
is extremely low (~1 in 100,000+ for typical documents), silent failures from ID
collisions would be very hard to debug. The performance cost of collision checking
is negligible since we already have the existing IDs from parsing.

```python
import uuid
import random
from typing import Set


def generate_valid_para_id(existing_ids: Set[str], max_attempts: int = 100) -> str:
    """
    Generate a unique, valid w14:paraId value.
    
    CRITICAL: First character MUST be 0-7. Word interprets paraId as a signed
    32-bit integer and rejects values >= 0x80000000 (first char 8-F).
    
    This constraint applies ONLY to paraId. Other hex IDs (textId, durableId,
    rsidR) can use the full 0-F range.
    
    Args:
        existing_ids: Set of all paraIds already in the document
        max_attempts: Maximum generation attempts before raising error
    
    Raises:
        RuntimeError: If unable to generate unique ID (should never happen)
    
    Validated 2026-02-16: Tested all 16 first-char values (0-F) across 4 comments.
    """
    for _ in range(max_attempts):
        raw = uuid.uuid4().hex[:8].upper()
        first_char = raw[0]
        if first_char in '89ABCDEF':
            # Map 8-F to 0-7 by taking modulo 8
            new_first = str(int(first_char, 16) % 8)
            raw = new_first + raw[1:]
        if raw not in existing_ids:
            return raw
    raise RuntimeError(f"Failed to generate unique paraId after {max_attempts} attempts")


def generate_hex_id(existing_ids: Set[str], max_attempts: int = 100) -> str:
    """
    Generate a unique random hex ID with no first-char constraint.
    
    Use for: textId, durableId, rsidR
    Do NOT use for: paraId (use generate_valid_para_id instead)
    
    Args:
        existing_ids: Set of existing IDs of this type in the document
        max_attempts: Maximum generation attempts before raising error
    """
    for _ in range(max_attempts):
        new_id = uuid.uuid4().hex[:8].upper()
        if new_id not in existing_ids:
            return new_id
    raise RuntimeError(f"Failed to generate unique hex ID after {max_attempts} attempts")


def generate_comment_id(existing_ids: Set[int], max_attempts: int = 1000) -> str:
    """
    Generate a unique comment ID (integer as string).
    
    Word uses sequential IDs but random IDs work fine for threading.
    We use random to avoid conflicts with existing IDs.
    
    Args:
        existing_ids: Set of existing comment IDs (as integers)
        max_attempts: Maximum generation attempts before raising error
    """
    for _ in range(max_attempts):
        new_id = random.randint(100, 9999)
        if new_id not in existing_ids:
            return str(new_id)
    raise RuntimeError(f"Failed to generate unique comment ID after {max_attempts} attempts")


# Helper to collect all existing IDs from a document
def collect_existing_ids(model: 'DocumentModel') -> dict:
    """
    Collect all existing IDs from a document for collision checking.
    
    Returns dict with keys: 'para_ids', 'text_ids', 'durable_ids', 'comment_ids'
    """
    para_ids = set()
    text_ids = set()
    durable_ids = set()
    comment_ids = set()
    
    # From paragraphs
    for para in model.body.iter_paragraphs():
        para_ids.add(para.para_id)
        text_ids.add(para.text_id)
    
    # From comments
    for comment in model.comments.comments.values():
        para_ids.add(comment.para_id)
        durable_ids.add(comment.durable_id)
        comment_ids.add(int(comment.comment_id))
    
    return {
        'para_ids': para_ids,
        'text_ids': text_ids,
        'durable_ids': durable_ids,
        'comment_ids': comment_ids,
    }
```

---

## Migration Path

To migrate from current architecture:

1. **Phase 1**: Implement DocumentParser + basic model (read-only)
   - Can coexist with current code
   - Validates that we parse everything correctly

2. **Phase 2**: Implement PlainTextView
   - Replace current paragraph_cache with views from model
   - Test LLM round-trips

3. **Phase 3**: Implement edit operations
   - Replace current docx_writer track change logic
   - Anchors now stay correct automatically

4. **Phase 4**: Implement DocumentSerializer
   - Replace current export logic
   - Full round-trip working

5. **Phase 5**: Remove old code
   - Delete comment_extractor.py, docx_writer.py
   - Clean up session_utils.py

Each phase can be tested independently before proceeding.

---

## Open Questions (Requiring Validation)

These aspects of DOCX handling have NOT been validated and may need testing before implementation:

### Track Changes

| Question | Why it matters | How to test |
|----------|----------------|-------------|
| What happens to comment anchors when referenced text is deleted via track changes? | Core to our edit workflow | Create document with comment, delete commented text with track changes, examine XML |
| Can `<w:del>` contain `commentRangeEnd`? | Affects anchor placement during deletions | Same as above |
| How does Word handle formatting changes (`<w:rPrChange>`)? | Future formatting support | Create document with bold→normal change, examine XML |
| What's the structure of move operations (`<w:moveFrom>`, `<w:moveTo>`)? | Future cut/paste support | Move text in Word with track changes, examine XML |

### Formatting

| Question | Why it matters | How to test |
|----------|----------------|-------------|
| How do character styles interact with direct formatting? | Proper formatting preservation | Apply style + direct formatting, examine XML |
| How are complex field codes structured (e.g., cross-references)? | Citation/reference preservation | Create document with various field types, examine XML |
| How does Word handle nested formatting (e.g., bold+italic+underline)? | Multiple formatting in single run | Create examples, examine XML |

### Tables

| Question | Why it matters | How to test |
|----------|----------------|-------------|
| Can comment anchors span table cells? | Comments on table content | Create comment spanning cells, examine XML |
| How do track changes work within table cells? | Editing table content | Make tracked edits in table, examine XML |

### Multi-Paragraph Content

| Question | Why it matters | How to test |
|----------|----------------|-------------|
| How are multi-paragraph comments anchored? | Comments on long passages | Create comment spanning paragraphs, examine XML |
| What's the `paraId` structure for comments with multiple paragraphs? | Complex comment content | Create multi-paragraph comment content, examine XML |

### Document Relationships

| Question | Why it matters | How to test |
|----------|----------------|-------------|
| What happens to `[Content_Types].xml` when adding comment files? | First-time comment addition | Add comment to document without comments, examine XML |
| How are relationship IDs (`rId`) managed? | Proper file linking | Examine `_rels/document.xml.rels` |

### Suggested Validation Process

For each question:
1. Create a minimal test document in Word with the specific feature
2. Extract and examine the XML
3. Document the structure in this file
4. Update data structures if needed

Priority order:
1. **High**: Track changes + anchors interaction (blocks core functionality)
2. **Medium**: Formatting preservation (needed for quality)
3. **Low**: Tables, multi-paragraph (edge cases)

---

## Reference Files

Test files created during validation:

| File | Purpose |
|------|---------|
| `test_data/test.docx` | Base test document with 4 comments |
| `test_data/test_tc_in_range.docx` | Track changes inside comment range |
| `test_data/test_comment_chain.docx` | Word-created threaded replies |
| `docs/docx_structure/original/` | Extracted XML from test.docx |
| `docs/docx_structure/output/` | Extracted XML from Stet output |
| `output/xml_tests_v2/` | Generated test files for assumption validation |
