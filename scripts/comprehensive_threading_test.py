#!/usr/bin/env python3
"""
Comprehensive Threading Test

Tests threading in a wider range of scenarios:
1. Multiple replies to the same comment (building a thread)
2. Replies to different comments in the same document
3. Documents with track changes
4. Documents with existing threads

Uses validated approach: random IDs, no sz elements, minified XML.
"""

import zipfile
import shutil
import uuid
import re
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, List

OUTPUT_DIR = Path("output/comprehensive_test")


def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID."""
    return uuid.uuid4().hex[:length].upper()


def get_all_comment_ids(docx_path: Path) -> List[str]:
    """Get all comment IDs from a document."""
    with zipfile.ZipFile(docx_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        return [m.group(1) for m in re.finditer(r'<w:comment[^>]*w:id="(\d+)"', comments_xml)]


def get_all_track_change_ids(docx_path: Path) -> List[str]:
    """Get all track change IDs from a document."""
    with zipfile.ZipFile(docx_path, 'r') as zf:
        doc_xml = zf.read('word/document.xml').decode('utf-8')
        # Track changes use w:id on ins, del, rPrChange, etc.
        ids = set()
        for m in re.finditer(r'<w:(ins|del|rPrChange|pPrChange)[^>]*w:id="(\d+)"', doc_xml):
            ids.add(m.group(2))
        return list(ids)


def generate_random_id(existing_ids: List[str]) -> str:
    """Generate a random ID that doesn't conflict with existing ones."""
    existing_set = set(int(x) for x in existing_ids if x.isdigit())
    while True:
        new_id = random.randint(100, 9999)
        if new_id not in existing_set:
            return str(new_id)


