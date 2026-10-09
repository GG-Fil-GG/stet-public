#!/usr/bin/env python3
"""
EXHAUSTIVE correlation analysis - extract EVERY attribute from ALL XML files.
"""

import json
import zipfile
import re
from pathlib import Path
from collections import defaultdict

USER_OBS = {
    1: 'S', 3: 'R', 4: 'S', 5: 'R', 9: 'R', 12: 'S', 14: 'S', 16: 'R',
    19: 'R', 22: 'R', 24: 'S', 26: 'S', 28: 'S', 29: 'R', 31: 'S', 34: 'R',
    37: 'S', 39: 'S', 41: 'S', 42: 'R', 46: 'R', 47: 'R', 49: 'S', 52: 'S',
    54: 'S', 57: 'S', 60: 'S', 64: 'R', 67: 'S', 69: 'S', 71: 'S', 72: 'S',
    73: 'S', 74: 'S', 76: 'S', 77: 'S', 79: 'S', 81: 'R', 83: 'R', 86: 'R',
    88: 'S', 91: 'S', 93: 'S', 95: 'S', 106: 'S', 108: 'S', 110: 'R',
    113: 'S', 118: 'R', 121: 'R', 122: 'S', 124: 'S', 126: 'S', 129: 'S',
    131: 'R', 134: 'S', 136: 'R', 139: 'S', 140: 'S', 143: 'S', 145: 'S',
}

def extract_all_attrs(tag_content):
    """Extract all attributes from an XML tag."""
    attrs = {}
    for match in re.finditer(r'(\w+:?\w+)="([^"]*)"', tag_content):
        attrs[match.group(1)] = match.group(2)
    return attrs

