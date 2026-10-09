#!/usr/bin/env python3
"""
Reply Diagnostic Tool - Analyze DOCX XML for reply insertion issues.

This script examines all relevant XML files within a DOCX archive to help
diagnose why some replies appear as standalone comments in Word.

The script examines:
- word/comments.xml - Comment content and structure
- word/commentsExtended.xml - Parent-child relationships (paraIdParent)
- word/commentsExtensible.xml - Additional comment metadata
- word/commentsIds.xml - Comment ID mappings
- word/document.xml - Comment anchors (commentRangeStart/End)
- word/people.xml - Author information

Usage:
    python scripts/diagnose_replies.py path/to/document.docx
    python scripts/diagnose_replies.py path/to/document.docx --thread 5
    python scripts/diagnose_replies.py path/to/document.docx --export
"""

import argparse
import json
import sys
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.comment_extractor import CommentExtractor


# =============================================================================
# XML NAMESPACES
# =============================================================================

NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'w16cid': 'http://schemas.microsoft.com/office/word/2016/wordml/cid',
    'w16cex': 'http://schemas.microsoft.com/office/word/2018/wordml/cex',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
}

# Namespace URI prefixes
NS_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NS_W14 = '{http://schemas.microsoft.com/office/word/2010/wordml}'
NS_W15 = '{http://schemas.microsoft.com/office/word/2012/wordml}'
NS_W16CID = '{http://schemas.microsoft.com/office/word/2016/wordml/cid}'


# =============================================================================
# XML EXTRACTION
# =============================================================================

def extract_xml_file(zf: zipfile.ZipFile, filepath: str) -> Optional[str]:
    """Extract and return XML file content as string."""
    try:
        if filepath in zf.namelist():
            return zf.read(filepath).decode('utf-8')
    except Exception as e:
        print(f"  Error reading {filepath}: {e}")
    return None


def parse_comments_xml(xml_content: str) -> Dict[str, Any]:
    """Parse word/comments.xml to extract comment data."""
    comments = {}
    
    try:
        root = ET.fromstring(xml_content)
        
        for comment in root.iter():
            if comment.tag.endswith('}comment'):
                comment_id = None
                author = None
                date = None
                para_ids = []  # Collect all para_ids within the comment
                
                for key, val in comment.attrib.items():
                    if key.endswith('}id'):
                        comment_id = val
                    elif key.endswith('}author'):
                        author = val
                    elif key.endswith('}date'):
                        date = val
                
                # Find para_ids within the comment's paragraphs
                # Each <w:p> inside the comment may have a w14:paraId attribute
                for child in comment.iter():
                    for key, val in child.attrib.items():
                        if key.endswith('}paraId'):
                            para_ids.append(val)
                
                if comment_id:
                    # Extract text
                    text_parts = []
                    for t in comment.iter():
                        if t.tag.endswith('}t') and t.text:
                            text_parts.append(t.text)
                    
                    # Use the last para_id as the linking para_id
                    # (this is typically the one used in commentsExtended.xml)
                    para_id = para_ids[-1] if para_ids else None
                    
                    comments[comment_id] = {
                        "id": comment_id,
                        "para_id": para_id,
                        "all_para_ids": para_ids,
                        "author": author,
                        "date": date,
                        "text": " ".join(text_parts),
                    }
    except Exception as e:
        print(f"  Error parsing comments.xml: {e}")
    
    return comments


def parse_comments_extended(xml_content: str) -> Dict[str, Dict]:
    """Parse word/commentsExtended.xml for parent-child relationships."""
    extended = {}
    
    try:
        root = ET.fromstring(xml_content)
        
        for elem in root.iter():
            if elem.tag.endswith('}commentEx'):
                para_id = None
                parent_para_id = None
                done = None
                
                for key, val in elem.attrib.items():
                    if key.endswith('}paraId'):
                        para_id = val
                    elif key.endswith('}paraIdParent'):
                        parent_para_id = val
                    elif key.endswith('}done'):
                        done = val
                
                if para_id:
                    extended[para_id] = {
                        "para_id": para_id,
                        "parent_para_id": parent_para_id,
                        "done": done == "1",
                    }
    except Exception as e:
        print(f"  Error parsing commentsExtended.xml: {e}")
    
    return extended


