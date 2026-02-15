"""
CBP Parser - Main Extraction Pipeline
=====================================

Primary CLI script that runs the complete CBP ruling extraction workflow.

Purpose:
- Extract structured data from CBP rulings using regex (always) + LLM (optional)
- Compare results against benchmark "ground truth"
- Generate detailed triage reports showing where methods agree/disagree
- Optionally export to Excel for manual review

Usage:
  python extract_rulings.py                    # Fast: regex only, JSON output
  python extract_rulings.py --llm              # Full: regex + LLM comparison
  python extract_rulings.py --excel            # Regex + Excel review (no LLM)
  python extract_rulings.py --llm --excel      # Full + Excel review
  python extract_rulings.py --base-dir /path   # Custom base directory (instead of cwd)
"""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime as dt

# Core pipeline modules
from cbp_parser.constants import FALLBACK_RULING_IDS
from cbp_parser.io_inputs import load_ruling_ids, load_benchmark_spec, load_benchmark_values
from cbp_parser.parsers import extract_record
from cbp_parser.tier_fetchers import fetch_tier_3
from cbp_parser.schema import export_to_goal_schema
from cbp_parser.llm import llm_extract
from cbp_parser.reports import triage_report_goal
from cbp_parser.utils import ensure_dir, load_json_if_exists
from cbp_parser.excel_export import export_to_excel
from cbp_parser.fetchers_report import run_all_tiers, export_fetchers_report


