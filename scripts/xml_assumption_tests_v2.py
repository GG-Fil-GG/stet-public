#!/usr/bin/env python3
"""
XML Assumption Tests v2 - Fixed XML generation

This version fixes the XML structure issues from v1 and adds new tests
based on findings:
- Test 2 showed: Anchors ARE required (no anchor = invisible reply)
- Test 5 showed: Only first reply threads when all point to same parent

New hypothesis: Replies should chain (each points to previous), not all to root.
"""

import zipfile
import shutil
import re
from pathlib import Path
from datetime import datetime
import uuid


PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DOCX = PROJECT_ROOT / "test_data" / "test.docx"
OUTPUT_DIR = PROJECT_ROOT / "output" / "xml_tests_v2"


def generate_para_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def generate_durable_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def read_xml_from_docx(docx_path: Path, xml_part: str) -> str:
    with zipfile.ZipFile(docx_path, 'r') as zf:
        return zf.read(xml_part).decode('utf-8')


def create_modified_docx(source_path: Path, output_path: Path, modifications: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_path, 'r') as zin:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.namelist():
                if item in modifications:
                    zout.writestr(item, modifications[item].encode('utf-8'))
                else:
                    zout.writestr(item, zin.read(item))


def get_original_comment_info(docx_path: Path) -> dict:
    comments_xml = read_xml_from_docx(docx_path, 'word/comments.xml')
    comment_matches = re.findall(r'<w:comment w:id="(\d+)"[^>]*>', comments_xml)
    para_id_matches = re.findall(r'w14:paraId="([A-F0-9]+)"', comments_xml)
    return {
        'comment_ids': comment_matches,
        'para_ids': para_id_matches,
        'max_comment_id': max(int(c) for c in comment_matches) if comment_matches else -1
    }


def add_comment_entry(comments_xml: str, comment_id: str, para_id: str, text: str, timestamp: str) -> str:
    """Add a comment entry to comments.xml."""
    new_comment = f'''
  <w:comment w:id="{comment_id}" w:author="Test" w:date="{timestamp}" w:initials="T">
    <w:p w14:paraId="{para_id}" w14:textId="{generate_para_id()}" w:rsidR="00000001" w:rsidRDefault="00000001">
      <w:pPr>
        <w:pStyle w:val="CommentText"/>
      </w:pPr>
      <w:r>
        <w:rPr>
          <w:rStyle w:val="CommentReference"/>
        </w:rPr>
        <w:annotationRef/>
      </w:r>
      <w:r>
        <w:t>{text}</w:t>
      </w:r>
    </w:p>
  </w:comment>
</w:comments>'''
    return comments_xml.replace('</w:comments>', new_comment)


def add_extended_entry(extended_xml: str, para_id: str, parent_para_id: str = None) -> str:
    """Add threading entry to commentsExtended.xml."""
    if parent_para_id:
        new_entry = f'  <w15:commentEx w15:paraId="{para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>\n'
    else:
        new_entry = f'  <w15:commentEx w15:paraId="{para_id}" w15:done="0"/>\n'
    return extended_xml.replace('</w15:commentsEx>', new_entry + '</w15:commentsEx>')


def add_ids_entry(ids_xml: str, para_id: str, durable_id: str) -> str:
    """Add entry to commentsIds.xml."""
    new_entry = f'  <w16cid:commentId w16cid:paraId="{para_id}" w16cid:durableId="{durable_id}"/>\n'
    return ids_xml.replace('</w16cid:commentsIds>', new_entry + '</w16cid:commentsIds>')


def add_extensible_entry(extensible_xml: str, durable_id: str, timestamp: str) -> str:
    """Add entry to commentsExtensible.xml."""
    new_entry = f'  <w16cex:commentExtensible w16cex:durableId="{durable_id}" w16cex:dateUtc="{timestamp}"/>\n'
    return extensible_xml.replace('</w16cex:commentsExtensible>', new_entry + '</w16cex:commentsExtensible>')


