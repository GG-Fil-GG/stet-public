"""
Structural edit computation for plain text revisions.

Handles paragraph alignment, split/merge/insert/delete, and applying
revised plain text back to the DocumentModel.
"""

from typing import Optional, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import DocumentModel
    from .edits import DocumentEdit


def _reorder_edits_for_safe_application(edits: List['DocumentEdit']) -> List['DocumentEdit']:
    """
    Reorder edits to ensure safe application order.
    
    The key issue: INSERT_PARAGRAPH edits using before_para_id or after_para_id
    will fail if that reference paragraph has already been deleted. So we must
    ensure INSERTs referencing a paragraph happen BEFORE any DELETE for that paragraph.
    
    Safe order:
    1. INSERT_PARAGRAPH edits (they depend on existing paragraphs)
    2. REPLACE edits (modify existing content)
    3. DELETE edits (within-paragraph)
    4. DELETE_PARAGRAPH edits (remove whole paragraphs)
    
    Within INSERT_PARAGRAPH, we also need to process in document order to ensure
    after_para_id references work correctly when inserting multiple paragraphs.
    """
    from .edits import EditType
    
    # Separate edits by type
    inserts = []
    replaces = []
    deletes_within = []
    deletes_paragraph = []
    other = []
    
    for edit in edits:
        if edit.edit_type == EditType.INSERT_PARAGRAPH:
            inserts.append(edit)
        elif edit.edit_type == EditType.DELETE_PARAGRAPH:
            deletes_paragraph.append(edit)
        elif edit.edit_type == EditType.REPLACE:
            replaces.append(edit)
        elif edit.edit_type == EditType.DELETE:
            deletes_within.append(edit)
        else:
            other.append(edit)
    
    # For inserts, we need to be careful about order:
    # If insert A creates para X, and insert B uses after_para_id=X,
    # then A must come before B.
    # 
    # For now, we'll use a simple heuristic: inserts using before_para_id
    # should come first, then inserts using after_para_id in the order
    # they were generated (which should be document order).
    inserts_before = [e for e in inserts if e.before_para_id]
    inserts_after = [e for e in inserts if e.after_para_id and not e.before_para_id]
    inserts_neither = [e for e in inserts if not e.before_para_id and not e.after_para_id]
    
    # Combine in safe order
    return inserts_before + inserts_after + inserts_neither + replaces + deletes_within + other + deletes_paragraph


