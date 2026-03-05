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
  python main.py                        # Fast: regex only, JSON output (NY)
  python main.py --llm                  # Full: regex + LLM comparison
  python main.py --excel                # Regex + Excel review (no LLM)
  python main.py --llm --excel          # Full + Excel review
  python main.py --jurisdiction ny      # Explicit NY (default)
  python main.py --jurisdiction ca      # CA rulings (once implemented)
  python main.py --base-dir /path       # Custom base directory (instead of cwd)
"""

import argparse
import json
import os
from dataclasses import asdict
from typing import List, Dict
from datetime import datetime as dt

from shared_modules.io_inputs import load_ruling_ids, load_benchmark_spec, load_benchmark_values
from shared_modules.reports import triage_report_goal
from shared_modules.utils import ensure_dir, load_json_if_exists
from shared_modules.excel_export import export_to_excel
from shared_modules.fetchers_report import run_all_tiers, export_fetchers_report
from shared_modules.performance_logger import PerformanceLogger
from shared_modules.llm_config import LLM_PRICING



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
        help="Export results to Excel workbook"
    )
    parser.add_argument(
        "--base_dir",
        type=str,
        default=None,
        help="Base directory for input_data/, output_data/, cache_data/ (default: current working directory)"
    )
    parser.add_argument(
    "--fetchers_report",
    action="store_true",
    help="Run all 3 tiers and generate fetchers comparison report (output_data/{jurisdiction}/checks/)"
    )

    parser.add_argument(
        "--performance-log",
        action="store_true",
        help="Enable performance logging (writes to output_data/{jurisdiction}/performance_logs/)"
    )
    parser.add_argument(
        "--jurisdiction",
        type=str,
        default="ny",
        choices=["ny", "ca"],
        help="Jurisdiction to process: 'ny' (default) or 'ca'"
    )

    args = parser.parse_args()
    jurisdiction = args.jurisdiction

    # ====================
    # JURISDICTION DISPATCH
    # ====================
    # Import jurisdiction-specific modules based on --jurisdiction flag.

    if jurisdiction == "ny":
        from shared_modules.config import NY_FALLBACK_RULING_IDS
        from jurisdiction_modules.ny.ny_regex_parser import extract_record
        from jurisdiction_modules.ny.ny_schema import export_to_goal_schema
        from jurisdiction_modules.ny.ny_llm import llm_extract
    elif jurisdiction == "ca":
        raise NotImplementedError(
            "CA jurisdiction is not yet implemented. "
            "See jurisdiction_modules/ca/ to add your implementation."
        )

    # ====================
    # DIRECTORY STRUCTURE
    # ====================

    # Use provided base_dir or default to current working directory
    if args.base_dir:
        base_dir = os.path.abspath(args.base_dir)
    else:
        base_dir = os.getcwd()

    cache_dir = os.path.join(base_dir, "cache_data", jurisdiction)
    out_dir = os.path.join(base_dir, "output_data", jurisdiction)
    raw_dir = os.path.join(out_dir, "extractions_raw")     # Raw extraction results
    checks_dir = os.path.join(out_dir, "checks")           # Comparison/triage reports

    # Create all output directories
    for d in [cache_dir, out_dir, raw_dir, checks_dir]:
        ensure_dir(d)

    if args.excel:
        ensure_dir(checks_dir)

    # Performance logging setup
    perf_log_dir = os.path.join(out_dir, "performance_logs")
    perf_logger = None
    if args.performance_log:
        ensure_dir(perf_log_dir)
        perf_logger = PerformanceLogger(perf_log_dir)

    # ====================
    # OUTPUT FILE PATHS
    # ====================

    llm_raw_path = os.path.join(raw_dir, "extract__llm__raw__all.json")
    regex_raw_path = os.path.join(raw_dir, "extract__regex__raw__all.json")
    triage_path = os.path.join(checks_dir, "check__triage__bench_regex_llm__goal__all.json")
    excel_path = os.path.join(checks_dir, "review.xlsx") if args.excel else None

    # ====================
    # BENCHMARK SETUP
    # ====================

    # Load benchmark specification (field definitions, regex patterns)
    # and ground truth values for comparison
    bench_spec = load_benchmark_spec(base_dir, jurisdiction=jurisdiction)
    bench_values = load_benchmark_values(base_dir, jurisdiction=jurisdiction)

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
    # PHASE 0 — ID LOADING
    # ====================

    phase0_start = dt.now()
    ruling_ids, id_source = load_ruling_ids(base_dir, fallback=NY_FALLBACK_RULING_IDS, jurisdiction=jurisdiction)
    phase0_elapsed = (dt.now() - phase0_start).total_seconds()
    n_rulings = len(ruling_ids)

    print("\n" + "=" * 60)
    print("PHASE 0 — ID LOADING")
    print("=" * 60)
    print(f"  Source:  {id_source}")

    # ====================
    # PHASE 1 — CACHE PRE-SCAN
    # ====================

    cached_set = set()
    for rid in ruling_ids:
        if os.path.exists(os.path.join(cache_dir, f"{rid}.normalized.txt")):
            cached_set.add(rid)

    phase1_cached_count = len(cached_set)
    phase1_fetched_count = n_rulings - phase1_cached_count

    print("\n" + "=" * 60)
    print("PHASE 1 — DOCUMENT CACHE PRE-SCAN")
    print("=" * 60)
    print(f"  Cached:      {phase1_cached_count} / {n_rulings}")
    print(f"  To fetch:    {phase1_fetched_count} / {n_rulings}")
    if phase1_fetched_count > 0:
        print("  Fetching uncached documents...")

    # ====================
    # PHASE 2/3 — EXTRACTION
    # ====================

    if args.llm:
        phase_label = "PHASE 2+3 — EXTRACTION (REGEX + LLM)"
    else:
        phase_label = "PHASE 2 — REGEX EXTRACTION"

    print("\n" + "=" * 60)
    print(phase_label)
    print("=" * 60)

    LLM_MODEL = "gpt-5-nano-2025-08-07"
    LLM_PROVIDER = "openai"
    llm_price = LLM_PRICING.get(LLM_PROVIDER, {}).get(LLM_MODEL, {"input_per_1k": 0.0, "output_per_1k": 0.0})

    # Running totals
    total_in_tok = 0
    total_out_tok = 0
    total_cost = 0.0
    total_fetch_sec = 0.0
    total_rx_sec = 0.0
    total_llm_sec = 0.0
    regex_ok = 0
    regex_fail = 0
    llm_ok = 0
    llm_fail = 0
    phase1_elapsed_sec = 0.0
    remaining_to_fetch = phase1_fetched_count

    # Print the headers of the tabular summary into the terminal
    if args.llm:
        hdr = (f"{'#':<8} {'Fetch.Sec':<10} {'Ruling':<9} {'Rx.Start':<9} {'Rx.End':<9} {'Rx.Status':<12} {'Rx.Sec':>7}"
            f" {'LLM.Start':<10} {'LLM.End':<9} {'LLM.Status':<12} {'LLM.Sec':>8}"
            f" {'IN Tok':>7} {'OUT Tok':>7} {'Cost':>10}")
    else:
        hdr = f"{'#':<8} {'Fetch.Sec':<10} {'Ruling':<9} {'Rx.Start':<9} {'Rx.End':<9} {'Rx.Status':<12} {'Rx.Sec':>7}"

    print(hdr)
    print("-" * len(hdr))

    # Print for each Ruling processed the tabular summary in the terminal
    for row_num, rid in enumerate(ruling_ids, 1):
        is_cache_hit = rid in cached_set

        # --- Document fetch ---
        fetch_start = dt.now()
        try:
            rec, text = extract_record(rid, cache_dir=cache_dir, jurisdiction=jurisdiction)
            fetch_end = dt.now()
            fetch_status = "Complete"
        except Exception as fetch_exc:
            fetch_end = dt.now()
            fetch_status = "Failed"
            text = ""
            rec = None
        fetch_elapsed = (fetch_end - fetch_start).total_seconds()
        total_fetch_sec += fetch_elapsed

        if not is_cache_hit:
            phase1_elapsed_sec += fetch_elapsed
            remaining_to_fetch -= 1
            print(f"  [FETCH]  {rid:<9} {fetch_elapsed:.2f}s   ({remaining_to_fetch} remaining)")

        fetch_display = "(cache)" if is_cache_hit else f"{fetch_elapsed:.2f}s"
        row_label = f"{row_num}/{n_rulings}"

        # --- Regex parsing ---
        rx_start = dt.now()
        try:
            if rec is not None:
                regex_raw_records.append(export_to_goal_schema(asdict(rec), bench_spec))
                rx_end = dt.now()
                rx_status = "Complete"
                regex_ok += 1
            else:
                raise ValueError("No record from fetch")
        except Exception:
            rx_end = dt.now()
            rx_status = "Failed"
            regex_fail += 1

        rx_elapsed = (rx_end - rx_start).total_seconds()
        total_rx_sec += rx_elapsed

        if perf_logger:
            perf_logger.track_ruling(is_cached=False)
            perf_logger.track_fetch(ruling_id=rid, start=fetch_start, end=fetch_end, status=fetch_status, cache_hit=False)
            perf_logger.track_regex(ruling_id=rid, start=rx_start, end=rx_end, status=rx_status)

        # --- LLM extraction (optional) ---
        if args.llm:
            llm_start = dt.now()
            llm_end = llm_start
            llm_status = "Failed"
            in_tok = out_tok = 0
            cost = 0.0
            try:
                llm_result = llm_extract(text=text, ruling_id=rid)
                token_usage = llm_result.get("token_usage", {})
                in_tok = token_usage.get("input_tokens", 0)
                out_tok = token_usage.get("output_tokens", 0)
                cost = (in_tok / 1000 * llm_price["input_per_1k"]) + (out_tok / 1000 * llm_price["output_per_1k"])
                total_in_tok += in_tok
                total_out_tok += out_tok
                total_cost += cost

                llm_raw_records.append(export_to_goal_schema(llm_result["extracted_data"], bench_spec))
                llm_updated_this_run = True
                llm_end = dt.now()
                llm_status = "Complete"
                llm_ok += 1
            except Exception as exc:
                    llm_end = dt.now()
                    llm_status = "Failed"
                    llm_fail += 1
                    print(f"  [LLM ERROR] {rid}: {exc}")
            llm_elapsed = (llm_end - llm_start).total_seconds()
            total_llm_sec += llm_elapsed

            if perf_logger:
                perf_logger.track_llm_call(
                    provider=LLM_PROVIDER,
                    model=LLM_MODEL,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    ruling_id=rid,
                    start=llm_start,
                    end=llm_end,
                    status=llm_status,
                )

            print(
                f"{row_label:<8} {fetch_display:<10} {rid:<9} {rx_start.strftime('%H:%M:%S'):<9} {rx_end.strftime('%H:%M:%S'):<9} {rx_status:<12} {rx_elapsed:>7.2f}"
                f" {llm_start.strftime('%H:%M:%S'):<10} {llm_end.strftime('%H:%M:%S'):<9} {llm_status:<12} {llm_elapsed:>8.2f}"
                f" {in_tok:>7} {out_tok:>7} ${cost:>9.4f}"
            )

        else:
            print(f"{row_label:<8} {fetch_display:<10} {rid:<9} {rx_start.strftime('%H:%M:%S'):<9} {rx_end.strftime('%H:%M:%S'):<9} {rx_status:<12} {rx_elapsed:>7.2f}")


    # Print the Totals row
    print("-" * len(hdr))
    rx_total = f"{regex_ok} OK" + (f", {regex_fail} Err" if regex_fail else "")
    if args.llm:
        llm_total = f"{llm_ok} OK" + (f", {llm_fail} Err" if llm_fail else "")
        avg_rx_sec  = total_rx_sec  / n_rulings if n_rulings else 0
        avg_llm_sec = total_llm_sec / n_rulings if n_rulings else 0
        avg_in_tok  = total_in_tok  / n_rulings if n_rulings else 0
        avg_out_tok = total_out_tok / n_rulings if n_rulings else 0
        avg_cost    = total_cost    / n_rulings if n_rulings else 0
        print(
            f"{'TOTAL':<8} {'':<10} {'':<9} {'':<9} {'':<9} {rx_total:<12} {total_rx_sec:>7.2f}"
            f" {'':<10} {'':<9} {llm_total:<12} {total_llm_sec:>8.2f}"
            f" {total_in_tok:>7} {total_out_tok:>7} ${total_cost:>9.4f}"
        )
        print(
            f"{'AVG':<8} {'':<10} {'':<9} {'':<9} {'':<9} {'':<12} {avg_rx_sec:>7.2f}"
            f" {'':<10} {'':<9} {'':<12} {avg_llm_sec:>8.2f}"
            f" {avg_in_tok:>7.0f} {avg_out_tok:>7.0f} ${avg_cost:>9.4f}"
        )
    else:
        avg_rx_sec = total_rx_sec / n_rulings if n_rulings else 0
        print(f"{'TOTAL':<8} {'':<10} {'':<9} {'':<9} {'':<9} {rx_total:<12} {total_rx_sec:>7.2f}")
        print(f"{'AVG':<8} {'':<10} {'':<9} {'':<9} {'':<9} {'':<12} {avg_rx_sec:>7.2f}")


    if args.fetchers_report:
        print("\n" + "=" * 60)
        print("RUNNING FETCHERS REPORT")
        print("=" * 60)
        fetchers_results = run_all_tiers(ruling_ids, cache_dir, jurisdiction=jurisdiction)
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        fetchers_excel_path = os.path.join(checks_dir, f"fetchers_report_{timestamp}.xlsx")
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
            timestamp=datetime.now(),
            perf_log_dir=perf_log_dir,
            jurisdiction=jurisdiction,
            base_dir=base_dir,
        )


    if args.fetchers_report:
        print(f"Fetchers report: {fetchers_excel_path}")


    # ====================
    # SESSION SUMMARY
    # ====================

    avg_fetch_miss = phase1_elapsed_sec / phase1_fetched_count if phase1_fetched_count else 0.0
    avg_rx_sec = total_rx_sec / n_rulings if n_rulings else 0.0
    avg_llm_sec = total_llm_sec / n_rulings if n_rulings else 0.0

    print("\n" + "=" * 60)
    print("SESSION SUMMARY")
    print("=" * 60)
    print(f"  Ruling ID source:    {id_source}")
    print()
    print(f"  Phase 0  ID load:       {phase0_elapsed:.2f}s")
    print(f"  Phase 1  Fetch:        {phase1_elapsed_sec:>7.2f}s total   (avg {avg_fetch_miss:>5.2f}s/ruling,  {phase1_cached_count} cached,  {phase1_fetched_count} fetched)")
    print(f"  Phase 2  Regex:        {total_rx_sec:>7.2f}s total   (avg {avg_rx_sec:>5.2f}s/ruling)")
    if args.llm:
        print(f"  Phase 3  LLM:          {total_llm_sec:>7.2f}s total   (avg {avg_llm_sec:>5.2f}s/ruling)")
    else:
        print(f"  Phase 3  LLM:            0.00s total   (avg  0.00s/ruling)   [disabled]")
    print()
    print(f"  LLM cost:             ${total_cost:.4f}   ({total_in_tok} in / {total_out_tok} out tokens)")

    # --- Extrapolation to 300k rulings ---
    EXTRAP_N = 300_000
    if n_rulings > 0:
        extrap_rx_hrs   = (total_rx_sec  / n_rulings * EXTRAP_N) / 3600
        extrap_cost     = total_cost     / n_rulings * EXTRAP_N
        print("\n" + "=" * 60)
        print(f"EXTRAPOLATION  ({EXTRAP_N:,} rulings)")
        print("=" * 60)
        extrap_rx_days = extrap_rx_hrs / 24
        print(f"  Regex time:   {extrap_rx_hrs:>8.1f} hrs  ({extrap_rx_days:.1f} days)")
        if args.llm:
            extrap_llm_hrs  = (total_llm_sec / n_rulings * EXTRAP_N) / 3600
            extrap_llm_days = extrap_llm_hrs / 24
            extrap_in_tok   = total_in_tok   / n_rulings * EXTRAP_N
            extrap_out_tok  = total_out_tok  / n_rulings * EXTRAP_N
            print(f"  LLM time:     {extrap_llm_hrs:>8.1f} hrs  ({extrap_llm_days:.1f} days)")
            print(f"  LLM tokens:   {extrap_in_tok/1_000_000:>7.1f}M in / {extrap_out_tok/1_000_000:>6.1f}M out")
            print(f"  LLM cost:     ${extrap_cost:>10,.2f}")

    print("\n" + "=" * 60)
    print("OUTPUT FILES")
    print("=" * 60)
    print(f"  Base directory:  {base_dir}")
    print(f"  Regex results:   {regex_raw_path}")
    if args.llm:
        print(f"  LLM results:     {llm_raw_path}")
    print(f"  Triage report:   {triage_path}")
    if args.excel and excel_path:
        print(f"  Excel export:    {excel_path}")
    print("=" * 60 + "\n")


    # Write performance log
    if perf_logger:
        perf_logger.write_log(jurisdiction=jurisdiction)



if __name__ == "__main__":
    main()