def parse_document_anchors(xml_content: str) -> Dict[str, Dict]:
    """Parse word/document.xml for comment anchors."""
    anchors = defaultdict(lambda: {"range_start": False, "range_end": False, "reference": False})
    
    try:
        root = ET.fromstring(xml_content)
        
        for elem in root.iter():
            comment_id = None
            for key, val in elem.attrib.items():
                if key.endswith('}id'):
                    comment_id = val
                    break
            
            if comment_id:
                if elem.tag.endswith('}commentRangeStart'):
                    anchors[comment_id]["range_start"] = True
                elif elem.tag.endswith('}commentRangeEnd'):
                    anchors[comment_id]["range_end"] = True
                elif elem.tag.endswith('}commentReference'):
                    anchors[comment_id]["reference"] = True
    except Exception as e:
        print(f"  Error parsing document.xml: {e}")
    
    return dict(anchors)


def parse_comments_ids(xml_content: str) -> Dict[str, str]:
    """Parse word/commentsIds.xml for ID mappings."""
    id_map = {}
    
    try:
        root = ET.fromstring(xml_content)
        
        for elem in root.iter():
            if elem.tag.endswith('}commentId'):
                para_id = None
                dur_id = None
                
                for key, val in elem.attrib.items():
                    if key.endswith('}paraId'):
                        para_id = val
                    elif key.endswith('}durableId'):
                        dur_id = val
                
                if para_id and dur_id:
                    id_map[para_id] = dur_id
    except Exception as e:
        print(f"  Error parsing commentsIds.xml: {e}")
    
    return id_map


def parse_people(xml_content: str) -> Dict[str, str]:
    """Parse word/people.xml for author information."""
    people = {}
    
    try:
        root = ET.fromstring(xml_content)
        
        for elem in root.iter():
            if elem.tag.endswith('}person'):
                author = None
                for key, val in elem.attrib.items():
                    if key.endswith('}author'):
                        author = val
                        break
                
                provider_id = None
                for child in elem:
                    if child.tag.endswith('}presenceInfo'):
                        for key, val in child.attrib.items():
                            if key.endswith('}providerId'):
                                provider_id = val
                                break
                
                if author:
                    people[author] = provider_id or "unknown"
    except Exception as e:
        print(f"  Error parsing people.xml: {e}")
    
    return people


# =============================================================================
# ANALYSIS
# =============================================================================

def build_thread_tree(
    comments: Dict, 
    extended: Dict
) -> Dict[str, List[Dict]]:
    """Build thread tree from comments and extended data."""
    # Map para_id to comment
    para_to_comment = {}
    for cid, comment in comments.items():
        if comment.get("para_id"):
            para_to_comment[comment["para_id"]] = comment
    
    # Get set of all para_ids that have parents (i.e., are replies)
    reply_para_ids = set()
    parent_mapping = {}  # para_id -> parent_para_id
    
    for para_id, ext_data in extended.items():
        parent_para_id = ext_data.get("parent_para_id")
        if parent_para_id:
            reply_para_ids.add(para_id)
            parent_mapping[para_id] = parent_para_id
    
    # Find root comments (those not in reply_para_ids)
    roots = []
    for para_id, comment in para_to_comment.items():
        if para_id not in reply_para_ids:
            roots.append({
                **comment,
                "is_reply": False,
            })
    
    # Also include comments that have no entry in extended.xml at all
    # (older Word documents might not have all comments in extended)
    extended_para_ids = set(extended.keys())
    for para_id, comment in para_to_comment.items():
        if para_id not in extended_para_ids and para_id not in reply_para_ids:
            if not any(r.get("para_id") == para_id for r in roots):
                roots.append({
                    **comment,
                    "is_reply": False,
                })
    
    # Build threads - find replies for each root
    threads = defaultdict(list)
    for para_id in reply_para_ids:
        parent = parent_mapping.get(para_id)
        comment = para_to_comment.get(para_id)
        if parent and comment:
            threads[parent].append({
                **comment,
                "is_reply": True,
                "parent_para_id": parent,
            })
    
    # Organize by root
    result = {}
    for root in roots:
        para_id = root.get("para_id")
        result[para_id] = {
            "root": root,
            "replies": threads.get(para_id, []),
        }
    
    return result


