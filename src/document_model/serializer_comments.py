"""Comment XML serialization and anchor handling."""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

from .comments import Comment
from .model import DocumentModel
from .utils import generate_hex_id

from .serializer_common import _sanitize_for_xml

class SerializerCommentsMixin:
    """Mixin providing serializer methods."""

    def _compute_removed_comments(self, zin, model: DocumentModel) -> None:
        """
        Determine which comments were removed since the source DOCX was loaded.

        A comment counts as removed when it appears in the source
        ``comments.xml`` but no longer exists in ``model.comments``. We resolve
        each removed comment's own paragraph id (from comments.xml) and durable
        id (from commentsIds.xml) so every comment part can strip its entries:

        - comments.xml / document.xml anchors key on the comment id
        - commentsExtended.xml / commentsIds.xml key on the comment's paraId
        - commentsExtensible.xml keys on the durableId

        Results are stored on ``self._removed_comment_ids`` /
        ``self._removed_para_ids`` / ``self._removed_durable_ids``.
        """
        self._removed_comment_ids = set()
        self._removed_para_ids = set()
        self._removed_durable_ids = set()

        names = zin.namelist()
        if 'word/comments.xml' not in names:
            return

        comments_xml = zin.read('word/comments.xml').decode('utf-8')

        # comment_id -> the comment's own paragraph id (first w14:paraId inside
        # each <w:comment> block).
        id_to_para: Dict[str, str] = {}
        for match in re.finditer(
            r'<w:comment\s+w:id="([^"]+)"[^>]*>.*?<w:p\s[^>]*w14:paraId="([^"]+)"',
            comments_xml,
            re.DOTALL,
        ):
            id_to_para[match.group(1)] = match.group(2)

        original_ids = set(id_to_para.keys())
        model_ids = set(model.comments.comments.keys())
        self._removed_comment_ids = original_ids - model_ids
        self._removed_para_ids = {
            id_to_para[cid] for cid in self._removed_comment_ids if cid in id_to_para
        }

        if 'word/commentsIds.xml' in names:
            ids_xml = zin.read('word/commentsIds.xml').decode('utf-8')
            para_to_durable: Dict[str, str] = {}
            for match in re.finditer(
                r'w16cid:paraId="([^"]+)"\s+w16cid:durableId="([^"]+)"',
                ids_xml,
            ):
                para_to_durable[match.group(1)] = match.group(2)
            self._removed_durable_ids = {
                para_to_durable[pid]
                for pid in self._removed_para_ids
                if pid in para_to_durable
            }

    def _strip_comment_blocks(self, xml: str) -> str:
        """Remove <w:comment> blocks for removed comment ids from comments.xml."""
        for cid in self._removed_comment_ids:
            xml = re.sub(
                r'<w:comment\s+w:id="' + re.escape(cid) + r'"[^>]*>.*?</w:comment>\s*',
                '',
                xml,
                flags=re.DOTALL,
            )
        return xml

    def _strip_part_entries(self, xml: str, attr: str, values: set) -> str:
        """Remove self-closing elements whose ``attr`` matches a removed value."""
        for value in values:
            xml = re.sub(
                r'<[^<>]*\s' + re.escape(attr) + r'="' + re.escape(value) + r'"[^<>]*/>\s*',
                '',
                xml,
            )
        return xml

    def _serialize_comments_xml(self, model: DocumentModel, original_xml: str) -> str:
        """
        Generate/update comments.xml from model.
        
        CRITICAL: Word displays replies in the order they appear in this file,
        so new replies must be inserted after existing thread entries for proper display.
        """
        closing_tag = '</w:comments>'
        if closing_tag not in original_xml:
            return original_xml
        
        # Strip comments removed from the model before adding new ones.
        original_xml = self._strip_comment_blocks(original_xml)
        
        # Get existing comment IDs
        existing_ids = self._extract_existing_comment_ids(original_xml)
        
        modified_xml = original_xml
        
        for thread in model.comments.threads.values():
            # Add root if new
            if thread.root.comment_id not in existing_ids:
                new_entry = self._build_comment_element(thread.root)
                insert_pos = modified_xml.rfind(closing_tag)
                modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                existing_ids.add(thread.root.comment_id)
            
            # Add new replies after existing thread entries
            for reply in thread.replies:
                if reply.comment_id not in existing_ids:
                    new_entry = self._build_comment_element(reply)
                    
                    # Find last entry for this thread by looking for existing comment IDs
                    # Comments in comments.xml are identified by w:id attribute
                    last_match = None
                    
                    # Check root's comment in the file
                    root_pattern = re.compile(
                        r'<w:comment\s+w:id="' + re.escape(thread.root.comment_id) + r'"[^>]*>.*?</w:comment>',
                        re.DOTALL
                    )
                    for match in root_pattern.finditer(modified_xml):
                        last_match = match
                    
                    # Check existing replies
                    for existing_reply in thread.replies:
                        if existing_reply.comment_id in existing_ids:
                            reply_pattern = re.compile(
                                r'<w:comment\s+w:id="' + re.escape(existing_reply.comment_id) + r'"[^>]*>.*?</w:comment>',
                                re.DOTALL
                            )
                            for match in reply_pattern.finditer(modified_xml):
                                if last_match is None or match.end() > last_match.end():
                                    last_match = match
                    
                    if last_match:
                        insert_pos = last_match.end()
                        modified_xml = modified_xml[:insert_pos] + '\n' + new_entry + modified_xml[insert_pos:]
                    else:
                        insert_pos = modified_xml.rfind(closing_tag)
                        modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                    
                    existing_ids.add(reply.comment_id)
        
        return modified_xml
    
    def _serialize_comments_extended_xml(self, model: DocumentModel, original_xml: str) -> str:
        """
        Generate/update commentsExtended.xml with threading relationships.
        
        Threading: replies have w15:paraIdParent pointing to root comment's paraId.
        CRITICAL: Word displays replies in the order they appear in the file, so new
        replies must be inserted right after existing thread entries, not at the end.
        """
        closing_tag = '</w15:commentsEx>'
        if closing_tag not in original_xml:
            return original_xml
        
        # Strip entries for removed comments (keyed on the comment's paraId).
        original_xml = self._strip_part_entries(
            original_xml, 'w15:paraId', self._removed_para_ids
        )
        
        # Get existing para IDs
        existing_para_ids = self._extract_existing_para_ids_from_extended(original_xml)
        
        modified_xml = original_xml
        
        for thread in model.comments.threads.values():
            # Add root if new (at end, since it's a new thread)
            if thread.root.para_id not in existing_para_ids:
                new_entry = self._build_comment_ex_element(thread.root)
                insert_pos = modified_xml.rfind(closing_tag)
                modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                existing_para_ids.add(thread.root.para_id)
            
            # Add new replies - insert after the last existing entry for this thread
            for reply in thread.replies:
                if reply.para_id not in existing_para_ids:
                    new_entry = self._build_comment_ex_element(reply)
                    
                    # Find insertion position: after the last existing entry for this thread
                    # Look for entries with this thread's root para_id as parent
                    root_para_id = thread.root.para_id
                    
                    # Find all existing entries for this thread (root or replies with paraIdParent=root)
                    thread_entry_pattern = re.compile(
                        r'<w15:commentEx\s+[^>]*w15:paraId="' + re.escape(root_para_id) + r'"[^>]*/>' +
                        r'|<w15:commentEx\s+[^>]*w15:paraIdParent="' + re.escape(root_para_id) + r'"[^>]*/>'
                    )
                    
                    last_match = None
                    match_count = 0
                    for match in thread_entry_pattern.finditer(modified_xml):
                        match_count += 1
                        last_match = match
                    
                    logger.debug("Thread %s: found %d existing entries for inserting reply %s", root_para_id, match_count, reply.para_id)
                    
                    if last_match:
                        # Insert after the last thread entry
                        insert_pos = last_match.end()
                        logger.debug("  Last match: %s...", last_match.group(0)[:80])
                        logger.debug("  Inserting at position %d", insert_pos)
                        modified_xml = modified_xml[:insert_pos] + '\n' + new_entry + modified_xml[insert_pos:]
                    else:
                        # Fallback: insert before closing tag
                        insert_pos = modified_xml.rfind(closing_tag)
                        logger.debug("  No match found, inserting at end (position %d)", insert_pos)
                        modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                    
                    existing_para_ids.add(reply.para_id)
        
        return modified_xml
    
    def _serialize_comments_ids_xml(self, model: DocumentModel, original_xml: str) -> str:
        """
        Generate/update commentsIds.xml with durable IDs.
        
        CRITICAL: Must maintain same order as commentsExtended.xml - new replies
        must be inserted after existing thread entries for proper Word display.
        """
        closing_tag = '</w16cid:commentsIds>'
        if closing_tag not in original_xml:
            return original_xml
        
        # Strip entries for removed comments (keyed on the comment's paraId).
        original_xml = self._strip_part_entries(
            original_xml, 'w16cid:paraId', self._removed_para_ids
        )
        
        # Get existing para IDs
        existing_para_ids = self._extract_existing_para_ids_from_ids(original_xml)
        
        modified_xml = original_xml
        
        for thread in model.comments.threads.values():
            # Add root if new
            if thread.root.para_id not in existing_para_ids:
                new_entry = self._build_comment_id_element(thread.root)
                insert_pos = modified_xml.rfind(closing_tag)
                modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                existing_para_ids.add(thread.root.para_id)
            
            # Add new replies after existing thread entries
            for reply in thread.replies:
                if reply.para_id not in existing_para_ids:
                    new_entry = self._build_comment_id_element(reply)
                    
                    root_para_id = thread.root.para_id
                    
                    # Find last entry for this thread (entries use paraId attribute)
                    thread_entry_pattern = re.compile(
                        r'<w16cid:commentId\s+[^>]*w16cid:paraId="(' + re.escape(root_para_id) + r')"[^>]*/>'
                    )
                    
                    # Also find replies (need to search by para_id of existing replies)
                    last_match = None
                    for existing_reply in thread.replies:
                        if existing_reply.para_id in existing_para_ids:
                            reply_pattern = re.compile(
                                r'<w16cid:commentId\s+[^>]*w16cid:paraId="' + re.escape(existing_reply.para_id) + r'"[^>]*/>'
                            )
                            for match in reply_pattern.finditer(modified_xml):
                                last_match = match
                    
                    # Also check the root
                    for match in thread_entry_pattern.finditer(modified_xml):
                        if last_match is None or match.end() > last_match.end():
                            last_match = match
                    
                    if last_match:
                        insert_pos = last_match.end()
                        modified_xml = modified_xml[:insert_pos] + '\n' + new_entry + modified_xml[insert_pos:]
                    else:
                        insert_pos = modified_xml.rfind(closing_tag)
                        modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                    
                    existing_para_ids.add(reply.para_id)
        
        return modified_xml
    
    def _serialize_comments_extensible_xml(
        self, model: DocumentModel, original_xml: str, comments_ids_xml: str = ''
    ) -> str:
        """
        Generate/update commentsExtensible.xml with UTC timestamps.
        
        CRITICAL: Must maintain same order as commentsIds.xml - new replies
        must be inserted after existing thread entries for proper Word display.
        
        Args:
            model: The DocumentModel
            original_xml: Original commentsExtensible.xml content
            comments_ids_xml: Original commentsIds.xml content (for para_id→durable_id mapping)
        """
        closing_tag = '</w16cex:commentsExtensible>'
        if closing_tag not in original_xml:
            return original_xml
        
        # Strip entries for removed comments (keyed on durableId, which may be
        # wrapped in curly braces in this part).
        if self._removed_durable_ids:
            durable_variants = set(self._removed_durable_ids)
            durable_variants |= {'{' + d + '}' for d in self._removed_durable_ids}
            original_xml = self._strip_part_entries(
                original_xml, 'w16cex:durableId', durable_variants
            )
        
        # Build para_id → durable_id mapping from commentsIds.xml
        para_id_to_durable_id: Dict[str, str] = {}
        if comments_ids_xml:
            for match in re.finditer(
                r'w16cid:paraId="([^"]+)"\s+w16cid:durableId="([^"]+)"',
                comments_ids_xml
            ):
                para_id_to_durable_id[match.group(1)] = match.group(2)
        
        # Get existing durable IDs
        existing_durable_ids = self._extract_existing_durable_ids_from_extensible(original_xml)
        
        modified_xml = original_xml
        
        for thread in model.comments.threads.values():
            # Add root if new (check by para_id via mapping)
            root_durable = thread.root.durable_id or para_id_to_durable_id.get(thread.root.para_id)
            if root_durable and root_durable not in existing_durable_ids:
                new_entry = self._build_comment_extensible_element(thread.root)
                insert_pos = modified_xml.rfind(closing_tag)
                modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                existing_durable_ids.add(root_durable)
            
            # Add new replies after existing thread entries
            for reply in thread.replies:
                reply_durable = reply.durable_id or para_id_to_durable_id.get(reply.para_id)
                if reply_durable and reply_durable not in existing_durable_ids:
                    new_entry = self._build_comment_extensible_element(reply)
                    
                    # Find last entry for this thread by looking for existing durable IDs (via para_id mapping)
                    last_match = None
                    match_count = 0
                    
                    # Collect all durable IDs for this thread (root + existing replies)
                    thread_durable_ids = []
                    root_d = thread.root.durable_id or para_id_to_durable_id.get(thread.root.para_id)
                    if root_d and root_d in existing_durable_ids:
                        thread_durable_ids.append(root_d)
                    
                    for existing_reply in thread.replies:
                        existing_d = existing_reply.durable_id or para_id_to_durable_id.get(existing_reply.para_id)
                        if existing_d and existing_d in existing_durable_ids:
                            thread_durable_ids.append(existing_d)
                    
                    # Find the last occurrence of any thread durable ID
                    for durable_id in thread_durable_ids:
                        pattern = re.compile(
                            r'<w16cex:commentExtensible\s+[^>]*w16cex:durableId="' + re.escape(durable_id) + r'"[^>]*/>'
                        )
                        for match in pattern.finditer(modified_xml):
                            if last_match is None or match.end() > last_match.end():
                                last_match = match
                                match_count += 1
                    
                    logger.debug("Extended thread %s: found %d entries for reply para_id=%s", thread.root.para_id, match_count, reply.para_id)
                    
                    if last_match:
                        insert_pos = last_match.end()
                        logger.debug("  Inserting at position %d", insert_pos)
                        modified_xml = modified_xml[:insert_pos] + '\n' + new_entry + modified_xml[insert_pos:]
                    else:
                        insert_pos = modified_xml.rfind(closing_tag)
                        logger.debug("  No match found, inserting at end")
                        modified_xml = modified_xml[:insert_pos] + new_entry + '\n' + modified_xml[insert_pos:]
                    
                    existing_durable_ids.add(reply_durable)
        
        return modified_xml
    
    def _serialize_comment_anchors(self, model: DocumentModel, doc_xml: str) -> str:
        """
        Insert/update comment anchors in document.xml.
        
        For ROOT comments with anchors, ensure:
        - <w:commentRangeStart w:id="X"/>
        - ... text ...
        - <w:commentRangeEnd w:id="X"/>
        - <w:r><w:commentReference w:id="X"/></w:r>
        
        For REPLY comments, Word expects anchors at the same location as parent,
        with order matching the comment order in comments.xml.
        NEW replies must be inserted AFTER the last existing reply anchor.
        """
        modified_xml = doc_xml
        
        # 1. Strip anchors for removed comments.
        modified_xml = self._strip_removed_anchors(modified_xml)
        
        # 2. Inject anchors for NEW root comments (added via add_comment_at).
        #    Reply anchors are handled by the loop below; a brand-new single
        #    comment thread has no replies, so it is handled here.
        for thread_id, thread in model.comments.threads.items():
            root = thread.root
            if root.anchor is None:
                continue
            if self._anchor_exists(modified_xml, root.comment_id):
                continue
            modified_xml = self._inject_root_anchor(modified_xml, root)
        
        # 3. Process each thread to find new replies that need anchors
        for thread_id, thread in model.comments.threads.items():
            # Skip if no replies
            if not thread.replies:
                continue
            
            # Get the root comment's ID (for finding parent anchors)
            root_comment = thread.root
            root_comment_id = root_comment.comment_id
            
            # Process each reply
            for reply in thread.replies:
                reply_comment_id = reply.comment_id
                
                # Check if this reply already has anchors
                if self._anchor_exists(modified_xml, reply_comment_id):
                    continue
                
                # Find the LAST existing anchor for this thread (root or existing replies)
                # to insert the new anchor AFTER it
                last_anchor_id = root_comment_id
                for existing_reply in thread.replies:
                    if existing_reply.comment_id != reply_comment_id:
                        if self._anchor_exists(modified_xml, existing_reply.comment_id):
                            last_anchor_id = existing_reply.comment_id
                
                # Add anchors for this reply after the LAST existing anchor
                rsid = generate_hex_id(set())
                
                # 1. Add commentRangeStart after last existing anchor's commentRangeStart
                last_range_start = f'<w:commentRangeStart w:id="{last_anchor_id}"/>'
                new_range_start = f'<w:commentRangeStart w:id="{reply_comment_id}"/>'
                
                if last_range_start in modified_xml:
                    modified_xml = modified_xml.replace(
                        last_range_start,
                        last_range_start + new_range_start
                    )
                
                # 2. Add commentRangeEnd and commentReference after last existing anchor's
                last_ref_pattern = f'<w:commentReference w:id="{last_anchor_id}"/>'
                new_range_end = f'<w:commentRangeEnd w:id="{reply_comment_id}"/>'
                new_ref = (
                    f'<w:r w:rsidR="{rsid}">'
                    f'<w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
                    f'<w:commentReference w:id="{reply_comment_id}"/>'
                    f'</w:r>'
                )
                
                # Find the closing </w:r> after last anchor's commentReference
                if last_ref_pattern in modified_xml:
                    ref_idx = modified_xml.find(last_ref_pattern)
                    close_r_idx = modified_xml.find('</w:r>', ref_idx)
                    if close_r_idx > 0:
                        insert_pos = close_r_idx + len('</w:r>')
                        modified_xml = (
                            modified_xml[:insert_pos] + 
                            new_range_end + new_ref + 
                            modified_xml[insert_pos:]
                        )
                
                logger.debug("Added anchors for reply %s after %s", reply_comment_id, last_anchor_id)
        
        return modified_xml
    
    def _anchor_exists(self, doc_xml: str, comment_id: str) -> bool:
        """Check if a comment anchor already exists in the document."""
        pattern = f'w:id="{comment_id}"'
        return pattern in doc_xml
    
    def _strip_removed_anchors(self, doc_xml: str) -> str:
        """
        Remove commentRangeStart/End markers and the commentReference run for
        every removed comment id from document.xml.
        """
        for cid in self._removed_comment_ids:
            doc_xml = re.sub(
                r'<w:commentRangeStart\s+w:id="' + re.escape(cid) + r'"\s*/>',
                '',
                doc_xml,
            )
            doc_xml = re.sub(
                r'<w:commentRangeEnd\s+w:id="' + re.escape(cid) + r'"\s*/>',
                '',
                doc_xml,
            )
            # The reference run: a <w:r> whose only meaningful child is the
            # commentReference for this id. Remove the whole run.
            doc_xml = re.sub(
                r'<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:commentReference\s+w:id="'
                + re.escape(cid)
                + r'"\s*/>(?:(?!</w:r>).)*?</w:r>',
                '',
                doc_xml,
                flags=re.DOTALL,
            )
        return doc_xml
    
    def _inject_root_anchor(self, doc_xml: str, root: Comment) -> str:
        """
        Insert anchors for a new root comment into its target paragraph.

        Places the highlight on the precise [start, end) character range that
        ``add_comment_at`` recorded, reusing the revisions mixin's offset→run
        machinery (``_insert_at_offset`` → ``_split_run_and_insert``). The end
        marker is inserted first (so the start offset stays valid), then the
        start marker — neither marker contributes displayed text, so the offset
        map is unperturbed between the two inserts.

        Known risk area: paragraphs containing field codes/citations, where the
        displayed-text offset model and the run/instrText structure can diverge.
        This is exercised explicitly by the M2 tests.
        """
        anchor = root.anchor
        cid = root.comment_id
        target_para_id = anchor.para_id
        
        para_pattern = re.compile(
            r'<w:p\s[^>]*w14:paraId="' + re.escape(target_para_id) + r'"[^>]*>.*?</w:p>',
            re.DOTALL,
        )
        match = para_pattern.search(doc_xml)
        if not match:
            logger.warning(
                "Cannot inject anchor for comment %s: paragraph %s not found",
                cid, target_para_id,
            )
            return doc_xml
        
        para_xml = match.group(0)
        rsid = generate_hex_id(set())
        range_start = f'<w:commentRangeStart w:id="{cid}"/>'
        range_end = f'<w:commentRangeEnd w:id="{cid}"/>'
        ref_run = (
            f'<w:r w:rsidR="{rsid}">'
            f'<w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>'
            f'<w:commentReference w:id="{cid}"/>'
            f'</w:r>'
        )
        
        new_para = self._insert_at_offset(para_xml, anchor.end_offset, range_end + ref_run)
        new_para = self._insert_at_offset(new_para, anchor.start_offset, range_start)
        
        return doc_xml[:match.start()] + new_para + doc_xml[match.end():]
    
    # =========================================================================
    # Helper methods for building XML elements
    # =========================================================================
    
    def _build_comment_element(self, comment: Comment) -> str:
        """Build a <w:comment> element for comments.xml.
        
        Generates proper Word comment structure with:
        - rsidR/rsidRDefault attributes on paragraph
        - CommentText paragraph style
        - CommentReference style and annotationRef element
        - Text content
        """
        safe_author = html.escape(comment.author)
        safe_initials = html.escape(comment.author_initials)
        safe_text = html.escape(_sanitize_for_xml(comment.text))
        rsid = generate_hex_id(set())
        
        date_str = ''
        if comment.date:
            date_str = comment.date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        return (
            f'<w:comment w:id="{comment.comment_id}" '
            f'w:author="{safe_author}" '
            f'w:date="{date_str}" '
            f'w:initials="{safe_initials}">'
            f'<w:p w14:paraId="{comment.para_id}" w14:textId="{comment.text_id}" '
            f'w:rsidR="{rsid}" w:rsidRDefault="{rsid}">'
            f'<w:pPr><w:pStyle w:val="CommentText"/></w:pPr>'
            f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:annotationRef/></w:r>'
            f'<w:r><w:t>{safe_text}</w:t></w:r>'
            f'</w:p>'
            f'</w:comment>'
        )
    
    def _build_comment_ex_element(self, comment: Comment) -> str:
        """Build a <w15:commentEx> element for commentsExtended.xml."""
        done = '1' if comment.is_resolved else '0'
        
        if comment.parent_para_id:
            return (
                f'<w15:commentEx w15:paraId="{comment.para_id}" '
                f'w15:paraIdParent="{comment.parent_para_id}" '
                f'w15:done="{done}"/>'
            )
        else:
            return (
                f'<w15:commentEx w15:paraId="{comment.para_id}" '
                f'w15:done="{done}"/>'
            )
    
    def _build_comment_id_element(self, comment: Comment) -> str:
        """Build a <w16cid:commentId> element for commentsIds.xml."""
        return (
            f'<w16cid:commentId w16cid:paraId="{comment.para_id}" '
            f'w16cid:durableId="{comment.durable_id}"/>'
        )
    
    def _build_comment_extensible_element(self, comment: Comment) -> str:
        """Build a <w16cex:commentExtensible> element for commentsExtensible.xml."""
        date_utc = ''
        if comment.date_utc:
            date_utc = comment.date_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        elif comment.date:
            date_utc = comment.date.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        return (
            f'<w16cex:commentExtensible w16cex:durableId="{comment.durable_id}" '
            f'w16cex:dateUtc="{date_utc}"/>'
        )
    
    # =========================================================================
    # Helper methods for extracting existing IDs
    # =========================================================================
    
    def _extract_existing_comment_ids(self, xml_content: str) -> Set[str]:
        """Extract existing comment IDs from comments.xml."""
        ids = set()
        for match in re.finditer(r'w:id="(\d+)"', xml_content):
            ids.add(match.group(1))
        return ids
    
    def _extract_existing_para_ids_from_extended(self, xml_content: str) -> Set[str]:
        """Extract existing paraIds from commentsExtended.xml."""
        ids = set()
        for match in re.finditer(r'w15:paraId="([^"]+)"', xml_content):
            ids.add(match.group(1))
        return ids
    
    def _extract_existing_para_ids_from_ids(self, xml_content: str) -> Set[str]:
        """Extract existing paraIds from commentsIds.xml."""
        ids = set()
        for match in re.finditer(r'w16cid:paraId="([^"]+)"', xml_content):
            ids.add(match.group(1))
        return ids
    
    def _extract_existing_durable_ids_from_extensible(self, xml_content: str) -> Set[str]:
        """Extract existing durableIds from commentsExtensible.xml."""
        ids = set()
        # Handle both formats: with and without curly braces
        for match in re.finditer(r'w16cex:durableId="([^"]+)"', xml_content):
            durable_id = match.group(1)
            # Strip curly braces if present
            if durable_id.startswith('{') and durable_id.endswith('}'):
                durable_id = durable_id[1:-1]
            ids.add(durable_id)
        return ids
    
