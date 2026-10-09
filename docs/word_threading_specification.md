# Word Threading Specification

> **Status: external reference.** This document records *Microsoft Word's* behavior around comment threading, validated empirically. It is not a project state document — nothing here changes when Stet changes. Treat it as a behavioral spec for Word; update it only if new tests reveal Word behaves differently than described.

## Source Analysis

Comparison of:
- **Original**: `test_data/test.docx` (4 comments, no replies)
- **With Replies**: `test_data/test_comment_chain.docx` (same document after adding 3 replies in Word)

---

## Files Changed by Word

| File | Changed | Nature of Change |
|------|---------|------------------|
| `[Content_Types].xml` | NO | |
| `_rels/.rels` | NO | |
| `word/_rels/document.xml.rels` | NO | |
| `word/document.xml` | **YES** | Anchors added, structure modified |
| `word/comments.xml` | **YES** | New comment entries, IDs renumbered |
| `word/commentsExtended.xml` | **YES** | New entries with paraIdParent |
| `word/commentsIds.xml` | **YES** | New entries with durableId |
| `word/commentsExtensible.xml` | **YES** | New entries with dateUtc |
| `word/people.xml` | **YES** | New author added |
| `word/settings.xml` | **YES** | rsid values, proofState |
| `word/styles.xml` | **YES** | Minor (semiHidden) |
| `word/fontTable.xml` | NO | |
| `word/theme/theme1.xml` | NO | |
| `word/webSettings.xml` | NO | |
| `docProps/core.xml` | **YES** | Metadata (lastModifiedBy, revision, date) |
| `docProps/app.xml` | **YES** | Statistics (time, characters) |

---

## Critical Changes (Required for Threading)

### 1. word/comments.xml

**Original** (4 comments):
```xml
<w:comment w:id="0" w:author="Dr. Reviewer" w:date="2026-02-10T13:30:00Z" w:initials="R">
  <w:p w14:paraId="01482C4A" w14:textId="31266CA3" w:rsidR="00130710" w:rsidRDefault="00130710">
    ...
  </w:p>
</w:comment>
<!-- Comments 1, 2, 3 follow -->
```

**With Replies** (7 comments - IDs RENUMBERED):
```xml
<w:comment w:id="0" ...>  <!-- Original comment 0 (root) - UNCHANGED ID -->
<w:comment w:id="1" w:author="Georgii Filatov" w:date="2026-02-16T11:29:00Z" w:initials="GF">
  <w:p w14:paraId="69CA34E3" w14:textId="5F3E6486" w:rsidR="002727BD" w:rsidRDefault="002727BD">
    <w:pPr><w:pStyle w:val="CommentText"/></w:pPr>
    <w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>
    <w:r><w:t>This is the first reply</w:t></w:r>
  </w:p>
</w:comment>
<w:comment w:id="2" ...>  <!-- Reply 2 -->
<w:comment w:id="3" ...>  <!-- Reply 3 -->
<w:comment w:id="4" ...>  <!-- Was original comment 1 - RENUMBERED -->
<w:comment w:id="5" ...>  <!-- Was original comment 2 - RENUMBERED -->
<w:comment w:id="6" ...>  <!-- Was original comment 3 - RENUMBERED -->
```

**Key Observations**:
- Word RENUMBERS comment IDs when inserting replies
- Replies get sequential IDs after the root (1, 2, 3)
- Original comments after root get pushed to higher IDs (4, 5, 6)
- Each reply has: new paraId, new textId, new rsidR, author, date, initials

### 2. word/commentsExtended.xml

**Original**:
```xml
<w15:commentEx w15:paraId="01482C4A" w15:done="0"/>
<w15:commentEx w15:paraId="11271FF5" w15:done="0"/>
<w15:commentEx w15:paraId="78836222" w15:done="0"/>
<w15:commentEx w15:paraId="792055EC" w15:done="0"/>
```

