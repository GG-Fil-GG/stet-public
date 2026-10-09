#!/usr/bin/env python3
"""
XML Assumption Tests for DOCX Comment Threading

This script creates modified DOCX files to test specific assumptions about
how Word handles comment threading, anchors, and track changes.

Each test produces a separate DOCX file that can be opened in Word to
verify the expected behavior.

Usage:
    python scripts/xml_assumption_tests.py

Output:
    output/xml_tests/test_1_*.docx
    output/xml_tests/test_2_*.docx
    ...
"""

import zipfile
import shutil
import re
from pathlib import Path
from datetime import datetime
import uuid


# Paths
PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DOCX = PROJECT_ROOT / "test_data" / "test.docx"
OUTPUT_DIR = PROJECT_ROOT / "output" / "xml_tests"


def generate_para_id() -> str:
    """Generate a random 8-character hex paraId."""
    return uuid.uuid4().hex[:8].upper()


def generate_durable_id() -> str:
    """Generate a random 8-character hex durableId."""
    return uuid.uuid4().hex[:8].upper()


def read_xml_from_docx(docx_path: Path, xml_part: str) -> str:
    """Read and return an XML part from a DOCX file."""
    with zipfile.ZipFile(docx_path, 'r') as zf:
        return zf.read(xml_part).decode('utf-8')


def create_modified_docx(
    source_path: Path,
    output_path: Path,
    modifications: dict
) -> None:
    """
    Create a modified DOCX by copying source and replacing specific XML parts.
    
    Args:
        source_path: Path to source DOCX
        output_path: Path for output DOCX
        modifications: Dict of {xml_part_path: new_content}
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(source_path, 'r') as zin:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                if item in modifications:
                    zout.writestr(item, modifications[item].encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item))


def get_original_comment_info(docx_path: Path) -> dict:
    """Extract info about existing comments from the source document."""
    comments_xml = read_xml_from_docx(docx_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(docx_path, 'word/commentsExtended.xml')
    
    # Extract comment IDs and paraIds
    comment_matches = re.findall(r'<w:comment w:id="(\d+)"[^>]*>', comments_xml)
    para_id_matches = re.findall(r'w14:paraId="([A-F0-9]+)"', comments_xml)
    
    return {
        'comment_ids': comment_matches,
        'para_ids': para_id_matches,
        'max_comment_id': max(int(c) for c in comment_matches) if comment_matches else -1
    }


# =============================================================================
# TEST CASE GENERATORS
# =============================================================================

def test_1_reply_identical_anchor(source_path: Path, output_path: Path) -> str:
    """
    TEST 1: Reply with IDENTICAL anchor to parent
    
    Hypothesis: If a reply has the exact same commentRangeStart/End positions
    as its parent, Word should show it as a threaded reply.
    
    This is the ideal case - replies share their parent's anchor.
    """
    info = get_original_comment_info(source_path)
    
    # We'll add a reply to comment 0 (first comment)
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]  # paraId of comment 0's paragraph
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 1. Modify comments.xml - add new comment
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 1: Reply with identical anchor to parent</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2. Modify commentsExtended.xml - add threading link
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    # 3. Modify commentsIds.xml - add durable ID
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_id = f'''  <w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>
</w16cid:commentsIds>'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_id)
    
    # 4. Modify commentsExtensible.xml - add timestamp
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = f'''  <w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{timestamp}"/>
</w16cex:commentsExtensible>'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible)
    
    # 5. Modify document.xml - add anchor at SAME position as parent
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Find parent's commentRangeEnd and add our markers right after parent's
    parent_range_end = f'<w:commentRangeEnd w:id="{parent_comment_id}"/>'
    new_anchor = f'{parent_range_end}<w:commentRangeStart w:id="{new_comment_id}"/><w:commentRangeEnd w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_range_end, new_anchor)
    
    # Add commentReference after parent's
    parent_ref_pattern = f'<w:commentReference w:id="{parent_comment_id}"/>'
    new_ref = f'''{parent_ref_pattern}</w:r><w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/></w:r><w:r'''
    # Simpler approach - just add after the closing </w:r> that contains parent ref
    parent_ref_end = f'<w:commentReference w:id="{parent_comment_id}"/></w:r>'
    new_ref = f'{parent_ref_end}<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_ref_end, new_ref)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply with IDENTICAL anchor position to parent (immediately after parent's rangeEnd)"


def test_2_reply_no_anchor(source_path: Path, output_path: Path) -> str:
    """
    TEST 2: Reply with NO anchor in document.xml
    
    Hypothesis: Maybe Word only needs commentsExtended.xml threading info,
    and the reply doesn't need its own anchor at all?
    
    This would be the simplest case if it works.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 1. comments.xml - add comment
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 2: Reply with NO anchor in document.xml</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2. commentsExtended.xml - add threading
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    # 3. commentsIds.xml
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_id = f'''  <w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>
</w16cid:commentsIds>'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_id)
    
    # 4. commentsExtensible.xml
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = f'''  <w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{timestamp}"/>
</w16cex:commentsExtensible>'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible)
    
    # 5. document.xml - NO CHANGES (no anchor for the reply)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
    })
    
    return "Reply with NO anchor in document.xml (only threading in commentsExtended.xml)"


