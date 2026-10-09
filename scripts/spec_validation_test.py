#!/usr/bin/env python3
"""
Specification Validation Test
=============================
Tests the threading specification from docs/word_threading_specification.md

This script creates test files following the spec exactly, with variations
to answer the open questions:
1. Is ID renumbering required, or can we use any unique ID?
2. Are the <w:sz> elements in reference runs required?
3. Does removing proofErr matter?
"""

import os
import sys
import shutil
import zipfile
import re
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "spec_validation"
TEST_DATA_DIR = Path(__file__).parent.parent / "test_data"


def generate_hex_id(length: int = 8) -> str:
    """Generate a random hex ID (uppercase)."""
    return ''.join(random.choices('0123456789ABCDEF', k=length))


def get_comment_info(docx_path: Path) -> Dict:
    """Extract all comment information from a DOCX file."""
    info = {
        'comments': [],  # List of {id, para_id, author, date, initials, text}
        'max_id': -1,
        'para_id_to_id': {},  # para_id -> comment_id mapping
    }
    
    with zipfile.ZipFile(docx_path, 'r') as zf:
        # Parse comments.xml
        if 'word/comments.xml' in zf.namelist():
            comments_xml = zf.read('word/comments.xml').decode('utf-8')
            
            for match in re.finditer(
                r'<w:comment\s+w:id="(\d+)"[^>]*w:author="([^"]*)"[^>]*w:date="([^"]*)"[^>]*w:initials="([^"]*)"[^>]*>',
                comments_xml
            ):
                comment_id = int(match.group(1))
                info['max_id'] = max(info['max_id'], comment_id)
                
                # Find paraId in this comment
                comment_end = comments_xml.find('</w:comment>', match.end())
                comment_content = comments_xml[match.start():comment_end]
                para_match = re.search(r'w14:paraId="([^"]+)"', comment_content)
                para_id = para_match.group(1) if para_match else None
                
                info['comments'].append({
                    'id': str(comment_id),
                    'para_id': para_id,
                    'author': match.group(2),
                    'date': match.group(3),
                    'initials': match.group(4),
                })
                
                if para_id:
                    info['para_id_to_id'][para_id] = str(comment_id)
    
    return info


