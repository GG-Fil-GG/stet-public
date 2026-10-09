#!/usr/bin/env python3
"""
Extract comments with their chain/thread structure and the text they refer to.
Final working version.
"""

import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from collections import defaultdict
import re
import os

def extract_text_from_element(elem):
    """Extract all text content from an XML element."""
    text_parts = []
    
    def get_text(node):
        if node.text:
            text_parts.append(node.text)
        for child in node:
            get_text(child)
            if child.tail:
                text_parts.append(child.tail)
    
    get_text(elem)
    return ''.join(text_parts).strip()

def get_comment_id_from_attr(elem):
    """Extract comment ID from element attributes."""
    for key, value in elem.attrib.items():
        if key.endswith('id') or key == 'id':
            return value
    return None

def extract_text_from_paragraph(para, start_idx, end_idx, ns):
    """Extract text from runs between start and end indices in a paragraph."""
    children = list(para)
    text_parts = []
    
    # Extract text from runs between start and end
    for i in range(start_idx + 1, end_idx):
        child = children[i]
        if child.tag.endswith('}r'):  # Run element
            for t_elem in child.findall('.//w:t', ns):
                if t_elem.text:
                    text_parts.append(t_elem.text)
        # Also check if the child itself is a text element (unlikely but possible)
        elif child.tag.endswith('}t') and child.text:
            text_parts.append(child.text)
    
    result = ' '.join(text_parts).strip()
    
    # If no text found between, try getting text from the run containing the start marker
    # (sometimes the text is in the same run as the comment marker)
    if not result and start_idx < len(children) - 1:
        # Check the run immediately after start
        next_child = children[start_idx + 1] if start_idx + 1 < len(children) else None
        if next_child and next_child.tag.endswith('}r'):
            for t_elem in next_child.findall('.//w:t', ns):
                if t_elem.text:
                    text_parts.append(t_elem.text)
            result = ' '.join(text_parts).strip()
    
    return result

def find_sentence_boundaries(text, position):
    """Find sentence boundaries around a given position in text.
    
    Returns (sentence_start, sentence_end) indices.
    Handles common abbreviations and edge cases.
    """
    # Common abbreviations that shouldn't end sentences
    abbreviations = {
        'dr.', 'mr.', 'mrs.', 'ms.', 'prof.', 'sr.', 'jr.', 'vs.', 'etc.', 'e.g.', 'i.e.',
        'u.s.', 'u.k.', 'a.m.', 'p.m.', 'no.', 'vol.', 'pp.', 'ed.', 'eds.', 'inc.', 'ltd.',
        'st.', 'ave.', 'blvd.', 'rd.', 'ct.', 'apt.', 'bldg.', 'dept.', 'govt.', 'mgr.'
    }
    
    # Find sentence start (look backwards for sentence-ending punctuation)
    sentence_start = 0
    for i in range(position, 0, -1):
        if text[i] in '.!?':
            # Check if it's an abbreviation
            # Look for word before the period
            word_start = i
            while word_start > 0 and text[word_start - 1] not in ' \n\t':
                word_start -= 1
            
            word = text[word_start:i].lower().strip()
            # Check if it's an abbreviation (common ones or single letter)
            if word in abbreviations or (len(word) == 1 and word.isalpha()):
                continue  # Not a sentence boundary
            
            # Check if followed by space and capital letter (or end of text)
            if i + 1 < len(text):
                next_char = text[i + 1]
                if next_char in ' \n\t':
                    # Check if next non-space is capital or end of text
                    j = i + 1
                    while j < len(text) and text[j] in ' \n\t':
                        j += 1
                    if j >= len(text) or text[j].isupper():
                        sentence_start = word_start
                        break
            else:
                # End of text
                sentence_start = word_start
                break
    
    # Find sentence end (look forwards for sentence-ending punctuation)
    sentence_end = len(text)
    for i in range(position, len(text)):
        if text[i] in '.!?':
            # Check if it's an abbreviation
            word_start = i
            while word_start > 0 and text[word_start - 1] not in ' \n\t':
                word_start -= 1
            
            word = text[word_start:i].lower().strip()
            if word in abbreviations or (len(word) == 1 and word.isalpha()):
                continue  # Not a sentence boundary
            
            # Check if followed by space and capital letter (or end of text)
            if i + 1 < len(text):
                next_char = text[i + 1]
                if next_char in ' \n\t':
                    j = i + 1
                    while j < len(text) and text[j] in ' \n\t':
                        j += 1
                    if j >= len(text) or text[j].isupper():
                        sentence_end = i + 1
                        break
            else:
                # End of text
                sentence_end = i + 1
                break
    
    return sentence_start, sentence_end

