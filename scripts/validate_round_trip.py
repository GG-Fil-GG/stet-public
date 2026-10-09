#!/usr/bin/env python3
"""
Round-trip validation for DocumentSerializer.

Validates that Parse → Serialize → Parse produces consistent results:
1. Parses a DOCX file
2. Serializes it to a new file
3. Re-parses the serialized file
4. Compares the two DocumentModels

Usage:
    python scripts/validate_round_trip.py [--verbose] [--file FILE]
    
Examples:
    python scripts/validate_round_trip.py                    # Test all files in test_data/
    python scripts/validate_round_trip.py --file test.docx   # Test specific file
    python scripts/validate_round_trip.py --verbose          # Show detailed comparison
"""

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.document_model import (
    DocumentModel,
    DocumentSerializer,
    parse_docx,
    Comment,
    CommentThread,
    Paragraph,
)


@dataclass
class ComparisonResult:
    """Result of comparing two DocumentModels."""
    filename: str
    success: bool
    
    # Counts
    original_paragraphs: int
    serialized_paragraphs: int
    original_comments: int
    serialized_comments: int
    original_threads: int
    serialized_threads: int
    
    # Differences
    differences: List[str]
    
    def __str__(self) -> str:
        status = "✓" if self.success else "✗"
        result = f"{status} {self.filename}"
        
        if not self.success:
            result += f"\n  Paragraphs: {self.original_paragraphs} → {self.serialized_paragraphs}"
            result += f"\n  Comments: {self.original_comments} → {self.serialized_comments}"
            result += f"\n  Threads: {self.original_threads} → {self.serialized_threads}"
            for diff in self.differences:
                result += f"\n  - {diff}"
        
        return result


def compare_models(
    original: DocumentModel,
    serialized: DocumentModel,
    filename: str,
    verbose: bool = False
) -> ComparisonResult:
    """
    Compare two DocumentModels for equivalence.
    
    Args:
        original: The original parsed model
        serialized: The re-parsed model after serialization
        filename: Name of the file being tested
        verbose: Whether to show detailed comparison
    
    Returns:
        ComparisonResult with comparison details
    """
    differences = []
    success = True
    
    # Compare paragraph counts
    orig_para = original.paragraph_count
    ser_para = serialized.paragraph_count
    if orig_para != ser_para:
        differences.append(f"Paragraph count: {orig_para} vs {ser_para}")
        success = False
    
    # Compare comment counts
    orig_comments = original.comment_count
    ser_comments = serialized.comment_count
    if orig_comments != ser_comments:
        differences.append(f"Comment count: {orig_comments} vs {ser_comments}")
        success = False
    
    # Compare thread counts
    orig_threads = original.thread_count
    ser_threads = serialized.thread_count
    if orig_threads != ser_threads:
        differences.append(f"Thread count: {orig_threads} vs {ser_threads}")
        success = False
    
    # Compare paragraph content (sample)
    if verbose:
        orig_paras = list(original.body.iter_paragraphs())
        ser_paras = list(serialized.body.iter_paragraphs())
        
        for i, (op, sp) in enumerate(zip(orig_paras, ser_paras)):
            if op.plain_text != sp.plain_text:
                differences.append(
                    f"Paragraph {i} text differs: '{op.plain_text[:50]}...' vs '{sp.plain_text[:50]}...'"
                )
                if len(differences) > 10:
                    differences.append("... (truncated)")
                    break
    
    # Compare thread structure
    for thread_id, orig_thread in original.comments.threads.items():
        ser_thread = serialized.comments.get_thread(thread_id)
        if not ser_thread:
            differences.append(f"Thread {thread_id} missing from serialized")
            success = False
            continue
        
        if orig_thread.reply_count != ser_thread.reply_count:
            differences.append(
                f"Thread {thread_id} reply count: {orig_thread.reply_count} vs {ser_thread.reply_count}"
            )
            success = False
    
    return ComparisonResult(
        filename=filename,
        success=success,
        original_paragraphs=orig_para,
        serialized_paragraphs=ser_para,
        original_comments=orig_comments,
        serialized_comments=ser_comments,
        original_threads=orig_threads,
        serialized_threads=ser_threads,
        differences=differences
    )


def validate_file(
    docx_path: Path,
    verbose: bool = False
) -> Tuple[bool, ComparisonResult]:
    """
    Perform round-trip validation on a single file.
    
    Args:
        docx_path: Path to the DOCX file
        verbose: Whether to show detailed comparison
    
    Returns:
        Tuple of (success, ComparisonResult)
    """
    try:
        # Parse original
        original = parse_docx(docx_path)
        
        # Serialize to temp file
        with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            serializer = DocumentSerializer()
            serializer.serialize(original, tmp_path)
            
            # Re-parse
            serialized = parse_docx(tmp_path)
            
            # Compare
            result = compare_models(original, serialized, docx_path.name, verbose)
            return (result.success, result)
            
        finally:
            # Clean up temp file
            if tmp_path.exists():
                tmp_path.unlink()
                
    except Exception as e:
        return (False, ComparisonResult(
            filename=docx_path.name,
            success=False,
            original_paragraphs=0,
            serialized_paragraphs=0,
            original_comments=0,
            serialized_comments=0,
            original_threads=0,
            serialized_threads=0,
            differences=[f"Error: {str(e)}"]
        ))


def main():
    parser = argparse.ArgumentParser(
        description='Validate round-trip serialization of DOCX files'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed comparison'
    )
    parser.add_argument(
        '--file', '-f',
        type=str,
        help='Specific file to test (relative to test_data/)'
    )
    args = parser.parse_args()
    
    # Find test files
    test_data_dir = project_root / 'test_data'
    if not test_data_dir.exists():
        print(f"Error: test_data directory not found at {test_data_dir}")
        sys.exit(1)
    
    if args.file:
        files = [test_data_dir / args.file]
        if not files[0].exists():
            print(f"Error: File not found: {files[0]}")
            sys.exit(1)
    else:
        files = list(test_data_dir.glob('*.docx'))
    
    if not files:
        print("No .docx files found to test")
        sys.exit(1)
    
    print(f"Round-trip validation for {len(files)} file(s)\n")
    print("=" * 60)
    
    passed = 0
    failed = 0
    results = []
    
    for file_path in files:
        success, result = validate_file(file_path, args.verbose)
        results.append(result)
        
        if success:
            passed += 1
            print(f"✓ {file_path.name}")
        else:
            failed += 1
            print(result)
    
    print("=" * 60)
    print(f"\nSummary: {passed} passed, {failed} failed out of {len(files)} files")
    
    if args.verbose and results:
        print("\n" + "=" * 60)
        print("Detailed Statistics:")
        print("=" * 60)
        
        total_para_orig = sum(r.original_paragraphs for r in results)
        total_para_ser = sum(r.serialized_paragraphs for r in results)
        total_comments_orig = sum(r.original_comments for r in results)
        total_comments_ser = sum(r.serialized_comments for r in results)
        
        print(f"Total paragraphs: {total_para_orig} → {total_para_ser}")
        print(f"Total comments: {total_comments_orig} → {total_comments_ser}")
        
        # Success rate
        success_rate = (passed / len(files)) * 100 if files else 0
        print(f"\nSuccess rate: {success_rate:.1f}%")
    
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
