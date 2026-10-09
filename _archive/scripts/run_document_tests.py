#!/usr/bin/env python3
"""
Document Test Runner - Batch testing with auto-detection.

This script runs Stet's comment extraction and export workflow on multiple
documents, automatically detecting document features and logging results.

Usage:
    python scripts/run_document_tests.py [test_data/documents/]
    python scripts/run_document_tests.py path/to/document.docx
    python scripts/run_document_tests.py --help

Results are saved to test_data/results/{timestamp}/
"""

import argparse
import json
import sys
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import shutil

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.comment_extractor import CommentExtractor
from src.docx_writer import create_modified_docx


# =============================================================================
# DOCUMENT FEATURE DETECTION
# =============================================================================

def detect_document_features(docx_path: str) -> Dict[str, Any]:
    """
    Auto-detect features present in a DOCX document.
    
    Args:
        docx_path: Path to the DOCX file
        
    Returns:
        Dict with detected features
    """
    features = {
        "has_comments": False,
        "comment_count": 0,
        "has_tables": False,
        "table_count": 0,
        "has_citations": False,
        "citation_count": 0,
        "has_track_changes": False,
        "has_replies": False,
        "reply_count": 0,
        "has_images": False,
        "paragraph_count": 0,
        "file_size_bytes": 0,
    }
    
    try:
        features["file_size_bytes"] = os.path.getsize(docx_path)
        
        with zipfile.ZipFile(docx_path, 'r') as zf:
            # Check for comments
            if 'word/comments.xml' in zf.namelist():
                features["has_comments"] = True
                comments_xml = zf.read('word/comments.xml')
                root = ET.fromstring(comments_xml)
                # Count <w:comment> elements
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                comments = root.findall('.//w:comment', ns)
                features["comment_count"] = len(comments)
            
            # Check for extended comments (replies)
            if 'word/commentsExtended.xml' in zf.namelist():
                ext_xml = zf.read('word/commentsExtended.xml')
                if b'paraIdParent' in ext_xml:
                    features["has_replies"] = True
                    # Count paraIdParent occurrences (rough reply count)
                    features["reply_count"] = ext_xml.count(b'paraIdParent')
            
            # Check document.xml for various features
            if 'word/document.xml' in zf.namelist():
                doc_xml = zf.read('word/document.xml')
                doc_str = doc_xml.decode('utf-8', errors='ignore')
                
                # Tables
                features["has_tables"] = '<w:tbl' in doc_str
                features["table_count"] = doc_str.count('<w:tbl ')
                
                # Track changes
                features["has_track_changes"] = '<w:ins ' in doc_str or '<w:del ' in doc_str
                
                # Citations (field codes)
                features["has_citations"] = '<w:fldChar' in doc_str or 'CITATION' in doc_str
                features["citation_count"] = doc_str.count('CITATION')
                
                # Paragraphs
                features["paragraph_count"] = doc_str.count('<w:p ')
            
            # Check for images
            features["has_images"] = any(
                f.startswith('word/media/') 
                for f in zf.namelist()
            )
    
    except Exception as e:
        features["detection_error"] = str(e)
    
    return features


# =============================================================================
# TEST EXECUTION
# =============================================================================