def extract_context_around_range(para, start_idx, end_idx, ns, context_chars=100, doc_root=None):
    """Extract text with context using stepwise expansion.
    
    Stepwise approach:
    1. Extract exact text and find containing word
    2. If single char and word < 25 chars → show word
    3. If word context < 120 chars → expand to sentence
    4. If sentence < 300 chars → expand to paragraph
    
    Returns format: "[word]" or "[word] in [sentence]" or "[word] in [paragraph]"
    """
    children = list(para)
    
    # Step 1: Get exact referenced text
    exact_text = extract_text_from_paragraph(para, start_idx, end_idx, ns)
    
    if not exact_text:
        return exact_text
    
    # Extract full paragraph text and track position of referenced text
    full_para_text = ''
    exact_pos = -1
    current_pos = 0
    
    # Track which child indices correspond to which text positions
    for i, child in enumerate(children):
        if child.tag.endswith('}r'):
            for t_elem in child.findall('.//w:t', ns):
                if t_elem.text:
                    text_len = len(t_elem.text)
                    # Check if this run is between start_idx and end_idx (the referenced range)
                    if start_idx < i < end_idx:
                        # This is part of the referenced text
                        # Find the position of exact_text within this range
                        if exact_pos == -1:
                            # Calculate position: sum of all text before this run
                            exact_pos = current_pos
                    full_para_text += t_elem.text
                    current_pos += text_len
    
    if not full_para_text:
        return f'[{exact_text}]'
    
    # If we couldn't determine position from structure, fall back to search
    if exact_pos == -1:
        # Try to find exact text, but prefer positions that make sense
        # (e.g., not at the very start if it's a common character)
        search_pos = full_para_text.find(exact_text)
        if search_pos != -1:
            exact_pos = search_pos
        else:
            return f'[{exact_text}]'
    
    # Verify that exact_text is actually at this position
    if full_para_text[exact_pos:exact_pos + len(exact_text)] != exact_text:
        # Position doesn't match, try to find it
        exact_pos = full_para_text.find(exact_text, max(0, exact_pos - 10))
        if exact_pos == -1:
            return f'[{exact_text}]'
    
    # Step 2: Find word containing exact text
    # Word boundaries: spaces, tabs, newlines, and common punctuation
    word_boundary_chars = ' \n\t.,;:!?()[]{}"\''
    
    word_start = exact_pos
    while word_start > 0 and full_para_text[word_start - 1] not in word_boundary_chars:
        word_start -= 1
    
    word_end = exact_pos + len(exact_text)
    while word_end < len(full_para_text) and full_para_text[word_end] not in word_boundary_chars:
        word_end += 1
    
    full_word = full_para_text[word_start:word_end]
    
    # Check if exact text appears multiple times (for ambiguity handling)
    exact_count = full_para_text.count(exact_text)
    is_ambiguous = exact_count > 1 and len(exact_text) <= 1
    
    # Step 3: Determine what to show based on thresholds
    WORD_THRESHOLD = 25
    SENTENCE_THRESHOLD = 120
    PARAGRAPH_THRESHOLD = 300
    
    # If single character and word is short, show word instead of char
    if len(exact_text) == 1 and len(full_word) < WORD_THRESHOLD:
        # Format: [word] (referencing "char" - Nth occurrence in paragraph)
        occurrence_num = full_para_text[:exact_pos].count(exact_text) + 1
        total_occurrences = full_para_text.count(exact_text)
        
        if total_occurrences > 1:
            # Multiple occurrences - show which one
            display_text = f'{full_word} (referencing "{exact_text}" - {occurrence_num}{"st" if occurrence_num == 1 else "nd" if occurrence_num == 2 else "rd" if occurrence_num == 3 else "th"} occurrence of "{exact_text}" in this paragraph)'
        else:
            # Only one occurrence - no need for position hint
            display_text = f'{full_word} (referencing "{exact_text}")'
    else:
        display_text = exact_text
    
    # Step 4: Stepwise expansion
    # Level 1: If word is long enough, just show word
    if len(full_word) >= SENTENCE_THRESHOLD:
        return f'[{display_text}]'
    
    # Level 2: Expand to sentence
    sentence_start, sentence_end = find_sentence_boundaries(full_para_text, exact_pos)
    sentence_text = full_para_text[sentence_start:sentence_end].strip()
    
    # If sentence is long enough, use it
    if len(sentence_text) >= SENTENCE_THRESHOLD:
        return f'[{display_text}] in {sentence_text}'
    
    # Level 3: Sentence is short, expand to paragraph
    para_text = full_para_text.strip()
    if len(para_text) <= PARAGRAPH_THRESHOLD:
        # Paragraph fits within threshold, use it
        return f'[{display_text}] in {para_text}'
    else:
        # Paragraph is too long, use sentence (which is complete)
        return f'[{display_text}] in {sentence_text}'