def main():
    output_dir = Path(__file__).parent.parent / "output" / "example_manuscript"
    orig_docx = output_dir / "example_manuscript.docx"
    export_docx = output_dir / "example_manuscript_with_replies.docx"
    
    # ========== EXTRACT FROM ORIGINAL ==========
    with zipfile.ZipFile(orig_docx, 'r') as z:
        orig_comments = z.read('word/comments.xml').decode('utf-8')
        orig_extended = z.read('word/commentsExtended.xml').decode('utf-8')
        orig_ids = z.read('word/commentsIds.xml').decode('utf-8')
        orig_extensible = z.read('word/commentsExtensible.xml').decode('utf-8')
        orig_doc = z.read('word/document.xml').decode('utf-8')
    
    # ========== EXTRACT FROM EXPORT ==========
    with zipfile.ZipFile(export_docx, 'r') as z:
        exp_comments = z.read('word/comments.xml').decode('utf-8')
        exp_extended = z.read('word/commentsExtended.xml').decode('utf-8')
        exp_ids = z.read('word/commentsIds.xml').decode('utf-8')
        exp_extensible = z.read('word/commentsExtensible.xml').decode('utf-8')
        exp_doc = z.read('word/document.xml').decode('utf-8')
    
    # ========== BUILD COMPLETE DATA FOR EACH ORIGINAL COMMENT ==========
    
    # 1. Parse ORIGINAL comments.xml - get ALL attributes
    orig_comment_data = {}
    for match in re.finditer(r'<w:comment([^>]*)>(.*?)</w:comment>', orig_comments, re.DOTALL):
        attrs = extract_all_attrs(match.group(1))
        body = match.group(2)
        cid = attrs.get('w:id')
        
        # Get ALL paragraph attributes
        para_attrs_list = []
        for pmatch in re.finditer(r'<w:p([^>]*)>', body):
            para_attrs_list.append(extract_all_attrs(pmatch.group(1)))
        
        orig_comment_data[cid] = {
            'comment_attrs': attrs,
            'para_attrs': para_attrs_list,
            'num_paras': len(para_attrs_list),
            'body_length': len(body),
        }
    
    # 2. Parse ORIGINAL commentsExtended.xml - get ALL attributes
    orig_extended_data = {}
    orig_extended_order = []
    for i, match in enumerate(re.finditer(r'<w15:commentEx([^/]*)/>', orig_extended)):
        attrs = extract_all_attrs(match.group(1))
        para_id = attrs.get('w15:paraId')
        orig_extended_data[para_id] = {
            'attrs': attrs,
            'position': i,
        }
        orig_extended_order.append(para_id)
    
    # 3. Parse ORIGINAL commentsIds.xml
    orig_ids_data = {}
    for match in re.finditer(r'<w16cid:commentId([^/]*)/>', orig_ids):
        attrs = extract_all_attrs(match.group(1))
        para_id = attrs.get('w16cid:paraId')
        orig_ids_data[para_id] = attrs
    
    # 4. Parse ORIGINAL commentsExtensible.xml
    orig_extensible_data = {}
    for match in re.finditer(r'<w16cex:commentExtensible([^/]*)/>', orig_extensible):
        attrs = extract_all_attrs(match.group(1))
        durable_id = attrs.get('w16cex:durableId')
        orig_extensible_data[durable_id] = attrs
    
    # 5. Map para_id -> durable_id
    para_to_durable = {v.get('w16cid:paraId'): v.get('w16cid:durableId') 
                       for v in orig_ids_data.values() if v.get('w16cid:paraId')}
    
    # ========== BUILD COMPREHENSIVE TABLE ==========
    
    print("=" * 200)
    print("EXHAUSTIVE CORRELATION TABLE - ALL ATTRIBUTES FROM ORIGINAL DOCUMENT")
    print("=" * 200)
    
    # Collect all unique attribute names
    all_ext_attrs = set()
    all_ids_attrs = set()
    all_extensible_attrs = set()
    
    for v in orig_extended_data.values():
        all_ext_attrs.update(v['attrs'].keys())
    for v in orig_ids_data.values():
        all_ids_attrs.update(v.keys())
    for v in orig_extensible_data.values():
        all_extensible_attrs.update(v.keys())
    
    print(f"\nAttributes in commentsExtended.xml: {sorted(all_ext_attrs)}")
    print(f"Attributes in commentsIds.xml: {sorted(all_ids_attrs)}")
    print(f"Attributes in commentsExtensible.xml: {sorted(all_extensible_attrs)}")
    
    # Build per-thread data
    thread_data = []
    
    for thread_id, obs in sorted(USER_OBS.items()):
        cid = str(thread_id)
        
        if cid not in orig_comment_data:
            continue
        
        cd = orig_comment_data[cid]
        
        # Get the para_id that's in commentsExtended (usually the last one for multi-para)
        registered_para_id = None
        for pa in cd['para_attrs']:
            pid = pa.get('w14:paraId')
            if pid and pid in orig_extended_data:
                registered_para_id = pid
                break
        
        ext_data = orig_extended_data.get(registered_para_id, {})
        ids_data = orig_ids_data.get(registered_para_id, {})
        
        durable_id = para_to_durable.get(registered_para_id)
        extensible_data = orig_extensible_data.get(durable_id, {})
        
        row = {
            'thread_id': thread_id,
            'obs': obs,
            'comment_id': cid,
            'num_paras': cd['num_paras'],
            'body_length': cd['body_length'],
            'registered_para_id': registered_para_id,
            'ext_position': ext_data.get('attrs', {}).get('position', ext_data.get('position')),
            'ext_done': ext_data.get('attrs', {}).get('w15:done'),
            'ext_paraIdParent': ext_data.get('attrs', {}).get('w15:paraIdParent'),
            'ids_durableId': ids_data.get('w16cid:durableId'),
            'extensible_dateUtc': extensible_data.get('w16cex:dateUtc'),
            # Comment attributes
            'author': cd['comment_attrs'].get('w:author', '')[:20],
            'date': cd['comment_attrs'].get('w:date', ''),
            'initials': cd['comment_attrs'].get('w:initials'),
            # First paragraph attributes
            'first_para_textId': cd['para_attrs'][0].get('w14:textId') if cd['para_attrs'] else None,
            'first_para_rsidR': cd['para_attrs'][0].get('w:rsidR') if cd['para_attrs'] else None,
        }
        thread_data.append(row)
    
    # ========== STATISTICAL ANALYSIS ==========
    
    print("\n" + "=" * 200)
    print("STATISTICAL COMPARISON: REPLY OK vs STANDALONE")
    print("=" * 200)
    
    reply_rows = [r for r in thread_data if r['obs'] == 'R']
    standalone_rows = [r for r in thread_data if r['obs'] == 'S']
    
    def analyze_attr(rows, attr_name):
        values = [r.get(attr_name) for r in rows if r.get(attr_name) is not None]
        if not values:
            return "N/A"
        if all(isinstance(v, (int, float)) for v in values):
            return f"avg={sum(values)/len(values):.2f}, min={min(values)}, max={max(values)}"
        # Count unique values
        counts = defaultdict(int)
        for v in values:
            counts[str(v)[:30]] += 1
        if len(counts) <= 5:
            return str(dict(counts))
        return f"{len(counts)} unique values"
    
    attrs_to_analyze = [
        'num_paras', 'body_length', 'ext_done', 'ext_paraIdParent',
        'initials', 'first_para_textId', 'first_para_rsidR'
    ]
    
    print(f"\n{'Attribute':<25} | {'Reply OK (n=' + str(len(reply_rows)) + ')':<50} | {'Standalone (n=' + str(len(standalone_rows)) + ')':<50}")
    print("-" * 130)
    
    for attr in attrs_to_analyze:
        r_analysis = analyze_attr(reply_rows, attr)
        s_analysis = analyze_attr(standalone_rows, attr)
        print(f"{attr:<25} | {r_analysis:<50} | {s_analysis:<50}")
    
    # ========== CHECK FOR EXISTING PARENT (REPLY CHAIN) ==========
    
    print("\n" + "=" * 200)
    print("EXISTING PARENT ANALYSIS (Is original comment itself a reply?)")
    print("=" * 200)
    
    reply_has_parent = sum(1 for r in reply_rows if r.get('ext_paraIdParent'))
    standalone_has_parent = sum(1 for r in standalone_rows if r.get('ext_paraIdParent'))
    
    print(f"\nReply OK comments that ARE THEMSELVES replies: {reply_has_parent}/{len(reply_rows)}")
    print(f"Standalone comments that ARE THEMSELVES replies: {standalone_has_parent}/{len(standalone_rows)}")
    
    # ========== CHECK POSITION IN commentsExtended ==========
    
    print("\n" + "=" * 200)
    print("POSITION ANALYSIS IN commentsExtended.xml")
    print("=" * 200)
    
    reply_positions = [ext_data.get('position') for r in reply_rows 
                       if (ext_data := orig_extended_data.get(r.get('registered_para_id'), {})) 
                       and ext_data.get('position') is not None]
    standalone_positions = [ext_data.get('position') for r in standalone_rows 
                            if (ext_data := orig_extended_data.get(r.get('registered_para_id'), {})) 
                            and ext_data.get('position') is not None]
    
    if reply_positions:
        print(f"\nReply OK positions: min={min(reply_positions)}, max={max(reply_positions)}, avg={sum(reply_positions)/len(reply_positions):.1f}")
    if standalone_positions:
        print(f"Standalone positions: min={min(standalone_positions)}, max={max(standalone_positions)}, avg={sum(standalone_positions)/len(standalone_positions):.1f}")
    
    # ========== FULL DATA DUMP ==========
    
    print("\n" + "=" * 200)
    print("FULL DATA DUMP FOR MANUAL INSPECTION")
    print("=" * 200)
    
    print(f"\n{'ID':>4} | {'O':^1} | {'#P':^3} | {'done':^4} | {'hasParent':^9} | {'textId':^10} | {'rsidR':^10} | {'Position':^8} | {'initials':^8}")
    print("-" * 100)
    
    for r in sorted(thread_data, key=lambda x: x['thread_id']):
        ext_data = orig_extended_data.get(r.get('registered_para_id'), {})
        pos = ext_data.get('position', '?')
        has_parent = 'YES' if r.get('ext_paraIdParent') else 'NO'
        
        print(f"{r['thread_id']:>4} | {r['obs']:^1} | {r['num_paras']:^3} | {r.get('ext_done', '?'):^4} | {has_parent:^9} | {str(r.get('first_para_textId', '?'))[:10]:^10} | {str(r.get('first_para_rsidR', '?'))[:10]:^10} | {pos:^8} | {str(r.get('initials', '?'))[:8]:^8}")


if __name__ == "__main__":
    main()
