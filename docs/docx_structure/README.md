# DOCX File Structure

> **Status: external reference.** This folder contains extracted XML from a sample DOCX before/after Stet processing, for human inspection. The descriptions below describe Microsoft Word's storage layout — they do not change when Stet changes.

A `.docx` file is actually a ZIP archive containing XML files. This folder contains extracted and formatted XML from two documents for comparison:

- **original/** - The source `test_data/test.docx` (before Stet processing)
- **output/** - The output `output/demo/test_with_replies_2.docx` (after Stet processing)

## Key Files

### Main Content

| File | Purpose |
|------|---------|
| `word/document.xml` | **The main document content** - paragraphs, runs, text, formatting, tables, and comment anchors (`commentRangeStart`, `commentRangeEnd`, `commentReference`) |
| `word/styles.xml` | Style definitions (Heading1, Normal, etc.) - formatting templates |

### Comments System (4 files work together)

| File | Purpose |
|------|---------|
| `word/comments.xml` | **Comment content** - the actual text of each comment, author, date. Each `<w:comment>` has an `id` and contains paragraphs with `paraId` |
| `word/commentsExtended.xml` | **Threading info** - links replies to parents via `paraIdParent`. This is how Word knows comment 5 is a reply to comment 1 |
| `word/commentsIds.xml` | **Durable IDs** - maps `paraId` to `durableId` for cross-session persistence |
| `word/commentsExtensible.xml` | **UTC timestamps** - stores `dateUtc` for each comment (more precise than the date in comments.xml) |

### Other Files

| File | Purpose |
|------|---------|
| `word/people.xml` | Author information (names, user IDs) |
| `word/settings.xml` | Document settings (track changes enabled, zoom level, etc.) |
| `word/fontTable.xml` | Fonts used in the document |
| `word/theme/theme1.xml` | Color scheme and theme settings |
| `[Content_Types].xml` | Declares what file types are in the package |
| `_rels/.rels` | Relationships between parts |
| `docProps/core.xml` | Metadata (author, created date, modified date) |
| `docProps/app.xml` | Application metadata (Word version, etc.) |

## Key Concepts

### Paragraphs and Runs

In `document.xml`, text is structured as:
```xml
<w:p>                           <!-- Paragraph -->
  <w:pPr>...</w:pPr>            <!-- Paragraph properties (alignment, spacing) -->
  <w:r>                         <!-- Run (a span of text with consistent formatting) -->
    <w:rPr>                     <!-- Run properties -->
      <w:b/>                    <!-- Bold -->
      <w:i/>                    <!-- Italic -->
    </w:rPr>
    <w:t>Hello world</w:t>      <!-- The actual text -->
  </w:r>
</w:p>
```

### Comment Anchors

Comments are anchored in `document.xml` using three elements:
```xml
<w:commentRangeStart w:id="0"/>   <!-- Where the highlighted text begins -->
  ... text being commented on ...
<w:commentRangeEnd w:id="0"/>     <!-- Where the highlighted text ends -->
<w:r>
  <w:commentReference w:id="0"/>  <!-- Links to the comment in comments.xml -->
</w:r>
```

### Track Changes

Deletions and insertions are marked inline:
```xml
<w:del w:id="1" w:author="Stet" w:date="...">
  <w:r><w:delText>old text</w:delText></w:r>
</w:del>
<w:ins w:id="2" w:author="Stet" w:date="...">
  <w:r><w:t>new text</w:t></w:r>
</w:ins>
```

### ParaId

Every paragraph has a unique `w14:paraId` attribute - an 8-character hex string (e.g., `"01482C4A"`). This is used to:
- Link comments to their location
- Link replies to parent comments
- Track paragraph identity across edits

## Comparing Original vs Output

Look at these files to see what Stet changed:

1. **document.xml** - See added `<w:del>` and `<w:ins>` elements for track changes, and new comment anchors
2. **comments.xml** - See Stet's reply comments added
3. **commentsExtended.xml** - See how replies link to parents via `paraIdParent`
4. **commentsIds.xml** - See new durableIds for Stet's comments
5. **commentsExtensible.xml** - See UTC timestamps for new comments
