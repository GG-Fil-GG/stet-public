# How Microsoft Word Stores Comments

This document describes the internal XML structure that Word uses to store comments in `.docx` files. This knowledge was hard-won through extensive trial and error while building the comment reply insertion feature.

## Overview

A `.docx` file is actually a ZIP archive containing XML files. Comments are stored across **five different XML files**, all of which must be updated correctly for a comment (or reply) to be visible in Word.

| File | Purpose |
|------|---------|
| `word/comments.xml` | The actual comment content |
| `word/commentsExtended.xml` | Thread relationships (parent-child linking) |
| `word/commentsIds.xml` | Persistent/durable IDs |
| `word/commentsExtensible.xml` | Extended metadata (Word 2018+) |
| `word/document.xml` | **Anchors** - where comments attach to text |

## File Details

### 1. `word/comments.xml`

Contains the actual comment elements with their text content.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="..." xmlns:w14="...">
  <w:comment w:id="43" w:author="Reviewer Name" w:date="2025-01-01T12:00:00Z" w:initials="RN">
    <w:p w14:paraId="020FFB22" w14:textId="77777777" w:rsidR="00DA6F6A" w:rsidRDefault="00DA6F6A">
      <w:pPr><w:pStyle w:val="CommentText"/></w:pPr>
      <w:r>
        <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
        <w:annotationRef/>
      </w:r>
      <w:r>
        <w:t>This is the comment text.</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>
```

**Key attributes:**
- `w:id` - Unique numeric ID for the comment
- `w:author` - Display name of the commenter
- `w:date` - ISO timestamp
- `w:initials` - Author's initials
- `w14:paraId` - Unique paragraph ID (8-char hex) - **CRITICAL for linking**
- `w14:textId` - Text ID (can be "77777777" for generated comments)
- `w:rsidR`, `w:rsidRDefault` - Revision Save IDs (track editing sessions)

**Important elements inside `<w:p>`:**
- `<w:pStyle w:val="CommentText"/>` - Required paragraph style
- `<w:annotationRef/>` - Required marker that this is a comment annotation

### 2. `word/commentsExtended.xml`

Links comments into threads using `paraId` references.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w15:commentsEx xmlns:w15="...">
  <w15:commentEx w15:paraId="020FFB22" w15:done="0"/>
  <w15:commentEx w15:paraId="A1B2C3D4" w15:paraIdParent="020FFB22" w15:done="0"/>
</w15:commentsEx>
```

**Key attributes:**
- `w15:paraId` - Matches the `w14:paraId` from `comments.xml`
- `w15:paraIdParent` - For replies: the `paraId` of the parent comment
- `w15:done` - Resolution status ("0" = open, "1" = resolved)

**Critical discovery:** The ORDER of entries matters. Replies should be positioned **immediately after their parent**, not appended at the end.

### 3. `word/commentsIds.xml`

Maps `paraId` to persistent `durableId` values.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cid:commentsIds xmlns:w16cid="...">
  <w16cid:commentId w16cid:paraId="020FFB22" w16cid:durableId="12345678"/>
  <w16cid:commentId w16cid:paraId="A1B2C3D4" w16cid:durableId="87654321"/>
</w16cid:commentsIds>
```

**Key attributes:**
- `w16cid:paraId` - Must match the other files
- `w16cid:durableId` - A persistent ID (8-char hex) that survives copy/paste

**Order matters here too** - should match `commentsExtended.xml` order.

### 4. `word/commentsExtensible.xml`

Extended metadata for Word 2018 and later.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w16cex:commentsExtensible xmlns:w16cex="...">
  <w16cex:commentExtensible w16cex:durableId="12345678" w16cex:dateUtc="2025-01-01T12:00:00Z"/>
</w16cex:commentsExtensible>
```

**Key attributes:**
- `w16cex:durableId` - Must match `commentsIds.xml`
- `w16cex:dateUtc` - UTC timestamp

### 5. `word/document.xml` - THE CRITICAL FILE

This is where comments are **anchored** to the document text. Without proper anchors, Word will silently delete comments when saving.

```xml
<w:p>
  <w:r>
    <w:t>Some text before </w:t>
  </w:r>
  <w:commentRangeStart w:id="43"/>
  <w:commentRangeStart w:id="459"/>  <!-- Reply's range start -->
  <w:r>
    <w:t>highlighted text</w:t>
  </w:r>
  <w:commentRangeEnd w:id="43"/>
  <w:r>
    <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
    <w:commentReference w:id="43"/>
  </w:r>
  <w:commentRangeEnd w:id="459"/>    <!-- Reply's range end -->
  <w:r w:rsidR="69D867CC">
    <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
    <w:commentReference w:id="459"/>  <!-- Reply's reference -->
  </w:r>
  <w:r>
    <w:t> some text after.</w:t>
  </w:r>
</w:p>
```

**Key elements:**
- `<w:commentRangeStart w:id="X"/>` - Marks where commented text begins
- `<w:commentRangeEnd w:id="X"/>` - Marks where commented text ends
- `<w:commentReference w:id="X"/>` - Links to the comment (inside a run with `CommentReference` style)

