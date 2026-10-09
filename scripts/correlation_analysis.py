#!/usr/bin/env python3
"""
Comprehensive correlation analysis to identify traits that differentiate
Reply OK vs Standalone comments.
"""

import json
import zipfile
import re
from pathlib import Path
from collections import defaultdict

# User observations from the checklist
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


def get_comment_info(docx_path):
    """Extract detailed info about each comment from the original document."""
    info = {}
    
    with zipfile.ZipFile(docx_path, 'r') as z:
        # Get comments.xml
        comments_xml = z.read('word/comments.xml').decode('utf-8')
        
        # Get commentsExtended.xml
        extended_xml = z.read('word/commentsExtended.xml').decode('utf-8')
        extended_para_ids = set(re.findall(r'w15:paraId="([^"]+)"', extended_xml))
        
        # Build parent map from commentsExtended
        parent_map = {}  # para_id -> parent_para_id
        for match in re.finditer(r'w15:paraId="([^"]+)"[^>]*w15:paraIdParent="([^"]+)"', extended_xml):
            parent_map[match.group(1)] = match.group(2)
        
        # Parse each comment
        comment_pattern = r'<w:comment[^>]*w:id="(\d+)"[^>]*>(.*?)</w:comment>'
        para_pattern = r'w14:paraId="([^"]+)"'
        
        for match in re.finditer(comment_pattern, comments_xml, re.DOTALL):
            cid = match.group(1)
            body = match.group(2)
            para_ids = re.findall(para_pattern, body)
            
            first_para_id = para_ids[0] if para_ids else None
            last_para_id = para_ids[-1] if para_ids else None
            
            # Check which para_id is in commentsExtended
            registered_para_id = None
            for pid in para_ids:
                if pid in extended_para_ids:
                    registered_para_id = pid
                    break
            
            # Is this comment itself a reply?
            is_reply = last_para_id in parent_map if last_para_id else False
            parent_para_id = parent_map.get(last_para_id) if last_para_id else None
            
            info[cid] = {
                'comment_id': cid,
                'num_paragraphs': len(para_ids),
                'first_para_id': first_para_id,
                'last_para_id': last_para_id,
                'registered_para_id': registered_para_id,
                'is_existing_reply': is_reply,
                'existing_parent_para_id': parent_para_id,
            }
    
    return info


def get_thread_structure(docx_path):
    """Analyze thread structure - how many comments per thread, reply chains."""
    with zipfile.ZipFile(docx_path, 'r') as z:
        extended_xml = z.read('word/commentsExtended.xml').decode('utf-8')
        comments_xml = z.read('word/comments.xml').decode('utf-8')
        
        # Build para_id -> comment_id mapping
        para_to_comment = {}
        comment_pattern = r'<w:comment[^>]*w:id="(\d+)"[^>]*>(.*?)</w:comment>'
        para_pattern = r'w14:paraId="([^"]+)"'
        
        for match in re.finditer(comment_pattern, comments_xml, re.DOTALL):
            cid = match.group(1)
            body = match.group(2)
            para_ids = re.findall(para_pattern, body)
            for pid in para_ids:
                para_to_comment[pid] = cid
        
        # Build parent relationships
        parent_map = {}  # comment_id -> parent_comment_id
        for match in re.finditer(r'w15:paraId="([^"]+)"[^>]*w15:paraIdParent="([^"]+)"', extended_xml):
            child_para = match.group(1)
            parent_para = match.group(2)
            
            child_cid = para_to_comment.get(child_para)
            parent_cid = para_to_comment.get(parent_para)
            
            if child_cid and parent_cid:
                parent_map[child_cid] = parent_cid
        
        # Build thread chains
        # Find root comments (no parent)
        roots = set(para_to_comment.values()) - set(parent_map.keys())
        
        # Count replies per root
        thread_info = {}
        for root in roots:
            # Count direct and indirect children
            children = []
            for child, parent in parent_map.items():
                # Walk up to find if this child belongs to this root
                current = child
                while current in parent_map:
                    current = parent_map[current]
                if current == root:
                    children.append(child)
            
            thread_info[root] = {
                'root_comment_id': root,
                'existing_reply_count': len(children),
                'reply_ids': children
            }
        
        return thread_info, parent_map


