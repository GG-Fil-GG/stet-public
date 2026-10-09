"""Special-Unicode protection for the agent transport seam (Stage 1, Milestone 9a).

Some LLMs corrupt special Unicode characters (``≥`` → garbled bytes) when they
re-type a paragraph. The card UI guards against this in
``src/llm_transport.py`` by swapping those characters for ``__UNICODE_*__``
placeholders before the provider call and restoring them after. The agent edit
path (``edit_paragraph``) had no equivalent, so this module adds the same
protection at the ``AgentLLMClient`` boundary (``src/agent/llm_tools.py``).

The placeholder map is **based on**
``llm_transport.LLMTransportMixin.UNICODE_PROTECTION_MAP`` (34 entries) rather than
refactored into a shared module: extracting it would edit the card-UI baseline,
which is out of scope for Stage 1. As of M9d the agent map is a **superset** of
the card-UI map — it adds punctuation that the pilot saw the model corrupt
(en/em dash, ellipsis, non-breaking hyphen) without touching the legacy card map.
The card-UI entries must stay in sync; the parity test enforces the superset.

Only **string values** are transformed — never tool names, JSON keys, numbers,
or booleans. Placeholders are alphanumeric + underscore, so they survive intact
inside JSON tool-call arguments. Transforms operate on copies: the loop's
persisted ``Message`` history and turn log keep real Unicode; only the payload
sent to the provider carries placeholders.
"""

from __future__ import annotations

from typing import Any

# Based on llm_transport.LLMTransportMixin.UNICODE_PROTECTION_MAP (no shared
# module by design — see docstring). The card-UI entries below must stay in sync;
# the M9d additions at the end are agent-only (superset, enforced by the parity test).
UNICODE_PROTECTION_MAP: dict[str, str] = {
    "≥": "__UNICODE_GTE__",
    "≤": "__UNICODE_LTE__",
    "±": "__UNICODE_PM__",
    "≠": "__UNICODE_NEQ__",
    "≈": "__UNICODE_APPROX__",
    "°": "__UNICODE_DEG__",
    "×": "__UNICODE_TIMES__",
    "÷": "__UNICODE_DIV__",
    "µ": "__UNICODE_MU__",
    "α": "__UNICODE_ALPHA__",
    "β": "__UNICODE_BETA__",
    "γ": "__UNICODE_GAMMA__",
    "δ": "__UNICODE_DELTA__",
    "Δ": "__UNICODE_DELTA_CAP__",
    "→": "__UNICODE_RARROW__",
    "←": "__UNICODE_LARROW__",
    "↑": "__UNICODE_UARROW__",
    "↓": "__UNICODE_DARROW__",
    "∞": "__UNICODE_INF__",
    "∑": "__UNICODE_SUM__",
    "∏": "__UNICODE_PROD__",
    "√": "__UNICODE_SQRT__",
    "∫": "__UNICODE_INT__",
    "∂": "__UNICODE_PARTIAL__",
    "∈": "__UNICODE_IN__",
    "∉": "__UNICODE_NOTIN__",
    "⊂": "__UNICODE_SUBSET__",
    "⊃": "__UNICODE_SUPERSET__",
    "∪": "__UNICODE_UNION__",
    "∩": "__UNICODE_INTERSECT__",
    "∧": "__UNICODE_AND__",
    "∨": "__UNICODE_OR__",
    "¬": "__UNICODE_NOT__",
    "∀": "__UNICODE_FORALL__",
    "∃": "__UNICODE_EXISTS__",
    # --- M9d additions (agent-only; not in the card-UI map) -----------------
    # Publishing punctuation the M9c pilot saw the model corrupt (en dash
    # U+2013 arrived as the control char U+0013). Protecting them keeps the raw
    # character away from the model entirely.
    "\u2013": "__UNICODE_NDASH__",       # – en dash
    "\u2014": "__UNICODE_MDASH__",       # — em dash
    "\u2026": "__UNICODE_HELLIP__",      # … horizontal ellipsis
    "\u2011": "__UNICODE_NBHYPHEN__",    # ‑ non-breaking hyphen
}

# Characters added by the agent path on top of the card-UI baseline (M9d).
M9D_AGENT_ADDITIONS = frozenset({"\u2013", "\u2014", "\u2026", "\u2011"})

# Reverse map for restoration (placeholder → character).
RESTORATION_MAP: dict[str, str] = {v: k for k, v in UNICODE_PROTECTION_MAP.items()}


def protect(text: str) -> str:
    """Replace special Unicode characters with ``__UNICODE_*__`` placeholders."""
    if not text:
        return text
    result = text
    for char, placeholder in UNICODE_PROTECTION_MAP.items():
        if char in result:
            result = result.replace(char, placeholder)
    return result


def restore(text: str) -> str:
    """Restore special Unicode characters from their placeholders."""
    if not text:
        return text
    result = text
    for placeholder, char in RESTORATION_MAP.items():
        if placeholder in result:
            result = result.replace(placeholder, char)
    return result


def protect_arguments(obj: Any) -> Any:
    """Return a copy of ``obj`` with every string value protected.

    Recurses into dicts (values only — keys are left untouched) and lists.
    Non-string scalars pass through unchanged.
    """
    if isinstance(obj, str):
        return protect(obj)
    if isinstance(obj, dict):
        return {key: protect_arguments(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [protect_arguments(item) for item in obj]
    return obj


def restore_arguments(obj: Any) -> Any:
    """Return a copy of ``obj`` with every string value restored.

    Inverse of :func:`protect_arguments`.
    """
    if isinstance(obj, str):
        return restore(obj)
    if isinstance(obj, dict):
        return {key: restore_arguments(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [restore_arguments(item) for item in obj]
    return obj