def test_3_reply_different_paragraph(source_path: Path, output_path: Path) -> str:
    """
    TEST 3: Reply with anchor in DIFFERENT paragraph than parent
    
    Hypothesis: This should show as a standalone comment, not a reply,
    because the anchor is in a completely different location.
    
    This tests whether anchor position matters for threading.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Read document.xml to find a different paragraph
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Find comment 3's anchor (last comment, different paragraph)
    # We'll add our reply's anchor near comment 3 instead of comment 0
    
    # 1. comments.xml
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 3: Reply with anchor in DIFFERENT paragraph</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2. commentsExtended.xml - STILL links to comment 0 as parent
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    # 3-4. IDs and extensible
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_id = f'''  <w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>
</w16cid:commentsIds>'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_id)
    
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = f'''  <w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{timestamp}"/>
</w16cex:commentsExtensible>'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible)
    
    # 5. document.xml - anchor near comment 3 (different paragraph)
    # Add anchor after comment 3's rangeEnd
    other_comment_id = "3"
    other_range_end = f'<w:commentRangeEnd w:id="{other_comment_id}"/>'
    new_anchor = f'{other_range_end}<w:commentRangeStart w:id="{new_comment_id}"/><w:commentRangeEnd w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(other_range_end, new_anchor)
    
    # Add reference after comment 3's reference
    other_ref_end = f'<w:commentReference w:id="{other_comment_id}"/></w:r>'
    new_ref = f'{other_ref_end}<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(other_ref_end, new_ref)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply threaded to comment 0 but ANCHOR placed near comment 3 (different paragraph)"


def test_4_threading_only_no_durable_id(source_path: Path, output_path: Path) -> str:
    """
    TEST 4: Reply with threading but NO entry in commentsIds.xml
    
    Hypothesis: Test whether durableId is required for threading to work.
    
    Some older Word versions might not use commentsIds.xml.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 1. comments.xml
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 4: Reply with NO durableId entry</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2. commentsExtended.xml - threading only
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    # 3. NO commentsIds.xml modification
    # 4. NO commentsExtensible.xml modification
    
    # 5. document.xml - add anchor
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    parent_range_end = f'<w:commentRangeEnd w:id="{parent_comment_id}"/>'
    new_anchor = f'{parent_range_end}<w:commentRangeStart w:id="{new_comment_id}"/><w:commentRangeEnd w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_range_end, new_anchor)
    
    parent_ref_end = f'<w:commentReference w:id="{parent_comment_id}"/></w:r>'
    new_ref = f'{parent_ref_end}<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_ref_end, new_ref)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply with threading but NO entries in commentsIds.xml or commentsExtensible.xml"