def add_anchor_after_parent(doc_xml: str, parent_id: str, new_id: str) -> str:
    """
    Add comment anchor immediately after parent's anchor (zero-width, same position).
    
    This inserts:
    - commentRangeStart/End after parent's rangeEnd
    - commentReference in a new run after parent's reference
    """
    # Insert rangeStart and rangeEnd after parent's rangeEnd
    parent_range_end = f'<w:commentRangeEnd w:id="{parent_id}"/>'
    new_range = f'{parent_range_end}<w:commentRangeStart w:id="{new_id}"/><w:commentRangeEnd w:id="{new_id}"/>'
    doc_xml = doc_xml.replace(parent_range_end, new_range)
    
    # Find where parent's commentReference run ends and insert a new complete run
    # Pattern: </w:commentReference></w:r> (end of reference run)
    # We need to find the specific one for the parent
    
    # Find parent's reference and the end of its containing run
    ref_pattern = f'<w:commentReference w:id="{parent_id}"/>'
    ref_idx = doc_xml.find(ref_pattern)
    if ref_idx > 0:
        # Find the closing </w:r> after this reference
        close_r_idx = doc_xml.find('</w:r>', ref_idx)
        if close_r_idx > 0:
            insert_pos = close_r_idx + len('</w:r>')
            # Insert complete new run with reference
            new_ref_run = f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_id}"/></w:r>'
            doc_xml = doc_xml[:insert_pos] + new_ref_run + doc_xml[insert_pos:]
    
    return doc_xml


# =============================================================================
# TEST CASES
# =============================================================================

def test_1_single_reply_correct_structure(source_path: Path, output_path: Path) -> str:
    """
    TEST 1: Single reply with all correct entries
    
    This is the "correct" structure based on our findings:
    - Entry in all 4 comment XML files
    - Zero-width anchor at same position as parent
    - Threading via paraIdParent
    """
    info = get_original_comment_info(source_path)
    
    parent_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    comments_xml = add_comment_entry(comments_xml, new_id, new_para_id, 
                                      "TEST 1: Single reply with correct structure", timestamp)
    extended_xml = add_extended_entry(extended_xml, new_para_id, parent_para_id)
    ids_xml = add_ids_entry(ids_xml, new_para_id, new_durable_id)
    extensible_xml = add_extensible_entry(extensible_xml, new_durable_id, timestamp)
    doc_xml = add_anchor_after_parent(doc_xml, parent_id, new_id)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Single reply with full correct structure (all 4 XML files + anchor)"


def test_2_chained_replies(source_path: Path, output_path: Path) -> str:
    """
    TEST 2: Multiple replies in a CHAIN (each points to previous)
    
    Hypothesis: Word expects B->A, C->B, D->C (chain), not B->A, C->A, D->A (flat)
    """
    info = get_original_comment_info(source_path)
    
    # Start with comment 0 as root
    root_id = "0"
    root_para_id = info['para_ids'][0]
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    # Create chain: Reply1 -> Root, Reply2 -> Reply1, Reply3 -> Reply2
    prev_id = root_id
    prev_para_id = root_para_id
    
    for i, label in enumerate(["First reply (->root)", "Second reply (->first)", "Third reply (->second)"]):
        new_id = str(info['max_comment_id'] + 1 + i)
        new_para_id = generate_para_id()
        new_durable_id = generate_durable_id()
        timestamp = f"2026-02-12T10:{10+i}:00Z"
        
        comments_xml = add_comment_entry(comments_xml, new_id, new_para_id,
                                          f"TEST 2: {label}", timestamp)
        extended_xml = add_extended_entry(extended_xml, new_para_id, prev_para_id)
        ids_xml = add_ids_entry(ids_xml, new_para_id, new_durable_id)
        extensible_xml = add_extensible_entry(extensible_xml, new_durable_id, timestamp)
        doc_xml = add_anchor_after_parent(doc_xml, prev_id, new_id)
        
        # Chain: next reply points to this one
        prev_id = new_id
        prev_para_id = new_para_id
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Three replies in CHAIN: Reply1->Root, Reply2->Reply1, Reply3->Reply2"