def run_extraction_test(docx_path: str) -> Dict[str, Any]:
    """
    Run comment extraction on a document.
    
    Returns:
        Dict with extraction results
    """
    result = {
        "success": False,
        "error": None,
        "thread_count": 0,
        "threads": [],
        "paragraph_count": 0,
        "extraction_time_ms": 0,
    }
    
    start = datetime.now()
    
    try:
        extractor = CommentExtractor(docx_path)
        threads = extractor.extract(
            include_resolved=True,
            include_orphaned=True,
            include_on_deleted_text=True
        )
        
        result["success"] = True
        result["thread_count"] = len(threads)
        
        # Summarize threads
        for t in threads:
            thread_summary = {
                "thread_id": t.thread_id,
                "comment_count": len(t.comments),
                "has_anchor": t.has_anchor,
                "is_resolved": t.is_resolved,
                "is_on_deleted_text": t.is_on_deleted_text,
                "root_comment_id": t.comments[0].id if t.comments else None,
                "root_comment_author": t.comments[0].author if t.comments else None,
                "referenced_text_length": len(t.referenced_text or ""),
                "exact_text": t.exact_text[:100] if t.exact_text else None,
            }
            result["threads"].append(thread_summary)
        
        # Get paragraph cache info
        cache = extractor.get_paragraph_cache()
        result["paragraph_count"] = len(cache)
        
    except Exception as e:
        result["error"] = str(e)
    
    elapsed = datetime.now() - start
    result["extraction_time_ms"] = int(elapsed.total_seconds() * 1000)
    
    return result


def run_export_test(
    docx_path: str, 
    output_path: str,
    mock_replies: List[Dict] = None
) -> Dict[str, Any]:
    """
    Run export test on a document.
    
    Args:
        docx_path: Source document path
        output_path: Output document path
        mock_replies: Optional list of mock replies to insert
        
    Returns:
        Dict with export results
    """
    result = {
        "success": False,
        "error": None,
        "output_valid": False,
        "export_time_ms": 0,
    }
    
    start = datetime.now()
    
    try:
        replies = mock_replies or []
        
        success, message = create_modified_docx(
            source_path=docx_path,
            output_path=output_path,
            replies=replies,
            author="Test Runner"
        )
        
        result["success"] = success
        if not success:
            result["error"] = message
        
        # Validate output
        if success and os.path.exists(output_path):
            result["output_valid"] = zipfile.is_zipfile(output_path)
            
            # Check XML validity
            try:
                with zipfile.ZipFile(output_path, 'r') as zf:
                    if 'word/document.xml' in zf.namelist():
                        doc_xml = zf.read('word/document.xml')
                        ET.fromstring(doc_xml)  # Validate XML
            except Exception as e:
                result["output_valid"] = False
                result["xml_error"] = str(e)
    
    except Exception as e:
        result["error"] = str(e)
    
    elapsed = datetime.now() - start
    result["export_time_ms"] = int(elapsed.total_seconds() * 1000)
    
    return result