def test_5_multiple_replies_same_parent(source_path: Path, output_path: Path) -> str:
    """
    TEST 5: Multiple replies to the same parent comment
    
    Hypothesis: Word should show all replies as a thread under the parent.
    
    Tests whether reply ordering is by date or by position in XML.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    replies = []
    for i, label in enumerate(["First reply", "Second reply", "Third reply"]):
        replies.append({
            'comment_id': str(info['max_comment_id'] + 1 + i),
            'para_id': generate_para_id(),
            'durable_id': generate_durable_id(),
            'text': f"TEST 5: {label}",
            # Stagger timestamps by 1 minute
            'timestamp': f"2026-02-12T10:{10+i}:00Z"
        })
    
    # 1. comments.xml
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comments = ""
    for r in replies:
        new_comments += f'''
  <w:comment w:id="{r['comment_id']}" w:author="Test" w:date="{r['timestamp']}" w:initials="T">
    <w:p w14:paraId="{r['para_id']}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>{r['text']}</w:t>
      </w:r>
    </w:p>
  </w:comment>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comments + '\n</w:comments>')
    
    # 2. commentsExtended.xml
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = ""
    for r in replies:
        new_extended += f'''  <w15:commentEx w15:paraId="{r['para_id']}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended + '</w15:commentsEx>')
    
    # 3. commentsIds.xml
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_ids = ""
    for r in replies:
        new_ids += f'''  <w16cid:commentId w16cid:paraId="{r['para_id']}" w16cid:durableId="{r['durable_id']}"/>
'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_ids + '</w16cid:commentsIds>')
    
    # 4. commentsExtensible.xml
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = ""
    for r in replies:
        new_extensible += f'''  <w16cex:commentExtensible w16cex:durableId="{r['durable_id']}" w16cex:dateUtc="{r['timestamp']}"/>
'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible + '</w16cex:commentsExtensible>')
    
    # 5. document.xml - add all anchors
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Add all range markers after parent's rangeEnd
    parent_range_end = f'<w:commentRangeEnd w:id="{parent_comment_id}"/>'
    new_anchors = parent_range_end
    for r in replies:
        new_anchors += f'<w:commentRangeStart w:id="{r["comment_id"]}"/><w:commentRangeEnd w:id="{r["comment_id"]}"/>'
    doc_xml = doc_xml.replace(parent_range_end, new_anchors)
    
    # Add all references
    parent_ref_end = f'<w:commentReference w:id="{parent_comment_id}"/></w:r>'
    new_refs = parent_ref_end
    for r in replies:
        new_refs += f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{r["comment_id"]}"/></w:r>'
    # Need to handle the closing </w:r> properly
    doc_xml = doc_xml.replace(parent_ref_end, new_refs)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "THREE replies to the same parent (comment 0), with staggered timestamps"


def test_6_reply_spanning_text(source_path: Path, output_path: Path) -> str:
    """
    TEST 6: Reply with anchor that spans actual text (not zero-width)
    
    Hypothesis: The reply's anchor spans the same text as the parent.
    
    Tests whether spanning the same text helps with threading.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 1. comments.xml
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 6: Reply with anchor SPANNING same text as parent</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2-4. Standard threading setup
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_id = f'''  <w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>
</w16cid:commentsIds>'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_id)
    
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = f'''  <w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{timestamp}"/>
</w16cex:commentsExtensible>'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible)
    
    # 5. document.xml - insert rangeStart right after parent's rangeStart
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Insert our rangeStart right after parent's rangeStart
    parent_range_start = f'<w:commentRangeStart w:id="{parent_comment_id}"/>'
    doc_xml = doc_xml.replace(
        parent_range_start,
        f'{parent_range_start}<w:commentRangeStart w:id="{new_comment_id}"/>'
    )
    
    # Insert our rangeEnd right after parent's rangeEnd
    parent_range_end = f'<w:commentRangeEnd w:id="{parent_comment_id}"/>'
    doc_xml = doc_xml.replace(
        parent_range_end,
        f'{parent_range_end}<w:commentRangeEnd w:id="{new_comment_id}"/>'
    )
    
    # Add reference
    parent_ref_end = f'<w:commentReference w:id="{parent_comment_id}"/></w:r>'
    new_ref = f'{parent_ref_end}<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_ref_end, new_ref)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply with anchor SPANNING the same text as parent (rangeStart after parent's, rangeEnd after parent's)"


def test_7_track_change_inside_comment(source_path: Path, output_path: Path) -> str:
    """
    TEST 7: Track change (insertion) inside a comment's anchored range
    
    Hypothesis: Adding a track change inside a comment range shouldn't
    break the comment.
    
    Tests track changes + comments interaction.
    """
    # Just modify document.xml to add a track change inside comment 0's range
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Find the text "Stetomab" which is inside comment 0's range
    # Add an insertion after it
    insertion = f'''<w:ins w:id="99" w:author="Test" w:date="{timestamp}">
<w:r><w:t> [INSERTED TEXT]</w:t></w:r>
</w:ins>'''
    
    # Insert after "Stetomab" - look for the closing </w:t> after it
    doc_xml = doc_xml.replace(
        '<w:t>Stetomab</w:t>',
        f'<w:t>Stetomab</w:t></w:r>{insertion}<w:r'
    )
    
    create_modified_docx(source_path, output_path, {
        'word/document.xml': doc_xml,
    })
    
    return "Track change (insertion) INSIDE comment 0's anchored range"


