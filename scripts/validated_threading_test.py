#!/usr/bin/env python3
"""
Validated Threading Test

Tests our best current understanding of Word comment threading:
- All 4 XML files required (comments, commentsExtended, commentsIds, commentsExtensible)
- Nested rangeStart anchors in document.xml
- NO <w:sz> elements added
- NO proofErr modification
- Any unique ID works (doesn't need to be sequential)

Run this to validate threading works across multiple documents.
"""

import zipfile
import shutil
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple

# Test configuration
TEST_DOCS = [
    "test_data/test.docx",
    "test_data/dummy.docx",
    "test_data/reply_test.docx",
]

OUTPUT_DIR = Path("output/validated_threading")


def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID."""
    return uuid.uuid4().hex[:length].upper()


def add_threaded_reply(
    docx_path: Path,
    parent_comment_id: str,
    reply_text: str,
    author: str = "Stet",
    initials: str = "S",
) -> Tuple[bool, str, Path]:
    """
    Add a threaded reply following our validated specification.
    
    Returns: (success, message, output_path)
    """
    output_path = OUTPUT_DIR / f"{docx_path.stem}_with_reply.docx"
    
    # Copy original
    shutil.copy(docx_path, output_path)
    
    # Find the highest existing comment ID to determine next sequential ID
    max_id = 0
    with zipfile.ZipFile(output_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        for match in re.finditer(r'<w:comment[^>]*w:id="(\d+)"', comments_xml):
            max_id = max(max_id, int(match.group(1)))
    
    # Use NEXT SEQUENTIAL ID (critical for some documents)
    new_comment_id = str(max_id + 1)
    
    # Generate other unique IDs
    new_para_id = generate_hex_id(8)
    new_text_id = generate_hex_id(8)
    new_rsid = generate_hex_id(8)
    new_durable_id = generate_hex_id(8)
    
    # Timestamps - use current UTC time
    now = datetime.now(timezone.utc)
    date_local = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Find parent's paraId and existing reply IDs
    parent_para_id = None
    existing_reply_ids = []
    existing_reply_para_ids = []
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        comments_extended_xml = zf.read('word/commentsExtended.xml').decode('utf-8')
        
        # Find parent comment's paraId
        pattern = rf'<w:comment[^>]*w:id="{parent_comment_id}"[^>]*>.*?w14:paraId="([^"]+)"'
        match = re.search(pattern, comments_xml, re.DOTALL)
        if match:
            parent_para_id = match.group(1)
        else:
            return False, f"Could not find parent comment {parent_comment_id}", output_path
        
        # Find existing replies to this parent (from commentsExtended)
        reply_pattern = rf'<w15:commentEx[^>]*w15:paraId="([^"]+)"[^>]*w15:paraIdParent="{parent_para_id}"'
        for m in re.finditer(reply_pattern, comments_extended_xml):
            existing_reply_para_ids.append(m.group(1))
        
        # Map paraIds to comment IDs - find comment containing each paraId
        # Use negative lookahead to not cross comment boundaries
        for reply_para_id in existing_reply_para_ids:
            # Find comment that contains this paraId (within same comment element)
            id_pattern = rf'<w:comment[^>]*w:id="(\d+)"[^>]*>(?:(?!</w:comment>).)*?w14:paraId="{reply_para_id}"'
            m = re.search(id_pattern, comments_xml, re.DOTALL)
            if m:
                existing_reply_ids.append(m.group(1))
        
        # Find durable ID of last existing reply (for commentsExtensible ordering)
        last_reply_durable_id = None
        if existing_reply_para_ids:
            comments_ids_xml = zf.read('word/commentsIds.xml').decode('utf-8')
            last_para_id = existing_reply_para_ids[-1]
            durable_pattern = rf'<w16cid:commentId[^>]*w16cid:paraId="{last_para_id}"[^>]*w16cid:durableId="([^"]+)"'
            m = re.search(durable_pattern, comments_ids_xml)
            if m:
                last_reply_durable_id = m.group(1)
    
    # Process all files
    modified_files = {}
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        for item in zf.namelist():
            content = zf.read(item)
            
            if item == 'word/comments.xml':
                content = add_comment_entry(
                    content.decode('utf-8'),
                    parent_comment_id, new_comment_id, new_para_id, new_text_id,
                    new_rsid, author, initials, date_local, reply_text
                ).encode('utf-8')
                
            elif item == 'word/commentsExtended.xml':
                content = add_comments_extended_entry(
                    content.decode('utf-8'),
                    parent_para_id, new_para_id
                ).encode('utf-8')
                
            elif item == 'word/commentsIds.xml':
                content = add_comments_ids_entry(
                    content.decode('utf-8'),
                    parent_para_id, new_para_id, new_durable_id,
                    existing_reply_para_ids
                ).encode('utf-8')
                
            elif item == 'word/commentsExtensible.xml':
                content = add_comments_extensible_entry(
                    content.decode('utf-8'),
                    new_durable_id, date_utc,
                    last_reply_durable_id
                ).encode('utf-8')
                
            elif item == 'word/document.xml':
                content = add_document_anchors(
                    content.decode('utf-8'),
                    parent_comment_id, new_comment_id, new_rsid,
                    existing_reply_ids
                ).encode('utf-8')
            
            modified_files[item] = content
    
    # Write modified archive
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in modified_files.items():
            zf.writestr(name, data)
    
    return True, f"Added reply (ID={new_comment_id}) to comment {parent_comment_id}", output_path


def add_comment_entry(xml: str, parent_id: str, new_id: str, para_id: str, 
                      text_id: str, rsid: str, author: str, initials: str,
                      date: str, text: str) -> str:
    """Add new comment entry after parent in comments.xml."""
    
    new_comment = f'''<w:comment w:id="{new_id}" w:author="{author}" w:date="{date}" w:initials="{initials}">
    <w:p w14:paraId="{para_id}" w14:textId="{text_id}" w:rsidR="{rsid}" w:rsidRDefault="{rsid}">
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
  '''
    
    # Find end of parent comment and insert after
    pattern = rf'(<w:comment[^>]*w:id="{parent_id}"[^>]*>.*?</w:comment>)\s*'
    match = re.search(pattern, xml, re.DOTALL)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_comment + xml[insert_pos:]
    
    return xml


def add_comments_extended_entry(xml: str, parent_para_id: str, new_para_id: str) -> str:
    """Add entry with paraIdParent AFTER all existing replies to the same parent."""
    
    new_entry = f'<w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>\n  '
    
    # Find ALL existing replies to this parent (entries with paraIdParent=parent_para_id)
    # Insert after the LAST one to maintain chronological order
    reply_pattern = rf'<w15:commentEx[^>]*w15:paraIdParent="{parent_para_id}"[^>]*/>'
    replies = list(re.finditer(reply_pattern, xml))
    
    if replies:
        # Insert after the last existing reply
        last_reply = replies[-1]
        insert_pos = last_reply.end()
        # Find the end of any whitespace after the last reply
        while insert_pos < len(xml) and xml[insert_pos] in ' \n\t':
            insert_pos += 1
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    else:
        # No existing replies - insert after parent entry
        pattern = rf'(<w15:commentEx[^>]*w15:paraId="{parent_para_id}"[^>]*/>\s*)'
        match = re.search(pattern, xml)
        if match:
            insert_pos = match.end()
            xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_comments_ids_entry(xml: str, parent_para_id: str, new_para_id: str, 
                           durable_id: str, existing_reply_para_ids: list = None) -> str:
    """Add entry AFTER all existing replies to the same parent in commentsIds.xml."""
    
    existing_reply_para_ids = existing_reply_para_ids or []
    new_entry = f'<w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{durable_id}"/>\n  '
    
    if existing_reply_para_ids:
        # Insert after the last existing reply
        last_reply_para_id = existing_reply_para_ids[-1]
        pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{last_reply_para_id}"[^>]*/>\s*)'
    else:
        # Insert after parent entry
        pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{parent_para_id}"[^>]*/>\s*)'
    
    match = re.search(pattern, xml)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_comments_extensible_entry(xml: str, durable_id: str, date_utc: str,
                                   insert_after_durable_id: str = None) -> str:
    """Add entry in commentsExtensible.xml after specified durableId or at start."""
    
    new_entry = f'<w16cex:commentExtensible w16cex:durableId="{durable_id}" w16cex:dateUtc="{date_utc}"/>\n  '
    
    if insert_after_durable_id:
        pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{insert_after_durable_id}"[^>]*/>\s*)'
    else:
        # Insert after first entry
        pattern = r'(<w16cex:commentExtensible[^>]*/>\s*)'
    
    match = re.search(pattern, xml)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_document_anchors(xml: str, parent_id: str, new_id: str, rsid: str, 
                         existing_reply_ids: list = None) -> str:
    """Add nested rangeStart and rangeEnd+reference in document.xml.
    
    Handles existing replies by inserting AFTER all of them to maintain order.
    """
    existing_reply_ids = existing_reply_ids or []
    
    # 1. Find where to insert rangeStart
    # If there are existing replies, insert after the LAST reply's rangeStart
    # Otherwise, insert after parent's rangeStart
    if existing_reply_ids:
        last_reply_id = existing_reply_ids[-1]
        last_start = f'<w:commentRangeStart w:id="{last_reply_id}"/>'
        new_start = f'<w:commentRangeStart w:id="{new_id}"/>'
        xml = xml.replace(last_start, last_start + new_start)
    else:
        parent_start = f'<w:commentRangeStart w:id="{parent_id}"/>'
        new_start = f'<w:commentRangeStart w:id="{new_id}"/>'
        xml = xml.replace(parent_start, parent_start + new_start)
    
    # 2. Find where to insert rangeEnd+reference
    # If there are existing replies, insert after the LAST reply's reference run
    # Otherwise, insert after parent's reference run
    if existing_reply_ids:
        last_reply_id = existing_reply_ids[-1]
        ref_pattern = rf'(<w:commentReference w:id="{last_reply_id}"/>\s*</w:r>)'
    else:
        ref_pattern = rf'(<w:commentReference w:id="{parent_id}"/>\s*</w:r>)'
    
    match = re.search(ref_pattern, xml)
    if match:
        insert_pos = match.end()
        # NO <w:sz> elements - validated to work
        new_elements = f'''
      <w:commentRangeEnd w:id="{new_id}"/>
      <w:r w:rsidR="{rsid}">
        <w:rPr>
          <w:rStyle w:val="CommentReference"/>
        </w:rPr>
        <w:commentReference w:id="{new_id}"/>
      </w:r>'''
        xml = xml[:insert_pos] + new_elements + xml[insert_pos:]
    
    return xml


def main():
    """Run validation tests."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    for doc_path in TEST_DOCS:
        doc = Path(doc_path)
        if not doc.exists():
            print(f"SKIP: {doc} not found")
            continue
        
        # Find first comment ID
        with zipfile.ZipFile(doc, 'r') as zf:
            comments_xml = zf.read('word/comments.xml').decode('utf-8')
            match = re.search(r'<w:comment[^>]*w:id="(\d+)"', comments_xml)
            if not match:
                print(f"SKIP: {doc} has no comments")
                continue
            first_comment_id = match.group(1)
        
        # Add reply
        success, msg, output_path = add_threaded_reply(
            doc,
            first_comment_id,
            f"Test reply added by validated_threading_test.py",
            author="ValidationTest",
            initials="VT"
        )
        
        results.append({
            'source': doc.name,
            'output': output_path.name,
            'parent_id': first_comment_id,
            'success': success,
            'message': msg
        })
        
        print(f"{'OK' if success else 'FAIL'}: {doc.name} -> {output_path.name}")
        print(f"       {msg}")
    
    # Write test matrix
    matrix_path = OUTPUT_DIR / "TEST_MATRIX.md"
    with open(matrix_path, 'w') as f:
        f.write("# Validated Threading Test Results\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Test Configuration\n\n")
        f.write("- NO `<w:sz>` elements added\n")
        f.write("- NO `<w:proofErr>` modification\n")
        f.write("- Random comment IDs (not sequential)\n")
        f.write("- All 4 comment XML files updated\n\n")
        f.write("## Results\n\n")
        f.write("| Source | Output | Parent ID | Threaded? | Notes |\n")
        f.write("|--------|--------|-----------|-----------|-------|\n")
        for r in results:
            f.write(f"| {r['source']} | {r['output']} | {r['parent_id']} | | |\n")
        f.write("\n## Instructions\n\n")
        f.write("1. Open each output file in Microsoft Word\n")
        f.write("2. Check if the reply appears **threaded** under the first comment\n")
        f.write("3. Fill in the 'Threaded?' column: Yes / No / Error\n")
    
    print(f"\nTest matrix written to: {matrix_path}")
    print("Please test the output files in Word and record results.")


if __name__ == "__main__":
    main()
