#!/usr/bin/env python3
"""
Analyze reply insertion patterns to identify why some replies appear 
as threaded replies and others appear as standalone comments.
"""

import json
import zipfile
import re
from pathlib import Path
from collections import defaultdict

# User's observations from the test checklist
# Format: thread_id -> "reply" or "standalone"
USER_OBSERVATIONS = {
    1: "standalone",
    3: "reply",
    4: "standalone",
    5: "reply",
    9: "reply",
    12: "standalone",
    14: "standalone",
    16: "reply",
    19: "reply",
    22: "reply",
    24: "standalone",
    26: "standalone",
    28: "standalone",
    29: "reply",
    31: "standalone",
    34: "reply",
    37: "standalone",
    39: "standalone",
    41: "standalone",
    42: "reply",
    46: "reply",
    47: "reply",
    49: "standalone",
    52: "standalone",
    54: "standalone",
    57: "standalone",
    60: "standalone",
    64: "reply",
    67: "standalone",
    69: "standalone",
    71: "standalone",
    72: "standalone",
    73: "standalone",
    74: "standalone",
    76: "standalone",
    77: "standalone",
    79: "standalone",
    81: "reply",
    83: "reply",
    86: "reply",
    88: "standalone",
    91: "standalone",
    93: "standalone",
    95: "standalone",
    106: "standalone",
    108: "standalone",
    110: "reply",
    113: "standalone",
    118: "reply",
    121: "reply",
    122: "standalone",
    124: "standalone",
    126: "standalone",
    129: "standalone",
    131: "reply",
    134: "standalone",
    136: "reply",
    139: "standalone",
    140: "standalone",
    143: "standalone",
    145: "standalone",
}

def load_session(session_path):
    """Load session.json"""
    with open(session_path, 'r') as f:
        return json.load(f)

def extract_comments_extended(docx_path):
    """Extract commentsExtended.xml and parse parent relationships"""
    with zipfile.ZipFile(docx_path, 'r') as z:
        if 'word/commentsExtended.xml' not in z.namelist():
            return {}
        
        content = z.read('word/commentsExtended.xml').decode('utf-8')
        
        # Parse each commentEx entry
        # Looking for: w15:paraId="XXX" and optional w15:paraIdParent="YYY"
        pattern = r'<w15:commentEx[^>]*w15:paraId="([^"]+)"[^>]*(?:w15:paraIdParent="([^"]+)")?[^>]*/>'
        
        entries = {}
        for match in re.finditer(pattern, content):
            para_id = match.group(1)
            parent_para_id = match.group(2)  # May be None
            entries[para_id] = {
                'para_id': para_id,
                'parent_para_id': parent_para_id,
                'has_parent': parent_para_id is not None
            }
        
        return entries

def extract_comments_xml(docx_path):
    """Extract comments.xml and get comment_id -> para_id mapping"""
    with zipfile.ZipFile(docx_path, 'r') as z:
        if 'word/comments.xml' not in z.namelist():
            return {}
        
        content = z.read('word/comments.xml').decode('utf-8')
        
        # Find each comment and its internal para_id
        # Looking for: <w:comment w:id="X"...> ... <w:p ... w14:paraId="Y">
        comments = {}
        
        # Split by comment tags
        comment_pattern = r'<w:comment[^>]*w:id="(\d+)"[^>]*>(.*?)</w:comment>'
        para_id_pattern = r'w14:paraId="([^"]+)"'
        
        for match in re.finditer(comment_pattern, content, re.DOTALL):
            comment_id = match.group(1)
            comment_content = match.group(2)
            
            # Find the para_id inside this comment
            para_match = re.search(para_id_pattern, comment_content)
            if para_match:
                comments[comment_id] = {
                    'comment_id': comment_id,
                    'comment_para_id': para_match.group(1)
                }
            else:
                comments[comment_id] = {
                    'comment_id': comment_id,
                    'comment_para_id': None
                }
        
        return comments