def diagnose_document(docx_path: str, specific_thread: str = None) -> Dict[str, Any]:
    """
    Perform full diagnostic analysis on a document.
    
    Args:
        docx_path: Path to the DOCX file
        specific_thread: If provided, focus on this thread ID
        
    Returns:
        Diagnostic report dictionary
    """
    report = {
        "document": Path(docx_path).name,
        "xml_files_present": [],
        "xml_files_missing": [],
        "comments": {},
        "extended": {},
        "anchors": {},
        "ids": {},
        "people": {},
        "threads": {},
        "issues": [],
    }
    
    print(f"\n{'='*60}")
    print(f"Diagnosing: {Path(docx_path).name}")
    print(f"{'='*60}")
    
    xml_files = [
        'word/comments.xml',
        'word/commentsExtended.xml',
        'word/commentsExtensible.xml',
        'word/commentsIds.xml',
        'word/document.xml',
        'word/people.xml',
    ]
    
    with zipfile.ZipFile(docx_path, 'r') as zf:
        # Check which files exist
        for xml_file in xml_files:
            if xml_file in zf.namelist():
                report["xml_files_present"].append(xml_file)
                print(f"  [+] {xml_file}")
            else:
                report["xml_files_missing"].append(xml_file)
                print(f"  [-] {xml_file} (not present)")
        
        # Parse each file
        print("\n  Parsing XML files...")
        
        # comments.xml
        content = extract_xml_file(zf, 'word/comments.xml')
        if content:
            report["comments"] = parse_comments_xml(content)
            print(f"    - comments.xml: {len(report['comments'])} comments")
        
        # commentsExtended.xml
        content = extract_xml_file(zf, 'word/commentsExtended.xml')
        if content:
            report["extended"] = parse_comments_extended(content)
            print(f"    - commentsExtended.xml: {len(report['extended'])} entries")
        
        # document.xml
        content = extract_xml_file(zf, 'word/document.xml')
        if content:
            report["anchors"] = parse_document_anchors(content)
            print(f"    - document.xml: {len(report['anchors'])} anchored comments")
        
        # commentsIds.xml
        content = extract_xml_file(zf, 'word/commentsIds.xml')
        if content:
            report["ids"] = parse_comments_ids(content)
            print(f"    - commentsIds.xml: {len(report['ids'])} ID mappings")
        
        # people.xml
        content = extract_xml_file(zf, 'word/people.xml')
        if content:
            report["people"] = parse_people(content)
            print(f"    - people.xml: {len(report['people'])} authors")
    
    # Build thread tree
    report["threads"] = build_thread_tree(report["comments"], report["extended"])
    print(f"\n  Found {len(report['threads'])} comment threads")
    
    # Analyze for issues
    print("\n  Checking for issues...")
    
    # Issue 1: Comments without anchors
    for cid, comment in report["comments"].items():
        anchor = report["anchors"].get(cid, {})
        if not anchor.get("range_start") and not anchor.get("reference"):
            report["issues"].append({
                "type": "ORPHANED_COMMENT",
                "comment_id": cid,
                "para_id": comment.get("para_id"),
                "text": comment.get("text", "")[:50],
                "description": "Comment has no anchor in document.xml"
            })
    
    # Issue 2: Replies without parent in extended
    for para_id, ext in report["extended"].items():
        parent = ext.get("parent_para_id")
        if parent:
            # Check if parent exists
            parent_exists = any(
                c.get("para_id") == parent 
                for c in report["comments"].values()
            )
            if not parent_exists:
                report["issues"].append({
                    "type": "ORPHANED_REPLY",
                    "para_id": para_id,
                    "parent_para_id": parent,
                    "description": "Reply references non-existent parent para_id"
                })
    
    # Issue 3: Extended entry without comment
    comment_para_ids = {c.get("para_id") for c in report["comments"].values()}
    for para_id in report["extended"]:
        if para_id not in comment_para_ids:
            report["issues"].append({
                "type": "EXTENDED_WITHOUT_COMMENT",
                "para_id": para_id,
                "description": "Entry in commentsExtended.xml has no matching comment"
            })
    
    # Print issues
    if report["issues"]:
        print(f"\n  Found {len(report['issues'])} potential issues:")
        for issue in report["issues"][:10]:  # Show first 10
            print(f"    - [{issue['type']}] {issue.get('description', '')}")
        if len(report["issues"]) > 10:
            print(f"    ... and {len(report['issues']) - 10} more")
    else:
        print("    No issues detected!")
    
    return report


