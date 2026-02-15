"""
CBP Parser - Data Schema Module
===============================
Defines standardized data structures and normalization rules for CBP rulings.

Purpose: 
- Ensure consistent field ordering and formatting across all extraction methods
- Convert internal data structures to benchmark "goal schema" format
- Handle special formatting requirements (like replying_person HTML)

Used by: reports.py to compare regex/LLM/benchmark results fairly.
"""

from typing import Dict

from shared.utils import collapse_ws



# =========================
# GOAL SCHEMA NORMALIZATION / EXPORT
# =========================
# Converts internal data structures to the exact format expected by benchmark tests

def normalize_replying_person(val: str) -> str:
    """
    Format replying_person field to match benchmark "goal" requirements.
    
    Benchmark expects literal '<br><br>' between signature lines.
    This function handles three input formats:
    1. Already HTML with <br> tags (normalizes spacing)
    2. Plain text with newlines (converts to <br>)
    3. Single line text (keeps as-is)
    
    Example:
        "John Doe\nCustoms Officer" → "John Doe<br>Customs Officer"
    """
    if val is None:
        return None
    if not isinstance(val, str):
        return val

    v = val.strip()
    if not v:
        return None

    # Already contains <br> -> normalize per segment but preserve delimiter
    if "<br" in v.lower():
        # normalize common variants to exact delimiter
        v = v.replace("<br />", "<br>").replace("<br/>", "<br>")
        parts = [p for p in v.split("<br>")]
        parts = [collapse_ws(p) for p in parts if collapse_ws(p)]
        return "<br>".join(parts)

    # Otherwise treat as multiline plain text
    lines = [ln.strip() for ln in v.splitlines() if ln.strip()]
    if len(lines) >= 2:
        lines = [collapse_ws(x) for x in lines if collapse_ws(x)]
        return "<br>".join(lines)

    return collapse_ws(v)


def export_to_goal_schema(internal_obj: dict, bench_spec: dict) -> dict:
    """
    Convert internal ruling data to canonical "goal schema" format for benchmarking.
    
    Benchmark tests require:
    1. Exact field ordering (from bench_spec["output"]["field_order"])
    2. Normalized replying_person HTML formatting  
    3. Collapsed whitespace on all other string fields
    
    Args:
        internal_obj: Dict with canonical underscore keys (hts_code, ruling_number, etc)
        bench_spec: Benchmark specification with required field_order
    
    Returns:
        Benchmark-ready dict with normalized formatting
    """
    field_order = bench_spec["output"]["field_order"]

    out = {}
    for k in field_order:
        out[k] = internal_obj.get(k)

    # Special formatting rule for benchmark compatibility
    out["replying_person"] = normalize_replying_person(out.get("replying_person"))

    # Generic whitespace collapse for other strings (skip replying_person, already handled)
    for k, v in list(out.items()):
        if v is None or not isinstance(v, str) or k == "replying_person":
            continue
        out[k] = collapse_ws(v)

    return out