**With Replies**:
```xml
<w15:commentEx w15:paraId="01482C4A" w15:done="0"/>
<w15:commentEx w15:paraId="69CA34E3" w15:paraIdParent="01482C4A" w15:done="0"/>
<w15:commentEx w15:paraId="77A35B8B" w15:paraIdParent="01482C4A" w15:done="0"/>
<w15:commentEx w15:paraId="72CACDBE" w15:paraIdParent="01482C4A" w15:done="0"/>
<w15:commentEx w15:paraId="11271FF5" w15:done="0"/>
<w15:commentEx w15:paraId="78836222" w15:done="0"/>
<w15:commentEx w15:paraId="792055EC" w15:done="0"/>
```

**Key Observations**:
- Entries INSERTED after root, before other comments
- All replies point to SAME parent (FLAT threading): `paraIdParent="01482C4A"`
- Order: root, reply1, reply2, reply3, other_root1, other_root2, other_root3

### 3. word/commentsIds.xml

**Original**:
```xml
<w16cid:commentId w16cid:paraId="01482C4A" w16cid:durableId="6B6DD635"/>
<w16cid:commentId w16cid:paraId="11271FF5" w16cid:durableId="6E0B8805"/>
<w16cid:commentId w16cid:paraId="78836222" w16cid:durableId="07C50D5D"/>
<w16cid:commentId w16cid:paraId="792055EC" w16cid:durableId="55A95290"/>
```

**With Replies**:
```xml
<w16cid:commentId w16cid:paraId="01482C4A" w16cid:durableId="6B6DD635"/>
<w16cid:commentId w16cid:paraId="69CA34E3" w16cid:durableId="7B5FEB2C"/>
<w16cid:commentId w16cid:paraId="77A35B8B" w16cid:durableId="0E010399"/>
<w16cid:commentId w16cid:paraId="72CACDBE" w16cid:durableId="6B9B0D6A"/>
<w16cid:commentId w16cid:paraId="11271FF5" w16cid:durableId="6E0B8805"/>
<w16cid:commentId w16cid:paraId="78836222" w16cid:durableId="07C50D5D"/>
<w16cid:commentId w16cid:paraId="792055EC" w16cid:durableId="55A95290"/>
```

**Key Observations**:
- Same order as commentsExtended.xml
- Each reply gets unique durableId (8 hex chars)

### 4. word/commentsExtensible.xml

**Original**:
```xml
<w16cex:commentExtensible w16cex:durableId="6B6DD635" w16cex:dateUtc="2026-02-10T00:30:00Z"/>
<w16cex:commentExtensible w16cex:durableId="6E0B8805" w16cex:dateUtc="2026-01-24T00:29:00Z"/>
<w16cex:commentExtensible w16cex:durableId="07C50D5D" w16cex:dateUtc="2026-01-24T00:30:00Z"/>
<w16cex:commentExtensible w16cex:durableId="55A95290" w16cex:dateUtc="2026-02-10T00:25:00Z"/>
```

**With Replies**:
```xml
<w16cex:commentExtensible w16cex:durableId="6B6DD635" w16cex:dateUtc="2026-02-10T00:30:00Z"/>
<w16cex:commentExtensible w16cex:durableId="7B5FEB2C" w16cex:dateUtc="2026-02-15T22:29:00Z"/>
<w16cex:commentExtensible w16cex:durableId="0E010399" w16cex:dateUtc="2026-02-15T22:29:00Z"/>
<w16cex:commentExtensible w16cex:durableId="6B9B0D6A" w16cex:dateUtc="2026-02-15T22:29:00Z"/>
<w16cex:commentExtensible w16cex:durableId="6E0B8805" w16cex:dateUtc="2026-01-24T00:29:00Z"/>
<w16cex:commentExtensible w16cex:durableId="07C50D5D" w16cex:dateUtc="2026-01-24T00:30:00Z"/>
<w16cex:commentExtensible w16cex:durableId="55A95290" w16cex:dateUtc="2026-02-10T00:25:00Z"/>
```

