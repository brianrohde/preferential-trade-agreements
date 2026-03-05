"""
CBP Parser - Core Utilities Module
==================================
Shared helper functions used across the entire CBP ruling extraction pipeline.
These handle file operations, text normalization, and pattern matching.

Purpose: Clean, reusable utilities that make CBP HTML documents easier to process.
Supports both regex and LLM extraction workflows.
"""

import json
import os
import re
from typing import Optional, List


# =========================
# FILE SYSTEM HELPERS
# =========================
# These functions handle common file/directory operations needed by the pipeline

def ensure_dir(path: str) -> None:
    """Create directory if it doesn't exist. 
    Used for output folders like reports/ or cache/."""
    os.makedirs(path, exist_ok=True)


def read_text(path: str) -> str:
    """Safely read UTF-8 text file. 
    Used for loading pretty-printed CBP rulings."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_json_if_exists(path: str):
    """Load JSON file if it exists, return None otherwise.
    Graceful fallback for missing benchmark files or previous results."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# TEXT NORMALIZATION
# =========================
# CBP HTML has messy whitespace - these functions clean it up for reliable matching

def collapse_ws(s: str) -> str:
    """Collapse all whitespace (spaces, tabs, newlines) to single spaces and strip.
    
    Example: "Hello   \n\n\tWorld!" → "Hello World"
    
    Used everywhere to normalize extracted text before comparison.
    """
    return " ".join(s.split()).strip()


def normalize_text(text: str) -> str:
    """Full text cleanup for CBP documents:
    - Convert Windows line endings to Unix
    - Collapse horizontal whitespace to single spaces  
    - Limit consecutive newlines to double-spacing
    - Strip leading/trailing whitespace
    
    Result: Consistent text ready for regex or LLM processing.
    """
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =========================
# PATTERN MATCHING
# =========================
# Smart regex helper used by extractors to find ruling sections

def first_match(patterns: List[str], text: str, flags=re.IGNORECASE) -> Optional[str]:
    """
    Try multiple regex patterns in order, return first match (normalized).
    
    Args:
        patterns: List of regex patterns to try
        text: Input text to search
        flags: Regex flags (default: case-insensitive)
    
    Returns:
        First matched group(1), normalized with collapse_ws(), or None
    
    Usage: Extractors call this to find ruling HTS codes, countries, etc.
           Stops at first successful match.
    """
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return re.sub(r"\s+", " ", m.group(1).strip())
    return None
