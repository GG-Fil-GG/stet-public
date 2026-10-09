#!/usr/bin/env python3
"""
Random ID Threading Test

Tests whether truly RANDOM comment IDs work for threading.
This isolates the ID strategy variable.

Key difference from previous tests:
- Uses random IDs like 847, 293, 999 (not sequential like max+1)
"""

import zipfile
import shutil
import uuid
import re
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple

# Test configuration
TEST_DOCS = [
    "test_data/test.docx",
    "test_data/dummy.docx",
    "test_data/reply_test.docx",
]

OUTPUT_DIR = Path("output/random_id_test")


def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID."""
    return uuid.uuid4().hex[:length].upper()


def generate_random_comment_id(existing_ids: list) -> str:
    """Generate a truly random comment ID that doesn't conflict with existing ones."""
    existing_set = set(int(x) for x in existing_ids)
    while True:
        # Generate random ID between 100 and 9999
        new_id = random.randint(100, 9999)
        if new_id not in existing_set:
            return str(new_id)


def add_threaded_reply(
    docx_path: Path,
    parent_comment_id: str,
    reply_text: str,
    author: str = "Stet",
    initials: str = "S",
) -> Tuple[bool, str, Path]:
    """
    Add a threaded reply using a RANDOM ID (not sequential).
    
    Returns: (success, message, output_path)
    """
    output_path = OUTPUT_DIR / f"{docx_path.stem}_random_id.docx"
    
    # Copy original
    shutil.copy(docx_path, output_path)
    
    # Find all existing comment IDs
    existing_ids = []
    with zipfile.ZipFile(output_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        for match in re.finditer(r'<w:comment[^>]*w:id="(\d+)"', comments_xml):
            existing_ids.append(match.group(1))
    
    # Use RANDOM ID (the key variable we're testing)
    new_comment_id = generate_random_comment_id(existing_ids)
    
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
        
        # Map paraIds to comment IDs
        for reply_para_id in existing_reply_para_ids:
            id_pattern = rf'<w:comment[^>]*w:id="(\d+)"[^>]*>(?:(?!</w:comment>).)*?w14:paraId="{reply_para_id}"'
            m = re.search(id_pattern, comments_xml, re.DOTALL)
            if m:
                existing_reply_ids.append(m.group(1))
        
        # Find durable ID of last existing reply
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
    
    return True, f"Added reply with RANDOM ID={new_comment_id} (existing: {existing_ids})", output_path


def add_comment_entry(xml: str, parent_id: str, new_id: str, para_id: str, 
                      text_id: str, rsid: str, author: str, initials: str,
                      date: str, text: str) -> str:
    """Add new comment entry after parent in comments.xml."""
    
    # MINIFIED format (matching spec_validation which worked)
    new_comment = f'<w:comment w:id="{new_id}" w:author="{author}" w:date="{date}" w:initials="{initials}"><w:p w14:paraId="{para_id}" w14:textId="{text_id}" w:rsidR="{rsid}" w:rsidRDefault="{rsid}"><w:pPr><w:pStyle w:val="CommentText"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r><w:r><w:t>{text}</w:t></w:r></w:p></w:comment>'
    
    # Find end of parent comment and insert after
    pattern = rf'(<w:comment[^>]*w:id="{parent_id}"[^>]*>.*?</w:comment>)'
    match = re.search(pattern, xml, re.DOTALL)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_comment + xml[insert_pos:]
    
    return xml


def add_comments_extended_entry(xml: str, parent_para_id: str, new_para_id: str) -> str:
    """Add entry with paraIdParent."""
    
    new_entry = f'<w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
    
    # Find existing replies to this parent, insert after last one
    reply_pattern = rf'<w15:commentEx[^>]*w15:paraIdParent="{parent_para_id}"[^>]*/>'
    replies = list(re.finditer(reply_pattern, xml))
    
    if replies:
        last_reply = replies[-1]
        insert_pos = last_reply.end()
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    else:
        # No existing replies - insert after parent entry
        pattern = rf'(<w15:commentEx[^>]*w15:paraId="{parent_para_id}"[^>]*/>)'
        match = re.search(pattern, xml)
        if match:
            insert_pos = match.end()
            xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_comments_ids_entry(xml: str, parent_para_id: str, new_para_id: str, 
                           durable_id: str, existing_reply_para_ids: list = None) -> str:
    """Add entry in commentsIds.xml."""
    
    existing_reply_para_ids = existing_reply_para_ids or []
    new_entry = f'<w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{durable_id}"/>'
    
    if existing_reply_para_ids:
        last_reply_para_id = existing_reply_para_ids[-1]
        pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{last_reply_para_id}"[^>]*/>)'
    else:
        pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{parent_para_id}"[^>]*/>)'
    
    match = re.search(pattern, xml)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_comments_extensible_entry(xml: str, durable_id: str, date_utc: str,
                                   insert_after_durable_id: str = None) -> str:
    """Add entry in commentsExtensible.xml."""
    
    new_entry = f'<w16cex:commentExtensible w16cex:durableId="{durable_id}" w16cex:dateUtc="{date_utc}"/>'
    
    if insert_after_durable_id:
        pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{insert_after_durable_id}"[^>]*/>)'
    else:
        pattern = r'(<w16cex:commentExtensible[^>]*/>)'
    
    match = re.search(pattern, xml)
    if match:
        insert_pos = match.end()
        xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
    
    return xml


def add_document_anchors(xml: str, parent_id: str, new_id: str, rsid: str, 
                         existing_reply_ids: list = None) -> str:
    """Add nested rangeStart and rangeEnd+reference in document.xml."""
    
    existing_reply_ids = existing_reply_ids or []
    
    # 1. Insert rangeStart after parent's (or last reply's) rangeStart
    if existing_reply_ids:
        last_reply_id = existing_reply_ids[-1]
        last_start = f'<w:commentRangeStart w:id="{last_reply_id}"/>'
        new_start = f'<w:commentRangeStart w:id="{new_id}"/>'
        xml = xml.replace(last_start, last_start + new_start)
    else:
        parent_start = f'<w:commentRangeStart w:id="{parent_id}"/>'
        new_start = f'<w:commentRangeStart w:id="{new_id}"/>'
        xml = xml.replace(parent_start, parent_start + new_start)
    
    # 2. Insert rangeEnd+reference after parent's (or last reply's) reference
    if existing_reply_ids:
        last_reply_id = existing_reply_ids[-1]
        ref_pattern = rf'(<w:commentReference w:id="{last_reply_id}"/>\s*</w:r>)'
    else:
        ref_pattern = rf'(<w:commentReference w:id="{parent_id}"/>\s*</w:r>)'
    
    match = re.search(ref_pattern, xml)
    if match:
        insert_pos = match.end()
        # NO <w:sz> elements
        new_elements = f'<w:commentRangeEnd w:id="{new_id}"/><w:r w:rsidR="{rsid}"><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_id}"/></w:r>'
        xml = xml[:insert_pos] + new_elements + xml[insert_pos:]
    
    return xml


def main():
    """Run random ID tests."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Set random seed for reproducibility (can comment out for true randomness)
    random.seed(42)
    
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
        
        # Add reply with RANDOM ID
        success, msg, output_path = add_threaded_reply(
            doc,
            first_comment_id,
            f"Reply with RANDOM ID - testing ID strategy",
            author="RandomTest",
            initials="RT"
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
        f.write("# Random ID Threading Test Results\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Test Configuration\n\n")
        f.write("- **RANDOM comment IDs** (e.g., 654, 847 - NOT sequential)\n")
        f.write("- NO `<w:sz>` elements\n")
        f.write("- NO `<w:proofErr>` modification\n")
        f.write("- Minified XML format (like spec_validation)\n\n")
        f.write("## Results\n\n")
        f.write("| Source | Output | Parent ID | Reply ID | Threaded? | Notes |\n")
        f.write("|--------|--------|-----------|----------|-----------|-------|\n")
        for r in results:
            # Extract reply ID from message
            reply_id = r['message'].split('ID=')[1].split(' ')[0] if 'ID=' in r['message'] else '?'
            f.write(f"| {r['source']} | {r['output']} | {r['parent_id']} | {reply_id} | | |\n")
        f.write("\n## Instructions\n\n")
        f.write("1. Open each output file in Microsoft Word\n")
        f.write("2. Check if the reply appears **threaded** under the first comment\n")
        f.write("3. Fill in the 'Threaded?' column: Yes / No / Error\n")
        f.write("\n## What This Tests\n\n")
        f.write("This test isolates the **ID strategy** variable:\n")
        f.write("- Previous tests used sequential IDs (max_id + 1)\n")
        f.write("- This test uses truly random IDs\n")
        f.write("- If random IDs work, then ID sequencing is NOT required\n")
    
    print(f"\nTest matrix written to: {matrix_path}")
    print("Please test the output files in Word and record results.")


if __name__ == "__main__":
    main()