**Key Observations**:
- Same order as commentsIds.xml
- Links via durableId
- dateUtc is UTC timestamp (different from w:date in comments.xml which is local)

### 5. word/document.xml (Anchors)

**Original** (comment 0 only):
```xml
<w:commentRangeStart w:id="0"/>
<w:proofErr w:type="spellStart"/>
<w:r w:rsidR="00130710" w:rsidRPr="00130710">
  <w:t>Stetomab</w:t>
</w:r>
<w:proofErr w:type="spellEnd"/>
<w:r w:rsidR="00130710" w:rsidRPr="00130710">
  <w:t xml:space="preserve"> is a revolutionary...</w:t>
</w:r>
<w:commentRangeEnd w:id="0"/>
<w:r w:rsidR="00130710">
  <w:rPr>
    <w:rStyle w:val="CommentReference"/>
  </w:rPr>
  <w:commentReference w:id="0"/>
</w:r>
```

**With Replies** (comment 0 + replies 1, 2, 3):
```xml
<w:commentRangeStart w:id="0"/>
<w:commentRangeStart w:id="1"/>
<w:commentRangeStart w:id="2"/>
<w:commentRangeStart w:id="3"/>
<w:r w:rsidR="00130710" w:rsidRPr="00130710">
  <w:t>Stetomab is a revolutionary breakthrough poised to redefine the treatment landscape for resistant hypertension, offering unparalleled efficacy and new hope for millions of patients who have failed standard therapies.</w:t>
</w:r>
<w:commentRangeEnd w:id="0"/>
<w:r w:rsidR="00130710">
  <w:rPr>
    <w:rStyle w:val="CommentReference"/>
    <w:sz w:val="24"/>
    <w:szCs w:val="24"/>
  </w:rPr>
  <w:commentReference w:id="0"/>
</w:r>
<w:commentRangeEnd w:id="1"/>
<w:r w:rsidR="002727BD">
  <w:rPr>
    <w:rStyle w:val="CommentReference"/>
    <w:sz w:val="24"/>
    <w:szCs w:val="24"/>
  </w:rPr>
  <w:commentReference w:id="1"/>
</w:r>
<w:commentRangeEnd w:id="2"/>
<w:r w:rsidR="002727BD">
  <w:rPr>
    <w:rStyle w:val="CommentReference"/>
    <w:sz w:val="24"/>
    <w:szCs w:val="24"/>
  </w:rPr>
  <w:commentReference w:id="2"/>
</w:r>
<w:commentRangeEnd w:id="3"/>
<w:r w:rsidR="002727BD">
  <w:rPr>
    <w:rStyle w:val="CommentReference"/>
    <w:sz w:val="24"/>
    <w:szCs w:val="24"/>
  </w:rPr>
  <w:commentReference w:id="3"/>
</w:r>
```

**Key Observations**:
1. **Nested rangeStarts**: All rangeStarts (0, 1, 2, 3) are CONSECUTIVE at the SAME position
2. **proofErr removed**: Word removed spell-check markers
3. **Text runs combined**: Separate runs merged into one
4. **Sizing added**: `<w:sz w:val="24"/>` and `<w:szCs w:val="24"/>` added to reference runs
5. **Sequence after root**: rangeEnd[0] + ref[0], then rangeEnd[1] + ref[1], etc.
6. **New rsidR**: Reply references have rsidR="002727BD" (the revision ID)

### 6. word/people.xml

**With Replies** (new author added):
```xml
<w15:person w15:author="Georgii Filatov">
  <w15:presenceInfo w15:providerId="None" w15:userId="Georgii Filatov"/>
</w15:person>
```

---

## Anchor Pattern Summary