def extract_original_comments(docx_path):
    """Extract comment info from original DOCX (before replies added)"""
    with zipfile.ZipFile(docx_path, 'r') as z:
        if 'word/comments.xml' not in z.namelist():
            return {}
        
        content = z.read('word/comments.xml').decode('utf-8')
        
        # Parse each comment to get: id, author, first para_id inside
        # Pattern: <w:comment w:id="X" w:author="Y" ...> ... <w:p ... w14:paraId="Z">
        comments = {}
        
        # Find all comments
        comment_pattern = r'<w:comment[^>]*w:id="(\d+)"[^>]*>(.*?)</w:comment>'
        para_id_pattern = r'w14:paraId="([^"]+)"'
        
        for match in re.finditer(comment_pattern, content, re.DOTALL):
            comment_id = match.group(1)
            comment_content = match.group(2)
            
            para_match = re.search(para_id_pattern, comment_content)
            para_id = para_match.group(1) if para_match else None
            
            comments[comment_id] = {
                'comment_id': comment_id,
                'para_id': para_id
            }
        
        return comments


def extract_commentsex_with_parents(docx_path):
    """Extract all commentEx entries showing parent relationships"""
    with zipfile.ZipFile(docx_path, 'r') as z:
        if 'word/commentsExtended.xml' not in z.namelist():
            return [], {}
        
        content = z.read('word/commentsExtended.xml').decode('utf-8')
        
        # Get raw entries in ORDER (order matters for threading!)
        entries = []
        para_to_parent = {}
        
        # Pattern with optional paraIdParent
        pattern = r'<w15:commentEx[^>]*w15:paraId="([^"]+)"(?:[^>]*w15:paraIdParent="([^"]+)")?[^>]*/>'
        
        for match in re.finditer(pattern, content):
            para_id = match.group(1)
            parent_para_id = match.group(2)  # May be None
            entries.append({
                'para_id': para_id,
                'parent_para_id': parent_para_id
            })
            para_to_parent[para_id] = parent_para_id
        
        return entries, para_to_parent


def find_reply_para_ids(exported_docx_path, original_docx_path):
    """
    Compare original and exported to find which para_ids are NEW (i.e., replies we added).
    Returns set of reply para_ids.
    """
    orig_comments = extract_comments_xml(original_docx_path)
    export_comments = extract_comments_xml(exported_docx_path)
    
    orig_para_ids = {c['comment_para_id'] for c in orig_comments.values() if c.get('comment_para_id')}
    export_para_ids = {c['comment_para_id'] for c in export_comments.values() if c.get('comment_para_id')}
    
    # Replies are in export but not in original
    reply_para_ids = export_para_ids - orig_para_ids
    return reply_para_ids


