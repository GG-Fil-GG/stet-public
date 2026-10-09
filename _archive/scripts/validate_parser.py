#!/usr/bin/env python3
"""
Validation Script - Compare new DocumentParser against legacy CommentExtractor.

This script tests both parsers on the same documents and reports differences.
Run this to validate that the DOM parser produces equivalent output.
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.comment_extractor import CommentExtractor
from src.document_model import parse_docx


@dataclass
class ComparisonResult:
    """Result of comparing old vs new parser for one document."""
    filename: str
    old_comment_count: int
    new_comment_count: int
    old_thread_count: int
    new_thread_count: int
    comment_count_match: bool
    thread_count_match: bool
    threading_match: bool
    threading_issues: List[str]
    anchor_match: bool
    anchor_issues: List[str]
    errors: List[str]


def compare_parsers(docx_path: Path) -> ComparisonResult:
    """
    Compare old CommentExtractor vs new DocumentParser on a single file.
    
    Returns a ComparisonResult with detailed comparison data.
    """
    result = ComparisonResult(
        filename=docx_path.name,
        old_comment_count=0,
        new_comment_count=0,
        old_thread_count=0,
        new_thread_count=0,
        comment_count_match=False,
        thread_count_match=False,
        threading_match=True,
        threading_issues=[],
        anchor_match=True,
        anchor_issues=[],
        errors=[]
    )
    
    try:
        # Parse with old extractor
        old_extractor = CommentExtractor(str(docx_path))
        old_threads = old_extractor.extract(include_resolved=True)
        
        result.old_thread_count = len(old_threads)
        result.old_comment_count = sum(len(t.comments) for t in old_threads)
        
    except Exception as e:
        result.errors.append(f"Old extractor error: {e}")
        return result
    
    try:
        # Parse with new parser
        model = parse_docx(docx_path)
        
        result.new_thread_count = model.thread_count
        result.new_comment_count = model.comment_count
        
    except Exception as e:
        result.errors.append(f"New parser error: {e}")
        return result
    
    # Compare counts
    result.comment_count_match = result.old_comment_count == result.new_comment_count
    result.thread_count_match = result.old_thread_count == result.new_thread_count
    
    # Compare threading relationships
    # Build old threading map: comment_id -> thread_id (root comment)
    old_thread_membership: Dict[str, str] = {}
    for thread in old_threads:
        root_id = thread.thread_id
        for comment in thread.comments:
            old_thread_membership[comment.id] = root_id
    
    # Build new threading map: comment_id -> thread_id
    new_thread_membership: Dict[str, str] = {}
    for thread in model.comments.threads.values():
        for comment in thread.all_comments:
            new_thread_membership[comment.comment_id] = thread.thread_id
    
    # Compare thread membership (are comments in the same threads?)
    all_comment_ids = set(old_thread_membership.keys()) | set(new_thread_membership.keys())
    for comment_id in all_comment_ids:
        old_thread = old_thread_membership.get(comment_id)
        new_thread = new_thread_membership.get(comment_id)
        if old_thread != new_thread:
            result.threading_match = False
            result.threading_issues.append(
                f"Comment {comment_id}: old thread={old_thread}, new thread={new_thread}"
            )
    
    # Compare anchors (para_id)
    # Build old anchor map: thread_id -> para_id
    old_anchors: Dict[str, str] = {}
    for thread in old_threads:
        if thread.comments:
            old_anchors[thread.thread_id] = thread.comments[0].para_id
    
    # Build new anchor map
    new_anchors: Dict[str, str] = {}
    for thread in model.comments.threads.values():
        if thread.root.anchor:
            new_anchors[thread.thread_id] = thread.root.anchor.para_id
    
    # Compare anchors
    for thread_id in old_anchors:
        old_para = old_anchors.get(thread_id)
        new_para = new_anchors.get(thread_id)
        if old_para and new_para and old_para != new_para:
            result.anchor_match = False
            result.anchor_issues.append(
                f"Thread {thread_id}: old para={old_para}, new para={new_para}"
            )
    
    return result


def run_validation(test_data_dir: Path) -> List[ComparisonResult]:
    """Run validation on all DOCX files in the test data directory."""
    results = []
    
    docx_files = list(test_data_dir.glob('*.docx'))
    print(f"\nValidating {len(docx_files)} documents...\n")
    print("=" * 80)
    
    for docx_path in sorted(docx_files):
        result = compare_parsers(docx_path)
        results.append(result)
        
        # Print result
        status = "✓" if (result.comment_count_match and 
                         result.thread_count_match and 
                         result.threading_match and
                         result.anchor_match and
                         not result.errors) else "✗"
        
        print(f"{status} {result.filename}")
        print(f"    Comments: old={result.old_comment_count}, new={result.new_comment_count} "
              f"{'✓' if result.comment_count_match else '✗'}")
        print(f"    Threads:  old={result.old_thread_count}, new={result.new_thread_count} "
              f"{'✓' if result.thread_count_match else '✗'}")
        
        if result.threading_issues:
            print(f"    Threading issues:")
            for issue in result.threading_issues[:3]:
                print(f"      - {issue}")
            if len(result.threading_issues) > 3:
                print(f"      ... and {len(result.threading_issues) - 3} more")
        
        if result.anchor_issues:
            print(f"    Anchor issues:")
            for issue in result.anchor_issues[:3]:
                print(f"      - {issue}")
            if len(result.anchor_issues) > 3:
                print(f"      ... and {len(result.anchor_issues) - 3} more")
        
        if result.errors:
            print(f"    Errors:")
            for error in result.errors:
                print(f"      - {error}")
        
        print()
    
    return results


def print_summary(results: List[ComparisonResult]) -> Tuple[int, int]:
    """Print summary of validation results."""
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total = len(results)
    passed = sum(1 for r in results if (
        r.comment_count_match and 
        r.thread_count_match and 
        r.threading_match and
        r.anchor_match and
        not r.errors
    ))
    
    comment_match = sum(1 for r in results if r.comment_count_match)
    thread_match = sum(1 for r in results if r.thread_count_match)
    threading_match = sum(1 for r in results if r.threading_match)
    anchor_match = sum(1 for r in results if r.anchor_match)
    no_errors = sum(1 for r in results if not r.errors)
    
    print(f"\nTotal documents tested: {total}")
    print(f"Fully matching:         {passed}/{total} ({100*passed/total:.1f}%)")
    print(f"\nBreakdown:")
    print(f"  Comment counts match: {comment_match}/{total}")
    print(f"  Thread counts match:  {thread_match}/{total}")
    print(f"  Threading matches:    {threading_match}/{total}")
    print(f"  Anchors match:        {anchor_match}/{total}")
    print(f"  No errors:            {no_errors}/{total}")
    
    return passed, total


if __name__ == "__main__":
    # Find test_data directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    test_data_dir = project_root / "test_data"
    
    if not test_data_dir.exists():
        print(f"Error: test_data directory not found at {test_data_dir}")
        sys.exit(1)
    
    results = run_validation(test_data_dir)
    passed, total = print_summary(results)
    
    # Exit with error if not all passed
    sys.exit(0 if passed == total else 1)
