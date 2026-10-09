"""Revision serialization and diff application to paragraphs."""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

from .model import DocumentModel
from .paragraph import Paragraph, RevisionType
from .revisions import Revision
from .utils import generate_hex_id

from .serializer_common import _sanitize_for_xml

class SerializerRevisionsMixin:
    """Mixin providing serializer methods."""

    def _serialize_revisions(self, model: DocumentModel, doc_xml: str) -> str:
        """
        Insert track change markup into document.xml using diff-based approach.
        
        Handles three types of changes:
        1. Modified paragraphs - word-level diffs with <w:ins>/<w:del> for changes
        2. New paragraphs - entire content wrapped in <w:ins>
        3. Deleted paragraphs - entire content wrapped in <w:del>
        
        Field codes (EndNote, Zotero citations) are preserved:
        1. Use field codes stored in paragraph (extracted at parse time)
        2. Model's plain_text already has placeholders (e.g., [CITATION_1])
        3. Extract original text and inject same placeholders for diff
        4. Compute diff on placeholder-containing texts (citations appear as EQUAL)
        5. Generate track changes with placeholders
        6. Restore field codes (replace placeholders with original XML)
        
        This produces cleaner track changes (showing only what changed, not
        full paragraph replacements) while preserving field codes exactly.
        """
        from src.diff_utils import compute_diff, DiffOperation
        
        modified_xml = doc_xml
        
        # Get revision metadata from first revision (author, timestamp)
        first_revision = next(iter(model.revisions.get_pending_revisions()), None)
        author = first_revision.author if first_revision else "Stet"
        timestamp = first_revision.timestamp if first_revision else datetime.now(timezone.utc)
        
        # Track the next revision ID to use
        next_rev_id = self._get_max_revision_id(doc_xml) + 1
        
        # =================================================================
        # STRUCTURAL CHANGES (Phase 5): Handle new and deleted paragraphs
        # =================================================================
        
        # Get all para_ids from original document and current model
        original_para_ids = self._extract_all_para_ids(doc_xml)
        model_para_ids = set(p.para_id for p in model.body.iter_paragraphs())
        
        # Identify new paragraphs (in model but not in original)
        new_para_ids = model_para_ids - original_para_ids
        
        # Identify deleted paragraphs (in original but not in model)
        deleted_para_ids = original_para_ids - model_para_ids
        
        # Process deleted paragraphs first (mark with <w:del>)
        for para_id in deleted_para_ids:
            modified_xml, next_rev_id = self._mark_paragraph_as_deleted(
                modified_xml, para_id, author, timestamp, next_rev_id
            )
        
        # Process new paragraphs (insert with <w:ins>)
        # Process in model order to maintain correct positioning
        for paragraph in model.body.iter_paragraphs():
            if paragraph.para_id in new_para_ids:
                # Find where to insert this paragraph
                after_para_id, before_para_id = self._find_insertion_position(
                    model, paragraph.para_id, original_para_ids
                )
                modified_xml, next_rev_id = self._insert_new_paragraph(
                    modified_xml, paragraph, after_para_id, before_para_id, author, timestamp, next_rev_id
                )
        
        # =================================================================
        # CONTENT CHANGES: Handle modified paragraphs (word-level diffs)
        # =================================================================
        
        # Find paragraphs that have been modified by checking RevisionStore
        # We use revision para_ids to identify which paragraphs need diff processing
        modified_para_ids = set()
        for revision in model.revisions.get_pending_revisions():
            # Only process paragraphs that exist in both original and model
            if revision.para_id in original_para_ids and revision.para_id in model_para_ids:
                modified_para_ids.add(revision.para_id)
        
        if not modified_para_ids and not new_para_ids and not deleted_para_ids:
            return doc_xml
        
        # Process each modified paragraph (content changes within existing paragraphs)
        for para_id in modified_para_ids:
            paragraph = model.get_paragraph(para_id)
            if not paragraph:
                continue
            
            # Get the current text from the model (already has placeholders if field_codes exist)
            current_text = paragraph.plain_text
            
            # Extract the original paragraph XML
            para_pattern = re.compile(
                r'<w:p\s[^>]*w14:paraId="' + para_id + r'"[^>]*>(.*?)</w:p>',
                re.DOTALL
            )
            match = para_pattern.search(modified_xml)
            if not match:
                continue
            
            original_para_content = match.group(1)
            
            # Use field codes from paragraph (stored at parse time)
            # This ensures consistent placeholders between model text and original
            field_codes = paragraph.field_codes
            
            if field_codes:
                # Extract original visible text and inject the same placeholders
                original_text = self._extract_visible_text_from_para_xml(original_para_content)
                original_text_with_placeholders = self._inject_placeholders_into_text(
                    original_text, field_codes
                )
                logger.debug("Paragraph %s has %d field code(s)", para_id, len(field_codes))
            else:
                # No field codes - extract original text directly
                _, _, original_text_with_placeholders = self._extract_field_codes(
                    original_para_content
                )
                if original_text_with_placeholders is None:
                    continue
            
            # current_text already has placeholders (from paragraph.plain_text)
            # Compute word-level diff (on placeholder-containing texts)
            diff_result = compute_diff(original_text_with_placeholders, current_text)
            
            if not diff_result.has_changes:
                continue
            
            # Apply diff-based track changes to this paragraph
            # Pass field_codes so they can be restored after generating content
            modified_xml, next_rev_id = self._apply_diff_to_paragraph(
                modified_xml, para_id, diff_result, author, timestamp, next_rev_id, model,
                field_codes=field_codes
            )
        
        return modified_xml
    
    def _get_max_revision_id(self, doc_xml: str) -> int:
        """Find the highest revision ID used in document.xml."""
        max_id = 0
        for match in re.finditer(r'w:id="(\d+)"', doc_xml):
            try:
                max_id = max(max_id, int(match.group(1)))
            except ValueError:
                pass
        return max_id
    
    def _extract_original_para_text(self, doc_xml: str, para_id: str) -> Optional[str]:
        """Extract the visible text from a paragraph in the original DOCX XML."""
        # Find the paragraph by para_id
        para_pattern = re.compile(
            r'<w:p\s[^>]*w14:paraId="' + para_id + r'"[^>]*>(.*?)</w:p>',
            re.DOTALL
        )
        match = para_pattern.search(doc_xml)
        if not match:
            return None
        
        para_content = match.group(1)
        
        # Extract text from <w:t> elements, excluding <w:delText>
        # First remove deletion content
        para_without_del = re.sub(r'<w:delText[^>]*>.*?</w:delText>', '', para_content, flags=re.DOTALL)
        
        # Extract all text
        text_parts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', para_without_del)
        return ''.join(text_parts)
    
    def _extract_original_anchors_from_paragraph(self, para_content: str) -> List[Dict]:
        """
        Extract comment anchor positions from the original paragraph XML.
        
        Walks through the paragraph content, tracking character positions
        (excluding deleted text) and recording where commentRangeStart/End markers appear.
        
        Returns:
            List of dicts with 'comment_id', 'start_offset', 'end_offset'
        """
        # Track comment ranges: comment_id -> {'start': int, 'end': int}
        comment_ranges = {}
        char_pos = 0
        
        # Remove existing deletions for character counting
        # (We count visible text only, same as how the parser does it)
        content_without_del = re.sub(r'<w:del\b[^>]*>.*?</w:del>', '', para_content, flags=re.DOTALL)
        
        # Parse through the content looking for markers and text
        # Use a simple sequential scan
        pos = 0
        while pos < len(content_without_del):
            # Check for commentRangeStart
            start_match = re.match(r'<w:commentRangeStart\s+w:id="(\d+)"\s*/>', content_without_del[pos:])
            if start_match:
                comment_id = start_match.group(1)
                if comment_id not in comment_ranges:
                    comment_ranges[comment_id] = {}
                comment_ranges[comment_id]['start'] = char_pos
                pos += len(start_match.group(0))
                continue
            
            # Check for commentRangeEnd
            end_match = re.match(r'<w:commentRangeEnd\s+w:id="(\d+)"\s*/>', content_without_del[pos:])
            if end_match:
                comment_id = end_match.group(1)
                if comment_id not in comment_ranges:
                    comment_ranges[comment_id] = {}
                comment_ranges[comment_id]['end'] = char_pos
                pos += len(end_match.group(0))
                continue
            
            # Check for text content (w:t)
            text_match = re.match(r'<w:t[^>]*>([^<]*)</w:t>', content_without_del[pos:])
            if text_match:
                text = text_match.group(1)
                char_pos += len(text)
                pos += len(text_match.group(0))
                continue
            
            # Skip other tags
            tag_match = re.match(r'<[^>]+>', content_without_del[pos:])
            if tag_match:
                pos += len(tag_match.group(0))
                continue
            
            # Skip single characters (shouldn't happen often)
            pos += 1
        
        # Convert to list format
        result = []
        for comment_id, range_info in comment_ranges.items():
            if 'start' in range_info and 'end' in range_info:
                result.append({
                    'comment_id': comment_id,
                    'start_offset': range_info['start'],
                    'end_offset': range_info['end']
                })
        
        return result
    
    def _map_anchor_positions_through_diff(
        self,
        diff_result,
        anchors: List[Dict]
    ) -> List[Dict]:
        """
        Map comment anchor positions from original text to OUTPUT text through diff operations.
        
        Key insight: The OUTPUT text includes BOTH visible and deleted text:
        - EQUAL: text appears in output at current position
        - DELETE: text appears in output at current position (will be in <w:del>)
        - INSERT: text appears in output at current position (will be in <w:ins>)
        
        Anchor positions should map to where the ORIGINAL characters appear in the output,
        whether in normal runs or in deletion runs. This preserves the semantic meaning
        of comments even when their referenced text is deleted.
        
        Enhancement: When an anchor covers text that is ENTIRELY deleted and immediately
        followed by an INSERT (i.e., a replacement), extend the anchor to also cover the
        replacement text. This ensures comments remain visible in Word even when their
        originally referenced text has been replaced.
        
        Args:
            diff_result: The diff result with operations
            anchors: List of dicts with 'comment_id', 'start_offset', 'end_offset'
            
        Returns:
            List of dicts with 'comment_id', 'new_start', 'new_end' positions
        """
        from src.diff_utils import DiffOperation
        
        if not anchors:
            return []
        
        # Build position mapping: for each original position, where does it appear in output?
        # 
        # Key insight: At any original position, we need to know where the CHARACTER at that
        # position appears in the output. This is determined by which operation contains it.
        #
        # We build a list of (orig_start, orig_end, output_start, output_end) chunks.
        # Only EQUAL and DELETE operations consume original text.
        # INSERT operations add to output but don't consume original positions.
        
        chunks = []  # Each chunk: (orig_start, orig_end, output_start, output_end)
        orig_pos = 0
        output_pos = 0
        
        # Also track all operations with their output ranges for replacement detection
        op_ranges = []  # Each: (op_type, orig_start, orig_end, output_start, output_end)
        
        for op in diff_result.operations:
            op_len = len(op.text)
            
            if op.op == DiffOperation.EQUAL:
                # Original chars map 1:1 to output
                chunks.append((orig_pos, orig_pos + op_len, output_pos, output_pos + op_len))
                op_ranges.append(('EQUAL', orig_pos, orig_pos + op_len, output_pos, output_pos + op_len))
                orig_pos += op_len
                output_pos += op_len
                
            elif op.op == DiffOperation.DELETE:
                # Deleted text: original chars appear in output (inside <w:del>)
                chunks.append((orig_pos, orig_pos + op_len, output_pos, output_pos + op_len))
                op_ranges.append(('DELETE', orig_pos, orig_pos + op_len, output_pos, output_pos + op_len))
                orig_pos += op_len
                output_pos += op_len
                
            elif op.op == DiffOperation.INSERT:
                # Inserted text adds to output but doesn't consume original positions
                # No chunk created - this just shifts output_pos
                op_ranges.append(('INSERT', None, None, output_pos, output_pos + op_len))
                output_pos += op_len
        
        final_output_pos = output_pos
        
        logger.debug("Built %d chunks for mapping", len(chunks))
        for i, (os, oe, ns, ne) in enumerate(chunks[:10]):
            logger.debug("  Chunk %d: orig[%d:%d] -> output[%d:%d]", i, os, oe, ns, ne)
        
        def map_position(pos: int) -> int:
            """Map a position from original text to output text.
            
            For boundary positions (where one chunk ends and another begins),
            we want the chunk where that CHARACTER lives. A position at the end
            of a DELETE chunk (e.g., pos=242 when DELETE is 235-242) should map
            to the START of the next chunk (e.g., EQUAL 242-341), not the end
            of the DELETE.
            
            The rule: Use orig_start <= pos < orig_end, except for the last chunk
            which needs to include its end boundary.
            """
            for i, (orig_start, orig_end, output_start, output_end) in enumerate(chunks):
                is_last = (i == len(chunks) - 1)
                
                if is_last:
                    # Last chunk: include end boundary
                    if orig_start <= pos <= orig_end:
                        offset = pos - orig_start
                        return output_start + offset
                else:
                    # Not last chunk: exclude end boundary so next chunk gets it
                    if orig_start <= pos < orig_end:
                        offset = pos - orig_start
                        return output_start + offset
            
            # Beyond all chunks - return final output position
            return final_output_pos
        
        def check_if_entirely_deleted_and_replaced(orig_start: int, orig_end: int, new_start: int, new_end: int) -> Optional[int]:
            """
            Check if the anchor covers text that is entirely within DELETE operations
            and if there's an INSERT immediately following (indicating a replacement).
            
            Returns the extended end position if replacement is detected, None otherwise.
            """
            # Find which operations the anchor spans
            anchor_ops = []
            for i, (op_type, op_orig_start, op_orig_end, op_out_start, op_out_end) in enumerate(op_ranges):
                if op_type == 'INSERT':
                    continue  # INSERTs don't consume original positions
                
                # Check if this operation overlaps with the anchor's original range
                if op_orig_start < orig_end and op_orig_end > orig_start:
                    anchor_ops.append((i, op_type, op_orig_start, op_orig_end, op_out_start, op_out_end))
            
            if not anchor_ops:
                return None
            
            # Check if ALL operations are DELETE
            all_delete = all(op[1] == 'DELETE' for op in anchor_ops)
            if not all_delete:
                return None
            
            # Find the last DELETE operation in the anchor
            last_delete_idx = anchor_ops[-1][0]
            last_delete_out_end = anchor_ops[-1][5]
            
            # Check if there's an INSERT immediately following
            if last_delete_idx + 1 < len(op_ranges):
                next_op = op_ranges[last_delete_idx + 1]
                if next_op[0] == 'INSERT':
                    # Found a replacement! Extend anchor to include the INSERT
                    insert_out_end = next_op[4]
                    logger.debug("  Detected replacement: extending anchor end from %d to %d", new_end, insert_out_end)
                    return insert_out_end
            
            return None
        
        # Map each anchor
        result = []
        for anchor in anchors:
            new_start = map_position(anchor['start_offset'])
            new_end = map_position(anchor['end_offset'])
            
            # Ensure end >= start
            if new_end < new_start:
                new_end = new_start
            
            # Check for replacement extension
            extended_end = check_if_entirely_deleted_and_replaced(
                anchor['start_offset'], anchor['end_offset'], new_start, new_end
            )
            if extended_end is not None:
                new_end = extended_end
            
            logger.debug("Comment %s: orig[%d:%d] -> output[%d:%d]",
                         anchor['comment_id'], anchor['start_offset'], anchor['end_offset'], new_start, new_end)
            
            result.append({
                'comment_id': anchor['comment_id'],
                'new_start': new_start,
                'new_end': new_end
            })
        
        return result
    
    def _insert_anchor_markers_at_positions(
        self,
        content_xml: str,
        anchor_positions: List[Dict],
        original_runs: List[Dict]
    ) -> str:
        """
        Insert comment anchor markers at the specified character positions.
        
        This walks through the content XML and inserts markers at run boundaries
        closest to the target positions.
        
        Args:
            content_xml: The generated content XML (runs with track changes)
            anchor_positions: List with 'comment_id', 'new_start', 'new_end'
            original_runs: The original runs with formatting info
            
        Returns:
            Content XML with anchor markers inserted
        """
        if not anchor_positions:
            return content_xml
        
        # Build list of markers to insert: (char_pos, marker_xml, is_end)
        markers = []
        for ap in anchor_positions:
            start_marker = f'<w:commentRangeStart w:id="{ap["comment_id"]}"/>'
            end_marker = f'<w:commentRangeEnd w:id="{ap["comment_id"]}"/>'
            markers.append((ap['new_start'], start_marker, False))
            markers.append((ap['new_end'], end_marker, True))
        
        # Sort: by position, then starts before ends at same position
        markers.sort(key=lambda x: (x[0], x[2]))
        
        # Build result by inserting markers at appropriate positions
        # We need to track character position in the output text
        result_parts = []
        current_char_pos = 0
        marker_idx = 0
        
        # Find all runs in the content and track their text positions
        run_pattern = re.compile(r'(<w:(?:ins|del)[^>]*>)?<w:r[^>]*>.*?</w:r>(</w:(?:ins|del)>)?', re.DOTALL)
        
        last_end = 0
        for match in run_pattern.finditer(content_xml):
            run_xml = match.group(0)
            run_start_in_xml = match.start()
            run_end_in_xml = match.end()
            
            # Extract text length from this run
            # Use a pattern that handles escaped characters in text content
            text_matches = re.findall(r'<w:(?:t|delText)[^>]*>(.*?)</w:(?:t|delText)>', run_xml, re.DOTALL)
            # IMPORTANT: Unescape XML entities to get true character count
            # (the mapping positions are based on plain text, not XML text)
            run_text_len = sum(len(html.unescape(t)) for t in text_matches)
            
            # Check if any markers should be inserted before this run
            pending_markers = []
            while marker_idx < len(markers) and markers[marker_idx][0] <= current_char_pos:
                pending_markers.append(markers[marker_idx][1])
                marker_idx += 1
            
            # Add any content before this run (shouldn't be much)
            result_parts.append(content_xml[last_end:run_start_in_xml])
            
            # Add pending markers
            result_parts.extend(pending_markers)
            
            # Check if any markers should be inserted within this run
            # For simplicity, we insert at the start of the run if the position
            # falls within the run
            in_run_markers = []
            while marker_idx < len(markers) and markers[marker_idx][0] < current_char_pos + run_text_len:
                in_run_markers.append(markers[marker_idx][1])
                marker_idx += 1
            
            if in_run_markers:
                # Insert markers before the run
                result_parts.extend(in_run_markers)
            
            result_parts.append(run_xml)
            current_char_pos += run_text_len
            last_end = run_end_in_xml
        
        # Add any remaining content after the last run
        result_parts.append(content_xml[last_end:])
        
        # Add any remaining markers at the end
        while marker_idx < len(markers):
            result_parts.append(markers[marker_idx][1])
            marker_idx += 1
        
        return ''.join(result_parts)
    
    def _apply_diff_to_paragraph(
        self,
        doc_xml: str,
        para_id: str,
        diff_result,
        author: str,
        timestamp: datetime,
        next_rev_id: int,
        model: Optional['DocumentModel'] = None,
        field_codes: Optional[Dict[str, str]] = None
    ) -> Tuple[str, int]:
        """
        Apply diff-based track changes to a paragraph.
        
        Uses word-level diff to identify what changed, then generates:
        - Regular runs for EQUAL text
        - <w:del> for DELETE operations
        - <w:ins> for INSERT operations
        
        Strategy:
        1. Find the complete paragraph (opening tag to closing tag)
        2. Extract pPr (paragraph properties) - these go at the start
        3. Get comment anchors and map their positions through the diff
        4. Generate diff-based content (with track changes)
        5. Insert comment markers at the mapped positions
        6. Restore field codes (replace placeholders with original XML)
        7. Extract commentReference runs - these go at the end
        8. Rebuild and replace the paragraph
        """
        from src.diff_utils import DiffOperation
        
        # Find the paragraph opening tag
        para_start_pattern = r'<w:p\s[^>]*w14:paraId="' + re.escape(para_id) + r'"[^>]*>'
        start_match = re.search(para_start_pattern, doc_xml)
        if not start_match:
            logger.warning("Could not find paragraph with paraId=%s", para_id)
            return doc_xml, next_rev_id
        
        para_start_pos = start_match.start()
        open_tag = start_match.group(0)
        content_start = start_match.end()
        
        # Check if this is a self-closing paragraph (<w:p ... />)
        # Self-closing paragraphs have no content and no closing tag
        if open_tag.endswith('/>'):
            logger.debug("Paragraph %s is self-closing (empty) - skipping diff application", para_id)
            return doc_xml, next_rev_id
        
        # Find the closing </w:p> tag
        close_pos = doc_xml.find('</w:p>', content_start)
        if close_pos == -1:
            logger.warning("Could not find closing </w:p> for paraId=%s", para_id)
            return doc_xml, next_rev_id
        
        para_content = doc_xml[content_start:close_pos]
        para_end_pos = close_pos + len('</w:p>')
        
        logger.debug("Processing para %s", para_id)
        logger.debug("  Original content length: %d", len(para_content))
        
        # Extract paragraph properties (pPr) - at the start
        pPr_match = re.search(r'<w:pPr[^>]*>.*?</w:pPr>', para_content, re.DOTALL)
        pPr = pPr_match.group(0) if pPr_match else ''
        
        # Get comment anchors from the ORIGINAL XML, not from the model
        # (Model anchors may have been shifted during editing)
        anchors_to_map = self._extract_original_anchors_from_paragraph(para_content)
        for a in anchors_to_map:
            logger.debug("  Found original anchor for comment %s: chars %d-%d", a['comment_id'], a['start_offset'], a['end_offset'])
        
        # Extract commentReference runs - MUST be restrictive to avoid greedy matching
        ref_run_pattern = r'<w:r\b[^>]*>(?:<w:rPr>(?:<[^>]+/>|<[^/][^>]*>[^<]*</[^>]+>)*</w:rPr>)?<w:commentReference[^/]*/></w:r>'
        comment_ref_runs = re.findall(ref_run_pattern, para_content)
        
        logger.debug("  Found: %d anchors to map, %d refRuns", len(anchors_to_map), len(comment_ref_runs))
        
        # Extract original runs with their formatting for preservation
        original_runs = self._extract_runs_with_formatting(para_content)
        logger.debug("  Extracted %d original runs with formatting", len(original_runs))
        
        # Map anchor positions through the diff
        mapped_anchors = self._map_anchor_positions_through_diff(diff_result, anchors_to_map)
        for ma in mapped_anchors:
            logger.debug("  Mapped anchor %s: new chars %d-%d", ma['comment_id'], ma['new_start'], ma['new_end'])
        
        # Generate diff-based content with formatting preservation
        timestamp_str = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        safe_author = html.escape(author)
        rsid = generate_hex_id(set())
        
        # Get revised HTML formatting if available
        revised_html = self._formatting_info.get(para_id, '')
        revised_formatting_segments = self._parse_html_formatting_segments(revised_html) if revised_html else []
        has_revised_formatting = bool(revised_formatting_segments)
        
        if has_revised_formatting:
            logger.debug("  Using revised HTML formatting (%d segments)", len(revised_formatting_segments))
        
        content_parts = []
        original_text_pos = 0  # Track position in original text for formatting lookup
        revised_text_pos = 0  # Track position in revised text for formatting lookup
        
        for op in diff_result.operations:
            if op.op == DiffOperation.EQUAL:
                if field_codes and '[CITATION_' in op.text:
                    # Field code placeholders are longer than their display text,
                    # so we must split to keep original_text_pos aligned with original_runs
                    segments = self._split_text_at_field_code_placeholders(op.text, field_codes)
                    for seg_type, seg_text, orig_advance in segments:
                        if seg_type == 'placeholder':
                            safe_text = html.escape(_sanitize_for_xml(seg_text))
                            content_parts.append(
                                f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                            )
                        elif has_revised_formatting:
                            runs_xml = self._generate_equal_runs_with_formatting(
                                original_runs, seg_text, original_text_pos, revised_text_pos,
                                revised_formatting_segments, rsid, safe_author, timestamp_str, next_rev_id
                            )
                            rPrChange_count = runs_xml.count('<w:rPrChange')
                            next_rev_id += rPrChange_count
                            content_parts.append(runs_xml)
                        else:
                            runs_xml = self._generate_runs_for_text_range(
                                original_runs, seg_text, original_text_pos, rsid, is_delete=False
                            )
                            content_parts.append(runs_xml)
                        original_text_pos += orig_advance
                        revised_text_pos += len(seg_text)
                elif has_revised_formatting:
                    runs_xml = self._generate_equal_runs_with_formatting(
                        original_runs, op.text, original_text_pos, revised_text_pos,
                        revised_formatting_segments, rsid, safe_author, timestamp_str, next_rev_id
                    )
                    rPrChange_count = runs_xml.count('<w:rPrChange')
                    next_rev_id += rPrChange_count
                    content_parts.append(runs_xml)
                    original_text_pos += len(op.text)
                    revised_text_pos += len(op.text)
                else:
                    runs_xml = self._generate_runs_for_text_range(
                        original_runs, op.text, original_text_pos, rsid, is_delete=False
                    )
                    content_parts.append(runs_xml)
                    original_text_pos += len(op.text)
                    revised_text_pos += len(op.text)
                
            elif op.op == DiffOperation.DELETE:
                if field_codes and '[CITATION_' in op.text:
                    segments = self._split_text_at_field_code_placeholders(op.text, field_codes)
                    for seg_type, seg_text, orig_advance in segments:
                        if seg_type == 'placeholder':
                            runs_xml = self._generate_runs_for_text_range(
                                original_runs, seg_text[:orig_advance], original_text_pos, rsid, is_delete=True
                            )
                        else:
                            runs_xml = self._generate_runs_for_text_range(
                                original_runs, seg_text, original_text_pos, rsid, is_delete=True
                            )
                        content_parts.append(
                            f'<w:del w:id="{next_rev_id}" w:author="{safe_author}" w:date="{timestamp_str}">'
                            f'{runs_xml}'
                            f'</w:del>'
                        )
                        next_rev_id += 1
                        original_text_pos += orig_advance
                else:
                    runs_xml = self._generate_runs_for_text_range(
                        original_runs, op.text, original_text_pos, rsid, is_delete=True
                    )
                    content_parts.append(
                        f'<w:del w:id="{next_rev_id}" w:author="{safe_author}" w:date="{timestamp_str}">'
                        f'{runs_xml}'
                        f'</w:del>'
                    )
                    next_rev_id += 1
                    original_text_pos += len(op.text)
                # DELETE doesn't advance revised_text_pos since text is removed
                
            elif op.op == DiffOperation.INSERT:
                # Inserted text - wrap in <w:ins>, apply user's formatting if available
                if has_revised_formatting:
                    # Generate runs with formatting from revised HTML, with rPrChange
                    runs_xml = self._generate_insert_runs_with_formatting(
                        op.text, revised_text_pos, revised_formatting_segments,
                        rsid, safe_author, timestamp_str, next_rev_id
                    )
                    # Count IDs used (both ins and rPrChange)
                    ins_count = runs_xml.count('<w:ins ')
                    rPrChange_count = runs_xml.count('<w:rPrChange')
                    next_rev_id += ins_count + rPrChange_count
                    content_parts.append(runs_xml)
                else:
                    # No formatting info - plain text insert
                    safe_text = html.escape(_sanitize_for_xml(op.text))
                    content_parts.append(
                        f'<w:ins w:id="{next_rev_id}" w:author="{safe_author}" w:date="{timestamp_str}">'
                        f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                        f'</w:ins>'
                    )
                    next_rev_id += 1
                
                revised_text_pos += len(op.text)
                # INSERT doesn't advance original_text_pos since it's new text
        
        # Join content and insert anchor markers at mapped positions
        content_xml = ''.join(content_parts)
        if mapped_anchors:
            content_xml = self._insert_anchor_markers_at_positions(
                content_xml, mapped_anchors, original_runs
            )
        
        # Restore field codes (replace placeholders with original field code XML)
        if field_codes:
            content_xml = self._restore_field_codes(content_xml, field_codes)
        
        # Rebuild paragraph in correct order:
        # 1. pPr (paragraph properties)
        # 2. content with embedded comment markers and restored field codes
        # 3. commentReference runs
        new_para_content = pPr + content_xml + ''.join(comment_ref_runs)
        
        new_para = open_tag + new_para_content + '</w:p>'
        
        logger.debug("  New content length: %d", len(new_para_content))
        logger.debug("  Replacing chars %d-%d (%d chars)", para_start_pos, para_end_pos, para_end_pos - para_start_pos)
        logger.debug("  With new para of %d chars", len(new_para))
        
        result = doc_xml[:para_start_pos] + new_para + doc_xml[para_end_pos:]
        
        logger.debug("  Result length: %d (was %d)", len(result), len(doc_xml))
        
        return result, next_rev_id
    
    def _apply_revisions_to_paragraph(
        self,
        doc_xml: str,
        paragraph: Paragraph,
        revisions: List[Revision]
    ) -> str:
        """
        Apply revisions to a specific paragraph in document.xml.
        
        Uses the diff_utils approach for track changes.
        """
        # Find the paragraph by para_id
        para_pattern = re.compile(
            r'(<w:p\s[^>]*w14:paraId="' + paragraph.para_id + r'"[^>]*>.*?</w:p>)',
            re.DOTALL
        )
        
        match = para_pattern.search(doc_xml)
        if not match:
            return doc_xml
        
        para_xml = match.group(1)
        
        # Sort revisions by position (reverse for safe modification)
        sorted_revisions = sorted(revisions, key=lambda r: r.start_offset, reverse=True)
        
        # Apply each revision
        modified_para = para_xml
        for revision in sorted_revisions:
            modified_para = self._apply_single_revision(modified_para, revision)
        
        return doc_xml[:match.start()] + modified_para + doc_xml[match.end():]
    
    def _apply_single_revision(self, para_xml: str, revision: Revision) -> str:
        """Apply a single revision to paragraph XML."""
        timestamp = revision.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ') if revision.timestamp else datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        safe_author = html.escape(revision.author)
        safe_text = html.escape(_sanitize_for_xml(revision.text))
        
        if revision.revision_type == RevisionType.INSERTION:
            # Create insertion markup
            ins_xml = (
                f'<w:ins w:id="{revision.revision_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'<w:r><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                f'</w:ins>'
            )
            # Insert after finding the position in paragraph runs
            return self._insert_at_offset(para_xml, revision.start_offset, ins_xml)
            
        elif revision.revision_type == RevisionType.DELETION:
            # Create deletion markup
            del_xml = (
                f'<w:del w:id="{revision.revision_id}" w:author="{safe_author}" w:date="{timestamp}">'
                f'<w:r><w:delText xml:space="preserve">{safe_text}</w:delText></w:r>'
                f'</w:del>'
            )
            # Replace text range with deletion markup
            return self._replace_at_offset(
                para_xml, revision.start_offset, revision.end_offset, del_xml, keep_deleted=True
            )
        
        return para_xml
    
    def _insert_at_offset(self, para_xml: str, offset: int, content: str) -> str:
        """Insert content at a character offset in paragraph XML."""
        # Find the run containing the offset
        runs_info = self._analyze_runs(para_xml)
        
        current_offset = 0
        for run_info in runs_info:
            run_end = current_offset + run_info['length']
            if current_offset <= offset < run_end:
                # Insert within this run
                offset_in_run = offset - current_offset
                if offset_in_run == 0:
                    # Insert before this run
                    return para_xml[:run_info['start']] + content + para_xml[run_info['start']:]
                elif offset_in_run == run_info['length']:
                    # Insert after this run
                    return para_xml[:run_info['end']] + content + para_xml[run_info['end']:]
                else:
                    # Split the run and insert
                    return self._split_run_and_insert(para_xml, run_info, offset_in_run, content)
            current_offset = run_end
        
        # Insert at end (before </w:p>)
        p_close = para_xml.rfind('</w:p>')
        if p_close != -1:
            return para_xml[:p_close] + content + para_xml[p_close:]
        return para_xml + content
    
    def _replace_at_offset(
        self,
        para_xml: str,
        start_offset: int,
        end_offset: int,
        content: str,
        keep_deleted: bool = False
    ) -> str:
        """Replace text at offset range in paragraph XML."""
        # For track changes with keep_deleted, we don't actually remove text
        # Instead, we wrap existing text in del markup
        if keep_deleted:
            return self._wrap_range_in_del(para_xml, start_offset, end_offset, content)
        
        # For actual replacement, find and modify runs
        return self._replace_runs_in_range(para_xml, start_offset, end_offset, content)
    
    def _wrap_range_in_del(
        self,
        para_xml: str,
        start_offset: int,
        end_offset: int,
        del_markup: str
    ) -> str:
        """Wrap a character range in deletion markup without removing text."""
        runs_info = self._analyze_runs(para_xml)
        
        # Find runs that overlap with the deletion range
        affected_runs = []
        current_offset = 0
        
        for run_info in runs_info:
            run_end = current_offset + run_info['length']
            if run_end > start_offset and current_offset < end_offset:
                affected_runs.append({
                    **run_info,
                    'text_start': current_offset,
                    'text_end': run_end
                })
            current_offset = run_end
        
        if not affected_runs:
            return para_xml
        
        # Build replacement: use the provided del_markup which already has the deleted text
        # Find the range of XML to replace
        first_run = affected_runs[0]
        last_run = affected_runs[-1]
        xml_start = first_run['start']
        xml_end = last_run['end']
        
        # Extract comment-related elements from the range being replaced
        range_xml = para_xml[xml_start:xml_end]
        preserved_elements = self._extract_comment_elements(range_xml)
        
        return para_xml[:xml_start] + del_markup + preserved_elements + para_xml[xml_end:]
    
    def _extract_comment_elements(self, xml_fragment: str) -> str:
        """
        Extract comment-related elements from an XML fragment.
        
        Preserves:
        - <w:commentRangeStart w:id="X"/>
        - <w:commentRangeEnd w:id="X"/>
        - <w:r>...<w:commentReference w:id="X"/>...</w:r>
        """
        preserved = []
        
        # Extract commentRangeStart elements
        for match in re.finditer(r'<w:commentRangeStart[^>]*/>', xml_fragment):
            preserved.append(match.group(0))
        
        # Extract commentRangeEnd elements
        for match in re.finditer(r'<w:commentRangeEnd[^>]*/>', xml_fragment):
            preserved.append(match.group(0))
        
        # Extract runs containing commentReference
        # Pattern: <w:r ...>...</w:commentReference .../></w:r>
        for match in re.finditer(r'<w:r[^>]*>.*?<w:commentReference[^/]*/></w:r>', xml_fragment, re.DOTALL):
            preserved.append(match.group(0))
        
        return ''.join(preserved)
    
    def _replace_runs_in_range(
        self,
        para_xml: str,
        start_offset: int,
        end_offset: int,
        content: str
    ) -> str:
        """Actually replace runs in a character range."""
        runs_info = self._analyze_runs(para_xml)
        
        if not runs_info:
            return para_xml
        
        # Find XML positions to replace
        affected = []
        current_offset = 0
        
        for run_info in runs_info:
            run_end = current_offset + run_info['length']
            if run_end > start_offset and current_offset < end_offset:
                affected.append({
                    **run_info,
                    'text_start': current_offset,
                    'text_end': run_end
                })
            current_offset = run_end
        
        if not affected:
            return para_xml
        
        first = affected[0]
        last = affected[-1]
        
        return para_xml[:first['start']] + content + para_xml[last['end']:]
    
    def _split_run_and_insert(
        self,
        para_xml: str,
        run_info: Dict,
        offset_in_run: int,
        content: str
    ) -> str:
        """Split a run at ``offset_in_run`` and insert ``content`` between halves.

        Both halves keep the original run opening + ``<w:rPr>`` and a balanced
        ``<w:t>``. If the run has no single ``<w:t>`` (e.g. a field-code run),
        fall back to inserting before the run so the output stays well-formed.
        """
        run_xml = para_xml[run_info['start']:run_info['end']]
        
        # Find the text element
        text_match = re.search(r'(<w:t[^>]*>)(.*?)(</w:t>)', run_xml, re.DOTALL)
        if not text_match:
            return para_xml[:run_info['start']] + content + para_xml[run_info['start']:]
        
        run_open = run_xml[:text_match.start(1)]   # <w:r ...> + <w:rPr>...</w:rPr>
        t_open = self._ensure_space_preserve(text_match.group(1))
        t_close = text_match.group(3)              # </w:t>
        run_tail = run_xml[text_match.end(3):]     # after </w:t>, incl. </w:r>
        
        text_before = text_match.group(2)[:offset_in_run]
        text_after = text_match.group(2)[offset_in_run:]
        
        # Both halves replicate the run opening + rPr; keep <w:t> balanced.
        first_run = run_open + t_open + text_before + t_close + '</w:r>'
        second_run = run_open + t_open + text_after + t_close + run_tail
        
        return (
            para_xml[:run_info['start']] + 
            first_run + content + second_run + 
            para_xml[run_info['end']:]
        )
    
    @staticmethod
    def _ensure_space_preserve(t_open_tag: str) -> str:
        """Ensure a ``<w:t>`` open tag preserves surrounding whitespace."""
        if 'xml:space' in t_open_tag:
            return t_open_tag
        return t_open_tag[:-1] + ' xml:space="preserve">'
    
    def _analyze_runs(self, para_xml: str) -> List[Dict]:
        """
        Analyze runs in paragraph XML to map character offsets to XML positions.
        
        Returns list of dicts: {start, end, length, text}
        """
        runs = []
        
        # Pattern to match runs with text
        run_pattern = re.compile(
            r'<w:r(?:\s[^>]*)?>(.*?)</w:r>',
            re.DOTALL
        )
        
        for match in run_pattern.finditer(para_xml):
            # Extract text from this run (excluding deleted text)
            run_content = match.group(1)
            
            # Get text (not delText)
            text = ''
            for t_match in re.finditer(r'<w:t[^>]*>([^<]*)</w:t>', run_content):
                text += t_match.group(1)
            
            if text:
                runs.append({
                    'start': match.start(),
                    'end': match.end(),
                    'length': len(text),
                    'text': text
                })
        
        return runs
    
    def _extract_all_para_ids(self, doc_xml: str) -> set:
        """
        Extract all paragraph IDs from document XML.
        
        Args:
            doc_xml: The document.xml content
            
        Returns:
            Set of all w14:paraId values found
        """
        para_id_pattern = re.compile(r'w14:paraId="([^"]+)"')
        return set(para_id_pattern.findall(doc_xml))
    
    def _mark_paragraph_as_deleted(
        self,
        doc_xml: str,
        para_id: str,
        author: str,
        timestamp: datetime,
        next_rev_id: int
    ) -> Tuple[str, int]:
        """
        Mark an entire paragraph as deleted by wrapping its content in <w:del>.
        
        This is used when a paragraph exists in the original document but has
        been removed from the model. The paragraph remains in the XML but its
        visible content is wrapped in deletion markup for track changes.
        
        Args:
            doc_xml: The document.xml content
            para_id: ID of the paragraph to mark as deleted
            author: Author name for the revision
            timestamp: Timestamp for the revision
            next_rev_id: Next available revision ID
            
        Returns:
            Tuple of (modified XML, next revision ID to use)
        """
        from datetime import timezone
        
        # Find the paragraph
        para_pattern = re.compile(
            r'(<w:p\s[^>]*w14:paraId="' + re.escape(para_id) + r'"[^>]*>)(.*?)(</w:p>)',
            re.DOTALL
        )
        match = para_pattern.search(doc_xml)
        if not match:
            return doc_xml, next_rev_id
        
        open_tag = match.group(1)
        content = match.group(2)
        close_tag = match.group(3)
        
        # Extract paragraph properties (pPr) - these should NOT be wrapped in del
        pPr_match = re.match(r'(<w:pPr\b.*?</w:pPr>)', content, re.DOTALL)
        pPr = pPr_match.group(1) if pPr_match else ''
        remaining_content = content[len(pPr):] if pPr else content
        
        # Format timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp_str = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        safe_author = html.escape(author)
        rsid = generate_hex_id(set())  # Generate a unique session ID
        
        # Wrap all runs in <w:del>
        # Find all runs and wrap each one
        run_pattern = re.compile(r'(<w:r(?:\s[^>]*)?>)(.*?)(</w:r>)', re.DOTALL)
        
        def wrap_run_in_del(m):
            nonlocal next_rev_id
            run_open = m.group(1)
            run_content = m.group(2)
            run_close = m.group(3)
            
            # Convert <w:t> to <w:delText>
            converted_content = re.sub(
                r'<w:t(\s[^>]*)?>([^<]*)</w:t>',
                r'<w:delText\1>\2</w:delText>',
                run_content
            )
            
            # Add rsidDel attribute to run
            if 'w:rsidDel' not in run_open:
                run_open = run_open.replace('<w:r', f'<w:r w:rsidDel="{rsid}"', 1)
            
            del_xml = (
                f'<w:del w:id="{next_rev_id}" w:author="{safe_author}" w:date="{timestamp_str}">'
                f'{run_open}{converted_content}{run_close}'
                f'</w:del>'
            )
            next_rev_id += 1
            return del_xml
        
        wrapped_content = run_pattern.sub(wrap_run_in_del, remaining_content)
        
        # Reconstruct the paragraph
        new_para = f'{open_tag}{pPr}{wrapped_content}{close_tag}'
        
        # Replace in document
        result = doc_xml[:match.start()] + new_para + doc_xml[match.end():]
        
        logger.debug("Marked paragraph %s as deleted", para_id)
        return result, next_rev_id
    
    def _insert_new_paragraph(
        self,
        doc_xml: str,
        paragraph: 'Paragraph',
        after_para_id: Optional[str],
        before_para_id: Optional[str],
        author: str,
        timestamp: datetime,
        next_rev_id: int
    ) -> Tuple[str, int]:
        """
        Insert a new paragraph into the document XML, wrapped in <w:ins>.
        
        This is used when a paragraph exists in the model but not in the original
        document. The entire paragraph content is marked as inserted.
        
        Args:
            doc_xml: The document.xml content
            paragraph: The Paragraph object to insert
            after_para_id: ID of the paragraph to insert after, or None
            before_para_id: ID of the paragraph to insert before (takes precedence)
            author: Author name for the revision
            timestamp: Timestamp for the revision
            next_rev_id: Next available revision ID
            
        Returns:
            Tuple of (modified XML, next revision ID to use)
        """
        from datetime import timezone
        
        # Format timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp_str = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
        safe_author = html.escape(author)
        rsid = generate_hex_id(set())  # Generate a unique session ID
        
        # Generate the paragraph XML
        para_xml = self._generate_paragraph_xml(
            paragraph, author, timestamp_str, rsid, next_rev_id
        )
        
        # Count how many revision IDs we used
        ins_count = para_xml.count('<w:ins ')
        next_rev_id += ins_count if ins_count > 0 else 1
        
        # Find insertion position
        # before_para_id takes precedence over after_para_id
        if before_para_id:
            # Find the opening tag of the paragraph to insert before
            before_pattern = re.compile(
                r'<w:p\s[^>]*w14:paraId="' + re.escape(before_para_id) + r'"',
                re.DOTALL
            )
            match = before_pattern.search(doc_xml)
            if match:
                insert_pos = match.start()
                logger.debug("Inserting before paragraph %s", before_para_id)
            else:
                # Fallback: insert before first paragraph
                first_para = re.search(r'<w:p\s', doc_xml)
                insert_pos = first_para.start() if first_para else len(doc_xml)
        elif after_para_id:
            # Find the closing tag of the paragraph to insert after
            after_pattern = re.compile(
                r'<w:p\s[^>]*w14:paraId="' + re.escape(after_para_id) + r'"[^>]*>.*?</w:p>',
                re.DOTALL
            )
            match = after_pattern.search(doc_xml)
            if match:
                insert_pos = match.end()
                
                # CRITICAL: Check if this paragraph is inside a table cell (<w:tc>)
                # If so, we need to insert AFTER the entire table, not inside the cell
                # Look backwards from the match to see if we're inside a table
                before_match = doc_xml[:match.start()]
                
                # Count open vs closed table tags before the paragraph
                # If we have more opens than closes, we're inside a table
                table_opens = len(re.findall(r'<w:tbl\b', before_match))
                table_closes = len(re.findall(r'</w:tbl>', before_match))
                
                if table_opens > table_closes:
                    # We're inside a table - find the end of the containing table
                    # and insert after it
                    logger.debug("after_para_id %s is inside a table - adjusting insertion position", after_para_id)
                    
                    # Find the next </w:tbl> after our position
                    remaining = doc_xml[match.end():]
                    
                    # We need to find the matching </w:tbl> for our nesting level
                    nesting = table_opens - table_closes  # Current nesting level
                    pos = 0
                    while nesting > 0 and pos < len(remaining):
                        next_open = remaining.find('<w:tbl', pos)
                        next_close = remaining.find('</w:tbl>', pos)
                        
                        if next_close == -1:
                            # No more closing tags - shouldn't happen in valid XML
                            break
                        
                        if next_open != -1 and next_open < next_close:
                            # Found nested table open before the close
                            nesting += 1
                            pos = next_open + 6
                        else:
                            # Found closing tag
                            nesting -= 1
                            pos = next_close + 8  # len('</w:tbl>')
                            if nesting == 0:
                                # This is our matching close tag
                                insert_pos = match.end() + pos
                                logger.debug("Adjusted insert position to after table")
                                break
            else:
                # Fallback: insert before first paragraph
                first_para = re.search(r'<w:p\s', doc_xml)
                insert_pos = first_para.start() if first_para else len(doc_xml)
        else:
            # Insert before first paragraph
            first_para = re.search(r'<w:p\s', doc_xml)
            insert_pos = first_para.start() if first_para else len(doc_xml)
        
        # Insert the paragraph
        result = doc_xml[:insert_pos] + '\n' + para_xml + doc_xml[insert_pos:]
        
        logger.debug("Inserted new paragraph %s", paragraph.para_id)
        return result, next_rev_id
    
    def _generate_paragraph_xml(
        self,
        paragraph: 'Paragraph',
        author: str,
        timestamp_str: str,
        rsid: str,
        rev_id: int
    ) -> str:
        """
        Generate Word XML for a new paragraph, with content wrapped in <w:ins>.
        
        Args:
            paragraph: The Paragraph object
            author: Author name for the revision
            timestamp_str: ISO formatted timestamp
            rsid: Revision session ID
            rev_id: Revision ID for the insertion
            
        Returns:
            Complete paragraph XML string
        """
        safe_author = html.escape(author)
        
        # Build the content - wrap in <w:ins>
        text = paragraph.plain_text
        
        # Check if paragraph has field codes that need to be restored
        field_codes = paragraph.field_codes if hasattr(paragraph, 'field_codes') and paragraph.field_codes else {}
        
        if field_codes:
            # Generate runs for each segment, restoring field codes
            runs_xml = self._generate_runs_with_field_codes(
                text, field_codes, rsid, rev_id, safe_author, timestamp_str
            )
            
            para_xml = (
                f'<w:p w14:paraId="{paragraph.para_id}" w14:textId="{paragraph.text_id}" '
                f'w:rsidR="{rsid}" w:rsidRDefault="{rsid}">'
                f'{runs_xml}'
                f'</w:p>'
            )
            logger.debug("Generated new paragraph %s with %d field code(s)", paragraph.para_id, len(field_codes))
        else:
            # Simple case: no field codes, just plain text
            safe_text = html.escape(_sanitize_for_xml(text))

            para_xml = (
                f'<w:p w14:paraId="{paragraph.para_id}" w14:textId="{paragraph.text_id}" '
                f'w:rsidR="{rsid}" w:rsidRDefault="{rsid}">'
                f'<w:ins w:id="{rev_id}" w:author="{safe_author}" w:date="{timestamp_str}">'
                f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                f'</w:ins>'
                f'</w:p>'
            )
        
        return para_xml
    
    def _generate_runs_with_field_codes(
        self,
        text: str,
        field_codes: Dict[str, str],
        rsid: str,
        rev_id: int,
        author: str,
        timestamp_str: str
    ) -> str:
        """
        Generate Word runs for text containing field code placeholders.
        
        Splits the text at placeholder positions and generates:
        - <w:ins> wrapped runs for regular text
        - Field code XML (not wrapped in ins) for placeholders
        
        Args:
            text: Plain text possibly containing [CITATION_X] placeholders
            field_codes: Dict mapping placeholder -> field code XML
            rsid: Revision session ID
            rev_id: Starting revision ID
            author: Author name for revisions
            timestamp_str: ISO formatted timestamp
            
        Returns:
            XML string with runs and field codes
        """
        import re
        
        # Find all placeholders and their positions
        placeholder_pattern = re.compile(r'\[CITATION_\d+\]')
        
        result_parts = []
        current_pos = 0
        current_rev_id = rev_id
        
        for match in placeholder_pattern.finditer(text):
            placeholder = match.group()
            start = match.start()
            end = match.end()
            
            # Add text before the placeholder (wrapped in <w:ins>)
            if start > current_pos:
                text_before = text[current_pos:start]
                safe_text = html.escape(_sanitize_for_xml(text_before))
                result_parts.append(
                    f'<w:ins w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp_str}">'
                    f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                    f'</w:ins>'
                )
                current_rev_id += 1
            
            # Add the field code XML (not wrapped in ins - it's preserved content)
            if placeholder in field_codes:
                result_parts.append(field_codes[placeholder])
                logger.debug("Restored field code %s in new paragraph", placeholder)
            else:
                # Placeholder not found in field_codes - keep as text
                safe_text = html.escape(_sanitize_for_xml(placeholder))
                result_parts.append(
                    f'<w:ins w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp_str}">'
                    f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                    f'</w:ins>'
                )
                current_rev_id += 1
            
            current_pos = end
        
        # Add any remaining text after the last placeholder
        if current_pos < len(text):
            text_after = text[current_pos:]
            safe_text = html.escape(_sanitize_for_xml(text_after))
            result_parts.append(
                f'<w:ins w:id="{current_rev_id}" w:author="{author}" w:date="{timestamp_str}">'
                f'<w:r w:rsidR="{rsid}"><w:t xml:space="preserve">{safe_text}</w:t></w:r>'
                f'</w:ins>'
            )
        
        return ''.join(result_parts)
    
    def _find_insertion_position(
        self,
        model: 'DocumentModel',
        para_id: str,
        original_para_ids: set
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Find the insertion position for a new paragraph in the XML.
        
        Returns either:
        - (after_para_id, None): Insert after this paragraph
        - (None, before_para_id): Insert before this paragraph
        - (None, None): Insert at beginning of document
        
        IMPORTANT: We use body-level elements (not iter_paragraphs) to avoid
        confusion with table cell paragraphs. This ensures we find the correct
        position relative to tables, not inside them.
        
        Args:
            model: The DocumentModel
            para_id: ID of the new paragraph we want to insert
            original_para_ids: Set of para_ids that exist in the original document
            
        Returns:
            Tuple of (after_para_id, before_para_id) - one or both may be None
        """
        # Find our paragraph's position in body.elements
        para_elem_index = model.body.get_element_index(para_id)
        if para_elem_index < 0:
            return None, None
        
        # Walk backwards through body-level elements to find insertion position
        # This correctly handles tables as single units, not as individual cells
        for i in range(para_elem_index - 1, -1, -1):
            element = model.body.elements[i]
            
            if hasattr(element, 'para_id'):
                # It's a paragraph
                if element.para_id in original_para_ids:
                    logger.debug("Insert after body-level paragraph %s", element.para_id)
                    return element.para_id, None
            elif hasattr(element, 'rows'):
                # It's a table - we need to insert AFTER the table
                # Find the next original paragraph to insert BEFORE it
                # (inserting before X puts us right after the table)
                for j in range(para_elem_index + 1, len(model.body.elements)):
                    next_elem = model.body.elements[j]
                    if hasattr(next_elem, 'para_id') and next_elem.para_id in original_para_ids:
                        logger.debug("Table before us - insert before paragraph %s", next_elem.para_id)
                        return None, next_elem.para_id
                
                # No original paragraph after us - use the last cell of the table as
                # "after" reference, which will trigger the table-detection logic in
                # _insert_new_paragraph
                last_cell_para = None
                for para in element.iter_paragraphs():
                    last_cell_para = para.para_id
                if last_cell_para:
                    logger.debug("Table before us, no original paragraph after - insert after table via last cell %s", last_cell_para)
                    return last_cell_para, None
                
                # Shouldn't happen, but fall through to continue searching
                logger.debug("Table has no cells, continuing search")
        
        # No suitable position found walking backwards
        # Try to find the NEXT original paragraph to insert BEFORE
        for i in range(para_elem_index + 1, len(model.body.elements)):
            element = model.body.elements[i]
            if hasattr(element, 'para_id') and element.para_id in original_para_ids:
                logger.debug("No element before us - insert before %s", element.para_id)
                return None, element.para_id
        
        return None, None