def main():
    # Paths
    output_dir = Path(__file__).parent.parent / "output" / "example_manuscript"
    session_path = output_dir / "session.json"
    original_docx = output_dir / "example_manuscript.docx"
    exported_docx = output_dir / "example_manuscript_with_replies.docx"
    
    print("=" * 120)
    print("REPLY PATTERN ANALYSIS - COMPREHENSIVE")
    print("=" * 120)
    
    # Load data
    session = load_session(session_path)
    
    # Original document's comments
    orig_comments = extract_original_comments(original_docx)
    orig_commentsex, _ = extract_commentsex_with_parents(original_docx)
    
    # Exported document's comments
    export_comments = extract_comments_xml(exported_docx)
    export_commentsex, export_para_to_parent = extract_commentsex_with_parents(exported_docx)
    
    # Find which para_ids are replies (new in export)
    orig_para_ids = {e['para_id'] for e in orig_commentsex}
    export_para_ids = {e['para_id'] for e in export_commentsex}
    reply_para_ids = export_para_ids - orig_para_ids
    
    print(f"\nOriginal doc: {len(orig_comments)} comments, {len(orig_commentsex)} commentEx entries")
    print(f"Exported doc: {len(export_comments)} comments, {len(export_commentsex)} commentEx entries")
    print(f"New replies added: {len(reply_para_ids)}")
    
    # The KEY insight: we need to match thread_id to original comment_id
    # Thread IDs seem to match comment IDs in most cases, but let me verify
    
    # Build: original comment_id -> original comment_para_id (the para_id inside the comment)
    comment_id_to_para_id = {}
    for cid, cdata in orig_comments.items():
        if cdata.get('para_id'):
            comment_id_to_para_id[cid] = cdata['para_id']
    
    print("\n" + "=" * 120)
    print("DETAILED THREAD ANALYSIS")
    print("=" * 120)
    print(f"{'Thread':>6} | {'Observed':^10} | {'Orig Comment':^14} | {'Orig ParaId':^12} | {'Reply ParaId':^12} | {'Parent in Ex':^12} | {'Match?':^6}")
    print("-" * 120)
    
    # We need to figure out which reply corresponds to which thread
    # The replies are added in thread order, so we can try to match by order
    
    # Sort threads by ID
    thread_ids = sorted([int(t) for t in session.get('threads', {}).keys()])
    
    # Get accepted threads in order they were accepted
    accepted_threads = []
    for tid in thread_ids:
        tdata = session['threads'][str(tid)]
        if tdata.get('status') == 'accepted':
            accepted_threads.append(tid)
    
    print(f"\nAccepted threads (in ID order, {len(accepted_threads)} total): {accepted_threads[:10]}...")
    
    # Now let's trace back: each reply should have been added for an accepted thread
    # The reply's parent should be the original comment's para_id
    
    # Build ordered list of reply para_ids (from commentsExtended order)
    reply_para_ids_ordered = []
    for entry in export_commentsex:
        if entry['para_id'] in reply_para_ids:
            reply_para_ids_ordered.append(entry)
    
    print(f"Replies in commentsEx order: {len(reply_para_ids_ordered)}")
    
    # Now correlate
    results = []
    
    for i, tid in enumerate(accepted_threads):
        if tid not in USER_OBSERVATIONS:
            continue
        
        observed = USER_OBSERVATIONS[tid]
        orig_comment_id = str(tid)  # Assuming thread ID matches comment ID
        orig_para_id = comment_id_to_para_id.get(orig_comment_id, "?")
        
        # Find the reply for this thread (by index in accepted order)
        reply_info = None
        if i < len(reply_para_ids_ordered):
            reply_info = reply_para_ids_ordered[i]
        
        reply_para_id = reply_info['para_id'] if reply_info else "?"
        parent_in_ex = reply_info['parent_para_id'] if reply_info else "?"
        
        # Check if parent matches
        match = "YES" if parent_in_ex == orig_para_id else "NO"
        
        results.append({
            'thread_id': tid,
            'observed': observed,
            'orig_comment_id': orig_comment_id,
            'orig_para_id': orig_para_id,
            'reply_para_id': reply_para_id,
            'parent_in_ex': parent_in_ex,
            'match': match
        })
        
        print(f"{tid:>6} | {observed:^10} | {orig_comment_id:^14} | {orig_para_id[:12]:^12} | {reply_para_id[:12]:^12} | {str(parent_in_ex)[:12]:^12} | {match:^6}")
    
    # Summary by match
    print("\n" + "=" * 120)
    print("CORRELATION ANALYSIS")
    print("=" * 120)
    
    reply_matched = [r for r in results if r['observed'] == 'reply' and r['match'] == 'YES']
    reply_unmatched = [r for r in results if r['observed'] == 'reply' and r['match'] == 'NO']
    standalone_matched = [r for r in results if r['observed'] == 'standalone' and r['match'] == 'YES']
    standalone_unmatched = [r for r in results if r['observed'] == 'standalone' and r['match'] == 'NO']
    
    print(f"Observed as REPLY, parent MATCHES orig: {len(reply_matched)}")
    print(f"Observed as REPLY, parent DOESN'T match: {len(reply_unmatched)}")
    print(f"Observed as STANDALONE, parent MATCHES orig: {len(standalone_matched)}")
    print(f"Observed as STANDALONE, parent DOESN'T match: {len(standalone_unmatched)}")
    
    if standalone_matched:
        print(f"\n*** ANOMALY: Standalone but parent matches ***")
        for r in standalone_matched[:5]:
            print(f"  Thread {r['thread_id']}: parent {r['parent_in_ex']} == orig {r['orig_para_id']}")

if __name__ == "__main__":
    main()
