import zipfile
from lxml import etree
import os

# --- Configuration ---
DOCX_FILE = "test_data/synthetic/test.docx"

# Namespaces
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml'
}

def extract_comments_robust(docx_path):
    if not os.path.exists(docx_path):
        print(f"Error: File not found: {docx_path}")
        return

    try:
        z = zipfile.ZipFile(docx_path, 'r')
    except Exception as e:
        print(f"Error opening docx: {e}")
        return

    # -------------------------------------------------------------------------
    # 1. PARSE commentsExtended.xml (Status & Threading)
    # -------------------------------------------------------------------------
    # Map: paraId -> {'is_done': bool, 'parent_paraId': str|None}
    extended_map = {}
    
    if 'word/commentsExtended.xml' in z.namelist():
        ext_tree = etree.fromstring(z.read('word/commentsExtended.xml'))
        for c_ex in ext_tree.xpath('//w15:commentEx', namespaces=NS):
            para_id = c_ex.get(f'{{{NS["w15"]}}}paraId')
            parent_para_id = c_ex.get(f'{{{NS["w15"]}}}paraIdParent')
            is_done = c_ex.get(f'{{{NS["w15"]}}}done') == '1'
            
            if para_id:
                extended_map[para_id] = {
                    'is_done': is_done,
                    'parent_paraId': parent_para_id
                }
    else:
        print("Warning: commentsExtended.xml not found. Resolved status may be inaccurate.")

    # -------------------------------------------------------------------------
    # 2. PARSE comments.xml (Content & IDs)
    # -------------------------------------------------------------------------
    comments_map = {} # paraId -> comment_data
    comment_id_to_para_id = {} # w:id -> paraId (for context lookup)

    if 'word/comments.xml' in z.namelist():
        com_tree = etree.fromstring(z.read('word/comments.xml'))
        
        for comment_node in com_tree.xpath('//w:comment', namespaces=NS):
            w_id = comment_node.get(f'{{{NS["w"]}}}id')
            author = comment_node.get(f'{{{NS["w"]}}}author')
            
            # Find the first paragraph's w14:paraId to link with Extended
            # (A comment might have multiple paragraphs, usually the first one holds the key)
            p_node = comment_node.find('.//w:p', namespaces=NS)
            if p_node is None: 
                continue # Empty comment?
            
            para_id = p_node.get(f'{{{NS["w14"]}}}paraId')
            
            # Extract text
            text_content = "".join(comment_node.xpath('.//w:t/text()', namespaces=NS))
            
            # Merge with Extended Info
            ext_info = extended_map.get(para_id, {'is_done': False, 'parent_paraId': None})
            
            if para_id:
                comments_map[para_id] = {
                    'w_id': w_id,
                    'para_id': para_id,
                    'author': author,
                    'text': text_content,
                    'is_done': ext_info['is_done'],
                    'parent_paraId': ext_info['parent_paraId']
                }
                comment_id_to_para_id[w_id] = para_id

    # -------------------------------------------------------------------------
    # 3. PARSE document.xml (Context Extraction)
    # -------------------------------------------------------------------------
    # Map: w:id (comment ID) -> Context Text
    context_map = {}
    
    if 'word/document.xml' in z.namelist():
        doc_tree = etree.fromstring(z.read('word/document.xml'))
        
        # We only need context for Root comments, but let's grab for all just in case
        for w_id in comment_id_to_para_id.keys():
            # Find <w:commentRangeStart w:id="w_id">
            start_node = doc_tree.xpath(f'//w:commentRangeStart[@w:id="{w_id}"]', namespaces=NS)
            
            if start_node:
                node = start_node[0]
                # Strategy: Grab the text of the *entire paragraph* containing the anchor
                # This fixes the "J" vs "Journal Requirements" issue.
                parent_p = node.xpath('./ancestor::w:p', namespaces=NS)
                if parent_p:
                    full_p_text = "".join(parent_p[0].xpath('.//w:t/text()', namespaces=NS))
                    context_map[w_id] = full_p_text.strip()
                else:
                    context_map[w_id] = "(Context in non-paragraph structure)"
            else:
                # Sometimes comments are anchored to the end of a run or similar
                context_map[w_id] = "(Anchor not found)"

    # -------------------------------------------------------------------------
    # 4. BUILD THREADS & FILTER
    # -------------------------------------------------------------------------
    threads = {} # Root_ParaID -> List of comments
    
    # Identify Roots and organize children
    # We use para_id as the key because that's what links parents
    
    for para_id, data in comments_map.items():
        parent_id = data['parent_paraId']
        
        # If no parent, or parent not found in our map (orphaned), it's a Root
        if not parent_id or parent_id not in comments_map:
            if para_id not in threads:
                threads[para_id] = []
            threads[para_id].append(data)
        else:
            # It is a child. Traverse up to find the ultimate Root.
            curr_parent_id = parent_id
            seen = set() # Prevent infinite loops
            root_found = None
            
            while curr_parent_id in comments_map:
                if curr_parent_id in seen: break
                seen.add(curr_parent_id)
                
                parent_data = comments_map[curr_parent_id]
                if not parent_data['parent_paraId']:
                    root_found = curr_parent_id
                    break
                curr_parent_id = parent_data['parent_paraId']
            
            if root_found:
                if root_found not in threads:
                    threads[root_found] = []
                    # Add the root itself if missing (logic check)
                    threads[root_found].append(comments_map[root_found])
                
                # Add this child to the root's thread
                threads[root_found].append(data)

    # -------------------------------------------------------------------------
    # 5. OUTPUT
    # -------------------------------------------------------------------------
    
    # Sort roots by w:id (approximate chronological order)
    # Helper to safe convert to int
    def get_int_id(pid):
        try:
            return int(comments_map[pid]['w_id'])
        except:
            return 999999

    sorted_roots = sorted(threads.keys(), key=get_int_id)
    
    valid_threads_count = 0
    final_output = []

    for root_pid in sorted_roots:
        thread = threads[root_pid]
        
        # Sort thread comments by ID (chronological)
        thread.sort(key=lambda x: int(x['w_id']))
        
        root_comment = thread[0]
        
        # FILTER: If Root is Done, skip entire thread
        if root_comment['is_done']:
            continue
            
        valid_threads_count += 1
        
        # Get Context
        ctx = context_map.get(root_comment['w_id'], "")
        if len(ctx) > 100: ctx = ctx[:100] + "..." # Truncate for display if huge
        
        # Build Card String
        card_str = []
        card_str.append(f"CARD ID: {root_comment['w_id']}")
        card_str.append(f"SECTION: (See Context)") # Section header extraction requires complex traversal
        card_str.append(f"CONTEXT (Snippet): {ctx}")
        card_str.append(f"THREAD LENGTH: {len(thread)}")
        
        for c in thread:
            card_str.append(f"  - [{c['author']}]: {c['text']}")
        
        card_str.append("-" * 40)
        final_output.append("\n".join(card_str))

    print(f"Total Cards (Threads) Found: {valid_threads_count}")
    print("=" * 60)
    print("\n".join(final_output))

if __name__ == "__main__":
    extract_comments_robust(DOCX_FILE)