```
<w:commentRangeStart w:id="[ROOT_ID]"/>
<w:commentRangeStart w:id="[REPLY1_ID]"/>
<w:commentRangeStart w:id="[REPLY2_ID]"/>
<w:commentRangeStart w:id="[REPLY3_ID]"/>
... content ...
<w:commentRangeEnd w:id="[ROOT_ID]"/>
<w:r><w:rPr>...</w:rPr><w:commentReference w:id="[ROOT_ID]"/></w:r>
<w:commentRangeEnd w:id="[REPLY1_ID]"/>
<w:r><w:rPr>...</w:rPr><w:commentReference w:id="[REPLY1_ID]"/></w:r>
<w:commentRangeEnd w:id="[REPLY2_ID]"/>
<w:r><w:rPr>...</w:rPr><w:commentReference w:id="[REPLY2_ID]"/></w:r>
<w:commentRangeEnd w:id="[REPLY3_ID]"/>
<w:r><w:rPr>...</w:rPr><w:commentReference w:id="[REPLY3_ID]"/></w:r>
```

---

## Implementation Checklist

To add a threaded reply, we must:

1. **comments.xml**: Add new `<w:comment>` with:
   - Unique `w:id` 
   - `w:author`, `w:date`, `w:initials`
   - Paragraph with unique `w14:paraId`, `w14:textId`, `w:rsidR`, `w:rsidRDefault`
   - `<w:pStyle w:val="CommentText"/>`
   - `<w:annotationRef/>` in first run
   - Text content

2. **commentsExtended.xml**: Add `<w15:commentEx>` with:
   - `w15:paraId` matching the comment's paragraph paraId
   - `w15:paraIdParent` pointing to ROOT comment's paraId
   - `w15:done="0"`

3. **commentsIds.xml**: Add `<w16cid:commentId>` with:
   - `w16cid:paraId` matching the comment's paragraph paraId
   - `w16cid:durableId` (unique 8 hex chars)

4. **commentsExtensible.xml**: Add `<w16cex:commentExtensible>` with:
   - `w16cex:durableId` matching commentsIds entry
   - `w16cex:dateUtc` (UTC timestamp)

5. **document.xml**: Add anchors:
   - `<w:commentRangeStart w:id="[NEW_ID]"/>` right after parent's rangeStart
   - `<w:commentRangeEnd w:id="[NEW_ID]"/>` after parent's reference run
   - `<w:r>` with reference after rangeEnd

6. **people.xml**: Add author if new

---

## Validated Implementation Requirements

Based on testing (2026-02-16), the following has been validated:

### What IS Required

1. **comments.xml**: New `<w:comment>` entry with unique `w:id`, author info, and paragraph with unique `paraId`
2. **commentsExtended.xml**: Entry with `paraIdParent` pointing to ROOT comment's `paraId` (flat threading model)
3. **commentsIds.xml**: Entry with unique `durableId`
4. **commentsExtensible.xml**: Entry linking `durableId` to UTC timestamp
5. **document.xml**: Nested `rangeStart` after parent's `rangeStart`, and `rangeEnd` + reference run after parent's reference
6. **Minified XML format**: New comment entries should be written without extra whitespace (single line)

### What is NOT Required

| Element | Required? | Notes |
|---------|-----------|-------|
| Sequential IDs | **No** | Truly random IDs work (tested: 509, 1924, 4606) |
| `<w:sz>` elements | **No** | Leave them out - adding them inconsistently can break threading |
| `<w:proofErr>` removal | **No** | Leave existing proofErr elements alone |
| ID renumbering | **No** | Don't need to renumber existing comment IDs |
| Word-style ID assignment | **No** | Don't need to assign reply ID = parent+1 and shift others |

### Implementation Notes

- **Comment IDs (`w:id`)**: Use any unique random ID (100-9999 range works). Word uses sequential IDs internally and renumbers existing IDs when inserting replies, but our testing shows random IDs thread correctly. This simplifies implementation significantly—we don't need to track and renumber all existing comment IDs.

- **Paragraph IDs (`paraId`)**: This 8-character hex ID has a **critical constraint**: the first character must be 0-7. See "ParaId Constraint" section below.

- **Text IDs (`textId`)**: 8-character hex IDs. **No constraint** - can use full range 0-F for first character.