def main():
    output_dir = Path(__file__).parent.parent / "output" / "example_manuscript"
    session_path = output_dir / "session.json"
    original_docx = output_dir / "example_manuscript.docx"
    exported_docx = output_dir / "example_manuscript_with_replies.docx"
    
    # Load data
    with open(session_path) as f:
        session = json.load(f)
    
    comment_info = get_comment_info(original_docx)
    thread_structure, parent_map = get_thread_structure(original_docx)
    
    # Build correlation table
    print("=" * 150)
    print("CORRELATION TABLE: Reply OK vs Standalone")
    print("=" * 150)
    print(f"{'Thread':>6} | {'Result':^10} | {'#Para':^5} | {'ExistReply':^10} | {'#Targets':^8} | {'InExtXml':^8} | {'ThreadReplies':^13}")
    print("-" * 150)
    
    # Collect traits for statistical analysis
    traits_reply = defaultdict(list)
    traits_standalone = defaultdict(list)
    
    threads = session.get('threads', {})
    
    for thread_id in sorted(USER_OBSERVATIONS.keys()):
        thread_id_str = str(thread_id)
        observation = USER_OBSERVATIONS[thread_id]
        
        # Get comment info - thread_id often equals the root comment_id
        cinfo = comment_info.get(thread_id_str, {})
        num_paras = cinfo.get('num_paragraphs', '?')
        
        # Is this comment itself already a reply in the original?
        is_existing_reply = cinfo.get('is_existing_reply', False)
        
        # Check if last_para_id is in commentsExtended
        last_para = cinfo.get('last_para_id', '')
        registered_para = cinfo.get('registered_para_id', '')
        in_ext_xml = (last_para == registered_para) if last_para else '?'
        
        # Session data
        thread_data = threads.get(thread_id_str, {})
        all_targets = thread_data.get('all_target_para_ids', [])
        num_targets = len(all_targets) if all_targets else 0
        
        # Thread structure - how many existing replies does this thread have?
        tinfo = thread_structure.get(thread_id_str, {})
        existing_replies = tinfo.get('existing_reply_count', 0)
        
        # Collect traits
        traits = traits_reply if observation == "reply" else traits_standalone
        traits['num_paras'].append(num_paras if isinstance(num_paras, int) else 0)
        traits['is_existing_reply'].append(1 if is_existing_reply else 0)
        traits['in_ext_xml'].append(1 if in_ext_xml == True else 0)
        traits['num_targets'].append(num_targets)
        traits['existing_replies'].append(existing_replies)
        
        print(f"{thread_id:>6} | {observation:^10} | {num_paras:^5} | {str(is_existing_reply):^10} | {num_targets:^8} | {str(in_ext_xml):^8} | {existing_replies:^13}")
    
    # Statistical summary
    print("\n" + "=" * 150)
    print("STATISTICAL SUMMARY")
    print("=" * 150)
    
    def avg(lst):
        return sum(lst) / len(lst) if lst else 0
    
    def pct(lst):
        return f"{sum(lst) / len(lst) * 100:.1f}%" if lst else "N/A"
    
    print(f"\n{'Trait':<30} | {'Reply OK (n=' + str(len(traits_reply['num_paras'])) + ')':^20} | {'Standalone (n=' + str(len(traits_standalone['num_paras'])) + ')':^20}")
    print("-" * 75)
    print(f"{'Avg paragraphs in comment':<30} | {avg(traits_reply['num_paras']):^20.2f} | {avg(traits_standalone['num_paras']):^20.2f}")
    print(f"{'% multi-paragraph (>1)':<30} | {pct([1 if x > 1 else 0 for x in traits_reply['num_paras']]):^20} | {pct([1 if x > 1 else 0 for x in traits_standalone['num_paras']]):^20}")
    print(f"{'% is existing reply':<30} | {pct(traits_reply['is_existing_reply']):^20} | {pct(traits_standalone['is_existing_reply']):^20}")
    print(f"{'% last_para in commentsExt':<30} | {pct(traits_reply['in_ext_xml']):^20} | {pct(traits_standalone['in_ext_xml']):^20}")
    print(f"{'Avg target paragraphs':<30} | {avg(traits_reply['num_targets']):^20.2f} | {avg(traits_standalone['num_targets']):^20.2f}")
    print(f"{'Avg existing replies in thread':<30} | {avg(traits_reply['existing_replies']):^20.2f} | {avg(traits_standalone['existing_replies']):^20.2f}")
    
    # Look for strong differentiators
    print("\n" + "=" * 150)
    print("KEY DIFFERENTIATORS")
    print("=" * 150)
    
    # Check if existing_replies is a strong signal
    reply_has_existing = [1 if x > 0 else 0 for x in traits_reply['existing_replies']]
    standalone_has_existing = [1 if x > 0 else 0 for x in traits_standalone['existing_replies']]
    
    print(f"\n% threads with existing replies:")
    print(f"  Reply OK:   {pct(reply_has_existing)}")
    print(f"  Standalone: {pct(standalone_has_existing)}")


if __name__ == "__main__":
    main()