def test_3_flat_replies(source_path: Path, output_path: Path) -> str:
    """
    TEST 3: Multiple replies FLAT (all point to root)
    
    Compare with test_2 to see which threading model Word expects.
    """
    info = get_original_comment_info(source_path)
    
    root_id = "0"
    root_para_id = info['para_ids'][0]
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    prev_anchor_id = root_id  # For positioning anchors
    
    for i, label in enumerate(["First reply (->root)", "Second reply (->root)", "Third reply (->root)"]):
        new_id = str(info['max_comment_id'] + 1 + i)
        new_para_id = generate_para_id()
        new_durable_id = generate_durable_id()
        timestamp = f"2026-02-12T10:{10+i}:00Z"
        
        comments_xml = add_comment_entry(comments_xml, new_id, new_para_id,
                                          f"TEST 3: {label}", timestamp)
        # FLAT: All point to root
        extended_xml = add_extended_entry(extended_xml, new_para_id, root_para_id)
        ids_xml = add_ids_entry(ids_xml, new_para_id, new_durable_id)
        extensible_xml = add_extensible_entry(extensible_xml, new_durable_id, timestamp)
        doc_xml = add_anchor_after_parent(doc_xml, prev_anchor_id, new_id)
        
        prev_anchor_id = new_id  # Next anchor goes after this one
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Three replies FLAT: All point to root (Reply1->Root, Reply2->Root, Reply3->Root)"


def test_4_reply_no_anchor_with_durable(source_path: Path, output_path: Path) -> str:
    """
    TEST 4: Reply with all metadata but NO anchor in document.xml
    
    Re-test from v1 - confirms anchors are required.
    """
    info = get_original_comment_info(source_path)
    
    parent_para_id = info['para_ids'][0]
    
    new_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    
    comments_xml = add_comment_entry(comments_xml, new_id, new_para_id,
                                      "TEST 4: Reply with NO anchor", timestamp)
    extended_xml = add_extended_entry(extended_xml, new_para_id, parent_para_id)
    ids_xml = add_ids_entry(ids_xml, new_para_id, new_durable_id)
    extensible_xml = add_extensible_entry(extensible_xml, new_durable_id, timestamp)
    # NO document.xml changes - no anchor
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
    })
    
    return "Reply with all metadata but NO anchor in document.xml"


def test_5_reply_minimal(source_path: Path, output_path: Path) -> str:
    """
    TEST 5: Reply with MINIMAL required entries
    
    Just comments.xml + commentsExtended.xml + anchor
    No commentsIds.xml or commentsExtensible.xml entries
    """
    info = get_original_comment_info(source_path)
    
    parent_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    comments_xml = add_comment_entry(comments_xml, new_id, new_para_id,
                                      "TEST 5: Minimal reply (no durableId)", timestamp)
    extended_xml = add_extended_entry(extended_xml, new_para_id, parent_para_id)
    doc_xml = add_anchor_after_parent(doc_xml, parent_id, new_id)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Minimal reply: comments.xml + commentsExtended.xml + anchor only"


def test_6_extended_ordering(source_path: Path, output_path: Path) -> str:
    """
    TEST 6: Test if commentsExtended.xml ordering matters
    
    Insert the reply's entry BEFORE the parent's entry in commentsExtended.xml
    """
    info = get_original_comment_info(source_path)
    
    parent_id = "0"
    parent_para_id = info['para_ids'][0]
    
    new_id = str(info['max_comment_id'] + 1)
    new_para_id = generate_para_id()
    new_durable_id = generate_durable_id()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    comments_xml = read_xml_from_docx(source_path, 'word/comments.xml')
    extended_xml = read_xml_from_docx(source_path, 'word/commentsExtended.xml')
    ids_xml = read_xml_from_docx(source_path, 'word/commentsIds.xml')
    extensible_xml = read_xml_from_docx(source_path, 'word/commentsExtensible.xml')
    doc_xml = read_xml_from_docx(source_path, 'word/document.xml')
    
    comments_xml = add_comment_entry(comments_xml, new_id, new_para_id,
                                      "TEST 6: Reply with reversed ordering in commentsExtended", timestamp)
    
    # Insert BEFORE the first entry (reversed order)
    first_entry = f'<w15:commentEx w15:paraId="{parent_para_id}"'
    new_entry = f'<w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>\n  '
    extended_xml = extended_xml.replace(first_entry, new_entry + first_entry)
    
    ids_xml = add_ids_entry(ids_xml, new_para_id, new_durable_id)
    extensible_xml = add_extensible_entry(extensible_xml, new_durable_id, timestamp)
    doc_xml = add_anchor_after_parent(doc_xml, parent_id, new_id)
    
    create_modified_docx(source_path, output_path, {
        'word/comments.xml': comments_xml,
        'word/commentsExtended.xml': extended_xml,
        'word/commentsIds.xml': ids_xml,
        'word/commentsExtensible.xml': extensible_xml,
        'word/document.xml': doc_xml,
    })
    
    return "Reply with entry placed BEFORE parent in commentsExtended.xml"