def is_text_too_short(text, char_threshold=15, word_threshold=3):
    """Check if referenced text is too short and needs context."""
    if not text:
        return True
    text = text.strip()
    # Check character length
    if len(text) < char_threshold:
        # Also check word count for very short texts
        word_count = len(text.split())
        if word_count < word_threshold:
            return True
    return False

def load_style_names(docx):
    """Load style ID to style name mapping from styles.xml."""
    style_map = {}
    try:
        if 'word/styles.xml' in docx.namelist():
            styles_xml = docx.read('word/styles.xml')
            styles_root = ET.fromstring(styles_xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            for style in styles_root.findall('.//w:style', ns):
                style_id = style.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId', '')
                name_elem = style.find('w:name', ns)
                if name_elem is not None:
                    style_name = name_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
                    if style_id and style_name:
                        style_map[style_id] = style_name
    except Exception as e:
        print(f"Warning: Could not load styles.xml: {e}")
    return style_map

def get_paragraph_style(para, ns, style_map=None):
    """Extract the style of a paragraph (e.g., Heading1, Heading2, Normal).
    
    Returns the style name if style_map is provided, otherwise returns the style ID.
    """
    pPr = para.find('w:pPr', ns)
    if pPr is not None:
        pStyle = pPr.find('w:pStyle', ns)
        if pStyle is not None:
            style_id = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
            if style_id:
                # If we have a style map, return the style name; otherwise return the ID
                if style_map and style_id in style_map:
                    return style_map[style_id]
                return style_id
    return None

def is_heading_style(style):
    """Check if a style is a heading style.
    
    Robust detection that handles various naming conventions:
    - Style IDs: "Heading1", "Heading2", "1", "2", "h1", "h2", etc.
    - Style names: "heading 1", "heading 2", "Heading 1", "Title", "Titre", etc.
    - Also checks for common heading patterns like "Heading", "Titre", "Überschrift", etc.
    
    Args:
        style: Style ID or style name (string)
    
    Returns:
        bool: True if the style appears to be a heading style
    """
    if not style:
        return False
    
    style_lower = style.lower().strip()
    
    # Common heading keywords in various languages
    heading_keywords = [
        'heading', 'head', 'titre', 'titel', 'überschrift', 'encabezado',
        'intestazione', 'rubrik', 'заголовок', '見出し', '标题'
    ]
    
    # Check if style contains any heading keyword
    for keyword in heading_keywords:
        if keyword in style_lower:
            return True
    
    # Check for title
    if 'title' in style_lower:
        return True
    
    # Check for numbered heading patterns: "1", "2", "3", "h1", "h2", etc.
    # (but exclude if it's clearly not a heading, like "Normal", "Body", etc.)
    if style_lower.isdigit() and len(style_lower) <= 2:
        # Single or double digit - could be a heading level
        # But we need to be careful - check if it's in a style map context
        # For now, we'll be conservative and only accept if it's explicitly a heading
        # This will be handled by the style_map lookup in get_paragraph_style
        pass
    
    # Check for explicit heading patterns: "h1", "h2", "heading1", etc.
    if re.match(r'^h\d+$', style_lower) or re.match(r'^heading\d+$', style_lower):
        return True
    
    return False

def extract_heading_text(para, ns):
    """Extract text from a heading paragraph.
    
    Concatenates text directly from runs to preserve word boundaries.
    Word splits words across runs, so we concatenate without adding spaces.
    """
    text = ''
    for run in para.findall('.//w:r', ns):
        for t_elem in run.findall('.//w:t', ns):
            if t_elem.text:
                # Concatenate directly - spaces in the text itself will be preserved
                text += t_elem.text
    return text.strip()

def build_paragraph_map(doc_root, ns, style_map=None):
    """Build maps for page numbers and headings for all paragraphs.
    
    Args:
        doc_root: Root element of document.xml
        ns: XML namespace dictionary
        style_map: Optional dict mapping style ID to style name (from styles.xml)
    
    Returns:
        para_to_page: dict mapping paragraph element to page number (unused, kept for compatibility)
        para_to_heading: dict mapping paragraph element to heading path (most specific heading with hierarchy)
    """
    para_to_page = {}
    para_to_heading = {}
    
    current_page = 1
    # Track heading hierarchy: [Title, Heading1, Heading2, Heading3, ...]
    heading_hierarchy = []
    
    all_paras = doc_root.findall('.//w:p', ns)
    
    for para in all_paras:
        # Check for page break in this paragraph
        for run in para.findall('.//w:r', ns):
            br = run.find('w:br', ns)
            if br is not None:
                br_type = br.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type')
                if br_type == 'page':
                    current_page += 1
        
        # Assign page number to this paragraph
        para_to_page[para] = current_page
        
        # Check if this paragraph is a heading
        style = get_paragraph_style(para, ns, style_map)
        if is_heading_style(style):
            heading_text = extract_heading_text(para, ns)
            if heading_text:
                # Determine heading level (0=Title, 1=Heading1, 2=Heading2, etc.)
                heading_level = 1  # Default to level 1
                if style:
                    style_lower = style.lower()
                    
                    # Try various patterns to extract heading level
                    # Pattern 1: "heading 1", "heading1", "Heading1" -> 1
                    match = re.search(r'heading\s*(\d+)', style_lower)
                    if match:
                        heading_level = int(match.group(1))
                    # Pattern 2: "h1", "h2" -> 1, 2
                    elif re.match(r'^h(\d+)$', style_lower):
                        match = re.match(r'^h(\d+)$', style_lower)
                        heading_level = int(match.group(1))
                    # Pattern 3: Just a number "1", "2" -> 1, 2 (if it's a heading style)
                    elif style_lower.isdigit() and len(style_lower) <= 2:
                        # Only treat as heading level if style name contains "heading"
                        # (we already know it's a heading from is_heading_style check)
                        heading_level = int(style_lower)
                    # Pattern 4: Title -> level 0
                    elif 'title' in style_lower and 'heading' not in style_lower:
                        heading_level = 0  # Title is level 0
                    # Pattern 5: If no number found, assume level 1
                    else:
                        heading_level = 1
                
                # Update heading hierarchy
                # Remove all headings at this level or lower (they're being replaced)
                # Then add this heading at the appropriate level
                heading_hierarchy = [h for h in heading_hierarchy if h['level'] < heading_level]
                heading_hierarchy.append({
                    'level': heading_level,
                    'text': heading_text
                })
                # Sort by level to maintain order
                heading_hierarchy.sort(key=lambda x: x['level'])
        
        # Build heading path for this paragraph
        # Show most specific heading first, then parent headings
        # Format: "Most Specific / Parent / Grandparent" (like file path)
        if heading_hierarchy:
            # Build path: reverse order to show most specific first
            # heading_hierarchy is sorted by level (lowest to highest: Title=0, Heading1=1, etc.)
            # We want most specific (highest level) first, so reverse it
            path_parts = [h['text'] for h in reversed(heading_hierarchy)]
            if len(path_parts) > 1:
                # Show as file path: "2.1 Study design / 2 Methods"
                heading_path = ' / '.join(path_parts)
            else:
                # Single heading, just show it
                heading_path = path_parts[0]
            
            para_to_heading[para] = heading_path
        else:
            para_to_heading[para] = None
    
    return para_to_page, para_to_heading

def extract_comment_thread_relationships(docx, comments_root, ns):
    """Extract parent-child relationships and resolved status from commentsExtended.xml.
    
    Returns:
        parent_map: dict mapping child_comment_id -> parent_comment_id
        para_id_to_comment_id: dict mapping paraId -> comment_id
        comment_done_status: dict mapping comment_id -> done status (0=unresolved, 1=resolved)
    """
    parent_map = {}
    para_id_to_comment_id = {}
    comment_done_status = {}
    
    try:
        # Check for extended comments file
        if 'word/commentsExtended.xml' not in docx.namelist():
            return parent_map, para_id_to_comment_id, comment_done_status
        
        extended_xml = docx.read('word/commentsExtended.xml')
        extended_root = ET.fromstring(extended_xml)
        ns_ex_full = '{http://schemas.microsoft.com/office/word/2012/wordml}'
        
        # Get all comments and commentEx elements (should be in same order)
        comments = comments_root.findall('.//w:comment', ns)
        # Find commentEx elements using full namespace (they don't use prefix in the XML)
        comments_ex = [elem for elem in extended_root.iter() if elem.tag == f'{ns_ex_full}commentEx']
        
        # Map paraId to comment ID and extract done status (they should be in same order)
        for i, comment_ex in enumerate(comments_ex):
            para_id = comment_ex.get('{http://schemas.microsoft.com/office/word/2012/wordml}paraId')
            done = comment_ex.get('{http://schemas.microsoft.com/office/word/2012/wordml}done', '0')
            
            if para_id and i < len(comments):
                comment_id = comments[i].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                if comment_id:
                    para_id_to_comment_id[para_id] = comment_id
                    # Store done status (convert to int: '0'=unresolved, '1'=resolved)
                    comment_done_status[comment_id] = int(done) if done.isdigit() else 0
        
        # Build parent relationships
        for comment_ex in comments_ex:
            para_id = comment_ex.get('{http://schemas.microsoft.com/office/word/2012/wordml}paraId')
            para_id_parent = comment_ex.get('{http://schemas.microsoft.com/office/word/2012/wordml}paraIdParent')
            
            if para_id_parent and para_id in para_id_to_comment_id:
                child_id = para_id_to_comment_id[para_id]
                parent_id = para_id_to_comment_id.get(para_id_parent)
                if parent_id:
                    parent_map[child_id] = parent_id
    
    except Exception as e:
        print(f"Warning: Could not parse extended comments: {e}")
    
    return parent_map, para_id_to_comment_id, comment_done_status

def extract_comments_with_ranges(docx_path):
    """Extract comments and the text they refer to."""
    comments_data = {}
    parent_map = {}  # Initialize to avoid UnboundLocalError if exception occurs early
    
    try:
        with zipfile.ZipFile(docx_path, 'r') as docx:
            # Extract all comments
            if 'word/comments.xml' not in docx.namelist():
                print(f"No comments found in {docx_path}")
                return comments_data, parent_map
            
            comments_xml = docx.read('word/comments.xml')
            comments_root = ET.fromstring(comments_xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            # Extract thread relationships and resolved status from extended comments
            parent_map, para_id_to_comment_id, comment_done_status = extract_comment_thread_relationships(docx, comments_root, ns)
            if parent_map:
                print(f"Found {len(parent_map)} explicit parent-child relationships in extended comments")
            
            for comment in comments_root.findall('.//w:comment', ns):
                comment_id = get_comment_id_from_attr(comment)
                if not comment_id:
                    continue
                
                author = 'Unknown'
                date = ''
                for key, value in comment.attrib.items():
                    if key.endswith('author') or key == 'author':
                        author = value
                    elif key.endswith('date') or key == 'date':
                        date = value
                
                comment_text = extract_text_from_element(comment)
                
                comments_data[comment_id] = {
                    'id': comment_id,
                    'author': author,
                    'date': date,
                    'text': comment_text,
                    'referenced_text': None,
                    'page': None,
                    'section': None
                }
            
            # Extract document to find comment ranges
            doc_xml = docx.read('word/document.xml')
            doc_root = ET.fromstring(doc_xml)
            
            # Load style names from styles.xml (needed for documents that use style IDs like "1", "2" instead of "Heading1", "Heading2")
            style_map = load_style_names(docx)
            
            # Build paragraph maps for page numbers and headings
            print("Building paragraph maps for page numbers and headings...")
            para_to_page, para_to_heading = build_paragraph_map(doc_root, ns, style_map)
            
            # Extract text for each comment by finding paragraphs
            extracted_count = 0
            for comment_id in comments_data.keys():
                # Find paragraph containing this comment's range
                para = None
                start_idx = None
                end_idx = None
                
                for para_elem in doc_root.findall('.//w:p', ns):
                    children = list(para_elem)
                    for i, child in enumerate(children):
                        if child.tag.endswith('}commentRangeStart'):
                            cid = get_comment_id_from_attr(child)
                            if cid and str(cid) == str(comment_id):
                                start_idx = i
                        elif child.tag.endswith('}commentRangeEnd'):
                            cid = get_comment_id_from_attr(child)
                            if cid and str(cid) == str(comment_id):
                                end_idx = i
                    
                    if start_idx is not None and end_idx is not None:
                        para = para_elem
                        break
                
                if para is not None and start_idx is not None and end_idx is not None:
                    # Extract section heading (page numbers removed - unreliable due to lack of explicit page breaks)
                    comments_data[comment_id]['section'] = para_to_heading.get(para, None)
                    
                    # Handle case where start and end are adjacent (single character comment)
                    if start_idx == end_idx - 1:
                        # Comment might be on a single character - try to get text from surrounding context
                        children = list(para)
                        # Check if there's a run right after start
                        if start_idx + 1 < len(children):
                            next_child = children[start_idx + 1]
                            if next_child.tag.endswith('}r'):
                                text_parts = []
                                for t_elem in next_child.findall('.//w:t', ns):
                                    if t_elem.text:
                                        text_parts.append(t_elem.text)
                                if text_parts:
                                    referenced_text = ' '.join(text_parts).strip()
                                    # If text is too short, expand with context
                                    if is_text_too_short(referenced_text):
                                        expanded_text = extract_context_around_range(para, start_idx, end_idx, ns, context_chars=100, doc_root=doc_root)
                                        comments_data[comment_id]['referenced_text'] = expanded_text
                                    else:
                                        comments_data[comment_id]['referenced_text'] = referenced_text
                                    extracted_count += 1
                    else:
                        referenced_text = extract_text_from_paragraph(para, start_idx, end_idx, ns)
                        if referenced_text:
                            # If text is too short, expand with context
                            if is_text_too_short(referenced_text):
                                expanded_text = extract_context_around_range(para, start_idx, end_idx, ns, context_chars=100, doc_root=doc_root)
                                comments_data[comment_id]['referenced_text'] = expanded_text
                            else:
                                comments_data[comment_id]['referenced_text'] = referenced_text
                            extracted_count += 1
                elif start_idx is not None or end_idx is not None:
                    # One marker found but not both - mark for manual inspection
                    comments_data[comment_id]['referenced_text'] = "[Incomplete range markers]"
            
            print(f"Extracted referenced text for {extracted_count} of {len(comments_data)} comments")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    return comments_data, parent_map

def identify_comment_threads(comments_data, parent_map=None):
    """Identify comment threads using Word's explicit parent-child relationships when available.
    
    Strategy:
    1. If parent_map exists (from commentsExtended.xml), use explicit parent-child relationships
    2. Otherwise, fall back to heuristics (same referenced text + consecutive IDs + signals)
    """
    threads = []
    processed = set()
    
    # Strategy 1: Use explicit parent-child relationships from extended comments
    if parent_map:
        # Build threads from parent relationships
        # Find root comments (comments that are not children of any other comment)
        root_comments = set(comments_data.keys()) - set(parent_map.keys())
        
        # For each root, build the thread (root + all descendants)
        for root_id in root_comments:
            thread = [comments_data[root_id]]
            
            # Find all children (direct and indirect)
            def find_children(parent_id):
                children = []
                for child_id, parent_id_in_map in parent_map.items():
                    if parent_id_in_map == parent_id:
                        children.append(child_id)
                        # Recursively find grandchildren
                        children.extend(find_children(child_id))
                return children
            
            child_ids = find_children(root_id)
            for child_id in child_ids:
                if child_id in comments_data:
                    thread.append(comments_data[child_id])
            
            # Sort thread by comment ID
            thread.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 9999)
            
            if len(thread) > 1:
                threads.append(thread)
                processed.update([c['id'] for c in thread])
            else:
                # Single comment (root with no children) - don't mark as processed yet
                # It will be handled by Strategy 2 (heuristics) or added as standalone
                # Only mark as processed if it's actually in a thread
                pass
    
    # Strategy 2: Fall back to heuristics for comments not in explicit threads
    # Group by referenced text (normalized)
    text_to_comments = defaultdict(list)
    for comment_id, comment in comments_data.items():
        if comment_id not in processed:
            ref_text = comment.get('referenced_text', '')
            if ref_text:
                text_key = ref_text[:200].strip().lower()
                text_key = ' '.join(text_key.split())
                if text_key:
                    text_to_comments[text_key].append(comment_id)
    
    # Create threads using heuristics for remaining comments
    for text_key, comment_ids in text_to_comments.items():
        if len(comment_ids) > 1:
            # Convert to integers for sorting
            comment_ids_int = []
            for cid in comment_ids:
                try:
                    comment_ids_int.append((int(cid), cid))
                except (ValueError, TypeError):
                    continue
            
            if len(comment_ids_int) < 2:
                continue
            
            # Sort by ID
            comment_ids_int.sort(key=lambda x: x[0])
            
            # Group into threads based on ID proximity and signals
            current_thread = [comment_ids_int[0][1]]
            for i in range(1, len(comment_ids_int)):
                prev_id = comment_ids_int[i-1][0]
                curr_id = comment_ids_int[i][0]
                
                prev_comment = comments_data[comment_ids_int[i-1][1]]
                curr_comment = comments_data[comment_ids_int[i][1]]
                
                is_consecutive = curr_id - prev_id == 1
                different_authors = prev_comment['author'] != curr_comment['author']
                
                # Check for reply indicators
                reply_indicators = ['revised', 'thank', 'thanks', 'agreed', 'yes', 'ok', 'confirm', 
                                   'reply', 'response', 'following up', 'as requested', 'done']
                suggests_reply = any(word in curr_comment['text'].lower()[:100] for word in reply_indicators)
                
                # Group if consecutive AND (different authors OR reply indicators OR 3+ comments)
                if is_consecutive and (different_authors or suggests_reply or len(current_thread) >= 2):
                    current_thread.append(comment_ids_int[i][1])
                else:
                    # Start a new thread
                    if len(current_thread) > 1:
                        thread_comments = [comments_data[cid] for cid in current_thread]
                        thread_comments.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 9999)
                        threads.append(thread_comments)
                        processed.update(current_thread)
                    current_thread = [comment_ids_int[i][1]]
            
            # Add the last thread if it has multiple comments
            if len(current_thread) > 1:
                thread_comments = [comments_data[cid] for cid in current_thread]
                thread_comments.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 9999)
                threads.append(thread_comments)
                processed.update(current_thread)
    
    # Add standalone comments (not in any thread)
    standalone = []
    for comment_id, comment in comments_data.items():
        if comment_id not in processed:
            standalone.append(comment)
    
    standalone.sort(key=lambda x: int(x['id']) if x['id'].isdigit() else 9999)
    threads.extend([[c] for c in standalone])
    
    # Sort all threads by the minimum comment ID in each thread
    threads.sort(key=lambda t: int(t[0]['id']) if t[0]['id'].isdigit() else 9999)
    
    return threads