def print_thread_details(report: Dict, thread_id: str = None):
    """Print detailed thread information."""
    threads = report["threads"]
    
    if thread_id:
        # Find thread by root comment ID
        matching = None
        for para_id, thread in threads.items():
            if thread["root"]["id"] == thread_id:
                matching = (para_id, thread)
                break
        
        if matching:
            para_id, thread = matching
            threads = {para_id: thread}
        else:
            print(f"\n  Thread {thread_id} not found")
            return
    
    print(f"\n{'='*60}")
    print("THREAD DETAILS")
    print(f"{'='*60}")
    
    for para_id, thread in threads.items():
        root = thread["root"]
        replies = thread["replies"]
        
        print(f"\n  Thread: {root['id']} (para_id: {para_id})")
        print(f"  Author: {root.get('author', 'Unknown')}")
        print(f"  Text: {root.get('text', '')[:80]}...")
        print(f"  Replies: {len(replies)}")
        
        anchor = report["anchors"].get(root["id"], {})
        print(f"  Anchor: range_start={anchor.get('range_start', False)}, "
              f"range_end={anchor.get('range_end', False)}, "
              f"reference={anchor.get('reference', False)}")
        
        if replies:
            print("  Reply chain:")
            for i, reply in enumerate(replies):
                print(f"    [{i+1}] ID: {reply['id']}, "
                      f"para_id: {reply.get('para_id', 'N/A')}")
                print(f"        Text: {reply.get('text', '')[:60]}...")
                
                # Check reply's anchor
                reply_anchor = report["anchors"].get(reply["id"], {})
                has_anchor = reply_anchor.get("range_start") or reply_anchor.get("reference")
                if has_anchor:
                    print(f"        WARNING: Reply has its own anchor (may appear standalone)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Diagnose DOCX comment/reply structure"
    )
    parser.add_argument("docx_path", help="Path to the DOCX file")
    parser.add_argument(
        "--thread", "-t",
        help="Focus on specific thread ID"
    )
    parser.add_argument(
        "--export", "-e",
        action="store_true",
        help="Export raw XML files for inspection"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.docx_path):
        print(f"File not found: {args.docx_path}")
        return 1
    
    # Run diagnostics
    report = diagnose_document(args.docx_path, args.thread)
    
    # Print thread details
    print_thread_details(report, args.thread)
    
    # Export if requested
    if args.export:
        output_dir = Path(args.output) if args.output else Path("test_data/xml_exports")
        doc_name = Path(args.docx_path).stem
        export_dir = output_dir / doc_name
        export_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"EXPORTING XML FILES")
        print(f"{'='*60}")
        
        with zipfile.ZipFile(args.docx_path, 'r') as zf:
            for xml_file in report["xml_files_present"]:
                content = zf.read(xml_file)
                out_file = export_dir / xml_file.replace('word/', '')
                with open(out_file, 'wb') as f:
                    f.write(content)
                print(f"  Exported: {out_file}")
        
        # Save report
        report_file = export_dir / "diagnosis_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  Report: {report_file}")
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Comments: {len(report['comments'])}")
    print(f"  Threads: {len(report['threads'])}")
    print(f"  Total replies: {sum(len(t['replies']) for t in report['threads'].values())}")
    print(f"  Issues found: {len(report['issues'])}")
    
    return 0 if not report["issues"] else 1


if __name__ == "__main__":
    sys.exit(main())
