"""
CBP Parser - Document Download + Caching
=======================================
Download CBP ruling “.doc” files, cache them locally, and convert them into
plain text suitable for regex/LLM extraction.

Key details:
- CBP “.doc” downloads are often HTML produced by Microsoft Word, not binary
  Word documents, so they can be parsed as HTML and converted to visible text.
- This module caches multiple artifact forms per ruling_id:
  - Raw .doc bytes (as downloaded)
  - Decoded HTML (for debugging/inspection)
  - Normalized text (collapsed/cleaned for regex searching)
  - “Pretty” text (line-structured for header/signature parsing)

Purpose: Provide a single, reliable API (`download_doc_text`) for extractors to
fetch text without worrying about networking or cache layout.
"""


import os
import re
from typing import Tuple

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import io
import subprocess
import time

# Constants
from .constants import YEAR_CANDIDATES, DOC_URL_TEMPLATE

# Shared utilities
from shared.utils import ensure_dir, read_text, normalize_text


# =========================
# CBP DOWNLOAD + CACHE + HTML -> TEXT
# =========================
# Core conversion and caching logic for CBP ruling documents.


def _extract_text_from_cfb_doc_with_word(doc_path: str) -> str:
    """
    Use Microsoft Word (COM) to open a legacy .doc (CFB) and return text.
    Requires Windows + Word installed + pywin32.
    """
    try:
        import win32com.client  # type: ignore
    except ImportError as e:
        raise RuntimeError("pywin32 is required: python -m pip install pywin32") from e

    word = win32com.client.DispatchEx("Word.Application")  # isolated instance [web:619]
    word.Visible = False

    try:
        doc = word.Documents.Open(os.path.abspath(doc_path), ReadOnly=True)
        try:
            return doc.Content.Text or ""
        finally:
            doc.Close(False)
    finally:
        word.Quit()




def doc_bytes_to_text(doc_bytes: bytes) -> str:
    """
    Convert downloaded CBP .doc bytes to normalized visible text.

    These CBP ".doc" downloads are commonly HTML produced by Word, so the
    conversion step is:
    1) Decode bytes -> HTML string.
    2) Parse HTML.
    3) Remove non-visible/script/style content.
    4) Extract visible text and normalize whitespace.

    Returns:
        Normalized text (single-space collapsed, stable newlines) intended for
        robust regex searching.
    """
    html = doc_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    # Remove tags that should not contribute to visible text.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n")
    return normalize_text(text)


def doc_bytes_to_pretty_text(docbytes: bytes) -> str:
    """
    Convert downloaded CBP .doc bytes to a “pretty” text variant.

    “Pretty” text aims to preserve letter-like structure (one line per logical
    block) which helps header parsing (dates/addresses) and signature parsing
    (replying person, titles, divisions).

    Returns:
        A newline-joined text block with empty lines removed.
    """
    html = docbytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    # Remove tags that should not contribute to visible text.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Preserve structure: force line breaks between blocks.
    text = soup.get_text(separator="\n")

    # Remove common Word field-code artifacts that sometimes leak into extracted text.
    text = re.sub(r"PAGE\s*\\\*\s*MERGEFORMAT\s*\d*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\\\*\s*MERGEFORMAT\s*\d*", "", text, flags=re.IGNORECASE)

    # Clean up while keeping line structure.
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]  # drop empty lines
    return "\n".join(lines)


