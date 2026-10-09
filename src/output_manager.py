"""
Output Manager - Handle structured output directory organization.

Provides consistent naming conventions and folder structures for:
- Extractor outputs (comments.json, comments.txt)
- LLM suggestion outputs (per-thread and session exports)
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


def sanitize_filename(name: str, max_length: int = 40) -> str:
    """
    Convert a filename to a safe, lowercase slug.
    
    Examples:
        "251208_Example Study PMS Final analysis_4th draft.docx"
        → "example_study_pms_final_analysis_4th"
    """
    # Remove file extension
    name = Path(name).stem
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove common prefixes (dates like 251208_, 20251208_, etc.)
    name = re.sub(r'^\d{6,8}_', '', name)
    
    # Remove common suffixes (like _4th draft, _tracked, _final, analysis, etc.)
    name = re.sub(r'_\d+(st|nd|rd|th)_draft.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_tracked.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_final.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_analysis.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_draft.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'_v\d+.*$', '', name, flags=re.IGNORECASE)  # version numbers
    
    # Replace spaces and special chars with underscores
    name = re.sub(r'[^a-z0-9]+', '_', name)
    
    # Remove leading/trailing underscores
    name = name.strip('_')
    
    # Remove consecutive underscores
    name = re.sub(r'_+', '_', name)
    
    # Truncate at word boundary if too long
    if len(name) > max_length:
        # Find last underscore before max_length
        truncated = name[:max_length]
        last_underscore = truncated.rfind('_')
        if last_underscore > max_length // 2:  # Only use if reasonable
            name = truncated[:last_underscore]
        else:
            name = truncated.rstrip('_')
    
    return name


def get_output_dir(docx_path: str, base_output_dir: str = "output") -> Path:
    """
    Get the output directory for a given document.
    
    Creates the directory structure if it doesn't exist:
        output/{document_slug}/
        output/{document_slug}/llm/
    
    Args:
        docx_path: Path to the .docx file
        base_output_dir: Base output directory (default: "output")
        
    Returns:
        Path to the document's output directory
    """
    # Get document slug
    doc_name = Path(docx_path).name
    slug = sanitize_filename(doc_name)
    
    # Create directory structure
    output_dir = Path(base_output_dir) / slug
    llm_dir = output_dir / "llm"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    llm_dir.mkdir(exist_ok=True)
    
    return output_dir


def get_extractor_paths(docx_path: str, base_output_dir: str = "output") -> dict:
    """
    Get the paths for extractor output files.
    
    Returns:
        dict with 'json' and 'txt' paths
    """
    output_dir = get_output_dir(docx_path, base_output_dir)
    return {
        'json': output_dir / "comments.json",
        'txt': output_dir / "comments.txt"
    }


def get_llm_thread_path(docx_path: str, thread_id: str, base_output_dir: str = "output") -> Path:
    """
    Get the path for an LLM suggestion for a specific thread.
    
    Returns:
        Path like output/{slug}/llm/thread_117.json
    """
    output_dir = get_output_dir(docx_path, base_output_dir)
    return output_dir / "llm" / f"thread_{thread_id}.json"


def get_llm_session_path(docx_path: str, base_output_dir: str = "output") -> Path:
    """
    Get the path for a full LLM session export.
    
    Returns:
        Path like output/{slug}/llm/session_2024-12-31.json
    """
    output_dir = get_output_dir(docx_path, base_output_dir)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return output_dir / "llm" / f"session_{date_str}.json"


def save_extractor_output(
    docx_path: str,
    threads_json: str,
    threads_txt: str,
    base_output_dir: str = "output"
) -> dict:
    """
    Save extractor output to the appropriate location.
    
    Args:
        docx_path: Path to the source .docx file
        threads_json: JSON string of extracted threads
        threads_txt: Human-readable text output
        base_output_dir: Base output directory
        
    Returns:
        dict with paths to saved files
    """
    paths = get_extractor_paths(docx_path, base_output_dir)
    
    with open(paths['json'], 'w', encoding='utf-8') as f:
        f.write(threads_json)
    
    with open(paths['txt'], 'w', encoding='utf-8') as f:
        f.write(threads_txt)
    
    return {
        'json': str(paths['json']),
        'txt': str(paths['txt'])
    }


def save_llm_suggestion(
    docx_path: str,
    thread_id: str,
    suggestion_data: dict,
    base_output_dir: str = "output"
) -> str:
    """
    Save an LLM suggestion for a specific thread.
    
    Args:
        docx_path: Path to the source .docx file
        thread_id: ID of the thread
        suggestion_data: Dict containing the suggestion
        base_output_dir: Base output directory
        
    Returns:
        Path to saved file
    """
    path = get_llm_thread_path(docx_path, thread_id, base_output_dir)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(suggestion_data, f, indent=2, ensure_ascii=False)
    
    return str(path)


def list_document_outputs(base_output_dir: str = "output") -> list:
    """
    List all document output directories.
    
    Returns:
        List of dicts with 'slug', 'path', and file counts
    """
    base = Path(base_output_dir)
    if not base.exists():
        return []
    
    results = []
    for item in base.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            llm_dir = item / "llm"
            llm_count = len(list(llm_dir.glob("thread_*.json"))) if llm_dir.exists() else 0
            
            results.append({
                'slug': item.name,
                'path': str(item),
                'has_comments_json': (item / "comments.json").exists(),
                'has_comments_txt': (item / "comments.txt").exists(),
                'llm_thread_count': llm_count
            })
    
    return sorted(results, key=lambda x: x['slug'])


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    # Test with sample document name
    test_doc = "251208_Example Study PMS Final analysis_4th draft.docx"
    
    print("=" * 60)
    print("Output Manager Test")
    print("=" * 60)
    
    print(f"\nOriginal filename: {test_doc}")
    print(f"Sanitized slug: {sanitize_filename(test_doc)}")
    
    print(f"\nOutput directory: {get_output_dir(f'test_data/{test_doc}')}")
    print(f"Extractor paths: {get_extractor_paths(f'test_data/{test_doc}')}")
    print(f"LLM thread path: {get_llm_thread_path(f'test_data/{test_doc}', '117')}")
    print(f"LLM session path: {get_llm_session_path(f'test_data/{test_doc}')}")

