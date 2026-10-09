#!/usr/bin/env python3
"""
Threading Stress Test
=====================
Tests threaded comment insertion across diverse documents to validate
our understanding of Word's threading requirements.

This script:
1. Copies test documents to output/threading_tests/
2. Adds threaded replies to existing comments
3. Generates a test matrix for manual verification in Word
"""

import os
import sys
import shutil
import zipfile
import re
import random
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "threading_tests"

# Documents to test (selected for diversity)
TEST_DOCUMENTS = [
    # (filename, description)
    ("test.docx", "Simple - 4 comments, our baseline"),
    ("test_comment_chain.docx", "Already has threading - can we add more?"),
    ("dummy.docx", "Simple - 3 comments"),
    # Real manuscripts stay in test_data/local/ and are not listed here.
]

# XML namespaces
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'w16cid': 'http://schemas.microsoft.com/office/word/2016/wordml/cid',
    'w16cex': 'http://schemas.microsoft.com/office/word/2018/wordml/cex',
}


def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID."""
    return ''.join(random.choices('0123456789ABCDEF', k=length))


def get_next_comment_id(comments_xml: str) -> int:
    """Find the highest comment ID and return the next one."""
    ids = [int(m) for m in re.findall(r'w:id="(\d+)"', comments_xml)]
    return max(ids) + 1 if ids else 0


def extract_comment_info(docx_path: Path) -> List[Dict]:
    """Extract info about existing comments from a DOCX file."""
    comments = []
    
    with zipfile.ZipFile(docx_path, 'r') as zf:
        if 'word/comments.xml' not in zf.namelist():
            return comments
            
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        
        # Parse commentsExtended for threading info
        threading = {}
        if 'word/commentsExtended.xml' in zf.namelist():
            ext_xml = zf.read('word/commentsExtended.xml').decode('utf-8')
            for match in re.finditer(
                r'w15:paraId="([^"]+)"(?:[^>]*w15:paraIdParent="([^"]+)")?',
                ext_xml
            ):
                para_id = match.group(1)
                parent_para_id = match.group(2)
                threading[para_id] = parent_para_id
        
        # Extract comment details
        for match in re.finditer(
            r'<w:comment\s+w:id="(\d+)"[^>]*>(.*?)</w:comment>',
            comments_xml, re.DOTALL
        ):
            comment_id = match.group(1)
            content = match.group(2)
            
            # Find paraId
            para_match = re.search(r'w14:paraId="([^"]+)"', content)
            para_id = para_match.group(1) if para_match else None
            
            # Check if this is already a reply
            is_reply = para_id in threading and threading.get(para_id) is not None
            
            comments.append({
                'id': comment_id,
                'para_id': para_id,
                'is_reply': is_reply,
                'parent_para_id': threading.get(para_id) if is_reply else None
            })
    
    return comments


def add_threaded_reply(
    docx_path: Path,
    parent_comment_id: str,
    parent_para_id: str,
    reply_text: str,
    test_name: str
) -> Tuple[bool, str]:
    """
    Add a threaded reply using Word-style nested anchors.
    
    Based on validated findings from test_comment_chain.docx analysis:
    - Flat threading (all replies point to root paraId)
    - Nested anchors at same start position
    - Entries in all 4 comment XML files
    """
    try:
        # First pass: determine the new comment ID
        with zipfile.ZipFile(docx_path, 'r') as zf:
            comments_xml = zf.read('word/comments.xml').decode('utf-8')
            new_comment_id = str(get_next_comment_id(comments_xml))
        
        # Generate other IDs
        new_para_id = generate_hex_id(8)
        new_text_id = generate_hex_id(8)
        new_durable_id = generate_hex_id(8)
        new_rsid = generate_hex_id(8)
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        timestamp_utc = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")  # Use timezone-aware
        
        temp_path = str(docx_path) + '.tmp'
        
        with zipfile.ZipFile(docx_path, 'r') as zin:
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.namelist():
                    content = zin.read(item)
                    
                    if item == 'word/comments.xml':
                        xml = content.decode('utf-8')
                        # Add new comment entry
                        new_comment = (
                            f'<w:comment w:id="{new_comment_id}" w:author="ThreadTest" '
                            f'w:date="{timestamp}" w:initials="TT">'
                            f'<w:p w14:paraId="{new_para_id}" w14:textId="{new_text_id}" '
                            f'w:rsidR="{new_rsid}" w:rsidRDefault="{new_rsid}">'
                            f'<w:pPr><w:pStyle w:val="CommentText"/></w:pPr>'
                            f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                            f'<w:annotationRef/></w:r>'
                            f'<w:r><w:t>{reply_text}</w:t></w:r>'
                            f'</w:p></w:comment>'
                        )
                        xml = xml.replace('</w:comments>', new_comment + '</w:comments>')
                        content = xml.encode('utf-8')
                        
                    elif item == 'word/commentsExtended.xml':
                        xml = content.decode('utf-8')
                        # Add commentEx with paraIdParent pointing to parent
                        new_entry = (
                            f'<w15:commentEx w15:paraId="{new_para_id}" '
                            f'w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
                        )
                        xml = xml.replace('</w15:commentsEx>', new_entry + '</w15:commentsEx>')
                        content = xml.encode('utf-8')
                        
                    elif item == 'word/commentsIds.xml':
                        xml = content.decode('utf-8')
                        # Add commentId entry
                        new_entry = (
                            f'<w16cid:commentId w16cid:paraId="{new_para_id}" '
                            f'w16cid:durableId="{new_durable_id}"/>'
                        )
                        xml = xml.replace('</w16cid:commentsIds>', new_entry + '</w16cid:commentsIds>')
                        content = xml.encode('utf-8')
                        
                    elif item == 'word/commentsExtensible.xml':
                        xml = content.decode('utf-8')
                        # Add commentExtensible entry
                        new_entry = (
                            f'<w16cex:commentExtensible w16cex:durableId="{new_durable_id}" '
                            f'w16cex:dateUtc="{timestamp_utc}"/>'
                        )
                        xml = xml.replace('</w16cex:commentsExtensible>', 
                                         new_entry + '</w16cex:commentsExtensible>')
                        content = xml.encode('utf-8')
                        
                    elif item == 'word/document.xml':
                        xml = content.decode('utf-8')
                        # Add anchor using Word-style nesting:
                        # CRITICAL: Must insert AFTER all existing replies to maintain order
                        # Word expects: rangeStart[root] → rangeStart[reply1] → rangeStart[reply2] → ...
                        #               rangeEnd[root] → ref[root] → rangeEnd[reply1] → ref[reply1] → ...
                        
                        # Find the LAST rangeStart in the thread (could be parent or existing reply)
                        # We need to find parent's rangeStart, then find any existing reply rangeStarts
                        parent_start = f'<w:commentRangeStart w:id="{parent_comment_id}"/>'
                        parent_start_idx = xml.find(parent_start)
                        
                        if parent_start_idx > 0:
                            # Look for consecutive rangeStarts after parent (existing replies)
                            # Insert our rangeStart after ALL of them
                            search_pos = parent_start_idx + len(parent_start)
                            last_range_start_end = search_pos
                            
                            # Keep finding consecutive rangeStarts
                            while True:
                                # Skip whitespace
                                temp_pos = search_pos
                                while temp_pos < len(xml) and xml[temp_pos] in ' \t\n\r':
                                    temp_pos += 1
                                
                                # Check if next element is a commentRangeStart
                                if xml[temp_pos:temp_pos+20].startswith('<w:commentRangeStart'):
                                    # Find end of this rangeStart
                                    end_tag = xml.find('/>', temp_pos)
                                    if end_tag > 0:
                                        last_range_start_end = end_tag + 2
                                        search_pos = last_range_start_end
                                    else:
                                        break
                                else:
                                    break
                            
                            # Insert our rangeStart after all existing ones
                            new_start = f'<w:commentRangeStart w:id="{new_comment_id}"/>'
                            xml = xml[:last_range_start_end] + new_start + xml[last_range_start_end:]
                        
                        # Find the LAST rangeEnd/reference pair in the thread
                        # We need to insert after all existing reply rangeEnd/references
                        parent_ref_pattern = f'<w:commentReference w:id="{parent_comment_id}"/>'
                        parent_ref_idx = xml.find(parent_ref_pattern)
                        
                        if parent_ref_idx > 0:
                            # Find the </w:r> after parent's reference
                            close_r_idx = xml.find('</w:r>', parent_ref_idx)
                            if close_r_idx > 0:
                                search_pos = close_r_idx + len('</w:r>')
                                last_insert_pos = search_pos
                                
                                # Look for consecutive rangeEnd/reference pairs (existing replies)
                                while True:
                                    # Skip whitespace
                                    temp_pos = search_pos
                                    while temp_pos < len(xml) and xml[temp_pos] in ' \t\n\r':
                                        temp_pos += 1
                                    
                                    # Check if next element is a commentRangeEnd
                                    if xml[temp_pos:temp_pos+18].startswith('<w:commentRangeEnd'):
                                        # Find the reference that follows
                                        end_tag = xml.find('/>', temp_pos)
                                        if end_tag > 0:
                                            # Look for the closing </w:r> of the reference
                                            ref_close = xml.find('</w:r>', end_tag)
                                            if ref_close > 0:
                                                last_insert_pos = ref_close + len('</w:r>')
                                                search_pos = last_insert_pos
                                            else:
                                                break
                                        else:
                                            break
                                    else:
                                        break
                                
                                # Insert our rangeEnd and reference after all existing ones
                                new_elements = (
                                    f'<w:commentRangeEnd w:id="{new_comment_id}"/>'
                                    f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                                    f'<w:commentReference w:id="{new_comment_id}"/></w:r>'
                                )
                                xml = xml[:last_insert_pos] + new_elements + xml[last_insert_pos:]
                        
                        content = xml.encode('utf-8')
                    
                    zout.writestr(item, content)
        
        # Replace original with modified
        os.replace(temp_path, docx_path)
        return True, f"Added reply (ID: {new_comment_id}) to comment {parent_comment_id}"
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, str(e)


def run_tests():
    """Run threading tests on all selected documents."""
    
    # Setup output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clear previous test results
    for f in OUTPUT_DIR.glob('*.docx'):
        f.unlink()
    
    test_data_dir = Path(__file__).parent.parent / "test_data"
    results = []
    
    print("=" * 70)
    print("THREADING STRESS TEST")
    print("=" * 70)
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    
    for filename, description in TEST_DOCUMENTS:
        src_path = test_data_dir / filename
        
        if not src_path.exists():
            print(f"SKIP: {filename} - file not found")
            results.append({
                'file': filename,
                'description': description,
                'status': 'SKIPPED',
                'reason': 'File not found'
            })
            continue
        
        print(f"Processing: {filename}")
        print(f"  Description: {description}")
        
        # Extract comment info
        comments = extract_comment_info(src_path)
        root_comments = [c for c in comments if not c['is_reply'] and c['para_id']]
        
        if not root_comments:
            print(f"  SKIP: No root comments found")
            results.append({
                'file': filename,
                'description': description,
                'status': 'SKIPPED',
                'reason': 'No root comments'
            })
            continue
        
        print(f"  Found {len(comments)} comments ({len(root_comments)} root comments)")
        
        # Create test copy
        test_name = Path(filename).stem
        dest_path = OUTPUT_DIR / f"{test_name}_threaded.docx"
        shutil.copy2(src_path, dest_path)
        
        # Add replies to first 3 root comments (or fewer if less available)
        test_comments = root_comments[:min(3, len(root_comments))]
        replies_added = 0
        
        for i, comment in enumerate(test_comments):
            reply_text = f"[Test Reply {i+1}] This is a test reply to validate threading."
            
            success, msg = add_threaded_reply(
                dest_path,
                comment['id'],
                comment['para_id'],
                reply_text,
                test_name
            )
            
            if success:
                replies_added += 1
                print(f"    Added reply to comment {comment['id']}: OK")
            else:
                print(f"    Failed to add reply to comment {comment['id']}: {msg}")
        
        # Add a second reply to the first comment to test multiple replies
        if test_comments:
            first_comment = test_comments[0]
            success, msg = add_threaded_reply(
                dest_path,
                first_comment['id'],
                first_comment['para_id'],
                "[Test Reply - Second] Testing multiple replies to same comment.",
                test_name
            )
            if success:
                replies_added += 1
                print(f"    Added second reply to comment {first_comment['id']}: OK")
        
        results.append({
            'file': filename,
            'output_file': dest_path.name,
            'description': description,
            'status': 'CREATED',
            'root_comments': len(root_comments),
            'replies_added': replies_added
        })
        print()
    
    # Generate test matrix
    print("=" * 70)
    print("TEST MATRIX")
    print("=" * 70)
    
    matrix_path = OUTPUT_DIR / "TEST_MATRIX.md"
    with open(matrix_path, 'w') as f:
        f.write("# Threading Stress Test Results\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Instructions\n\n")
        f.write("1. Open each file in Microsoft Word\n")
        f.write("2. Check if the test replies appear as **threaded replies** (indented under parent)\n")
        f.write("3. Fill in the 'Result' column below\n\n")
        f.write("## Test Files\n\n")
        f.write("| File | Description | Replies Added | Result | Notes |\n")
        f.write("|------|-------------|---------------|--------|-------|\n")
        
        for r in results:
            if r['status'] == 'CREATED':
                f.write(f"| {r['output_file']} | {r['description']} | {r['replies_added']} | | |\n")
            else:
                f.write(f"| {r['file']} | {r['description']} | N/A | {r['status']} | {r.get('reason', '')} |\n")
        
        f.write("\n## What to Check\n\n")
        f.write("For each file, verify:\n")
        f.write("- [ ] File opens without errors\n")
        f.write("- [ ] Test replies appear as indented/threaded under parent comment\n")
        f.write("- [ ] Multiple replies to same comment are all threaded\n")
        f.write("- [ ] Document content is not corrupted\n\n")
        f.write("## Result Legend\n\n")
        f.write("- **PASS**: All replies are correctly threaded\n")
        f.write("- **PARTIAL**: Some replies threaded, some standalone\n")
        f.write("- **FAIL**: No replies threaded, or file won't open\n")
        f.write("- **CORRUPT**: File opens but content is damaged\n")
    
    print(f"Test matrix written to: {matrix_path}")
    print()
    print("FILES READY FOR TESTING:")
    for r in results:
        if r['status'] == 'CREATED':
            print(f"  - {r['output_file']} ({r['replies_added']} replies added)")
    
    return results


if __name__ == '__main__':
    run_tests()