def add_reply_per_spec(
    docx_path: Path,
    parent_comment_id: str,
    parent_para_id: str,
    reply_text: str,
    author: str = "SpecTest",
    initials: str = "ST",
    # Variation flags
    use_next_sequential_id: bool = True,  # Q1: ID renumbering
    add_sz_elements: bool = True,          # Q2: sz elements
    remove_prooferr: bool = False,         # Q3: proofErr removal
) -> Tuple[bool, str, str]:
    """
    Add a threaded reply following the specification exactly.
    
    Returns: (success, message, new_comment_id)
    """
    try:
        # Generate IDs
        new_para_id = generate_hex_id(8)
        new_text_id = generate_hex_id(8)
        new_durable_id = generate_hex_id(8)
        new_rsid = generate_hex_id(8)
        
        # Timestamps
        now = datetime.now()
        now_utc = datetime.now(timezone.utc)
        timestamp_local = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        timestamp_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        temp_path = str(docx_path) + '.tmp'
        new_comment_id = None
        
        with zipfile.ZipFile(docx_path, 'r') as zin:
            # First pass: determine new comment ID
            comments_xml = zin.read('word/comments.xml').decode('utf-8')
            max_id = max([int(m) for m in re.findall(r'w:id="(\d+)"', comments_xml)] + [-1])
            
            if use_next_sequential_id:
                # Per spec: Word uses sequential IDs
                new_comment_id = str(max_id + 1)
            else:
                # Variation: use a high random ID
                new_comment_id = str(max_id + 100 + random.randint(1, 1000))
            
            with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.namelist():
                    content = zin.read(item)
                    
                    if item == 'word/comments.xml':
                        xml = content.decode('utf-8')
                        
                        # Build new comment entry per spec
                        new_comment = (
                            f'<w:comment w:id="{new_comment_id}" w:author="{author}" '
                            f'w:date="{timestamp_local}" w:initials="{initials}">'
                            f'<w:p w14:paraId="{new_para_id}" w14:textId="{new_text_id}" '
                            f'w:rsidR="{new_rsid}" w:rsidRDefault="{new_rsid}">'
                            f'<w:pPr><w:pStyle w:val="CommentText"/></w:pPr>'
                            f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                            f'<w:annotationRef/></w:r>'
                            f'<w:r><w:t>{reply_text}</w:t></w:r>'
                            f'</w:p></w:comment>'
                        )
                        
                        # Insert after parent comment (per spec: replies follow root)
                        # Find end of parent comment
                        parent_pattern = f'w:id="{parent_comment_id}"'
                        parent_idx = xml.find(parent_pattern)
                        if parent_idx > 0:
                            # Find end of this comment
                            comment_end = xml.find('</w:comment>', parent_idx)
                            if comment_end > 0:
                                insert_pos = comment_end + len('</w:comment>')
                                xml = xml[:insert_pos] + new_comment + xml[insert_pos:]
                            else:
                                # Fallback: append before closing tag
                                xml = xml.replace('</w:comments>', new_comment + '</w:comments>')
                        else:
                            xml = xml.replace('</w:comments>', new_comment + '</w:comments>')
                        
                        content = xml.encode('utf-8')
                    
                    elif item == 'word/commentsExtended.xml':
                        xml = content.decode('utf-8')
                        
                        # Per spec: insert after root entry, with paraIdParent
                        new_entry = (
                            f'<w15:commentEx w15:paraId="{new_para_id}" '
                            f'w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
                        )
                        
                        # Find parent entry and insert after it
                        parent_pattern = f'w15:paraId="{parent_para_id}"'
                        parent_idx = xml.find(parent_pattern)
                        if parent_idx > 0:
                            # Find end of this entry
                            entry_end = xml.find('/>', parent_idx)
                            if entry_end > 0:
                                insert_pos = entry_end + 2
                                xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
                            else:
                                xml = xml.replace('</w15:commentsEx>', new_entry + '</w15:commentsEx>')
                        else:
                            xml = xml.replace('</w15:commentsEx>', new_entry + '</w15:commentsEx>')
                        
                        content = xml.encode('utf-8')
                    
                    elif item == 'word/commentsIds.xml':
                        xml = content.decode('utf-8')
                        
                        # Per spec: insert after parent's entry
                        new_entry = (
                            f'<w16cid:commentId w16cid:paraId="{new_para_id}" '
                            f'w16cid:durableId="{new_durable_id}"/>'
                        )
                        
                        parent_pattern = f'w16cid:paraId="{parent_para_id}"'
                        parent_idx = xml.find(parent_pattern)
                        if parent_idx > 0:
                            entry_end = xml.find('/>', parent_idx)
                            if entry_end > 0:
                                insert_pos = entry_end + 2
                                xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
                            else:
                                xml = xml.replace('</w16cid:commentsIds>', new_entry + '</w16cid:commentsIds>')
                        else:
                            xml = xml.replace('</w16cid:commentsIds>', new_entry + '</w16cid:commentsIds>')
                        
                        content = xml.encode('utf-8')
                    
                    elif item == 'word/commentsExtensible.xml':
                        xml = content.decode('utf-8')
                        
                        # Per spec: insert linked by durableId
                        new_entry = (
                            f'<w16cex:commentExtensible w16cex:durableId="{new_durable_id}" '
                            f'w16cex:dateUtc="{timestamp_utc}"/>'
                        )
                        
                        # Find parent's durableId first
                        # Need to look up parent's durableId from commentsIds
                        parent_durable_pattern = f'w16cid:paraId="{parent_para_id}"[^>]*w16cid:durableId="([^"]+)"'
                        # We need to read commentsIds to get this...
                        # For now, just append after matching durableId pattern or at end
                        
                        # Simpler: just append in same position as commentsIds (after root's entry)
                        # Since we don't have easy access to parent's durableId here,
                        # we'll insert based on order (after first entry which is likely root)
                        first_entry_end = xml.find('/>')
                        if first_entry_end > 0 and first_entry_end < xml.find('</w16cex:commentsExtensible>'):
                            insert_pos = first_entry_end + 2
                            xml = xml[:insert_pos] + new_entry + xml[insert_pos:]
                        else:
                            xml = xml.replace('</w16cex:commentsExtensible>', 
                                            new_entry + '</w16cex:commentsExtensible>')
                        
                        content = xml.encode('utf-8')
                    
                    elif item == 'word/document.xml':
                        xml = content.decode('utf-8')
                        
                        # Q3: Optionally remove proofErr elements
                        if remove_prooferr:
                            xml = re.sub(r'<w:proofErr[^/]*/>', '', xml)
                        
                        # Per spec: insert rangeStart right after parent's rangeStart
                        parent_range_start = f'<w:commentRangeStart w:id="{parent_comment_id}"/>'
                        new_range_start = f'<w:commentRangeStart w:id="{new_comment_id}"/>'
                        
                        if parent_range_start in xml:
                            xml = xml.replace(parent_range_start, 
                                            parent_range_start + new_range_start)
                        
                        # Per spec: insert rangeEnd + reference after parent's reference run
                        parent_ref = f'<w:commentReference w:id="{parent_comment_id}"/>'
                        parent_ref_idx = xml.find(parent_ref)
                        
                        if parent_ref_idx > 0:
                            # Find the </w:r> after parent's reference
                            close_r_idx = xml.find('</w:r>', parent_ref_idx)
                            if close_r_idx > 0:
                                insert_pos = close_r_idx + len('</w:r>')
                                
                                # Build reference run per spec
                                if add_sz_elements:
                                    # Q2: With sz elements (per spec)
                                    new_elements = (
                                        f'<w:commentRangeEnd w:id="{new_comment_id}"/>'
                                        f'<w:r w:rsidR="{new_rsid}">'
                                        f'<w:rPr>'
                                        f'<w:rStyle w:val="CommentReference"/>'
                                        f'<w:sz w:val="24"/>'
                                        f'<w:szCs w:val="24"/>'
                                        f'</w:rPr>'
                                        f'<w:commentReference w:id="{new_comment_id}"/>'
                                        f'</w:r>'
                                    )
                                else:
                                    # Q2: Without sz elements
                                    new_elements = (
                                        f'<w:commentRangeEnd w:id="{new_comment_id}"/>'
                                        f'<w:r w:rsidR="{new_rsid}">'
                                        f'<w:rPr>'
                                        f'<w:rStyle w:val="CommentReference"/>'
                                        f'</w:rPr>'
                                        f'<w:commentReference w:id="{new_comment_id}"/>'
                                        f'</w:r>'
                                    )
                                
                                xml = xml[:insert_pos] + new_elements + xml[insert_pos:]
                        
                        content = xml.encode('utf-8')
                    
                    zout.writestr(item, content)
        
        # Replace original with modified
        os.replace(temp_path, docx_path)
        return True, f"Reply added (ID: {new_comment_id})", new_comment_id
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, str(e), None


