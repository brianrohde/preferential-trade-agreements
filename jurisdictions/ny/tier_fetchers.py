"""
CBP Parser - Tier Fetchers
==========================

Unified module for fetching CBP ruling text via multiple strategies:
- Tier 1: JSON API (fast, potentially incomplete)
- Tier 2: HTML Page (medium speed, consistent structure)
- Tier 3: Document Download (slow, highest quality)

All tiers return the same interface: (normalized_text, pretty_text, source_meta)
"""

import os
import re
import json
from typing import Tuple, Dict, Optional
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import io

# Constants
from .constants import YEAR_CANDIDATES, DOC_URL_TEMPLATE
# Shared utilities
from shared.utils import ensure_dir, read_text, normalize_text


# =========================
# TIER 1: JSON API
# =========================

def fetch_tier_1(ruling_id: str, cache_dir: str) -> Tuple[str, str, Dict]:
    """
    Fetch ruling text from CBP JSON API.
    
    Uses undocumented endpoint: https://rulings.cbp.gov/api/ruling/{ruling_id}
    
    Args:
        ruling_id: CBP ruling identifier (e.g., "N340865")
        cache_dir: Directory for caching artifacts
    
    Returns:
        (normalized_text, pretty_text, meta)
        - normalized_text: single-space collapsed for regex
        - pretty_text: line-structured for header/signature parsing
        - meta: dict with source info
    
    Raises:
        RuntimeError: If API call fails or returns unusable data
    """
    ensure_dir(cache_dir)
    ruling_id = ruling_id.strip().upper()
    
    # Cache paths specific to tier 1
    cache_json_path = os.path.join(cache_dir, f"{ruling_id}.tier1.json")
    cache_txt_path = os.path.join(cache_dir, f"{ruling_id}.tier1.normalized.txt")
    cache_pretty_path = os.path.join(cache_dir, f"{ruling_id}.tier1.pretty.txt")
    
    # Return cached if available
    if os.path.exists(cache_txt_path) and os.path.exists(cache_pretty_path):
        return (
            read_text(cache_txt_path),
            read_text(cache_pretty_path),
            {"source": "tier_1_json_api", "cached": True}
        )
    
    # Fetch from API
    api_url = f"https://rulings.cbp.gov/api/ruling/{ruling_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        # Save raw JSON
        with open(cache_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Extract text from JSON structure
        raw_text = None
        if isinstance(data, dict) and data.get("rulingText"):
            raw_text = data["rulingText"]
        elif isinstance(data, dict) and data.get("attachments"):
            attachments = data["attachments"]
            if isinstance(attachments, list) and attachments:
                raw_text = attachments[0].get("content", "")
        
        if not raw_text:
            raise RuntimeError(f"No usable text in API response for {ruling_id}")
        
        # Convert to normalized and pretty formats
        soup = BeautifulSoup(raw_text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        
        text_normalized = normalize_text(soup.get_text("\n"))
        
        # Pretty text: preserve line structure
        text_pretty = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text_pretty.splitlines() if ln.strip()]
        text_pretty = "\n".join(lines)
        
        # Cache results
        with open(cache_txt_path, "w", encoding="utf-8") as f:
            f.write(text_normalized)
        with open(cache_pretty_path, "w", encoding="utf-8") as f:
            f.write(text_pretty)
        
        return (
            text_normalized,
            text_pretty,
            {"source": "tier_1_json_api", "cached": False, "api_url": api_url}
        )
        
    except Exception as e:
        raise RuntimeError(f"Tier 1 API fetch failed for {ruling_id}: {e}")


# =========================
# TIER 2: HTML PAGE
# =========================

def fetch_tier_2(ruling_id: str, cache_dir: str) -> Tuple[str, str, Dict]:
    """
    Fetch ruling text from public HTML page.
    
    Uses public URL: https://rulings.cbp.gov/ruling/{ruling_id}
    Also attempts to extract embedded JSON from <script> tags as fallback.
    
    Args:
        ruling_id: CBP ruling identifier
        cache_dir: Directory for caching artifacts
    
    Returns:
        (normalized_text, pretty_text, meta)
    
    Raises:
        RuntimeError: If page fetch fails or contains no usable text
    """
    ensure_dir(cache_dir)
    ruling_id = ruling_id.strip().upper()
    
    # Cache paths specific to tier 2
    cache_html_path = os.path.join(cache_dir, f"{ruling_id}.tier2.html")
    cache_txt_path = os.path.join(cache_dir, f"{ruling_id}.tier2.normalized.txt")
    cache_pretty_path = os.path.join(cache_dir, f"{ruling_id}.tier2.pretty.txt")
    
    # Return cached if available
    if os.path.exists(cache_txt_path) and os.path.exists(cache_pretty_path):
        return (
            read_text(cache_txt_path),
            read_text(cache_pretty_path),
            {"source": "tier_2_html_page", "cached": True}
        )
    
    # Fetch HTML page
    page_url = f"https://rulings.cbp.gov/ruling/{ruling_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(page_url, headers=headers, timeout=20)
        response.raise_for_status()
        html_content = response.text
        
        # Save raw HTML
        with open(cache_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Try to extract rulingText from embedded JSON in script tags (fallback)
        ruling_text_from_script = None
        for script in soup.find_all("script"):
            if script.string and "rulingText" in script.string:
                try:
                    json_match = re.search(r'\{.*"rulingText".*\}', script.string, re.DOTALL)
                    if json_match:
                        payload = json.loads(json_match.group(0))
                        if isinstance(payload, dict) and payload.get("rulingText"):
                            ruling_text_from_script = payload["rulingText"]
                            break
                except Exception:
                    pass
        
        # If we found embedded JSON, use it; otherwise use full page HTML
        if ruling_text_from_script:
            soup = BeautifulSoup(ruling_text_from_script, "html.parser")
        
        # Remove non-visible elements
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        
        # Normalized text
        text_normalized = normalize_text(soup.get_text("\n"))
        
        # Pretty text: preserve structure
        text_pretty = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text_pretty.splitlines() if ln.strip()]
        text_pretty = "\n".join(lines)
        
        # Cache results
        with open(cache_txt_path, "w", encoding="utf-8") as f:
            f.write(text_normalized)
        with open(cache_pretty_path, "w", encoding="utf-8") as f:
            f.write(text_pretty)
        
        return (
            text_normalized,
            text_pretty,
            {"source": "tier_2_html_page", "cached": False, "page_url": page_url}
        )
        
    except Exception as e:
        raise RuntimeError(f"Tier 2 HTML fetch failed for {ruling_id}: {e}")


# =========================
# TIER 3: DOCUMENT DOWNLOAD (Refactored from cbp_download.py)
# =========================

def _extract_text_from_cfb_doc_with_word(doc_path: str) -> str:
    """
    Use Microsoft Word (COM) to open a legacy .doc (CFB) and return text.
    Requires Windows + Word installed + pywin32.
    """
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise RuntimeError("pywin32 is required: python -m pip install pywin32") from e
    
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(doc_path), ReadOnly=True)
        try:
            return doc.Content.Text or ""
        finally:
            doc.Close(False)
    finally:
        word.Quit()