def run_document_test(docx_path: str, output_dir: Path) -> Dict[str, Any]:
    """
    Run complete test suite on a single document.
    
    Args:
        docx_path: Path to the document
        output_dir: Directory to store results
        
    Returns:
        Dict with all test results
    """
    doc_name = Path(docx_path).stem
    doc_output_dir = output_dir / doc_name
    doc_output_dir.mkdir(parents=True, exist_ok=True)
    
    result = {
        "document": Path(docx_path).name,
        "path": str(docx_path),
        "test_time": datetime.now().isoformat(),
        "features": {},
        "extraction": {},
        "export": {},
    }
    
    print(f"\n{'='*60}")
    print(f"Testing: {Path(docx_path).name}")
    print(f"{'='*60}")
    
    # 1. Detect features
    print("  [1/3] Detecting features...")
    result["features"] = detect_document_features(docx_path)
    print(f"        Comments: {result['features']['comment_count']}, "
          f"Tables: {result['features']['table_count']}, "
          f"Citations: {result['features']['citation_count']}")
    
    # 2. Run extraction
    print("  [2/3] Running extraction...")
    result["extraction"] = run_extraction_test(docx_path)
    if result["extraction"]["success"]:
        print(f"        Extracted {result['extraction']['thread_count']} threads "
              f"in {result['extraction']['extraction_time_ms']}ms")
    else:
        print(f"        FAILED: {result['extraction']['error']}")
    
    # 3. Run export
    print("  [3/3] Running export test...")
    export_path = str(doc_output_dir / f"{doc_name}_exported.docx")
    result["export"] = run_export_test(docx_path, export_path)
    if result["export"]["success"]:
        print(f"        Export successful in {result['export']['export_time_ms']}ms")
    else:
        print(f"        FAILED: {result['export']['error']}")
    
    # Save individual result
    result_file = doc_output_dir / "result.json"
    with open(result_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    return result


# =============================================================================
# MAIN RUNNER
# =============================================================================

def find_docx_files(path: str) -> List[str]:
    """Find all DOCX files in path (file or directory)."""
    path = Path(path)
    
    if path.is_file() and path.suffix == '.docx':
        return [str(path)]
    
    if path.is_dir():
        return [str(f) for f in path.rglob('*.docx')]
    
    return []


def generate_summary(results: List[Dict], output_dir: Path) -> Dict:
    """Generate summary report from test results."""
    summary = {
        "test_run_time": datetime.now().isoformat(),
        "total_documents": len(results),
        "extraction_success": 0,
        "extraction_failed": 0,
        "export_success": 0,
        "export_failed": 0,
        "total_threads": 0,
        "feature_matrix": {},
    }
    
    for r in results:
        if r["extraction"]["success"]:
            summary["extraction_success"] += 1
            summary["total_threads"] += r["extraction"]["thread_count"]
        else:
            summary["extraction_failed"] += 1
        
        if r["export"]["success"]:
            summary["export_success"] += 1
        else:
            summary["export_failed"] += 1
        
        # Build feature matrix
        doc_name = r["document"]
        summary["feature_matrix"][doc_name] = {
            k: v for k, v in r["features"].items()
            if isinstance(v, bool) or (isinstance(v, int) and v > 0)
        }
    
    # Save summary
    summary_file = output_dir / "summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Also save as CSV for easy viewing
    csv_file = output_dir / "feature_matrix.csv"
    with open(csv_file, 'w') as f:
        # Header
        all_features = set()
        for features in summary["feature_matrix"].values():
            all_features.update(features.keys())
        headers = ["document"] + sorted(all_features)
        f.write(",".join(headers) + "\n")
        
        # Rows
        for doc, features in summary["feature_matrix"].items():
            row = [doc]
            for h in headers[1:]:
                val = features.get(h, "")
                row.append(str(val) if val else "")
            f.write(",".join(row) + "\n")
    
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run Stet document tests with auto-detection"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="test_data/documents",
        help="Path to document(s) to test (file or directory)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory for results"
    )
    
    args = parser.parse_args()
    
    # Find documents
    docx_files = find_docx_files(args.path)
    if not docx_files:
        # Try test_data directly if documents subdir doesn't exist
        alt_path = Path(args.path).parent if Path(args.path).name == "documents" else Path("test_data")
        docx_files = find_docx_files(str(alt_path))
    
    if not docx_files:
        print(f"No DOCX files found in: {args.path}")
        print("Usage: python scripts/run_document_tests.py [path/to/documents/]")
        return 1
    
    print(f"Found {len(docx_files)} document(s) to test")
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else Path("test_data/results") / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Results will be saved to: {output_dir}")
    
    # Run tests
    results = []
    for docx_path in docx_files:
        try:
            result = run_document_test(docx_path, output_dir)
            results.append(result)
        except Exception as e:
            print(f"ERROR testing {docx_path}: {e}")
            results.append({
                "document": Path(docx_path).name,
                "path": docx_path,
                "error": str(e),
            })
    
    # Generate summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    summary = generate_summary(results, output_dir)
    
    print(f"Documents tested: {summary['total_documents']}")
    print(f"Extraction: {summary['extraction_success']} passed, {summary['extraction_failed']} failed")
    print(f"Export: {summary['export_success']} passed, {summary['export_failed']} failed")
    print(f"Total threads found: {summary['total_threads']}")
    print(f"\nResults saved to: {output_dir}")
    
    return 0 if summary['extraction_failed'] == 0 and summary['export_failed'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
