"""
CBP Parser - Reports & Triage Utilities
======================================
Helpers for comparing extracted records (regex and/or LLM) against the benchmark
and against each other.

This module produces lightweight JSON-serializable report structures used by:
- Bench comparison (method vs benchmark values).
- Disagreement detection (regex vs LLM).
- Triage output (fields worth manual review).

Purpose: Centralize comparison logic and keep whitespace normalization rules
consistent across reports (especially around `replying_person`).
"""


from typing import Dict, List

from .utils import collapse_ws


# =========================
# REPORTS / CHECKS
# =========================
# These functions operate on already-extracted records (dicts), not raw text.
# They return nested dicts/lists that are easy to write to JSON.


def compare_to_benchmark(
    predicted_raw_records: List[Dict],
    bench_values: List[Dict],
    bench_spec: Dict,
    pred_label: str,
) -> Dict[str, Dict[str, Dict[str, object]]]:
    """
    Compare predicted goal-schema records to benchmark example records.

    Args:
        predicted_raw_records: List of extracted records (dicts) in goal-schema keys.
        bench_values: List of benchmark records (dicts) in goal-schema keys.
        bench_spec: Benchmark specification dict (must include output.field_order).
        pred_label: Label used in the report for the predicted side (e.g., "regex" or "llm").

    Returns:
        Dict keyed by ruling_id, containing only fields that differ:
            {
              "N340865": {
                "duty_rate": { "<pred_label>": "...", "bench": "..." },
                ...
              },
              ...
            }

    Notes:
    - Applies whitespace collapsing to string fields for stable comparisons, except
      `replying_person` which is treated as whitespace-sensitive per the spec.
    """
    fields = bench_spec["output"]["field_order"]
    bench_by_id = {r.get("ruling_id"): r for r in bench_values}

    report: Dict[str, Dict[str, Dict[str, object]]] = {}
    for pred in predicted_raw_records:
        rid = pred.get("ruling_id")
        bench = bench_by_id.get(rid)
        if not rid or not bench:
            continue

        diffs = {}
        for k in fields:
            pv = pred.get(k)
            iv = bench.get(k)

            # Apply the same whitespace normalization as elsewhere in the pipeline.
            # `replying_person` is intentionally excluded because the benchmark
            # often expects exact formatting (e.g., line breaks / <br> behavior).
            if isinstance(pv, str) and k != "replying_person":
                pv = collapse_ws(pv)
            if isinstance(iv, str) and k != "replying_person":
                iv = collapse_ws(iv)

            # Only record differences; matching fields are omitted from the output.
            if pv != iv:
                diffs[k] = {pred_label: pv, "bench": iv}

        if diffs:
            report[rid] = diffs

    return report


def disagreement_report_goal(regex_goal: List[Dict], llm_goal: List[Dict], bench_spec: dict) -> Dict[str, List[str]]:
    """
    Compare regex vs LLM outputs in goal-schema space.

    Args:
        regex_goal: List of regex-extracted records (goal-schema dicts).
        llm_goal: List of LLM-extracted records (goal-schema dicts).
        bench_spec: Benchmark specification dict (must include output.field_order).

    Returns:
        {ruling_id: [field_name, ...]} for any fields where regex != llm.

    Notes:
    - This report is intentionally compact: it lists field names only.
    - Whitespace is collapsed for string comparisons to avoid noise from
      formatting differences.
    """
    fields = bench_spec["output"]["field_order"]
    by_id_llm = {r.get("ruling_id"): r for r in llm_goal}

    report: Dict[str, List[str]] = {}
    for rr in regex_goal:
        rid = rr.get("ruling_id")
        lr = by_id_llm.get(rid)
        if not rid or not lr:
            continue

        diffs = []
        for k in fields:
            rv = rr.get(k)
            lv = lr.get(k)

            # Normalize whitespace for stability (this function does not special-case
            # replying_person because the output is just a “fields differ” list).
            if isinstance(rv, str):
                rv = collapse_ws(rv)
            if isinstance(lv, str):
                lv = collapse_ws(lv)

            if rv != lv:
                diffs.append(k)

        if diffs:
            report[rid] = diffs

    return report