def add_reply(
    docx_path: Path,
    output_path: Path,
    parent_comment_id: str,
    reply_text: str,
    author: str = "CompTest",
    initials: str = "CT",
) -> Tuple[bool, str]:
    """Add a threaded reply using random ID and minified XML."""
    
    # Only copy if source != destination
    if docx_path.resolve() != output_path.resolve():
        shutil.copy(docx_path, output_path)
    
    # Collect all IDs (comments + track changes) to avoid conflicts
    comment_ids = get_all_comment_ids(output_path)
    track_ids = get_all_track_change_ids(output_path)
    all_ids = comment_ids + track_ids
    
    new_comment_id = generate_random_id(all_ids)
    new_para_id = generate_hex_id(8)
    new_text_id = generate_hex_id(8)
    new_rsid = generate_hex_id(8)
    new_durable_id = generate_hex_id(8)
    
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Find parent's paraId and existing replies
    parent_para_id = None
    existing_reply_ids = []
    existing_reply_para_ids = []
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        comments_extended_xml = zf.read('word/commentsExtended.xml').decode('utf-8')
        
        # Find parent's paraId
        pattern = rf'<w:comment[^>]*w:id="{parent_comment_id}"[^>]*>.*?w14:paraId="([^"]+)"'
        match = re.search(pattern, comments_xml, re.DOTALL)
        if match:
            parent_para_id = match.group(1)
        else:
            return False, f"Parent comment {parent_comment_id} not found"
        
        # Find existing replies
        reply_pattern = rf'<w15:commentEx[^>]*w15:paraId="([^"]+)"[^>]*w15:paraIdParent="{parent_para_id}"'
        for m in re.finditer(reply_pattern, comments_extended_xml):
            existing_reply_para_ids.append(m.group(1))
        
        for reply_para_id in existing_reply_para_ids:
            id_pattern = rf'<w:comment[^>]*w:id="(\d+)"[^>]*>(?:(?!</w:comment>).)*?w14:paraId="{reply_para_id}"'
            m = re.search(id_pattern, comments_xml, re.DOTALL)
            if m:
                existing_reply_ids.append(m.group(1))
        
        # Get parent's durableId (needed for commentsExtensible ordering)
        comments_ids_xml = zf.read('word/commentsIds.xml').decode('utf-8')
        parent_durable_id = None
        parent_durable_pattern = rf'<w16cid:commentId[^>]*w16cid:paraId="{parent_para_id}"[^>]*w16cid:durableId="([^"]+)"'
        m = re.search(parent_durable_pattern, comments_ids_xml)
        if m:
            parent_durable_id = m.group(1)
        
        last_reply_durable_id = None
        if existing_reply_para_ids:
            last_para_id = existing_reply_para_ids[-1]
            durable_pattern = rf'<w16cid:commentId[^>]*w16cid:paraId="{last_para_id}"[^>]*w16cid:durableId="([^"]+)"'
            m = re.search(durable_pattern, comments_ids_xml)
            if m:
                last_reply_durable_id = m.group(1)
    
    # Modify files
    modified_files = {}
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        for item in zf.namelist():
            content = zf.read(item)
            
            if item == 'word/comments.xml':
                xml = content.decode('utf-8')
                # Minified comment
                new_comment = f'<w:comment w:id="{new_comment_id}" w:author="{author}" w:date="{date_str}" w:initials="{initials}"><w:p w14:paraId="{new_para_id}" w14:textId="{new_text_id}" w:rsidR="{new_rsid}" w:rsidRDefault="{new_rsid}"><w:pPr><w:pStyle w:val="CommentText"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r><w:r><w:t>{reply_text}</w:t></w:r></w:p></w:comment>'
                pattern = rf'(<w:comment[^>]*w:id="{parent_comment_id}"[^>]*>.*?</w:comment>)'
                match = re.search(pattern, xml, re.DOTALL)
                if match:
                    xml = xml[:match.end()] + new_comment + xml[match.end():]
                content = xml.encode('utf-8')
                
            elif item == 'word/commentsExtended.xml':
                xml = content.decode('utf-8')
                new_entry = f'<w15:commentEx w15:paraId="{new_para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
                reply_pattern = rf'<w15:commentEx[^>]*w15:paraIdParent="{parent_para_id}"[^>]*/>'
                replies = list(re.finditer(reply_pattern, xml))
                if replies:
                    insert_pos = replies[-1].end()
                else:
                    pattern = rf'(<w15:commentEx[^>]*w15:paraId="{parent_para_id}"[^>]*/>)'
                    match = re.search(pattern, xml)
                    insert_pos = match.end() if match else len(xml) - 20
                xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
                content = xml.encode('utf-8')
                
            elif item == 'word/commentsIds.xml':
                xml = content.decode('utf-8')
                new_entry = f'<w16cid:commentId w16cid:paraId="{new_para_id}" w16cid:durableId="{new_durable_id}"/>'
                if existing_reply_para_ids:
                    pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{existing_reply_para_ids[-1]}"[^>]*/>)'
                else:
                    pattern = rf'(<w16cid:commentId[^>]*w16cid:paraId="{parent_para_id}"[^>]*/>)'
                match = re.search(pattern, xml)
                if match:
                    xml = xml[:match.end()] + new_entry + xml[match.end():]
                content = xml.encode('utf-8')
                
            elif item == 'word/commentsExtensible.xml':
                xml = content.decode('utf-8')
                new_entry = f'<w16cex:commentExtensible w16cex:durableId="{new_durable_id}" w16cex:dateUtc="{date_str}"/>'
                if last_reply_durable_id:
                    # Insert after last existing reply's entry
                    pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{last_reply_durable_id}"[^>]*/>)'
                elif parent_durable_id:
                    # Insert after PARENT's entry (not first entry!)
                    pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{parent_durable_id}"[^>]*/>)'
                else:
                    # Fallback: insert after first entry
                    pattern = r'(<w16cex:commentExtensible[^>]*/>)'
                match = re.search(pattern, xml)
                if match:
                    xml = xml[:match.end()] + new_entry + xml[match.end():]
                content = xml.encode('utf-8')
                
            elif item == 'word/document.xml':
                xml = content.decode('utf-8')
                # Insert rangeStart
                if existing_reply_ids:
                    last_start = f'<w:commentRangeStart w:id="{existing_reply_ids[-1]}"/>'
                else:
                    last_start = f'<w:commentRangeStart w:id="{parent_comment_id}"/>'
                xml = xml.replace(last_start, last_start + f'<w:commentRangeStart w:id="{new_comment_id}"/>')
                
                # Insert rangeEnd + reference
                if existing_reply_ids:
                    ref_pattern = rf'(<w:commentReference w:id="{existing_reply_ids[-1]}"/>\s*</w:r>)'
                else:
                    ref_pattern = rf'(<w:commentReference w:id="{parent_comment_id}"/>\s*</w:r>)'
                match = re.search(ref_pattern, xml)
                if match:
                    new_elements = f'<w:commentRangeEnd w:id="{new_comment_id}"/><w:r w:rsidR="{new_rsid}"><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/></w:r>'
                    xml = xml[:match.end()] + new_elements + xml[match.end():]
                content = xml.encode('utf-8')
            
            modified_files[item] = content
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in modified_files.items():
            zf.writestr(name, data)
    
    return True, f"Added reply ID={new_comment_id}"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(123)  # Reproducible
    
    results = []
    
    # Test 1: Multiple replies to same comment (build a thread)
    print("=== Test 1: Building a thread with multiple replies ===")
    test_doc = Path("test_data/test.docx")
    if test_doc.exists():
        output1 = OUTPUT_DIR / "test_multi_reply.docx"
        shutil.copy(test_doc, output1)
        
        # Add first reply
        success, msg = add_reply(output1, output1, "0", "First reply to build thread")
        print(f"  Reply 1: {msg}")
        results.append(("test_multi_reply.docx", "1st reply to comment 0", success, msg))
        
        # Add second reply to same comment
        success, msg = add_reply(output1, output1, "0", "Second reply to same thread")
        print(f"  Reply 2: {msg}")
        results.append(("test_multi_reply.docx", "2nd reply to comment 0", success, msg))
        
        # Add third reply
        success, msg = add_reply(output1, output1, "0", "Third reply - full thread test")
        print(f"  Reply 3: {msg}")
        results.append(("test_multi_reply.docx", "3rd reply to comment 0", success, msg))
    
    # Test 2: Replies to different comments in same doc
    print("\n=== Test 2: Replies to different comments ===")
    if test_doc.exists():
        output2 = OUTPUT_DIR / "test_different_comments.docx"
        shutil.copy(test_doc, output2)
        
        # Reply to comment 0
        success, msg = add_reply(output2, output2, "0", "Reply to first comment")
        print(f"  Comment 0: {msg}")
        results.append(("test_different_comments.docx", "reply to comment 0", success, msg))
        
        # Reply to comment 1
        success, msg = add_reply(output2, output2, "1", "Reply to second comment")
        print(f"  Comment 1: {msg}")
        results.append(("test_different_comments.docx", "reply to comment 1", success, msg))
        
        # Reply to comment 3
        success, msg = add_reply(output2, output2, "3", "Reply to fourth comment")
        print(f"  Comment 3: {msg}")
        results.append(("test_different_comments.docx", "reply to comment 3", success, msg))
    
    # Test 3: Document with track changes
    print("\n=== Test 3: Document with track changes ===")
    dummy_doc = Path("test_data/dummy.docx")
    if dummy_doc.exists():
        # Check if it has track changes
        track_ids = get_all_track_change_ids(dummy_doc)
        print(f"  dummy.docx has track change IDs: {track_ids}")
        
        output3 = OUTPUT_DIR / "dummy_with_tc_reply.docx"
        success, msg = add_reply(dummy_doc, output3, "0", "Reply in doc with track changes")
        print(f"  Result: {msg}")
        results.append(("dummy_with_tc_reply.docx", "reply in doc with track changes", success, msg))
    
    # Test 4: Adding to existing thread (reply_test.docx already has replies)
    print("\n=== Test 4: Extending existing thread ===")
    reply_doc = Path("test_data/reply_test.docx")
    if reply_doc.exists():
        output4 = OUTPUT_DIR / "reply_test_extended.docx"
        success, msg = add_reply(reply_doc, output4, "1", "New reply extending existing thread")
        print(f"  Result: {msg}")
        results.append(("reply_test_extended.docx", "extend existing thread", success, msg))
    
    # Write test matrix
    matrix_path = OUTPUT_DIR / "TEST_MATRIX.md"
    with open(matrix_path, 'w') as f:
        f.write("# Comprehensive Threading Test Results\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Test Configuration\n\n")
        f.write("- Random IDs (validated approach)\n")
        f.write("- Minified XML\n")
        f.write("- No `<w:sz>` elements\n\n")
        f.write("## Test Scenarios\n\n")
        f.write("| File | Scenario | Reply ID | Threaded? | Notes |\n")
        f.write("|------|----------|----------|-----------|-------|\n")
        for filename, scenario, success, msg in results:
            reply_id = msg.split('ID=')[1] if 'ID=' in msg else '?'
            f.write(f"| {filename} | {scenario} | {reply_id} | | |\n")
        f.write("\n## What to Check\n\n")
        f.write("1. **test_multi_reply.docx**: Comment 0 should have 3 threaded replies in order\n")
        f.write("2. **test_different_comments.docx**: Comments 0, 1, and 3 should each have 1 reply\n")
        f.write("3. **dummy_with_tc_reply.docx**: Reply should thread despite track changes in doc\n")
        f.write("4. **reply_test_extended.docx**: New reply should appear at end of existing thread\n")
    
    print(f"\nTest matrix: {matrix_path}")
    print("Please test in Word and record results.")


if __name__ == "__main__":
    main()
