"""
diff_utils.py - Core diffing functionality for text comparison.

Re-exports from focused submodules for backward compatibility.
"""

from .diff_core import (
    DiffOperation,
    DiffOp,
    DiffResult,
    tokenize_words,
    compute_diff,
    merge_adjacent_ops,
    has_meaningful_changes,
    diff_to_markdown,
)
from .diff_html import (
    diff_to_html,
    diff_to_html_paragraph_aware,
    diff_to_editable_html,
    strip_html_tags,
    highlight_text_in_html,
)
from .diff_word_xml import (
    diff_to_word_xml,
    html_to_word_runs,
    diff_to_word_xml_with_formatting,
)
from .diff_formatting import (
    parse_html_formatting,
    build_html_formatting_map,
    get_formatting_for_text_range,
    get_formatting_segments_for_range,
    merge_formatting_for_revision,
)

__all__ = [
    "DiffOperation",
    "DiffOp",
    "DiffResult",
    "tokenize_words",
    "compute_diff",
    "merge_adjacent_ops",
    "has_meaningful_changes",
    "diff_to_markdown",
    "diff_to_html",
    "diff_to_html_paragraph_aware",
    "diff_to_editable_html",
    "strip_html_tags",
    "highlight_text_in_html",
    "diff_to_word_xml",
    "html_to_word_runs",
    "diff_to_word_xml_with_formatting",
    "parse_html_formatting",
    "build_html_formatting_map",
    "get_formatting_for_text_range",
    "get_formatting_segments_for_range",
    "merge_formatting_for_revision",
]

if __name__ == "__main__":
    print("=" * 60)
    print("diff_utils.py - Interactive Demo")
    print("=" * 60)
    
    # Demo 1: Basic diff
    print("\n1. Basic word replacement:")
    result = compute_diff(
        "The quick brown fox jumps over the lazy dog.",
        "The fast brown fox leaps over the sleepy dog."
    )
    print(f"   Original: {result.original}")
    print(f"   Revised:  {result.revised}")
    print(f"   Has changes: {result.has_changes}")
    print(f"   Summary: {result.change_summary}")
    print("   Operations:")
    for op in result.operations:
        print(f"      {op}")
    
    # Demo 2: HTML output
    print("\n2. HTML output:")
    html_output = diff_to_html(result)
    print(f"   {html_output[:200]}...")
    
    # Demo 3: Markdown output
    print("\n3. Markdown output:")
    md_output = diff_to_markdown(result)
    print(f"   {md_output}")
    
    # Demo 4: Word XML output
    print("\n4. Word XML output (first 300 chars):")
    xml_output, next_id = diff_to_word_xml(
        result,
        author="Test Author",
        timestamp="2026-01-19T12:00:00Z",
        base_revision_id=1,
        rsid="ABC12345"
    )
    print(f"   {xml_output[:300]}...")
    print(f"   Next revision ID: {next_id}")
    
    # Demo 5: Edge cases
    print("\n5. Edge cases:")
    
    # Identical strings
    result = compute_diff("Same text", "Same text")
    print(f"   Identical: has_changes={result.has_changes}, ops={len(result.operations)}")
    
    # Empty original
    result = compute_diff("", "New text")
    print(f"   Empty original: ops={result.operations}")
    
    # Empty revised
    result = compute_diff("Old text", "")
    print(f"   Empty revised: ops={result.operations}")
    
    # Complete replacement
    result = compute_diff("Old text", "New content")
    print(f"   Complete replacement: ops={result.operations}")
    
    print("\n" + "=" * 60)
    print("Demo complete!")