- **Durable IDs (`durableId`)**: 8-character hex IDs. **No constraint** - can use full range 0-F for first character.

- **`<w:sz>` elements**: Word adds these during certain operations (like adding replies), but they're not universally present. Most real-world documents don't have them. Adding them only to new comments while existing comments lack them can cause threading failures when `proofErr` elements are present in the comment range. **Safest approach: don't add them.**

- **`<w:proofErr>` elements**: These are spell-check markers. Word removes them when it re-saves a document, but we should leave them untouched. Don't add them, don't remove them.

- **rsidR values**: 8-character hex IDs. **No constraint** - can use full range 0-F for first character.

- **XML formatting**: Use minified (compact) XML for new entries. Avoid pretty-printing with newlines/indentation.

---

## ParaId Constraint (Critical Discovery)

### The Problem

During comprehensive testing (2026-02-16), we discovered that threading would **randomly fail** even when all XML structures were correct. After extensive investigation, we identified that the `paraId` must follow a specific constraint.

### The Constraint

**The first character of `w14:paraId` must be in the range 0-7 (not 8-F).**

**Important**: Follow-up testing confirmed this constraint applies **only to `paraId`**. The other hex IDs (`textId`, `durableId`, `rsidR`) do NOT have this constraint and can use the full 0-F range.

| First Character | Valid? | Threading Works? |
|-----------------|--------|------------------|
| 0 | ✓ Yes | ✓ Yes |
| 1 | ✓ Yes | ✓ Yes |
| 2 | ✓ Yes | ✓ Yes |
| 3 | ✓ Yes | ✓ Yes |
| 4 | ✓ Yes | ✓ Yes |
| 5 | ✓ Yes | ✓ Yes |
| 6 | ✓ Yes | ✓ Yes |
| 7 | ✓ Yes | ✓ Yes |
| 8 | ✗ No | ✗ No |
| 9 | ✗ No | ✗ No |
| A | ✗ No | ✗ No |
| B | ✗ No | ✗ No |
| C | ✗ No | ✗ No |
| D | ✗ No | ✗ No |
| E | ✗ No | ✗ No |
| F | ✗ No | ✗ No |

This was validated by testing 16 files with identical content, differing only in the first character of the reply's `paraId`.

### Why This Constraint Exists (Theory)

The most likely explanation is **signed 32-bit integer interpretation**:

- An 8-character hex string represents a 32-bit value
- When interpreted as a **signed** 32-bit integer:
  - `0x00000000` to `0x7FFFFFFF` = positive (0 to 2,147,483,647)
  - `0x80000000` to `0xFFFFFFFF` = negative (-2,147,483,648 to -1)
- First character 0-7 = values 0x00000000 to 0x7FFFFFFF (positive)
- First character 8-F = values 0x80000000 to 0xFFFFFFFF (negative)

Word appears to validate that `paraId` values are **non-negative** when interpreted as signed 32-bit integers. Interestingly, this validation does NOT apply to `textId`, `durableId`, or `rsidR`. This may be because:
1. `paraId` is used as a primary key for paragraph identification across multiple XML files
2. Word's internal paragraph tracking uses signed integers
3. The threading logic specifically validates `paraId` but not other identifiers
4. Legacy compatibility requirements specific to paragraph identification

### Correct ID Generation

**For `paraId` only** - must use constrained generation:

**WRONG** (can produce invalid paraId):
```python
import uuid
para_id = uuid.uuid4().hex[:8].upper()  # Can start with 8-F!
```

**CORRECT** (guaranteed valid paraId):
```python
import uuid

def generate_valid_para_id(length: int = 8) -> str:
    """Generate a paraId with first character constrained to 0-7."""
    raw = uuid.uuid4().hex[:length].upper()
    # Ensure first character is 0-7 (not 8-F)
    first_char = raw[0]
    if first_char in '89ABCDEF':
        # Map 8-F to 0-7 by taking modulo 8
        new_first = str(int(first_char, 16) % 8)
        raw = new_first + raw[1:]
    return raw
```