def run_tests():
    """Run specification validation tests."""
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clear previous results
    for f in OUTPUT_DIR.glob('*.docx'):
        f.unlink()
    
    print("=" * 70)
    print("SPECIFICATION VALIDATION TEST")
    print("=" * 70)
    print(f"Based on: docs/word_threading_specification.md")
    print(f"Output: {OUTPUT_DIR}")
    print()
    
    # Test configurations
    test_configs = [
        # (name, description, use_next_sequential_id, add_sz_elements, remove_prooferr)
        ("baseline", "Spec exactly as documented", True, True, False),
        ("no_renumber", "Q1: Non-sequential ID", False, True, False),
        ("no_sz", "Q2: Without sz elements", True, False, False),
        ("remove_proof", "Q3: With proofErr removed", True, True, True),
        ("minimal", "All variations: non-seq ID, no sz, no proofErr removal", False, False, False),
    ]
    
    # Test documents (start simple, then complex)
    test_docs = [
        ("test.docx", "Baseline - 4 comments"),
        ("dummy.docx", "Simple - 3 comments"),
    ]
    
    results = []
    
    for doc_name, doc_desc in test_docs:
        source_path = TEST_DATA_DIR / doc_name
        if not source_path.exists():
            print(f"SKIP: {doc_name} not found")
            continue
        
        print(f"\n{'='*60}")
        print(f"Document: {doc_name} ({doc_desc})")
        print(f"{'='*60}")
        
        # Get comment info
        info = get_comment_info(source_path)
        if not info['comments']:
            print(f"  No comments found, skipping")
            continue
        
        # Use first comment as parent
        parent = info['comments'][0]
        print(f"  Parent comment: ID={parent['id']}, paraId={parent['para_id']}")
        
        for config_name, config_desc, use_seq_id, add_sz, remove_proof in test_configs:
            # Create test copy
            output_name = f"{Path(doc_name).stem}_{config_name}.docx"
            output_path = OUTPUT_DIR / output_name
            shutil.copy2(source_path, output_path)
            
            # Add reply
            success, msg, new_id = add_reply_per_spec(
                output_path,
                parent['id'],
                parent['para_id'],
                f"[{config_name}] Test reply following specification.",
                use_next_sequential_id=use_seq_id,
                add_sz_elements=add_sz,
                remove_prooferr=remove_proof,
            )
            
            status = "OK" if success else "FAIL"
            print(f"  {config_name}: {status} - {msg}")
            
            results.append({
                'document': doc_name,
                'config': config_name,
                'description': config_desc,
                'output_file': output_name,
                'success': success,
                'message': msg,
            })
    
    # Generate test matrix
    matrix_path = OUTPUT_DIR / "TEST_MATRIX.md"
    with open(matrix_path, 'w') as f:
        f.write("# Specification Validation Test Results\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Test Configuration\n\n")
        f.write("| Config | Description | Sequential ID | sz Elements | Remove proofErr |\n")
        f.write("|--------|-------------|---------------|-------------|----------------|\n")
        for name, desc, seq_id, sz, proof in test_configs:
            f.write(f"| {name} | {desc} | {'Yes' if seq_id else 'No'} | {'Yes' if sz else 'No'} | {'Yes' if proof else 'No'} |\n")
        
        f.write("\n## Test Results\n\n")
        f.write("| File | Config | Created | Threaded? | Notes |\n")
        f.write("|------|--------|---------|-----------|-------|\n")
        for r in results:
            created = "Yes" if r['success'] else "No"
            f.write(f"| {r['output_file']} | {r['config']} | {created} | | |\n")
        
        f.write("\n## Instructions\n\n")
        f.write("1. Open each file in Microsoft Word\n")
        f.write("2. Check if the test reply appears **threaded** under the first comment\n")
        f.write("3. Fill in the 'Threaded?' column: Yes / No / Error\n")
        f.write("4. Add any notes about issues observed\n\n")
        f.write("## Questions Being Tested\n\n")
        f.write("1. **Q1 (no_renumber)**: Can we use non-sequential IDs?\n")
        f.write("2. **Q2 (no_sz)**: Are `<w:sz>` elements required in reference runs?\n")
        f.write("3. **Q3 (remove_proof)**: Does removing proofErr help or hurt?\n")
    
    print(f"\n{'='*60}")
    print(f"Test matrix: {matrix_path}")
    print(f"Files created: {len([r for r in results if r['success']])}")
    print("Please test in Word and fill in the results.")


if __name__ == '__main__':
    run_tests()