# =============================================================================
# MAIN
# =============================================================================

def main():
    if not SOURCE_DOCX.exists():
        print(f"ERROR: Source file not found: {SOURCE_DOCX}")
        return 1
    
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)
    
    tests = [
        (test_1_single_reply_correct_structure, "single_reply"),
        (test_2_chained_replies, "chained_replies"),
        (test_3_flat_replies, "flat_replies"),
        (test_4_reply_no_anchor_with_durable, "no_anchor"),
        (test_5_reply_minimal, "minimal"),
        (test_6_extended_ordering, "ordering"),
    ]
    
    print("=" * 70)
    print("DOCX XML ASSUMPTION TESTS v2")
    print("=" * 70)
    print(f"\nSource: {SOURCE_DOCX}")
    print(f"Output: {OUTPUT_DIR}/")
    print()
    
    results = []
    
    for i, (test_func, name) in enumerate(tests, 1):
        output_file = OUTPUT_DIR / f"test_{i}_{name}.docx"
        try:
            description = test_func(SOURCE_DOCX, output_file)
            # Validate XML
            with zipfile.ZipFile(output_file, 'r') as zf:
                doc_xml = zf.read('word/document.xml')
                import xml.etree.ElementTree as ET
                ET.fromstring(doc_xml)  # Will raise if invalid
            results.append((i, name, "SUCCESS", description))
            print(f"[TEST {i}] {name}: Created (XML valid)")
        except ET.ParseError as e:
            results.append((i, name, "XML_ERROR", str(e)))
            print(f"[TEST {i}] {name}: XML ERROR - {e}")
        except Exception as e:
            results.append((i, name, "ERROR", str(e)))
            print(f"[TEST {i}] {name}: ERROR - {e}")
    
    # Write results
    summary_file = OUTPUT_DIR / "TEST_RESULTS.md"
    with open(summary_file, 'w') as f:
        f.write("# XML Assumption Tests v2 Results\n\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n\n")
        f.write("## Key Questions\n\n")
        f.write("1. **Test 1**: Does a single properly-structured reply thread correctly?\n")
        f.write("2. **Test 2 vs 3**: Does Word expect CHAINED replies (each->prev) or FLAT (all->root)?\n")
        f.write("3. **Test 4**: Confirms anchors are required\n")
        f.write("4. **Test 5**: Are commentsIds/Extensible entries required?\n")
        f.write("5. **Test 6**: Does ordering in commentsExtended.xml matter?\n\n")
        f.write("## Test Files\n\n")
        f.write("| Test | File | Description | Expected | Actual |\n")
        f.write("|------|------|-------------|----------|--------|\n")
        
        expected = [
            "Threaded reply",
            "All 3 threaded in order",
            "Only first threaded? Or all?",
            "Reply invisible (no anchor)",
            "Threaded (or error?)",
            "Threaded (or error?)",
        ]
        
        for (i, name, status, desc), exp in zip(results, expected):
            f.write(f"| {i} | test_{i}_{name}.docx | {desc} | {exp} | _____ |\n")
    
    print()
    print(f"Results: {summary_file}")
    print("\nKey comparison: Test 2 (chained) vs Test 3 (flat)")
    
    return 0


if __name__ == "__main__":
    exit(main())