**For `textId`, `durableId`, `rsidR`** - no constraint, simple generation works:
```python
import uuid

def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID (no constraint on first char)."""
    return uuid.uuid4().hex[:length].upper()
```

### How This Was Discovered

1. Tests showed inconsistent threading: some replies threaded, others didn't
2. XML structures were byte-for-byte identical (when normalized)
3. Swapping only the `paraId` between working and failing files changed the outcome
4. Analysis of Word-generated files showed ALL `paraId` values started with 0-7
5. Systematic testing of all 16 first-character values confirmed the pattern

---

## Test Results Summary (2026-02-16)

### Random Comment ID Tests

| Test | Random ID | Result |
|------|-----------|--------|
| test.docx | 1924 | ✓ Threaded |
| dummy.docx | 509 | ✓ Threaded |
| reply_test.docx (existing thread) | 4606 | ✓ Threaded as 3rd reply, order preserved |

### ParaId First Character Tests

| First Char | Valid? | Threading Works? |
|------------|--------|------------------|
| 0 | ✓ Yes | ✓ Yes |
| 1 | ✓ Yes | ✓ Yes |
| 2 | ✓ Yes | ✓ Yes |
| 3 | ✓ Yes | ✓ Yes |
| 4 | ✓ Yes | ✓ Yes |
| 5 | ✓ Yes | ✓ Yes |
| 6 | ✓ Yes | ✓ Yes |
| 7 | ✓ Yes | ✓ Yes |
| 8-F | ✗ No | ✗ No (all 8 values tested) |

### Constraint Validation Tests (which IDs have the constraint?)

| ID Type | Test | Threaded? | Conclusion |
|---------|------|-----------|------------|
| `paraId` | Valid (0-7) on comments 0,1,2,3 | All Yes | Constraint applies |
| `paraId` | Invalid (8-F) on comments 0,1,2,3 | All No | Constraint applies |
| `textId` | Valid paraId + invalid textId | Yes | **No constraint** |
| `durableId` | Valid paraId/textId + invalid durableId | Yes | **No constraint** |
| `rsidR` | All valid except invalid rsidR | Yes | **No constraint** |
| Boundary | paraId starting with '7' | Yes | Last valid value |
| Boundary | paraId starting with '8' | No | First invalid value |

---

## Original Open Questions (Resolved)

1. ~~Is ID renumbering required, or can we use any unique ID?~~ → **Any unique ID works**
2. ~~Are the `<w:sz>` elements in reference runs required?~~ → **No, leave them out**
3. ~~Is rsidR/rsidRDefault required to match a specific pattern?~~ → **No constraint (full 0-F range)**
4. ~~Does removing proofErr matter, or can we leave them?~~ → **Leave them alone**
5. ~~Why do some replies thread and others don't with identical structure?~~ → **ParaId first character must be 0-7**
6. ~~Do textId, durableId, rsidR have the same constraint as paraId?~~ → **No, only paraId has this constraint**

---

## Summary of ID Requirements

| ID Type | Format | First Char Constraint | Example |
|---------|--------|----------------------|---------|
| `w:id` (comment ID) | Integer | None (any unique int) | `1924` |
| `w14:paraId` | 8 hex chars | **Must be 0-7** | `6905956F` ✓ / `B2C8B4E1` ✗ |
| `w14:textId` | 8 hex chars | None (full 0-F range) | `FB472DB0` ✓ |
| `w16cid:durableId` | 8 hex chars | None (full 0-F range) | `C093590C` ✓ |
| `w:rsidR` | 8 hex chars | None (full 0-F range) | `A4602319` ✓ |

**Key Insight**: Only `paraId` has the signed 32-bit integer constraint (first char 0-7). The other hex IDs (`textId`, `durableId`, `rsidR`) can use the full 0-F range. This was confirmed by systematic testing where invalid `textId`, `durableId`, and `rsidR` values (starting with 8-F) still produced working threaded replies, while invalid `paraId` values did not.