def main():
    # Get the root directory of comments_addresser (parent of starting_point)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    
    docx_file = os.path.join(root_dir, "test_data", "synthetic", "test.docx")
    output_file = os.path.join(root_dir, "output", "test_comments.txt")
    
    print(f"Extracting comments with context from: {docx_file}\n")
    print("=" * 80)
    
    comments_data, parent_map = extract_comments_with_ranges(docx_file)
    
    if not comments_data:
        print("No comments found.")
        return
    
    print(f"\nTotal comments: {len(comments_data)}\n")
    
    # Identify threads
    threads = identify_comment_threads(comments_data, parent_map)
    threaded_count = sum(1 for t in threads if len(t) > 1)
    
    print(f"Comment threads: {threaded_count}")
    print(f"Standalone comments: {len(threads) - threaded_count}\n")
    
    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("COMMENTS WITH CONTEXT (Chains/Threads and Referenced Text)\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total comments: {len(comments_data)}\n")
        f.write(f"Comment threads: {threaded_count}\n")
        f.write(f"Extracted from: {docx_file}\n")
        f.write(f"Extraction date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for thread_num, thread in enumerate(threads, 1):
            f.write("\n" + "=" * 80 + "\n")
            if len(thread) > 1:
                f.write(f"THREAD {thread_num} ({len(thread)} comments in chain)\n")
            else:
                f.write(f"COMMENT {thread_num}\n")
            f.write("=" * 80 + "\n\n")
            
            # For threads, show referenced text and section once at the thread level
            # (all comments in a thread reference the same text and are in the same section)
            if len(thread) > 1:
                # Get referenced text and section from first comment (they should all be the same)
                first_comment = thread[0]
                
                # Show section at thread level
                if first_comment.get('section'):
                    f.write(f"Section: {first_comment['section']}\n")
                
                # Show referenced text at thread level
                if first_comment.get('referenced_text'):
                    ref_text = first_comment['referenced_text']
                    if ref_text != "[Incomplete range markers]":
                        f.write(f"\nReferenced Text:\n{'─' * 40}\n")
                        if len(ref_text) > 500:
                            f.write(f"{ref_text[:500]}... [truncated]\n")
                        else:
                            f.write(f"{ref_text}\n")
                        f.write(f"{'─' * 40}\n")
                
                f.write("\n")
            
            for i, comment in enumerate(thread, 1):
                f.write(f"{'─' * 80}\n")
                if len(thread) > 1:
                    f.write(f"  Reply {i} of {len(thread)}\n")
                f.write(f"{'─' * 80}\n")
                f.write(f"Comment ID: {comment['id']}\n")
                f.write(f"Author: {comment['author']}\n")
                if comment['date']:
                    date_str = comment['date'].split('T')[0] if 'T' in comment['date'] else comment['date']
                    f.write(f"Date: {date_str}\n")
                
                # For standalone comments (not in threads), show section
                # For threads, section is already shown at thread level
                if len(thread) == 1 and comment.get('section'):
                    f.write(f"Section: {comment['section']}\n")
                
                # For standalone comments (not in threads), show referenced text
                # For threads, referenced text is already shown at thread level
                if len(thread) == 1 and comment.get('referenced_text'):
                    ref_text = comment['referenced_text']
                    if ref_text != "[Incomplete range markers]":
                        f.write(f"\nReferenced Text:\n{'─' * 40}\n")
                        if len(ref_text) > 500:
                            f.write(f"{ref_text[:500]}... [truncated]\n")
                        else:
                            f.write(f"{ref_text}\n")
                        f.write(f"{'─' * 40}\n")
                
                f.write(f"\nComment:\n{comment['text']}\n\n")
    
    print(f"✓ Saved to: {output_file}")

if __name__ == "__main__":
    main()