def compute_structural_edits(
    original_para_texts: List[str],
    revised_para_texts: List[str],
    para_ids: List[str],
    author: str = "Stet",
    track_changes: bool = True,
    thread_id: Optional[str] = None,
    existing_para_ids: Optional[set] = None,
    before_first_para_id: Optional[str] = None,
    first_para_id: Optional[str] = None
) -> List['DocumentEdit']:
    """
    Compute edits including structural changes (paragraph split/merge/insert/delete).
    
    This is the key function for handling structural changes in revisions.
    It compares original and revised paragraph lists and generates appropriate
    DocumentEdit objects including INSERT_PARAGRAPH and DELETE_PARAGRAPH.
    
    Args:
        original_para_texts: List of original paragraph texts
        revised_para_texts: List of revised paragraph texts (split by \\n\\n)
        para_ids: List of paragraph IDs corresponding to original_para_texts
        author: Author name for tracked changes
        track_changes: Whether to create tracked changes
        thread_id: Thread ID for revision tracking
        existing_para_ids: Set of existing para_ids for collision avoidance
        before_first_para_id: Para ID of the paragraph BEFORE the first para_id
                              in the full document (DEPRECATED - use first_para_id instead)
        first_para_id: The first target paragraph ID. Used for insertions at the
                       "beginning" of the target region - we insert BEFORE this
                       paragraph rather than trying to find something to insert AFTER.
        
    Returns:
        List of DocumentEdit objects in application order
    """
    from .edits import DocumentEdit, EditType
    from .utils import generate_valid_para_id
    from src.diff_utils import compute_diff, DiffOperation
    
    edits = []
    existing_ids = existing_para_ids or set()
    
    orig_count = len(original_para_texts)
    rev_count = len(revised_para_texts)
    
    if orig_count == 0:
        # No original paragraphs - can't do anything
        return edits
    
    if rev_count == 0:
        # All paragraphs deleted
        for para_id in para_ids:
            edit = DocumentEdit.delete_paragraph(
                para_id=para_id,
                author=author,
                track_change=track_changes,
                thread_id=thread_id
            )
            edits.append(edit)
        return edits
    
    # Case 1: Same paragraph count - just within-paragraph edits
    if orig_count == rev_count:
        for i, (para_id, orig_text, rev_text) in enumerate(zip(para_ids, original_para_texts, revised_para_texts)):
            if orig_text != rev_text:
                # Compute within-paragraph edits
                para_edits = _compute_within_paragraph_edits(
                    para_id, orig_text, rev_text, author, track_changes, thread_id
                )
                edits.extend(para_edits)
        return edits
    
    # Case 2: Different paragraph counts - use alignment algorithm
    alignment = _align_paragraphs(original_para_texts, revised_para_texts)
    
    # Process alignment to generate edits
    for align_op in alignment:
        op_type = align_op['type']
        
        if op_type == 'match':
            # Paragraph content may have changed
            orig_idx = align_op['orig_idx']
            rev_idx = align_op['rev_idx']
            para_id = para_ids[orig_idx]
            orig_text = original_para_texts[orig_idx]
            rev_text = revised_para_texts[rev_idx]
            
            if orig_text != rev_text:
                para_edits = _compute_within_paragraph_edits(
                    para_id, orig_text, rev_text, author, track_changes, thread_id
                )
                edits.extend(para_edits)
                
        elif op_type == 'delete':
            # Paragraph deleted
            orig_idx = align_op['orig_idx']
            para_id = para_ids[orig_idx]
            edit = DocumentEdit.delete_paragraph(
                para_id=para_id,
                author=author,
                track_change=track_changes,
                thread_id=thread_id
            )
            edits.append(edit)
            
        elif op_type == 'insert':
            # New paragraph inserted
            rev_idx = align_op['rev_idx']
            rev_text = revised_para_texts[rev_idx]
            
            # Find insertion position
            # We support both after_para_id and before_para_id:
            # - after_para_id: insert after this paragraph
            # - before_para_id: insert before this paragraph (takes precedence)
            after_para_id = align_op.get('after_para_id')
            before_para_id = None
            
            if after_para_id is None:
                after_para_id_idx = align_op.get('after_para_id_idx')
                if after_para_id_idx is not None and after_para_id_idx < len(para_ids):
                    after_para_id = para_ids[after_para_id_idx]
                elif first_para_id is not None:
                    # UNIVERSAL SOLUTION: Insert BEFORE the first target paragraph.
                    # This works correctly regardless of what comes before the target
                    # (tables, other paragraphs, etc.) because we're not trying to 
                    # find something to insert AFTER.
                    before_para_id = first_para_id
                    print(f"[STRUCTURAL] Inserting before first target paragraph {first_para_id}", flush=True)
                elif before_first_para_id is not None:
                    # DEPRECATED fallback: insert after the paragraph that comes before
                    # the first target. This can fail with tables.
                    after_para_id = before_first_para_id
                # else both stay None = truly insert at beginning of document
            
            # Generate new para_id
            new_para_id = generate_valid_para_id(existing_ids)
            existing_ids.add(new_para_id)
            
            edit = DocumentEdit.insert_paragraph(
                after_para_id=after_para_id,
                before_para_id=before_para_id,
                text=rev_text,
                new_para_id=new_para_id,
                author=author,
                track_change=track_changes,
                thread_id=thread_id
            )
            edits.append(edit)
            
        elif op_type == 'split':
            # One paragraph split into multiple
            orig_idx = align_op['orig_idx']
            rev_indices = align_op['rev_indices']
            para_id = para_ids[orig_idx]
            
            # First revised paragraph replaces the original
            first_rev_text = revised_para_texts[rev_indices[0]]
            orig_text = original_para_texts[orig_idx]
            
            if orig_text != first_rev_text:
                para_edits = _compute_within_paragraph_edits(
                    para_id, orig_text, first_rev_text, author, track_changes, thread_id
                )
                edits.extend(para_edits)
            
            # Additional revised paragraphs are inserted after
            insert_after = para_id
            for rev_idx in rev_indices[1:]:
                new_para_id = generate_valid_para_id(existing_ids)
                existing_ids.add(new_para_id)
                
                edit = DocumentEdit.insert_paragraph(
                    after_para_id=insert_after,
                    text=revised_para_texts[rev_idx],
                    new_para_id=new_para_id,
                    author=author,
                    track_change=track_changes,
                    thread_id=thread_id
                )
                edits.append(edit)
                insert_after = new_para_id
                
        elif op_type == 'merge':
            # Multiple paragraphs merged into one
            orig_indices = align_op['orig_indices']
            rev_idx = align_op['rev_idx']
            
            # First original paragraph gets the merged content
            first_para_id = para_ids[orig_indices[0]]
            merged_text = revised_para_texts[rev_idx]
            first_orig_text = original_para_texts[orig_indices[0]]
            
            # Replace first paragraph content with merged content
            para_edits = _compute_within_paragraph_edits(
                first_para_id, first_orig_text, merged_text, author, track_changes, thread_id
            )
            edits.extend(para_edits)
            
            # Delete the other original paragraphs
            for orig_idx in orig_indices[1:]:
                para_id = para_ids[orig_idx]
                edit = DocumentEdit.delete_paragraph(
                    para_id=para_id,
                    author=author,
                    track_change=track_changes,
                    thread_id=thread_id
                )
                edits.append(edit)
    
    return edits