def test_8_nested_comment_range(source_path: Path, output_path: Path) -> str:
    """
    TEST 8: Reply anchor completely INSIDE parent's anchor range
    
    Hypothesis: If the reply's range is a subset of parent's range,
    it should still thread correctly.
    
    Tests nested anchor ranges.
    """
    info = get_original_comment_info(source_path)
    
    parent_comment_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_comment_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # 1. comments.xml
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    new_comment = f'''
  <w:comment w:id="{new_comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{new_para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:r>
        <w:t>TEST 8: Reply with anchor NESTED inside parent's range</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    comments_xml = comments_xml.replace('</w:comments>', new_comment)
    
    # 2-4. Standard threading
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    new_extended = f'''  <w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>
</w15:commentsEx>'''
    extended_xml = extended_xml.replace('</w15:commentsEx>', new_extended)
    
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    new_id = f'''  <w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>
</w16cid:commentsIds>'''
    ids_xml = ids_xml.replace('</w16cid:commentsIds>', new_id)
    
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    new_extensible = f'''  <w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{timestamp}"/>
</w16cex:commentsExtensible>'''
    extensible_xml = extensible_xml.replace('</w16cex:commentsExtensible>', new_extensible)
    
    # 5. document.xml - put reply anchor INSIDE parent's range (around just "Stetomab")
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Add rangeStart before "Stetomab" and rangeEnd after it
    # This makes the reply reference just "Stetomab" while parent references the whole sentence
    doc_xml = doc_xml.replace(
        '<w:t>Stetomab</w:t>',
        f'<w:commentRangeStart w:id="{new_comment_id}"/><w:t>Stetomab</w:t></w:r><w:commentRangeEnd w:id="{new_comment_id}"/><w:r'
    )
    
    # Add reference at end of paragraph
    parent_ref_end = f'<w:commentReference w:id="{parent_comment_id}"/></w:r>'
    new_ref = f'{parent_ref_end}<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/>'
    doc_xml = doc_xml.replace(parent_ref_end, new_ref)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply with anchor NESTED inside parent's range (only references 'Stetomab', parent references whole sentence)"


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all tests and generate output files."""
    
    if not SOURCE_DOCX.exists():
        print(f"ERROR: Source file not found: {SOURCE_DOCX}")
        return 1
    
    # Clean and create output directory
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)
    
    # Define all tests
    tests = [
        (test_1_reply_identical_anchor, "identical_anchor"),
        (test_2_reply_no_anchor, "no_anchor"),
        (test_3_reply_different_paragraph, "different_paragraph"),
        (test_4_threading_only_no_durable_id, "no_durable_id"),
        (test_5_multiple_replies_same_parent, "multiple_replies"),
        (test_6_reply_spanning_text, "spanning_text"),
        (test_7_track_change_inside_comment, "track_change_inside"),
        (test_8_nested_comment_range, "nested_range"),
    ]
    
    print("=" * 70)
    print("DOCX XML ASSUMPTION TESTS")
    print("=" * 70)
    print(f"\nSource: {SOURCE_DOCX}")
    print(f"Output: {OUTPUT_DIR}/")
    print()
    
    results = []
    
    for i, (test_func, name) in enumerate(tests, 1):
        output_file = OUTPUT_DIR / f"test_{i}_{name}.docx"
        try:
            description = test_func(SOURCE_DOCX, output_file)
            results.append((i, name, "SUCCESS", description))
            print(f"[TEST {i}] {name}: Created")
        except Exception as e:
            results.append((i, name, "ERROR", str(e)))
            print(f"[TEST {i}] {name}: ERROR - {e}")
    
    # Write results summary
    summary_file = OUTPUT_DIR / "TEST_RESULTS.md"
    with open(summary_file, 'w') as f:
        f.write("# XML Assumption Test Results\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write("## Test Files\n\n")
        f.write("Open each file in Microsoft Word and record the observed behavior.\n\n")
        f.write("| Test | File | Description | Expected | Actual |\n")
        f.write("|------|------|-------------|----------|--------|\n")
        
        expected = [
            "Threaded reply",
            "Threaded reply (or error?)",
            "Standalone comment",
            "Threaded (or error?)",
            "3 threaded replies in order",
            "Threaded reply",
            "Comment intact with track change",
            "Threaded reply",
        ]
        
        for (i, name, status, desc), exp in zip(results, expected):
            if status == "SUCCESS":
                f.write(f"| {i} | test_{i}_{name}.docx | {desc} | {exp} | _____ |\n")
            else:
                f.write(f"| {i} | ERROR | {desc} | - | - |\n")
        
        f.write("\n## How to Test\n\n")
        f.write("1. Open each .docx file in Microsoft Word\n")
        f.write("2. Look at the Comments pane\n")
        f.write("3. For threading tests: Does the test comment appear as a reply under the original?\n")
        f.write("4. For track change tests: Is the comment still visible and anchored correctly?\n")
        f.write("5. Record your observations in the 'Actual' column\n")
        f.write("\n## Key Questions\n\n")
        f.write("- Is `paraIdParent` in commentsExtended.xml sufficient for threading?\n")
        f.write("- Does anchor position matter for threading?\n")
        f.write("- Can we omit commentsIds.xml entries?\n")
        f.write("- How does Word order multiple replies?\n")
    
    print()
    print("=" * 70)
    print(f"Generated {len([r for r in results if r[2] == 'SUCCESS'])} test files")
    print(f"Results summary: {summary_file}")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Open each .docx file in Microsoft Word")
    print("2. Check the Comments pane")
    print("3. Record observations in TEST_RESULTS.md")
    
    return 0


if __name__ == "__main__":
    exit(main())