def main() -> None:
    # ====================
    # COMMAND LINE SETUP
    # ====================

    parser = argparse.ArgumentParser(
        description="CBP ruling extraction: regex + optional LLM, with benchmark comparison."
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Also run LLM extraction via the default OpenAI 5 Nano Model API, or the speccified optional model"
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="Export results to Excel workbook (out/04_review/review.xlsx)"
    )
    parser.add_argument(
        "--base_dir",
        type=str,
        default=None,
        help="Base directory for in/, out/, cache/ (default: current working directory)"
    )
    parser.add_argument(
    "--fetchers_report",
    action="store_true",
    help="Run all 3 tiers and generate fetchers comparison report (out/05_fetchers_report/)"
)
    
    args = parser.parse_args()

    # ====================
    # DIRECTORY STRUCTURE
    # ====================

    # Use provided base_dir or default to current working directory
    if args.base_dir:
        base_dir = os.path.abspath(args.base_dir)
    else:
        base_dir = os.getcwd()

    cache_dir = os.path.join(base_dir, "cache")
    out_dir = os.path.join(base_dir, "out")
    raw_dir = os.path.join(out_dir, "02_extractions_raw")     # Raw extraction results
    checks_dir = os.path.join(out_dir, "03_checks")           # Comparison/triage reports
    review_dir = os.path.join(out_dir, "04_review")           # Excel exports (if --excel)
    fetchers_report_dir = os.path.join(out_dir, "04_review")    # Fetcher report (if --fetchers_report)

    # Create all output directories
    for d in [cache_dir, out_dir, raw_dir, checks_dir]:
        ensure_dir(d)

    if args.excel:
        ensure_dir(review_dir)

    # ====================
    # OUTPUT FILE PATHS
    # ====================

    llm_raw_path = os.path.join(raw_dir, "extract__llm__raw__all.json")
    regex_raw_path = os.path.join(raw_dir, "extract__regex__raw__all.json")
    triage_path = os.path.join(checks_dir, "check__triage__bench_regex_llm__goal__all.json")
    excel_path = os.path.join(review_dir, "review.xlsx") if args.excel else None

    # ====================
    # BENCHMARK SETUP
    # ====================

    # Load benchmark specification (field definitions, regex patterns)
    # and ground truth values for comparison
    bench_spec = load_benchmark_spec(base_dir)
    bench_values = load_benchmark_values(base_dir)

    # ====================
    # LOAD/INIT RESULTS
    # ====================

    # Load cached LLM results if available (avoids redundant API calls)
    llm_raw_records: List[Dict] = []
    llm_updated_this_run = False
    if not args.llm:
        cached = load_json_if_exists(llm_raw_path)
        if isinstance(cached, list):
            # Convert cached LLM results to goal schema format for comparison
            llm_raw_records = [export_to_goal_schema(r, bench_spec) for r in cached]

    regex_raw_records: List[Dict] = []

    # ====================
    # PROCESS ALL RULINGS
    # ====================

    # Get list of ruling IDs to process (from config file or fallback list)
    ruling_ids = load_ruling_ids(base_dir, fallback=FALLBACK_RULING_IDS)

    # Main extraction loop: one ruling at a time
    for rid in ruling_ids:
        # ALWAYS run regex extraction (fast, reliable baseline)
        rec, text = extract_record(rid, cache_dir=cache_dir)
        regex_raw_records.append(export_to_goal_schema(asdict(rec), bench_spec))

        # OPTIONAL LLM extraction (slower, called only with --llm flag)
        if args.llm:
            try:
                llm_obj = llm_extract(text, ruling_id=rid)  # ← Use KEYWORD argument
                llm_raw_records.append(export_to_goal_schema(llm_obj, bench_spec))
                llm_updated_this_run = True
            except Exception as e:
                # Graceful error handling - don't crash pipeline on LLM failure
                print(f"[LLM ERROR] {rid}: {e}")

    if args.fetchers_report:
        print("\n" + "=" * 60)
        print("RUNNING FETCHERS REPORT")
        print("=" * 60)
        fetchers_results = run_all_tiers(ruling_ids, cache_dir)
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        fetchers_excel_path = os.path.join(fetchers_report_dir, f"fetchers_report_{timestamp}.xlsx")
        export_fetchers_report(fetchers_results, fetchers_excel_path)

    # ====================
    # SAVE RAW EXTRACTIONS
    # ====================

    # Store regex results (always generated)
    with open(regex_raw_path, "w", encoding="utf-8") as f:
        json.dump(regex_raw_records, f, ensure_ascii=False, indent=2)

    # Store LLM results (only if --llm was used and extraction succeeded)
    if args.llm and llm_raw_records:
        with open(llm_raw_path, "w", encoding="utf-8") as f:
            json.dump(llm_raw_records, f, ensure_ascii=False, indent=2)

    # ====================
    # GENERATE TRIAGE REPORT
    # ====================

    # Create comprehensive comparison report: regex vs LLM vs benchmark
    # include_fields_where_method_vs_bench=True → shows all fields where
    # any method disagrees with benchmark (key for research analysis)
    triage = triage_report_goal(
        regex_raw_records=regex_raw_records,
        llm_raw_records=llm_raw_records,
        bench_values=bench_values,
        bench_spec=bench_spec,
        include_fields_where_method_vs_bench=True,
    )

    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(triage, f, ensure_ascii=False, indent=2)

    # ====================
    # OPTIONAL EXCEL EXPORT
    # ====================

    if args.excel and excel_path:

        from datetime import datetime

        export_to_excel(
            output_path=excel_path,
            triage=triage,
            bench_spec=bench_spec,
            regex_records=regex_raw_records,
            llm_records=llm_raw_records,
            bench_values=bench_values,
            llm_enabled=args.llm,
            llm_updated_this_run=llm_updated_this_run,
            timestamp=datetime.now()
        )


    if args.fetchers_report:
        print(f"Fetchers report: {fetchers_excel_path}")


    # ====================
    # SUMMARY OUTPUT
    # ====================

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Base directory: {base_dir}")
    print(f"Rulings processed: {len(regex_raw_records)}")
    print(f"Regex results: {regex_raw_path}")
    if args.llm:
        print(f"LLM results: {llm_raw_path}")
    print(f"Triage report: {triage_path}")
    if args.excel and excel_path:
        print(f"Excel export: {excel_path}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