def _compute_within_paragraph_edits(
    para_id: str,
    original_text: str,
    revised_text: str,
    author: str,
    track_changes: bool,
    thread_id: Optional[str]
) -> List['DocumentEdit']:
    """
    Compute within-paragraph edits for a single paragraph.
    
    Uses a single REPLACE edit for simplicity and correctness.
    This ensures the entire paragraph is updated atomically without
    offset adjustment issues when applying multiple edits.
    """
    from .edits import DocumentEdit, EditType
    
    if original_text == revised_text:
        return []
    
    # Use a single REPLACE edit for the entire paragraph
    # This is simpler and avoids offset adjustment issues with sequential edits
    edit = DocumentEdit(
        edit_type=EditType.REPLACE,
        para_id=para_id,
        start_offset=0,
        end_offset=len(original_text),
        text=revised_text,
        author=author,
        track_change=track_changes,
        thread_id=thread_id
    )
    
    return [edit]


def _align_paragraphs(
    original_texts: List[str],
    revised_texts: List[str]
) -> List[Dict]:
    """
    Align original and revised paragraph lists to detect structural changes.
    
    Uses sequence alignment (similar to diff) to detect:
    - Matching paragraphs (content may differ)
    - Deleted paragraphs
    - Inserted paragraphs
    - Split paragraphs (one → many)
    - Merged paragraphs (many → one)
    
    Returns:
        List of alignment operations with type and indices
    """
    from difflib import SequenceMatcher
    
    # Use SequenceMatcher to find matching blocks
    # We compare paragraph texts to find the best alignment
    matcher = SequenceMatcher(
        None,
        original_texts,
        revised_texts,
        autojunk=False
    )
    
    alignment = []
    
    # Get matching blocks: each is (orig_start, rev_start, length)
    matching_blocks = matcher.get_matching_blocks()
    
    orig_idx = 0
    rev_idx = 0
    
    for orig_start, rev_start, length in matching_blocks:
        # Handle gaps before this matching block
        
        # Original paragraphs before the match (potential deletes or merge sources)
        orig_gap = list(range(orig_idx, orig_start))
        # Revised paragraphs before the match (potential inserts or merge results)
        rev_gap = list(range(rev_idx, rev_start))
        
        if orig_gap and rev_gap:
            # Both sides have paragraphs - could be merge, split, or mixed
            # Use heuristics to detect merge vs split vs mixed changes
            gap_alignment = _align_gap(
                original_texts, revised_texts, orig_gap, rev_gap
            )
            alignment.extend(gap_alignment)
        elif orig_gap:
            # Only original has paragraphs - deletions
            for i in orig_gap:
                alignment.append({
                    'type': 'delete',
                    'orig_idx': i
                })
        elif rev_gap:
            # Only revised has paragraphs - insertions
            # Find the best after_para_id
            after_para_id_idx = orig_start - 1 if orig_start > 0 else None
            for i in rev_gap:
                alignment.append({
                    'type': 'insert',
                    'rev_idx': i,
                    'after_para_id_idx': after_para_id_idx
                })
        
        # Handle the matching block
        for i in range(length):
            alignment.append({
                'type': 'match',
                'orig_idx': orig_start + i,
                'rev_idx': rev_start + i
            })
        
        orig_idx = orig_start + length
        rev_idx = rev_start + length
    
    # Post-process to convert after_para_id_idx to after_para_id
    # (This will be done by the caller who has access to para_ids)
    
    return alignment


