#!/usr/bin/env python3
"""
ParaId Constraint Validation Test

Validates that the w14:paraId (and related hex IDs) constraint holds across various scenarios:
1. The first character must be 0-7 (not 8-F)
2. Tests if textId, durableId, and rsidR have the same constraint
3. Tests across different comments and document types

Based on discovery: Word interprets these 8-char hex IDs as signed 32-bit integers,
rejecting values >= 0x80000000 (negative when signed).
"""

import zipfile
import shutil
import uuid
import re
import random
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, List, Optional

OUTPUT_DIR = Path("output/paraid_validation")


def generate_valid_hex_id(length: int = 8) -> str:
    """Generate a hex ID with first character constrained to 0-7 (valid)."""
    raw = uuid.uuid4().hex[:length].upper()
    first_char = raw[0]
    if first_char in '89ABCDEF':
        # Map 8-F to 0-7
        new_first = str(int(first_char, 16) % 8)
        raw = new_first + raw[1:]
    return raw


def generate_invalid_hex_id(length: int = 8) -> str:
    """Generate a hex ID with first character in 8-F range (invalid)."""
    first_char = random.choice('89ABCDEF')
    rest = uuid.uuid4().hex[1:length].upper()
    return first_char + rest


def get_all_comment_ids(docx_path: Path) -> List[str]:
    """Get all comment IDs from a document."""
    with zipfile.ZipFile(docx_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        return [m.group(1) for m in re.finditer(r'<w:comment[^>]*w:id="(\d+)"', comments_xml)]


def get_all_track_change_ids(docx_path: Path) -> List[str]:
    """Get all track change IDs from a document."""
    with zipfile.ZipFile(docx_path, 'r') as zf:
        doc_xml = zf.read('word/document.xml').decode('utf-8')
        ids = set()
        for m in re.finditer(r'<w:(ins|del|rPrChange|pPrChange)[^>]*w:id="(\d+)"', doc_xml):
            ids.add(m.group(2))
        return list(ids)


def generate_random_comment_id(existing_ids: List[str]) -> str:
    """Generate a random comment ID that doesn't conflict."""
    existing_set = set(int(x) for x in existing_ids if x.isdigit())
    while True:
        new_id = random.randint(100, 9999)
        if new_id not in existing_set:
            return str(new_id)


def add_reply_with_custom_ids(
    docx_path: Path,
    output_path: Path,
    parent_comment_id: str,
    reply_text: str,
    para_id: str,
    text_id: str,
    rsid: str,
    durable_id: str,
    author: str = "ValidTest",
    initials: str = "VT",
) -> Tuple[bool, str]:
    """Add a threaded reply with specific IDs (for testing constraints)."""
    
    if docx_path.resolve() != output_path.resolve():
        shutil.copy(docx_path, output_path)
    
    comment_ids = get_all_comment_ids(output_path)
    track_ids = get_all_track_change_ids(output_path)
    all_ids = comment_ids + track_ids
    
    new_comment_id = generate_random_comment_id(all_ids)
    
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Find parent's paraId
    parent_para_id = None
    existing_reply_ids = []
    existing_reply_para_ids = []
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        comments_xml = zf.read('word/comments.xml').decode('utf-8')
        comments_extended_xml = zf.read('word/commentsExtended.xml').decode('utf-8')
        comments_ids_xml = zf.read('word/commentsIds.xml').decode('utf-8')
        
        pattern = rf'<w:comment[^>]*w:id="{parent_comment_id}"[^>]*>.*?w14:paraId="([^"]+)"'
        match = re.search(pattern, comments_xml, re.DOTALL)
        if match:
            parent_para_id = match.group(1)
        else:
            return False, f"Parent comment {parent_comment_id} not found"
        
        reply_pattern = rf'<w15:commentEx[^>]*w15:paraId="([^"]+)"[^>]*w15:paraIdParent="{parent_para_id}"'
        for m in re.finditer(reply_pattern, comments_extended_xml):
            existing_reply_para_ids.append(m.group(1))
        
        for reply_para_id in existing_reply_para_ids:
            id_pattern = rf'<w:comment[^>]*w:id="(\d+)"[^>]*>(?:(?!</w:comment>).)*?w14:paraId="{reply_para_id}"'
            m = re.search(id_pattern, comments_xml, re.DOTALL)
            if m:
                existing_reply_ids.append(m.group(1))
        
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
    
    modified_files = {}
    
    with zipfile.ZipFile(output_path, 'r') as zf:
        for item in zf.namelist():
            content = zf.read(item)
            
            if item == 'word/comments.xml':
                xml = content.decode('utf-8')
                new_comment = f'<w:comment w:id="{new_comment_id}" w:author="{author}" w:date="{date_str}" w:initials="{initials}"><w:p w14:paraId="{para_id}" w14:textId="{text_id}" w:rsidR="{rsid}" w:rsidRDefault="{rsid}"><w:pPr><w:pStyle w:val="CommentText"/></w:pPr><w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r><w:r><w:t>{reply_text}</w:t></w:r></w:p></w:comment>'
                pattern = rf'(<w:comment[^>]*w:id="{parent_comment_id}"[^>]*>.*?</w:comment>)'
                match = re.search(pattern, xml, re.DOTALL)
                if match:
                    xml = xml[:match.end()] + new_comment + xml[match.end():]
                content = xml.encode('utf-8')
                
            elif item == 'word/commentsExtended.xml':
                xml = content.decode('utf-8')
                new_entry = f'<w15:commentEx w15:paraId="{para_id}" w15:paraIdParent="{parent_para_id}" w15:done="0"/>'
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
                new_entry = f'<w16cid:commentId w16cid:paraId="{para_id}" w16cid:durableId="{durable_id}"/>'
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
                new_entry = f'<w16cex:commentExtensible w16cex:durableId="{durable_id}" w16cex:dateUtc="{date_str}"/>'
                if last_reply_durable_id:
                    pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{last_reply_durable_id}"[^>]*/>)'
                elif parent_durable_id:
                    pattern = rf'(<w16cex:commentExtensible[^>]*w16cex:durableId="{parent_durable_id}"[^>]*/>)'
                else:
                    pattern = r'(<w16cex:commentExtensible[^>]*/>)'
                match = re.search(pattern, xml)
                if match:
                    xml = xml[:match.end()] + new_entry + xml[match.end():]
                content = xml.encode('utf-8')
                
            elif item == 'word/document.xml':
                xml = content.decode('utf-8')
                if existing_reply_ids:
                    last_start = f'<w:commentRangeStart w:id="{existing_reply_ids[-1]}"/>'
                else:
                    last_start = f'<w:commentRangeStart w:id="{parent_comment_id}"/>'
                xml = xml.replace(last_start, last_start + f'<w:commentRangeStart w:id="{new_comment_id}"/>')
                
                if existing_reply_ids:
                    ref_pattern = rf'(<w:commentReference w:id="{existing_reply_ids[-1]}"/>\s*</w:r>)'
                else:
                    ref_pattern = rf'(<w:commentReference w:id="{parent_comment_id}"/>\s*</w:r>)'
                match = re.search(ref_pattern, xml)
                if match:
                    new_elements = f'<w:commentRangeEnd w:id="{new_comment_id}"/><w:r w:rsidR="{rsid}"><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{new_comment_id}"/></w:r>'
                    xml = xml[:match.end()] + new_elements + xml[match.end():]
                content = xml.encode('utf-8')
            
            modified_files[item] = content
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in modified_files.items():
            zf.writestr(name, data)
    
    return True, f"Added reply ID={new_comment_id}, paraId={para_id}"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(456)  # Different seed from comprehensive test
    
    test_doc = Path("test_data/test.docx")
    if not test_doc.exists():
        print(f"ERROR: {test_doc} not found")
        return
    
    results = []
    
    # =========================================================================
    # SECTION 1: Validate paraId constraint across different comments
    # =========================================================================
    print("=" * 70)
    print("SECTION 1: ParaId constraint across different comments")
    print("=" * 70)
    
    for comment_id in ["0", "1", "2", "3"]:
        print(f"\n--- Comment {comment_id} ---")
        
        # Valid paraId (first char 0-7)
        valid_para_id = generate_valid_hex_id()
        output_valid = OUTPUT_DIR / f"comment_{comment_id}_valid_paraid.docx"
        success, msg = add_reply_with_custom_ids(
            test_doc, output_valid, comment_id,
            f"Reply with VALID paraId to comment {comment_id}",
            para_id=valid_para_id,
            text_id=generate_valid_hex_id(),
            rsid=generate_valid_hex_id(),
            durable_id=generate_valid_hex_id(),
        )
        print(f"  Valid ({valid_para_id}): {msg}")
        results.append((f"comment_{comment_id}_valid_paraid.docx", comment_id, 
                       "valid paraId", valid_para_id, "?"))
        
        # Invalid paraId (first char 8-F)
        invalid_para_id = generate_invalid_hex_id()
        output_invalid = OUTPUT_DIR / f"comment_{comment_id}_invalid_paraid.docx"
        success, msg = add_reply_with_custom_ids(
            test_doc, output_invalid, comment_id,
            f"Reply with INVALID paraId to comment {comment_id}",
            para_id=invalid_para_id,
            text_id=generate_valid_hex_id(),
            rsid=generate_valid_hex_id(),
            durable_id=generate_valid_hex_id(),
        )
        print(f"  Invalid ({invalid_para_id}): {msg}")
        results.append((f"comment_{comment_id}_invalid_paraid.docx", comment_id,
                       "invalid paraId", invalid_para_id, "?"))
    
    # =========================================================================
    # SECTION 2: Test textId constraint (valid paraId, invalid textId)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 2: TextId constraint test")
    print("=" * 70)
    
    # Valid paraId + invalid textId
    valid_para = generate_valid_hex_id()
    invalid_text = generate_invalid_hex_id()
    output = OUTPUT_DIR / "valid_paraid_invalid_textid.docx"
    success, msg = add_reply_with_custom_ids(
        test_doc, output, "0",
        "Testing: valid paraId but INVALID textId",
        para_id=valid_para,
        text_id=invalid_text,
        rsid=generate_valid_hex_id(),
        durable_id=generate_valid_hex_id(),
    )
    print(f"  paraId={valid_para} (valid), textId={invalid_text} (invalid): {msg}")
    results.append(("valid_paraid_invalid_textid.docx", "0",
                   f"valid paraId, INVALID textId", f"p:{valid_para} t:{invalid_text}", "?"))
    
    # =========================================================================
    # SECTION 3: Test durableId constraint (valid paraId/textId, invalid durableId)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 3: DurableId constraint test")
    print("=" * 70)
    
    valid_para = generate_valid_hex_id()
    valid_text = generate_valid_hex_id()
    invalid_durable = generate_invalid_hex_id()
    output = OUTPUT_DIR / "valid_para_text_invalid_durable.docx"
    success, msg = add_reply_with_custom_ids(
        test_doc, output, "0",
        "Testing: valid paraId/textId but INVALID durableId",
        para_id=valid_para,
        text_id=valid_text,
        rsid=generate_valid_hex_id(),
        durable_id=invalid_durable,
    )
    print(f"  paraId={valid_para}, textId={valid_text} (valid), durableId={invalid_durable} (invalid): {msg}")
    results.append(("valid_para_text_invalid_durable.docx", "0",
                   f"valid paraId/textId, INVALID durableId", f"d:{invalid_durable}", "?"))
    
    # =========================================================================
    # SECTION 4: Test rsidR constraint (all else valid, invalid rsidR)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 4: RsidR constraint test")
    print("=" * 70)
    
    valid_para = generate_valid_hex_id()
    valid_text = generate_valid_hex_id()
    valid_durable = generate_valid_hex_id()
    invalid_rsid = generate_invalid_hex_id()
    output = OUTPUT_DIR / "all_valid_except_rsid.docx"
    success, msg = add_reply_with_custom_ids(
        test_doc, output, "0",
        "Testing: all valid EXCEPT rsidR",
        para_id=valid_para,
        text_id=valid_text,
        rsid=invalid_rsid,
        durable_id=valid_durable,
    )
    print(f"  All valid except rsidR={invalid_rsid} (invalid): {msg}")
    results.append(("all_valid_except_rsid.docx", "0",
                   f"all valid, INVALID rsidR", f"r:{invalid_rsid}", "?"))
    
    # =========================================================================
    # SECTION 5: All valid IDs - comprehensive test
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 5: All valid IDs (control group)")
    print("=" * 70)
    
    # All valid for each comment
    for comment_id in ["0", "1", "2", "3"]:
        valid_para = generate_valid_hex_id()
        valid_text = generate_valid_hex_id()
        valid_rsid = generate_valid_hex_id()
        valid_durable = generate_valid_hex_id()
        output = OUTPUT_DIR / f"all_valid_comment_{comment_id}.docx"
        success, msg = add_reply_with_custom_ids(
            test_doc, output, comment_id,
            f"All valid IDs test for comment {comment_id}",
            para_id=valid_para,
            text_id=valid_text,
            rsid=valid_rsid,
            durable_id=valid_durable,
        )
        print(f"  Comment {comment_id} (all valid): {msg}")
        results.append((f"all_valid_comment_{comment_id}.docx", comment_id,
                       "all valid IDs", f"p:{valid_para[:4]}.. t:{valid_text[:4]}.. d:{valid_durable[:4]}..", "?"))
    
    # =========================================================================
    # SECTION 6: Boundary test (7 vs 8)
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 6: Boundary test (7 vs 8 first character)")
    print("=" * 70)
    
    # Exactly at boundary - 7
    boundary_7 = "7" + uuid.uuid4().hex[1:8].upper()
    output = OUTPUT_DIR / "boundary_7.docx"
    success, msg = add_reply_with_custom_ids(
        test_doc, output, "0",
        "Boundary test: paraId starts with 7",
        para_id=boundary_7,
        text_id=generate_valid_hex_id(),
        rsid=generate_valid_hex_id(),
        durable_id=generate_valid_hex_id(),
    )
    print(f"  paraId={boundary_7} (starts with 7): {msg}")
    results.append(("boundary_7.docx", "0", "boundary: first char = 7", boundary_7, "?"))
    
    # Exactly at boundary - 8
    boundary_8 = "8" + uuid.uuid4().hex[1:8].upper()
    output = OUTPUT_DIR / "boundary_8.docx"
    success, msg = add_reply_with_custom_ids(
        test_doc, output, "0",
        "Boundary test: paraId starts with 8",
        para_id=boundary_8,
        text_id=generate_valid_hex_id(),
        rsid=generate_valid_hex_id(),
        durable_id=generate_valid_hex_id(),
    )
    print(f"  paraId={boundary_8} (starts with 8): {msg}")
    results.append(("boundary_8.docx", "0", "boundary: first char = 8", boundary_8, "?"))
    
    # =========================================================================
    # SECTION 7: Multiple replies - all valid
    # =========================================================================
    print("\n" + "=" * 70)
    print("SECTION 7: Multiple replies with all valid IDs")
    print("=" * 70)
    
    output = OUTPUT_DIR / "multi_reply_all_valid.docx"
    shutil.copy(test_doc, output)
    
    for i in range(3):
        valid_para = generate_valid_hex_id()
        success, msg = add_reply_with_custom_ids(
            output, output, "0",
            f"Reply {i+1} with all valid IDs",
            para_id=valid_para,
            text_id=generate_valid_hex_id(),
            rsid=generate_valid_hex_id(),
            durable_id=generate_valid_hex_id(),
        )
        print(f"  Reply {i+1}: {msg}")
    results.append(("multi_reply_all_valid.docx", "0", 
                   "3 replies, all valid IDs", "multiple", "?"))
    
    # =========================================================================
    # Write test matrix
    # =========================================================================
    matrix_path = OUTPUT_DIR / "VALIDATION_MATRIX.md"
    with open(matrix_path, 'w') as f:
        f.write("# ParaId Constraint Validation Test Matrix\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("**Hypothesis:** The first character of w14:paraId must be 0-7 (not 8-F).\n\n")
        f.write("**Additional hypotheses being tested:**\n")
        f.write("- Does textId have the same constraint?\n")
        f.write("- Does durableId have the same constraint?\n")
        f.write("- Does rsidR have the same constraint?\n\n")
        f.write("---\n\n")
        
        f.write("## Section 1: ParaId Constraint Across Different Comments\n\n")
        f.write("| File | Comment | Test Type | ID Value | Threaded? | Notes |\n")
        f.write("|------|---------|-----------|----------|-----------|-------|\n")
        for r in results:
            if r[0].startswith("comment_"):
                f.write(f"| {r[0]} | {r[1]} | {r[2]} | `{r[3]}` | | |\n")
        
        f.write("\n## Section 2: TextId Constraint\n\n")
        f.write("| File | Test Type | ID Values | Threaded? | Notes |\n")
        f.write("|------|-----------|-----------|-----------|-------|\n")
        for r in results:
            if "textid" in r[0].lower():
                f.write(f"| {r[0]} | {r[2]} | `{r[3]}` | | |\n")
        
        f.write("\n## Section 3: DurableId Constraint\n\n")
        f.write("| File | Test Type | ID Values | Threaded? | Notes |\n")
        f.write("|------|-----------|-----------|-----------|-------|\n")
        for r in results:
            if "durable" in r[0].lower():
                f.write(f"| {r[0]} | {r[2]} | `{r[3]}` | | |\n")
        
        f.write("\n## Section 4: RsidR Constraint\n\n")
        f.write("| File | Test Type | ID Values | Threaded? | Notes |\n")
        f.write("|------|-----------|-----------|-----------|-------|\n")
        for r in results:
            if "rsid" in r[0].lower():
                f.write(f"| {r[0]} | {r[2]} | `{r[3]}` | | |\n")
        
        f.write("\n## Section 5: All Valid IDs (Control Group)\n\n")
        f.write("| File | Comment | Test Type | Threaded? | Notes |\n")
        f.write("|------|---------|-----------|-----------|-------|\n")
        for r in results:
            if r[0].startswith("all_valid_comment_"):
                f.write(f"| {r[0]} | {r[1]} | {r[2]} | | |\n")
        
        f.write("\n## Section 6: Boundary Tests (7 vs 8)\n\n")
        f.write("| File | First Char | paraId | Threaded? | Notes |\n")
        f.write("|------|------------|--------|-----------|-------|\n")
        for r in results:
            if "boundary" in r[0].lower():
                f.write(f"| {r[0]} | {r[0].split('_')[1].replace('.docx','')} | `{r[3]}` | | |\n")
        
        f.write("\n## Section 7: Multiple Replies\n\n")
        f.write("| File | Test Type | Threaded? | Notes |\n")
        f.write("|------|-----------|-----------|-------|\n")
        for r in results:
            if "multi_reply" in r[0].lower():
                f.write(f"| {r[0]} | {r[2]} | | |\n")
        
        f.write("\n---\n\n")
        f.write("## Expected Results\n\n")
        f.write("Based on our hypothesis:\n\n")
        f.write("| Section | Expected Outcome |\n")
        f.write("|---------|------------------|\n")
        f.write("| 1: Valid paraId | All should be threaded |\n")
        f.write("| 1: Invalid paraId | None should be threaded |\n")
        f.write("| 2: Invalid textId | Unknown - testing if textId has same constraint |\n")
        f.write("| 3: Invalid durableId | Unknown - testing if durableId has same constraint |\n")
        f.write("| 4: Invalid rsidR | Unknown - testing if rsidR has same constraint |\n")
        f.write("| 5: All valid | All should be threaded (control group) |\n")
        f.write("| 6: Boundary 7 | Should be threaded (last valid value) |\n")
        f.write("| 6: Boundary 8 | Should NOT be threaded (first invalid value) |\n")
        f.write("| 7: Multiple replies | All should be threaded |\n")
        
        f.write("\n---\n\n")
        f.write("## Summary (fill in after testing)\n\n")
        f.write("**ParaId constraint validated:** Yes / No\n\n")
        f.write("**TextId has same constraint:** Yes / No / Partial\n\n")
        f.write("**DurableId has same constraint:** Yes / No / Partial\n\n")
        f.write("**RsidR has same constraint:** Yes / No / Partial\n\n")
        f.write("**Additional observations:**\n\n")
    
    print(f"\n{'=' * 70}")
    print(f"Test files generated in: {OUTPUT_DIR}")
    print(f"Test matrix: {matrix_path}")
    print(f"Total test files: {len([f for f in OUTPUT_DIR.glob('*.docx')])}")
    print("=" * 70)
    print("\nPlease test each file in Word and record results in the matrix.")


if __name__ == "__main__":
    main()
