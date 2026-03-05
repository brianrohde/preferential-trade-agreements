"""
CBP Parser - Input Loaders
=========================
File and configuration loaders for the CBP ruling extraction pipeline.

This module handles:
- Loading ruling IDs from standard input locations (JSON/CSV/XLSX).
- Loading benchmark specification and benchmark values used for evaluation.

Purpose: Provide a simple, spec-driven way to locate inputs while keeping the
rest of the pipeline independent of file formats.
"""


import csv
import json
import os
from typing import List, Dict, Tuple


# Optional dependency: XLSX support requires pandas (and typically openpyxl).
# If pandas is not installed, XLSX inputs will raise a clear ImportError.
try:
    import pandas as pd
except ImportError:
    pd = None


# =========================
# INPUT LOADING
# =========================
# Ruling IDs can be provided in multiple formats; this module tries them in order:
# JSON -> CSV -> XLSX -> fallback argument.


def _normalize_ruling_ids(items: List[str]) -> List[str]:
    """
    Normalize a list of ruling IDs into a clean, unique, stable-ordered list.

    Rules:
    - Coerce non-strings to strings.
    - Strip leading/trailing whitespace.
    - Drop empty values and duplicates (first occurrence wins).

    Returns:
        List of cleaned ruling-id strings.
    """
    cleaned = []
    seen = set()

    for rid in items:
        if rid is None:
            continue
        if not isinstance(rid, str):
            rid = str(rid)

        rid2 = rid.strip()
        if not rid2 or rid2 in seen:
            continue

        seen.add(rid2)
        cleaned.append(rid2)

    return cleaned


def load_ruling_ids(base_dir: str, fallback: List[str], jurisdiction: str = "ny") -> Tuple[List[str], str]:
    """
    Load ruling IDs from the standard input folder, falling back to provided defaults.

    Search order (first match wins):
    0) input_data/{jurisdiction}/ruling_ids/{jurisdiction}_ruling_ids_scraper.jsonl
    1) input_data/{jurisdiction}/ruling_ids/ruling_ids.json
    2) input_data/{jurisdiction}/ruling_ids/ruling_ids.csv
    3) input_data/{jurisdiction}/ruling_ids/ruling_ids.xlsx  (requires pandas + openpyxl)
    4) fallback list passed by caller

    Args:
        base_dir: Project base directory containing the `input_data/` folder.
        fallback: Ruling IDs to use if no input file exists.
        jurisdiction: Jurisdiction subfolder name (e.g. "ny", "ca").

    Returns:
        Tuple of (normalized list of ruling IDs, source description string).
    """
    rulings_dir = os.path.join(base_dir, "input_data", jurisdiction, "ruling_ids")
    jsonl_path = os.path.join(rulings_dir, f"{jurisdiction}_ruling_ids_scraper.jsonl")
    json_path = os.path.join(rulings_dir, "ruling_ids.json")
    csv_path = os.path.join(rulings_dir, "ruling_ids.csv")
    xlsx_path = os.path.join(rulings_dir, "ruling_ids.xlsx")

    # 0) JSONL scraper file
    # One JSON object per line. Skip lines where "type" == "session_summary".
    # Extract "ruling_number" from each remaining line.
    if os.path.exists(jsonl_path):
        ids = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "session_summary":
                    continue
                ruling_number = obj.get("ruling_number")
                if ruling_number is not None:
                    ids.append(ruling_number)
        ids = _normalize_ruling_ids(ids)
        return ids, f"JSONL scraper ({jurisdiction}_ruling_ids_scraper.jsonl) — {len(ids)} rulings"

    # 1) JSON
    # Accepted JSON shapes:
    # - A list: ["N340865", ...]
    # - A dict with a "ruling_ids" list: {"ruling_ids": [...]}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            obj = json.load(f)

        if isinstance(obj, list):
            ids = _normalize_ruling_ids(obj)
            return ids, f"JSON file (ruling_ids.json) — {len(ids)} rulings"

        if isinstance(obj, dict) and isinstance(obj.get("ruling_ids"), list):
            ids = _normalize_ruling_ids(obj["ruling_ids"])
            return ids, f"JSON file (ruling_ids.json) — {len(ids)} rulings"

        raise ValueError("ruling_ids.json must be a list or a dict with key 'ruling_ids' (list)")

    # 2) CSV
    # Supports either:
    # - Headered CSV with a "ruling_id" column (preferred), or
    # - Headerless CSV where the first column contains ruling IDs.
    if os.path.exists(csv_path):
        ids = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                # Prefer named columns if present; otherwise use the first column.
                lowered = {h.lower(): h for h in reader.fieldnames}
                col = lowered.get("ruling_id") or lowered.get("ruling_id") or reader.fieldnames[0]
                for row in reader:
                    ids.append(row.get(col))
            else:
                # No header: read first column.
                f.seek(0)
                raw = csv.reader(f)
                for row in raw:
                    if row:
                        ids.append(row[0])

        ids = _normalize_ruling_ids(ids)
        return ids, f"CSV file (ruling_ids.csv) — {len(ids)} rulings"

    # 3) XLSX (requires pandas + openpyxl)
    # Reads the first sheet by default. Prefers a "ruling_id" column if present;
    # otherwise uses the first column in the sheet.
    if os.path.exists(xlsx_path):
        if pd is None:
            raise ImportError("Excel ruling IDs found but pandas is not installed. Install: pip install pandas openpyxl")

        df = pd.read_excel(xlsx_path)  # first sheet by default
        if df.shape[1] == 0:
            ids = _normalize_ruling_ids([])
            return ids, f"Excel file (ruling_ids.xlsx) — {len(ids)} rulings"

        # Prefer named columns; otherwise first column.
        cols = {c.lower(): c for c in df.columns if isinstance(c, str)}
        col = cols.get("ruling_id") or cols.get("ruling_id") or df.columns[0]
        ids = _normalize_ruling_ids(df[col].tolist())
        return ids, f"Excel file (ruling_ids.xlsx) — {len(ids)} rulings"

    # 4) Fallback
    ids = _normalize_ruling_ids(fallback)
    return ids, f"Fallback config list — {len(ids)} rulings"


# =========================
# BENCHMARK LOADERS
# =========================
# These are small helpers that read the benchmark JSON files in fixed locations.


def load_benchmark_spec(base_dir: str, jurisdiction: str = "ny") -> dict:
    """
    Load the benchmark specification JSON.

    The spec typically contains output field ordering and formatting rules used
    by the rest of the pipeline (export, comparisons, reports).

    Args:
        base_dir: Project base directory containing the `input_data/` folder.
        jurisdiction: Jurisdiction subfolder name (e.g. "ny", "ca").
    """
    path = os.path.join(base_dir, "input_data", jurisdiction, "benchmarks", "benchmark_spec.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_benchmark_values(base_dir: str, jurisdiction: str = "ny") -> List[Dict]:
    """
    Load the benchmark "gold" values JSON.

    Args:
        base_dir: Project base directory containing the `input_data/` folder.
        jurisdiction: Jurisdiction subfolder name (e.g. "ny", "ca").

    Returns:
        List of goal-schema records keyed by `ruling_id`, used for evaluation.
    """
    path = os.path.join(base_dir, "input_data", jurisdiction, "benchmarks", "benchmark_values.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