def download_doc_text(ruling_id: str, cache_dir: str) -> Tuple[str, str]:
    """
    Download (or load from cache) the ruling document for a given ruling_id.

    Cache behavior:
    - If all expected cache files exist, return cached text immediately (no network).
    - Otherwise, try downloading for each candidate year until one succeeds.

    Args:
        ruling_id: CBP ruling identifier (e.g., "N340865").
        cache_dir: Directory used to store cached artifacts.

    Returns:
        (text, pretty)
        - text: normalized visible text for regex searching.
        - pretty: line-structured text used for header/signature parsing.

    Raises:
        RuntimeError: If the document cannot be found in any YEAR_CANDIDATES year.
        requests.HTTPError: If a non-404 HTTP error occurs during download.
    """
    ensure_dir(cache_dir)

    # Existing cache (normalized text)
    cache_txt_path = os.path.join(cache_dir, f"{ruling_id}.normalized.txt")

    # New caches (raw + html)
    cache_raw_doc_path = os.path.join(cache_dir, f"{ruling_id}.raw.doc")  # HTML-doc bytes
    cache_raw_pdf_path = os.path.join(cache_dir, f"{ruling_id}.raw.pdf")  # PDF bytes
    cache_pdf_debug_path = os.path.join(cache_dir, f"{ruling_id}.pdf")    # same as raw.pdf, explicit name for transparency
    cache_html_path = os.path.join(cache_dir, f"{ruling_id}.raw.html")    # only for HTML-doc branch (decoded)
    cache_pretty_path = os.path.join(cache_dir, f"{ruling_id}.pretty.txt")

    # If we already have all artifacts, return cached variants (no network).
    if os.path.exists(cache_txt_path) and os.path.exists(cache_pretty_path):
        return read_text(cache_txt_path), read_text(cache_pretty_path)

    # Use a browser-like user agent to reduce the risk of being blocked.
    headers = {"User-Agent": "Mozilla/5.0"}

    last_404_url = None

    # Try each year candidate in order until the document is found.
    for year in YEAR_CANDIDATES:
        url = DOC_URL_TEMPLATE.format(year=year, ruling_id=ruling_id)
        r = requests.get(url, headers=headers, timeout=60)

        # 404 means “not found for this year”; continue trying other years.
        if r.status_code == 404:
            last_404_url = url
            continue

        # Any other non-success code should fail fast.
        r.raise_for_status()

        data = r.content
        head8 = data[:8]
        head_lower = data[:200].lower()

        is_pdf = data[:4] == b"%PDF"
        is_cfb = head8 == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"  # Compound File Binary (legacy Office) [web:468]
        looks_like_html = (b"<html" in head_lower) or (b"<!doctype html" in head_lower) or (b"<body" in head_lower)

        # 1) PDF branch
        if is_pdf:
            with open(cache_raw_pdf_path, "wb") as f:
                f.write(data)
            with open(cache_pdf_debug_path, "wb") as f:
                f.write(data)

            reader = PdfReader(io.BytesIO(data))
            pages_text = [(p.extract_text() or "") for p in reader.pages]
            pretty = normalize_text("\n".join(pages_text))

            with open(cache_pretty_path, "w", encoding="utf-8") as f:
                f.write(pretty)
            with open(cache_txt_path, "w", encoding="utf-8") as f:
                f.write(pretty)

            print(f"{ruling_id} downloaded PDF (served from .doc endpoint) year={year}")
            return pretty, pretty

        # 2) Legacy binary .doc (CFB) branch
        elif is_cfb:
            with open(cache_raw_doc_path, "wb") as f:
                f.write(data)

            try:
                extracted = _extract_text_from_cfb_doc_with_word(cache_raw_doc_path)  # Word COM automation [web:477]
            except Exception as e:
                raise RuntimeError(
                    f"Legacy .doc (CFB) extraction failed for {ruling_id} year={year}. "
                    f"Saved raw bytes to: {cache_raw_doc_path}. "
                    f"Requires Windows + Microsoft Word + pywin32. Underlying error: {type(e).__name__}: {e}"
                )

            pretty = normalize_text(extracted)


            with open(cache_pretty_path, "w", encoding="utf-8") as f:
                f.write(pretty)
            with open(cache_txt_path, "w", encoding="utf-8") as f:
                f.write(pretty)

            print(f"{ruling_id} downloaded legacy binary .doc (CFB) year={year}")
            return pretty, pretty

        # 3) HTML-doc branch
        elif looks_like_html:
            with open(cache_raw_doc_path, "wb") as f:
                f.write(data)

            html = data.decode("utf-8", errors="ignore")
            with open(cache_html_path, "w", encoding="utf-8") as f:
                f.write(html)

            pretty = doc_bytes_to_pretty_text(data)
            with open(cache_pretty_path, "w", encoding="utf-8") as f:
                f.write(pretty)

            text = doc_bytes_to_text(data)
            with open(cache_txt_path, "w", encoding="utf-8") as f:
                f.write(text)

            print(f"{ruling_id} downloaded HTML-doc year={year}")
            return text, pretty

        # 4) Unknown
        else:
            raise RuntimeError(
                f"Unexpected file type for {ruling_id} year={year}. "
                f"First bytes={head8!r}, Content-Type={r.headers.get('Content-Type')}"
            )

    # If all years 404, raise a clear error including the last tried URL.
    raise RuntimeError(
        f"Doc not found for {ruling_id} in any YEAR_CANDIDATES. Last tried: {last_404_url}"
    )


# =========================
# Artifacts / debugging
# =========================
# Helpers to save human-inspectable reference outputs for troubleshooting.


def save_reference_text(ruling_id: str, text: str, out_dir: str) -> None:
    """
    Save a text blob as a named reference artifact for manual inspection.

    This is typically used when debugging extraction behavior for a specific ruling.
    """
    ensure_dir(out_dir)
    path = os.path.join(out_dir, f"{ruling_id}_reference_text.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def save_reference_artifacts(ruling_id: str, cache_dir: str, artifacts_root: str) -> None:
    """
    Copy cached ruling artifacts into a per-ruling artifact folder.

    This function copies (if present):
    - Raw .doc bytes
    - Raw HTML
    - Normalized text
    - Pretty text

    Purpose: Make it easy to bundle all materials needed to debug a ruling into
    one directory under `artifacts_root/<ruling_id>/`.
    """
    out_dir = os.path.join(artifacts_root, ruling_id)
    ensure_dir(out_dir)

    src_doc = os.path.join(cache_dir, f"{ruling_id}.raw.doc")
    src_html = os.path.join(cache_dir, f"{ruling_id}.raw.html")
    src_txt = os.path.join(cache_dir, f"{ruling_id}.normalized.txt")
    src_pretty = os.path.join(cache_dir, f"{ruling_id}.pretty.txt")
    src_raw_pdf = os.path.join(cache_dir, f"{ruling_id}.raw.pdf")
    src_pdf_debug = os.path.join(cache_dir, f"{ruling_id}.pdf")


    dst_doc = os.path.join(out_dir, f"{ruling_id}.raw.doc")
    dst_html = os.path.join(out_dir, f"{ruling_id}.raw.html")
    dst_txt = os.path.join(out_dir, f"{ruling_id}.normalized.txt")
    dst_pretty = os.path.join(out_dir, f"{ruling_id}.pretty.txt")
    dst_raw_pdf = os.path.join(out_dir, f"{ruling_id}.raw.pdf")
    dst_pdf_debug = os.path.join(out_dir, f"{ruling_id}.pdf")

    pairs = [
        (src_doc, dst_doc),
        (src_html, dst_html),
        (src_txt, dst_txt),
        (src_pretty, dst_pretty),
        (src_raw_pdf, dst_raw_pdf),
        (src_pdf_debug, dst_pdf_debug),
    ]

    for src, dst in pairs:
        if os.path.exists(src):
            with open(src, "rb") as fsrc:
                data = fsrc.read()
            with open(dst, "wb") as fdst:
                fdst.write(data)