def _doc_bytes_to_text(doc_bytes: bytes) -> str:
    """Convert CBP .doc bytes (usually HTML) to normalized text."""
    html = doc_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return normalize_text(text)


def _doc_bytes_to_pretty_text(doc_bytes: bytes) -> str:
    """Convert CBP .doc bytes to pretty (line-structured) text."""
    html = doc_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Remove Word field-code artifacts
    text = re.sub(r"PAGE\s*\\\*\s*MERGEFORMAT\s*\d*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\\\*\s*MERGEFORMAT\s*\d*", "", text, flags=re.IGNORECASE)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def fetch_tier_3(ruling_id: str, cache_dir: str) -> Tuple[str, str, Dict]:
    """
    Download ruling document (.doc or .pdf) and extract text.
    
    This is the refactored version of cbp_download.py's download_doc_text().
    
    Args:
        ruling_id: CBP ruling identifier
        cache_dir: Directory for caching artifacts
    
    Returns:
        (normalized_text, pretty_text, meta)
    
    Raises:
        RuntimeError: If document cannot be found in any candidate year
    """
    ensure_dir(cache_dir)
    ruling_id = ruling_id.strip().upper()
    
    # Cache paths (keep same naming as original for compatibility)
    cache_txt_path = os.path.join(cache_dir, f"{ruling_id}.normalized.txt")
    cache_pretty_path = os.path.join(cache_dir, f"{ruling_id}.pretty.txt")
    cache_raw_doc_path = os.path.join(cache_dir, f"{ruling_id}.raw.doc")
    cache_raw_pdf_path = os.path.join(cache_dir, f"{ruling_id}.raw.pdf")
    cache_html_path = os.path.join(cache_dir, f"{ruling_id}.raw.html")
    
    # Return cached if available
    if os.path.exists(cache_txt_path) and os.path.exists(cache_pretty_path):
        return (
            read_text(cache_txt_path),
            read_text(cache_pretty_path),
            {"source": "tier_3_document_download", "cached": True}
        )
    
    headers = {"User-Agent": "Mozilla/5.0"}
    last_404_url = None
    
    # Try each year until document is found
    for year in YEAR_CANDIDATES:
        url = DOC_URL_TEMPLATE.format(year=year, ruling_id=ruling_id)
        r = requests.get(url, headers=headers, timeout=60)
        
        if r.status_code == 404:
            last_404_url = url
            continue
        
        r.raise_for_status()
        data = r.content
        
        # Detect file type
        head8 = data[:8]
        is_pdf = data[:4] == b"%PDF"
        is_cfb = head8 == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
        looks_like_html = (b"<html" in data[:200].lower() or b"<!doctype" in data[:200].lower())
        
        if is_pdf:
            # Save raw PDF
            with open(cache_raw_pdf_path, "wb") as f:
                f.write(data)
            
            # Extract text from PDF
            pdf_reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join(page.extract_text() or "" for page in pdf_reader.pages)
            text_normalized = normalize_text(text)
            text_pretty = text  # PDF extraction doesn't have clean line structure
            
        elif is_cfb:
            # Real legacy .doc file - requires Word COM
            with open(cache_raw_doc_path, "wb") as f:
                f.write(data)
            text = _extract_text_from_cfb_doc_with_word(cache_raw_doc_path)
            text_normalized = normalize_text(text)
            text_pretty = text
            
        elif looks_like_html:
            # HTML-based .doc (most common)
            with open(cache_raw_doc_path, "wb") as f:
                f.write(data)
            with open(cache_html_path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(data.decode("utf-8", errors="ignore"))
            
            text_normalized = _doc_bytes_to_text(data)
            text_pretty = _doc_bytes_to_pretty_text(data)
        
        else:
            raise RuntimeError(f"Unknown file format for {ruling_id}")
        
        # Cache results
        with open(cache_txt_path, "w", encoding="utf-8") as f:
            f.write(text_normalized)
        with open(cache_pretty_path, "w", encoding="utf-8") as f:
            f.write(text_pretty)
        
        return (
            text_normalized,
            text_pretty,
            {"source": "tier_3_document_download", "cached": False, "url": url, "year": year}
        )
    
    raise RuntimeError(f"Could not find document for {ruling_id} in any year. Last tried: {last_404_url}")


# =========================
# CONVENIENCE WRAPPER
# =========================

def fetch_ruling_text(ruling_id: str, cache_dir: str, tier: int = 3) -> Tuple[str, str, Dict]:
    """
    Fetch ruling text using specified tier.
    
    Args:
        ruling_id: CBP ruling identifier
        cache_dir: Cache directory
        tier: Which tier to use (1=API, 2=HTML, 3=Document)
    
    Returns:
        (normalized_text, pretty_text, meta)
    """
    if tier == 1:
        return fetch_tier_1(ruling_id, cache_dir)
    elif tier == 2:
        return fetch_tier_2(ruling_id, cache_dir)
    elif tier == 3:
        return fetch_tier_3(ruling_id, cache_dir)
    else:
        raise ValueError(f"Invalid tier: {tier}. Must be 1, 2, or 3.")
