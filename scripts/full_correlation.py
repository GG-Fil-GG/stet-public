#!/usr/bin/env python3
"""
Complete correlation analysis - collect ALL possible data points in one table.
"""

import json
import zipfile
import re
from pathlib import Path

USER_OBSERVATIONS = {
    1: "S", 3: "R", 4: "S", 5: "R", 9: "R", 12: "S", 14: "S", 16: "R",
    19: "R", 22: "R", 24: "S", 26: "S", 28: "S", 29: "R", 31: "S", 34: "R",
    37: "S", 39: "S", 41: "S", 42: "R", 46: "R", 47: "R", 49: "S", 52: "S",
    54: "S", 57: "S", 60: "S", 64: "R", 67: "S", 69: "S", 71: "S", 72: "S",
    73: "S", 74: "S", 76: "S", 77: "S", 79: "S", 81: "R", 83: "R", 86: "R",
    88: "S", 91: "S", 93: "S", 95: "S", 106: "S", 108: "S", 110: "R",
    113: "S", 118: "R", 121: "R", 122: "S", 124: "S", 126: "S", 129: "S",
    131: "R", 134: "S", 136: "R", 139: "S", 140: "S", 143: "S", 145: "S",
}

def main():
    output_dir = Path(__file__).parent.parent / "output" / "example_manuscript"
    orig_docx = output_dir / "example_manuscript.docx"
    export_docx = output_dir / "example_manuscript_with_replies.docx"
    
    # ===== COLLECT ALL DATA FROM ORIGINAL DOCUMENT =====
    with zipfile.ZipFile(orig_docx, 'r') as z:
        comments_xml = z.read('word/comments.xml').decode('utf-8')
        extended_xml = z.read('word/commentsExtended.xml').decode('utf-8')
    
    # 1. Parse comments.xml: comment_id -> list of para_ids
    comment_para_ids = {}  # comment_id -> [para_id1, para_id2, ...]
    comment_pattern = r'<w:comment[^>]*w:id="(\d+)"[^>]*>(.*?)</w:comment>'
    para_pattern = r'w14:paraId="([^"]+)"'
    for match in re.finditer(comment_pattern, comments_xml, re.DOTALL):
        cid = match.group(1)
        body = match.group(2)
        para_ids = re.findall(para_pattern, body)
        comment_para_ids[cid] = para_ids
    
    # 2. Parse commentsExtended.xml: para_id set and parent relationships
    orig_ext_para_ids = set(re.findall(r'w15:paraId="([^"]+)"', extended_xml))
    
    # Build ordered list of entries
    orig_ext_entries = []  # [(para_id, parent_para_id or None), ...]
    ext_pattern = r'<w15:commentEx[^/]*w15:paraId="([^"]+)"(?:[^/]*w15:paraIdParent="([^"]+)")?[^/]*/>'
    for match in re.finditer(ext_pattern, extended_xml):
        para_id = match.group(1)
        parent = match.group(2)
        orig_ext_entries.append((para_id, parent))
    
    # 3. Map para_id -> comment_id (using which para_id is in commentsExtended)
    para_to_comment = {}
    for cid, pids in comment_para_ids.items():
        for pid in pids:
            if pid in orig_ext_para_ids:
                para_to_comment[pid] = cid
                break  # Only map the one that's in commentsExtended
    
    # 4. Build thread chains: find root and all replies
    # parent_map: comment_id -> parent_comment_id
    parent_map = {}
    for para_id, parent_para in orig_ext_entries:
        if parent_para:
            child_cid = para_to_comment.get(para_id)
            parent_cid = para_to_comment.get(parent_para)
            if child_cid and parent_cid:
                parent_map[child_cid] = parent_cid
    
    # 5. For each root comment, build the full chain
    def get_thread_chain(root_cid):
        """Returns list of comment_ids in thread order: [root, reply1, reply2, ...]"""
        chain = [root_cid]
        # Find all comments that have this root as ancestor
        children = {cid: parent for cid, parent in parent_map.items()}
        
        # BFS to find all descendants
        to_process = [root_cid]
        while to_process:
            current = to_process.pop(0)
            for child, parent in list(children.items()):
                if parent == current:
                    chain.append(child)
                    to_process.append(child)
                    del children[child]
        return chain
    
    # ===== COLLECT DATA FROM EXPORTED DOCUMENT =====
    with zipfile.ZipFile(export_docx, 'r') as z:
        export_comments_xml = z.read('word/comments.xml').decode('utf-8')
        export_extended_xml = z.read('word/commentsExtended.xml').decode('utf-8')
    
    export_ext_para_ids = set(re.findall(r'w15:paraId="([^"]+)"', export_extended_xml))
    new_reply_para_ids = export_ext_para_ids - orig_ext_para_ids
    
    # Map new reply para_id -> its parent
    new_reply_parents = {}
    for match in re.finditer(ext_pattern, export_extended_xml):
        para_id = match.group(1)
        parent = match.group(2)
        if para_id in new_reply_para_ids:
            new_reply_parents[para_id] = parent
    
    # Map comment_id -> para_id for exported comments
    export_comment_para_ids = {}
    for match in re.finditer(comment_pattern, export_comments_xml, re.DOTALL):
        cid = match.group(1)
        body = match.group(2)
        para_ids = re.findall(para_pattern, body)
        if para_ids:
            export_comment_para_ids[cid] = para_ids[-1]  # Last para_id
    
    # ===== BUILD COMPREHENSIVE TABLE =====
    print("COMPREHENSIVE CORRELATION TABLE")
    print("=" * 200)
    print(f"{'Thrd':>4} | {'Obs':^3} | {'#Para':^5} | {'1stPara':^10} | {'LastPara':^10} | {'InExt':^10} | "
          f"{'Chain':^20} | {'LastInChain':^11} | {'LastParaId':^10} | {'ParentUsed':^10} | {'ParentValid':^11} | {'Position':^8}")
    print("-" * 200)
    
    results = []
    
    for thread_id in sorted(USER_OBSERVATIONS.keys()):
        obs = USER_OBSERVATIONS[thread_id]
        cid = str(thread_id)
        
        # Original comment info
        pids = comment_para_ids.get(cid, [])
        num_para = len(pids)
        first_para = pids[0] if pids else "?"
        last_para = pids[-1] if pids else "?"
        
        # Which para_id is in commentsExtended?
        in_ext = "?"
        for pid in pids:
            if pid in orig_ext_para_ids:
                in_ext = pid[:8]
                break
        
        # Thread chain
        chain = get_thread_chain(cid)
        chain_str = "->".join(chain[:4])
        if len(chain) > 4:
            chain_str += f"...({len(chain)})"
        
        last_in_chain = chain[-1]
        
        # Last comment's para_id (this is what we should use as parent)
        last_chain_pids = comment_para_ids.get(last_in_chain, [])
        last_chain_para = "?"
        for pid in last_chain_pids:
            if pid in orig_ext_para_ids:
                last_chain_para = pid
                break
        
        # Find the new reply we added for this thread (by looking at what parent we used)
        # We need to find which new reply has a parent matching what we expected
        parent_used = "?"
        parent_valid = "?"
        position = "?"
        
        # Try to find the reply by matching parent to last_chain_para
        for new_para, parent in new_reply_parents.items():
            if parent == last_chain_para or (last_chain_para == "?" and parent == last_para):
                parent_used = parent[:8] if parent else "None"
                parent_valid = "YES" if parent in orig_ext_para_ids else "NO"
                
                # Check position in commentsExtended
                # Find indices
                export_entries = re.findall(r'w15:paraId="([^"]+)"', export_extended_xml)
                if parent in export_entries and new_para in export_entries:
                    parent_idx = export_entries.index(parent)
                    reply_idx = export_entries.index(new_para)
                    position = f"{reply_idx - parent_idx:+d}"
                break
        
        row = {
            'thread': thread_id,
            'obs': obs,
            'num_para': num_para,
            'first_para': first_para[:8],
            'last_para': last_para[:8],
            'in_ext': in_ext,
            'chain': chain_str,
            'last_in_chain': last_in_chain,
            'last_chain_para': last_chain_para[:8] if last_chain_para != "?" else "?",
            'parent_used': parent_used,
            'parent_valid': parent_valid,
            'position': position
        }
        results.append(row)
        
        print(f"{thread_id:>4} | {obs:^3} | {num_para:^5} | {first_para[:8]:^10} | {last_para[:8]:^10} | {in_ext:^10} | "
              f"{chain_str:^20} | {last_in_chain:^11} | {last_chain_para[:8] if last_chain_para != '?' else '?':^10} | "
              f"{parent_used:^10} | {parent_valid:^11} | {position:^8}")
    
    # ===== STATISTICAL ANALYSIS =====
    print("\n" + "=" * 200)
    print("STATISTICAL ANALYSIS BY OBSERVATION")
    print("=" * 200)
    
    reply_ok = [r for r in results if r['obs'] == 'R']
    standalone = [r for r in results if r['obs'] == 'S']
    
    def analyze(rows, label):
        print(f"\n{label} (n={len(rows)}):")
        
        # Parent validity
        valid = sum(1 for r in rows if r['parent_valid'] == 'YES')
        invalid = sum(1 for r in rows if r['parent_valid'] == 'NO')
        unknown = sum(1 for r in rows if r['parent_valid'] == '?')
        print(f"  Parent valid: YES={valid}, NO={invalid}, ?={unknown}")
        
        # Position distribution
        positions = [int(r['position']) for r in rows if r['position'] not in ['?', '']]
        if positions:
            print(f"  Position (reply idx - parent idx): min={min(positions)}, max={max(positions)}, avg={sum(positions)/len(positions):.1f}")
            pos_1 = sum(1 for p in positions if p == 1)
            pos_other = sum(1 for p in positions if p != 1)
            print(f"  Position == +1 (immediately after parent): {pos_1}")
            print(f"  Position != +1: {pos_other}")
        
        # Chain length
        chain_lens = []
        for r in rows:
            chain = r['chain']
            if '(' in chain:
                length = int(chain.split('(')[1].rstrip(')'))
            else:
                length = chain.count('->') + 1
            chain_lens.append(length)
        print(f"  Chain length: min={min(chain_lens)}, max={max(chain_lens)}, avg={sum(chain_lens)/len(chain_lens):.1f}")
        
        # Multi-paragraph
        multi = sum(1 for r in rows if r['num_para'] > 1)
        print(f"  Multi-paragraph comments: {multi} ({multi/len(rows)*100:.1f}%)")
    
    analyze(reply_ok, "REPLY OK")
    analyze(standalone, "STANDALONE")
    
    # ===== KEY FINDING =====
    print("\n" + "=" * 200)
    print("KEY CORRELATIONS")
    print("=" * 200)
    
    # Check if position is the key
    reply_pos_1 = sum(1 for r in reply_ok if r['position'] not in ['?', ''] and int(r['position']) == 1)
    reply_pos_other = sum(1 for r in reply_ok if r['position'] not in ['?', ''] and int(r['position']) != 1)
    stand_pos_1 = sum(1 for r in standalone if r['position'] not in ['?', ''] and int(r['position']) == 1)
    stand_pos_other = sum(1 for r in standalone if r['position'] not in ['?', ''] and int(r['position']) != 1)
    
    print(f"\nPosition == +1 (immediately after parent):")
    print(f"  Reply OK: {reply_pos_1}/{reply_pos_1+reply_pos_other} ({reply_pos_1/(reply_pos_1+reply_pos_other)*100:.0f}%)" if reply_pos_1+reply_pos_other > 0 else "  Reply OK: N/A")
    print(f"  Standalone: {stand_pos_1}/{stand_pos_1+stand_pos_other} ({stand_pos_1/(stand_pos_1+stand_pos_other)*100:.0f}%)" if stand_pos_1+stand_pos_other > 0 else "  Standalone: N/A")


if __name__ == "__main__":
    main()