def _align_gap(
    original_texts: List[str],
    revised_texts: List[str],
    orig_indices: List[int],
    rev_indices: List[int]
) -> List[Dict]:
    """
    Align a gap region where both original and revised have paragraphs.
    
    Uses text similarity to detect merges, splits, or unrelated changes.
    """
    alignment = []
    
    # Heuristic: Compare character counts to detect merge vs split
    orig_total_chars = sum(len(original_texts[i]) for i in orig_indices)
    rev_total_chars = sum(len(revised_texts[i]) for i in rev_indices)
    
    # Simple case: 1 original, multiple revised = likely split
    if len(orig_indices) == 1 and len(rev_indices) > 1:
        # Check if revised texts concatenated are similar to original
        combined_rev = ' '.join(revised_texts[i] for i in rev_indices)
        orig_text = original_texts[orig_indices[0]]
        
        # Use similarity ratio
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, orig_text, combined_rev).ratio()
        
        if similarity > 0.5:  # Likely a split
            alignment.append({
                'type': 'split',
                'orig_idx': orig_indices[0],
                'rev_indices': rev_indices
            })
            return alignment
    
    # Simple case: multiple original, 1 revised = likely merge
    if len(orig_indices) > 1 and len(rev_indices) == 1:
        # Check if original texts concatenated are similar to revised
        combined_orig = ' '.join(original_texts[i] for i in orig_indices)
        rev_text = revised_texts[rev_indices[0]]
        
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, combined_orig, rev_text).ratio()
        
        if similarity > 0.5:  # Likely a merge
            alignment.append({
                'type': 'merge',
                'orig_indices': orig_indices,
                'rev_idx': rev_indices[0]
            })
            return alignment
    
    # General case: Try to match by similarity
    # For each revised paragraph, find the most similar original
    used_orig = set()
    used_rev = set()
    
    # Find best matches
    matches = []
    for rev_i in rev_indices:
        rev_text = revised_texts[rev_i]
        best_orig = None
        best_similarity = 0.3  # Minimum threshold
        
        for orig_i in orig_indices:
            if orig_i in used_orig:
                continue
            orig_text = original_texts[orig_i]
            
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, orig_text, rev_text).ratio()
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_orig = orig_i
        
        if best_orig is not None:
            matches.append((best_orig, rev_i))
            used_orig.add(best_orig)
            used_rev.add(rev_i)
    
    # Add matches
    for orig_i, rev_i in matches:
        alignment.append({
            'type': 'match',
            'orig_idx': orig_i,
            'rev_idx': rev_i
        })
    
    # Add deletions for unmatched originals
    for orig_i in orig_indices:
        if orig_i not in used_orig:
            alignment.append({
                'type': 'delete',
                'orig_idx': orig_i
            })
    
    # Add insertions for unmatched revised
    for rev_i in rev_indices:
        if rev_i not in used_rev:
            # Insert after the last matched original, or after deleted originals
            after_idx = None
            
            # First try: find position from matched paragraphs
            for orig_i, matched_rev_i in matches:
                if matched_rev_i < rev_i:
                    after_idx = orig_i
            
            # Fallback: if no matches, use the last original in this gap
            # This ensures inserts go where the deleted paragraphs were,
            # not at the beginning of the document
            if after_idx is None and orig_indices:
                # Use the paragraph BEFORE the first original in this gap
                # (i.e., the first orig_idx - 1, if it exists)
                first_orig_in_gap = min(orig_indices)
                if first_orig_in_gap > 0:
                    after_idx = first_orig_in_gap - 1
                # else after_idx stays None = insert at beginning (correct for first para)
            
            alignment.append({
                'type': 'insert',
                'rev_idx': rev_i,
                'after_para_id_idx': after_idx
            })
    
    return alignment


