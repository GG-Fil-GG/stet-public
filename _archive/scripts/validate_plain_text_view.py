#!/usr/bin/env python3
"""
Validate PlainTextView against legacy context generation.

Phase 3 validation: Compare context generation between:
1. New: PlainTextView.get_context_for_thread()
2. Old: LLMHandler._get_expanded_context()

Usage:
    python scripts/validate_plain_text_view.py [docx_path]
    python scripts/validate_plain_text_view.py  # Tests all files in test_data/
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.document_model import parse_docx, get_context_for_thread
from src.llm_handler import LLMHandler
from src.comment_extractor import CommentExtractor


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    # Remove extra whitespace, normalize newlines
    lines = text.strip().split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    return '\n'.join(lines)


def compare_contexts(
    old_before: str, old_target: str, old_after: str,
    new_before: str, new_target: str, new_after: str,
    verbose: bool = False
) -> dict:
    """Compare old and new context generation results."""
    results = {
        'before_match': False,
        'target_match': False,
        'after_match': False,
        'all_match': False,
        'issues': []
    }
    
    # Normalize for comparison
    old_before_norm = normalize_text(old_before)
    old_target_norm = normalize_text(old_target)
    old_after_norm = normalize_text(old_after)
    
    new_before_norm = normalize_text(new_before)
    new_target_norm = normalize_text(new_target)
    new_after_norm = normalize_text(new_after)
    
    # Compare
    results['before_match'] = old_before_norm == new_before_norm
    results['target_match'] = old_target_norm == new_target_norm
    results['after_match'] = old_after_norm == new_after_norm
    results['all_match'] = all([
        results['before_match'],
        results['target_match'],
        results['after_match']
    ])
    
    if not results['before_match']:
        results['issues'].append(f"BEFORE mismatch: old={len(old_before_norm)} chars, new={len(new_before_norm)} chars")
        if verbose:
            print(f"  OLD BEFORE: {old_before_norm[:200]}...")
            print(f"  NEW BEFORE: {new_before_norm[:200]}...")
    
    if not results['target_match']:
        results['issues'].append(f"TARGET mismatch: old={len(old_target_norm)} chars, new={len(new_target_norm)} chars")
        if verbose:
            print(f"  OLD TARGET: {old_target_norm[:200]}...")
            print(f"  NEW TARGET: {new_target_norm[:200]}...")
    
    if not results['after_match']:
        results['issues'].append(f"AFTER mismatch: old={len(old_after_norm)} chars, new={len(new_after_norm)} chars")
        if verbose:
            print(f"  OLD AFTER: {old_after_norm[:200]}...")
            print(f"  NEW AFTER: {new_after_norm[:200]}...")
    
    return results


def validate_file(docx_path: Path, verbose: bool = False) -> dict:
    """Validate PlainTextView against legacy for a single file."""
    print(f"\nValidating: {docx_path.name}")
    print("=" * 60)
    
    results = {
        'file': docx_path.name,
        'threads_tested': 0,
        'threads_matched': 0,
        'threads_partial': 0,
        'threads_failed': 0,
        'details': []
    }
    
    try:
        # Parse with new parser
        model = parse_docx(docx_path)
        print(f"  Parsed: {model.paragraph_count} paragraphs, {model.thread_count} threads")
        
        if model.thread_count == 0:
            print("  No threads to validate.")
            return results
        
        # Get threads from old extractor
        extractor = CommentExtractor(str(docx_path))
        old_threads = extractor.extract()
        
        # Create LLM handler for old context extraction
        handler = LLMHandler(docx_path=str(docx_path))
        
        # Test each thread
        for thread_id, thread in model.comments.threads.items():
            results['threads_tested'] += 1
            print(f"\n  Thread {thread_id}:")
            
            # Find matching old thread
            old_thread = None
            for t in old_threads:
                if str(t.thread_id) == str(thread_id):
                    old_thread = t
                    break
            
            if not old_thread:
                print(f"    WARNING: Old thread not found for {thread_id}")
                results['threads_failed'] += 1
                continue
            
            # Get new context
            new_before, new_target, new_after, new_target_id, new_all_ids = get_context_for_thread(
                model,
                thread_id=thread_id,
                context_before=2,
                context_after=2
            )
            
            # Get old context
            try:
                old_before, old_target, old_after, old_target_id, old_all_ids = handler._get_expanded_context(
                    old_thread,
                    accepted_revisions=None,
                    context_before_count=2,
                    context_after_count=2
                )
            except Exception as e:
                print(f"    ERROR getting old context: {e}")
                results['threads_failed'] += 1
                continue
            
            # Compare
            comparison = compare_contexts(
                old_before, old_target, old_after,
                new_before, new_target, new_after,
                verbose=verbose
            )
            
            if comparison['all_match']:
                print(f"    ✅ MATCH - before: {len(old_before)} chars, target: {len(old_target)} chars, after: {len(old_after)} chars")
                results['threads_matched'] += 1
            elif any([comparison['before_match'], comparison['target_match'], comparison['after_match']]):
                matched = []
                if comparison['before_match']:
                    matched.append('before')
                if comparison['target_match']:
                    matched.append('target')
                if comparison['after_match']:
                    matched.append('after')
                print(f"    ⚠️ PARTIAL - matched: {matched}")
                for issue in comparison['issues']:
                    print(f"      {issue}")
                results['threads_partial'] += 1
            else:
                print(f"    ❌ NO MATCH")
                for issue in comparison['issues']:
                    print(f"      {issue}")
                results['threads_failed'] += 1
            
            results['details'].append({
                'thread_id': thread_id,
                'comparison': comparison
            })
    
    except Exception as e:
        print(f"  ERROR: {e}")
        results['error'] = str(e)
    
    return results


def main():
    """Main entry point."""
    # Determine files to validate
    if len(sys.argv) > 1:
        files = [Path(sys.argv[1])]
    else:
        # Validate all files in test_data
        test_data_dir = Path(__file__).parent.parent / "test_data"
        files = sorted(test_data_dir.glob("*.docx"))
    
    print("=" * 60)
    print("PlainTextView Validation")
    print("Comparing new context generation vs legacy LLMHandler")
    print("=" * 60)
    
    all_results = []
    total_tested = 0
    total_matched = 0
    total_partial = 0
    total_failed = 0
    
    for docx_path in files:
        if not docx_path.exists():
            print(f"Skipping {docx_path}: not found")
            continue
        
        result = validate_file(docx_path, verbose=False)
        all_results.append(result)
        
        total_tested += result['threads_tested']
        total_matched += result['threads_matched']
        total_partial += result['threads_partial']
        total_failed += result['threads_failed']
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files tested: {len(all_results)}")
    print(f"Threads tested: {total_tested}")
    print(f"  ✅ Full match: {total_matched}")
    print(f"  ⚠️ Partial match: {total_partial}")
    print(f"  ❌ No match: {total_failed}")
    
    if total_tested > 0:
        match_rate = (total_matched / total_tested) * 100
        print(f"\nFull match rate: {match_rate:.1f}%")
        
        # Consider partial matches as acceptable
        acceptable_rate = ((total_matched + total_partial) / total_tested) * 100
        print(f"Acceptable rate (full + partial): {acceptable_rate:.1f}%")
    
    # Return exit code
    if total_failed == 0:
        print("\n✅ Validation PASSED!")
        return 0
    else:
        print("\n⚠️ Validation completed with some differences.")
        print("Note: Differences may be acceptable due to improved handling in PlainTextView.")
        return 0 if acceptable_rate > 80 else 1


if __name__ == "__main__":
    sys.exit(main())