**Critical for replies:** Reply anchors must be placed at the **same location** as the parent comment's anchor. The reply's `commentRangeStart` goes right after the parent's, and the `commentRangeEnd` + `commentReference` go right after the parent's reference.

## Adding a Comment Reply: Complete Checklist

To programmatically add a reply to an existing comment:

### Step 1: Generate IDs
- `new_comment_id` - Next available numeric ID (max existing + 1)
- `new_para_id` - Random 8-char uppercase hex (e.g., "A1B2C3D4")
- `new_durable_id` - Random 8-char uppercase hex
- `rsid` - Random 8-char uppercase hex for revision tracking

### Step 2: Update `comments.xml`
Insert new `<w:comment>` element **immediately after the parent comment**:
```xml
<w:comment w:id="459" w:author="Author" w:date="2025-01-01T12:00:00Z" w:initials="AU">
  <w:p w14:paraId="A1B2C3D4" w14:textId="77777777" w:rsidR="RSID" w:rsidRDefault="RSID">
    <w:pPr><w:pStyle w:val="CommentText"/></w:pPr>
    <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>
    <w:r><w:t>Reply text here</w:t></w:r>
  </w:p>
</w:comment>
```

### Step 3: Update `commentsExtended.xml`
Insert **immediately after parent's entry**:
```xml
<w15:commentEx w15:paraId="A1B2C3D4" w15:paraIdParent="020FFB22" w15:done="0"/>
```

### Step 4: Update `commentsIds.xml`
Insert **in same relative position**:
```xml
<w16cid:commentId w16cid:paraId="A1B2C3D4" w16cid:durableId="DURABLE"/>
```

### Step 5: Update `commentsExtensible.xml`
Append (order less critical here):
```xml
<w16cex:commentExtensible w16cex:durableId="DURABLE" w16cex:dateUtc="2025-01-01T12:00:00Z"/>
```

### Step 6: Update `document.xml` (CRITICAL!)
Find the parent's anchor and add reply's anchor elements:

1. Find `<w:commentRangeStart w:id="PARENT_ID"/>`
2. Insert `<w:commentRangeStart w:id="NEW_ID"/>` right after it
3. Find parent's `<w:commentReference w:id="PARENT_ID"/>`
4. After the `</w:r>` that contains it, insert:
   ```xml
   <w:commentRangeEnd w:id="NEW_ID"/>
   <w:r w:rsidR="RSID">
     <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
     <w:commentReference w:id="NEW_ID"/>
   </w:r>
   ```

## Common Pitfalls

### 1. Missing `document.xml` anchor
**Symptom:** Comment appears to be added (visible in XML) but Word deletes it on save.
**Cause:** Word validates that comments have anchors in the document.
**Fix:** Add `commentRangeStart`, `commentRangeEnd`, and `commentReference` to `document.xml`.

### 2. Wrong order in XML files
**Symptom:** Reply doesn't appear as a reply, or appears disconnected.
**Cause:** Entries appended at end instead of after parent.
**Fix:** Insert entries at correct position (after parent's entry).

### 3. Missing `paraId` consistency
**Symptom:** Word reports file corruption or removes entries.
**Cause:** The `paraId` in `<w:p>` inside `comments.xml` doesn't match `commentsExtended.xml`.
**Fix:** Use the same generated `paraId` in all files.

### 4. Missing `rsid` attributes
**Symptom:** Word may repair or modify the file unexpectedly.
**Cause:** Missing `w:rsidR` and `w:rsidRDefault` attributes.
**Fix:** Generate and include RSID values.

### 5. Missing `commentsExtensible.xml` entry
**Symptom:** Works in older Word versions but not Word 2018+.
**Cause:** This file is required for modern Word.
**Fix:** Add entry with `durableId` and `dateUtc`.

## Namespace Reference

| Prefix | Namespace URI |
|--------|---------------|
| `w` | `http://schemas.openxmlformats.org/wordprocessingml/2006/main` |
| `w14` | `http://schemas.microsoft.com/office/word/2010/wordml` |
| `w15` | `http://schemas.microsoft.com/office/word/2012/wordml` |
| `w16cid` | `http://schemas.microsoft.com/office/word/2016/wordml/cid` |
| `w16cex` | `http://schemas.microsoft.com/office/word/2018/wordml/cex` |

## Tools for Debugging

1. **Unzip the `.docx`:** `unzip document.docx -d extracted/`
2. **Compare files:** `diff original/word/comments.xml modified/word/comments.xml`
3. **Pretty-print XML:** `xmllint --format comments.xml`
4. **Count entries:** Check that all 4 comment files have the same number of entries

## References

- [ECMA-376 Office Open XML](https://www.ecma-international.org/publications-and-standards/standards/ecma-376/)
- Word's XML is proprietary but follows Open XML standards with Microsoft extensions

---

*Document created: January 2026*
*Based on reverse-engineering Word 2024 for macOS*