def triage_report_goal(
    regex_raw_records: List[Dict],
    llm_raw_records: List[Dict],
    bench_values: List[Dict],
    bench_spec: Dict,
    include_fields_where_method_vs_bench: bool = True,
) -> Dict[str, Dict[str, Dict[str, object]]]:
    """
    Create a triage report combining regex, LLM, and benchmark comparisons.

    The goal is to flag fields that likely need manual review, including:
    - LLM record missing entirely for a ruling.
    - Regex vs LLM disagreement on a field.
    - (Optional) Either method differs from the benchmark on a field.

    Args:
        regex_raw_records: Regex-extracted records (goal-schema dicts).
        llm_raw_records: LLM-extracted records (goal-schema dicts).
        bench_values: Benchmark records (goal-schema dicts).
        bench_spec: Benchmark specification dict (must include output.field_order).
        include_fields_where_method_vs_bench: If True, include fields where either
            method disagrees with the benchmark (when benchmark exists for the ruling).

    Returns:
        A nested dict keyed by ruling_id -> field -> {"bench": ..., "regex": ..., "llm": ...}
        for only the fields that meet the triage inclusion criteria.

    Notes:
    - String comparisons collapse whitespace for all fields except `replying_person`,
      which remains exact to respect formatting expectations.
    - The report stores original (un-collapsed) values so the triage JSON is easier
      to inspect and debug.
    """
    fields = bench_spec["output"]["field_order"]

    by_id_llm = {r.get("ruling_id"): r for r in llm_raw_records}
    by_id_bench = {r.get("ruling_id"): r for r in bench_values}

    report: Dict[str, Dict[str, Dict[str, object]]] = {}
    for regex_rec in regex_raw_records:
        ruling_id = regex_rec.get("ruling_id")
        if not ruling_id:
            continue

        llm_rec = by_id_llm.get(ruling_id)
        llm_missing = llm_rec is None

        # Benchmark may not exist for every ruling id (depending on the dataset split).
        bench_rec = by_id_bench.get(ruling_id)  # may be None

        diffs: Dict[str, Dict[str, object]] = {}
        for field in fields:
            regex_val = regex_rec.get(field)
            llm_val = llm_rec.get(field) if llm_rec else None
            bench_val = bench_rec.get(field) if bench_rec else None

            # Comparison values: collapse whitespace for stability, but keep
            # replying_person exact (formatting-sensitive).
            regex_cmp = collapse_ws(regex_val) if isinstance(regex_val, str) and field != "replying_person" else regex_val
            llm_cmp = collapse_ws(llm_val) if isinstance(llm_val, str) and field != "replying_person" else llm_val
            bench_cmp = collapse_ws(bench_val) if isinstance(bench_val, str) and field != "replying_person" else bench_val

            # Pairwise comparisons used to decide whether the field is triage-worthy.
            regex_vs_llm = (llm_rec is not None) and (regex_cmp != llm_cmp)
            regex_vs_bench = (bench_rec is not None) and (regex_cmp != bench_cmp)
            llm_vs_bench = (bench_rec is not None) and (llm_cmp != bench_cmp)

            # Inclusion rules:
            # - Always include if the LLM record is missing (so the ruling is easy to spot).
            # - Include if regex and LLM disagree.
            # - Optionally include if either method disagrees with the benchmark.
            include_field = (
                llm_missing
                or regex_vs_llm
                or (include_fields_where_method_vs_bench and (regex_vs_bench or llm_vs_bench))
            )

            if not include_field:
                continue

            # Store original values (not collapsed) so the triage output can be
            # reviewed without losing formatting context.
            diffs[field] = {"bench": bench_val, "regex": regex_val, "llm": llm_val}

        if diffs:
            report[ruling_id] = diffs

    return report