def apply_revision_from_plain_text(
    model: 'DocumentModel',
    para_ids: List[str],
    revised_text: str,
    author: str = "Stet",
    track_changes: bool = True,
    thread_id: Optional[str] = None,
    original_texts: Optional[List[str]] = None
) -> List['DocumentEdit']:
    """
    Apply revision from plain text to the DocumentModel.
    
    This is THE unified entry point for all plain text → DOM conversion:
    - LLM output → DOM
    - User UI edits → DOM
    
    Args:
        model: The DocumentModel to modify
        para_ids: List of paragraph IDs being revised
        revised_text: The revised text (paragraphs separated by \\n\\n)
        author: Author name for tracked changes
        track_changes: Whether to create tracked changes
        thread_id: Thread ID for revision tracking
        original_texts: Optional explicit original texts for comparison.
                       If provided, these are used instead of reading from DOM.
                       This is critical for re-accepts where the DOM already
                       has a previous revision applied.
        
    Returns:
        List of applied DocumentEdit objects
    """
    from .edits import EditType
    
    if not para_ids:
        return []
    
    # Collect field codes from original paragraphs BEFORE applying edits
    # These will be copied to any new paragraphs created by splits
    original_field_codes = {}
    for para_id in para_ids:
        para = model.get_paragraph(para_id)
        if para and para.field_codes:
            original_field_codes.update(para.field_codes)
    
    # Get original paragraph texts - use provided texts or read from model
    if original_texts is not None:
        original_para_texts = original_texts
        print(f"[PLAIN_TEXT] Using provided original texts ({len(original_texts)} paragraphs)", flush=True)
    else:
        original_para_texts = []
        for para_id in para_ids:
            para = model.get_paragraph(para_id)
            if para:
                original_para_texts.append(para.plain_text)
            else:
                original_para_texts.append("")
    
    # Parse revised text into paragraphs
    revised_para_texts = [p for p in revised_text.split('\n\n') if p.strip()]
    
    # If no revised paragraphs but there's text, treat as single paragraph
    if not revised_para_texts and revised_text.strip():
        revised_para_texts = [revised_text.strip()]
    
    # Get existing para_ids for collision avoidance
    existing_para_ids = set()
    for element in model.body.elements:
        if hasattr(element, 'para_id'):
            existing_para_ids.add(element.para_id)
    
    # Determine the first target paragraph ID for insertion positioning
    # When inserting at the "beginning" of the target region, we insert BEFORE
    # this paragraph. This is a universal solution that works regardless of
    # what comes before (tables, other paragraphs, etc.)
    first_para_id = para_ids[0] if para_ids else None
    
    # Compute structural edits
    edits = compute_structural_edits(
        original_para_texts=original_para_texts,
        revised_para_texts=revised_para_texts,
        para_ids=para_ids,
        author=author,
        track_changes=track_changes,
        thread_id=thread_id,
        existing_para_ids=existing_para_ids,
        first_para_id=first_para_id
    )
    
    # CRITICAL: Reorder edits to ensure INSERTs happen before DELETEs
    # that would remove their reference paragraphs.
    # Without this, an INSERT using before_para_id='X' would fail
    # if a DELETE for para_id='X' is applied first.
    edits = _reorder_edits_for_safe_application(edits)
    
    # Apply edits to model
    applied_edits = []
    new_para_ids = []  # Track newly created paragraph IDs
    
    for edit in edits:
        # Track INSERT_PARAGRAPH edits for field code copying
        if edit.edit_type == EditType.INSERT_PARAGRAPH and edit.new_para_id:
            new_para_ids.append(edit.new_para_id)
        
        success = model.apply_edit(edit)
        if success:
            applied_edits.append(edit)
        else:
            print(f"[PLAIN_TEXT] Warning: Failed to apply edit: {edit}", flush=True)
    
    # Copy field codes to newly created paragraphs
    # This ensures that citation placeholders like [CITATION_1] can be restored
    # even when they end up in a new paragraph after a split
    if original_field_codes and new_para_ids:
        for new_para_id in new_para_ids:
            new_para = model.get_paragraph(new_para_id)
            if new_para:
                # Copy field codes that are referenced in this paragraph's text
                para_text = new_para.plain_text
                for placeholder, field_code in original_field_codes.items():
                    if placeholder in para_text:
                        if not new_para.field_codes:
                            new_para.field_codes = {}
                        new_para.field_codes[placeholder] = field_code
                        print(f"[PLAIN_TEXT] Copied field code {placeholder} to new paragraph {new_para_id}", flush=True)
    
    return applied_edits
