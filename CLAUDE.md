# pta-cbp-parser — Claude Code Guide

## Project Purpose
Extract structured data fields from U.S. Customs and Border Protection (CBP) tariff ruling letters using regex heuristics + optional LLM, then compare results against ground-truth benchmarks and export Excel review reports.

## Team Structure
- **NY jurisdiction** (this repo owner): `jurisdictions/ny/` — CBP New York office rulings
- **CA jurisdiction** (colleague): `jurisdictions/ca/` — Canada rulings (stub, to be implemented)

Each jurisdiction owns its own `config.py`, `schema.py`, `regex_parser.py`, `document_fetchers.py`, `llm.py`.  
Shared utilities live in `shared/`. The CLI entry point (`extract_rulings.py`) routes via `--jurisdiction`.

## Quick Start
```powershell
# Setup
python -m venv .venv && .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env  # then fill in API keys

# Run (NY is default)
python extract_rulings.py                        # regex only
python extract_rulings.py --llm                  # + LLM extraction
python extract_rulings.py --excel                # + Excel report
python extract_rulings.py --jurisdiction ca      # CA rulings (once implemented)

# Utilities
python shared\clean_cache.py                     # clear download cache
```

## Directory Map
```
pta-cbp-parser/
├── extract_rulings.py          # CLI entry point — orchestrates the full pipeline
├── jurisdictions/
│   ├── ny/                     # NY-specific modules (maintained by repo owner)
│   │   ├── config.py           # Constants: fallback IDs, year list, download URL
│   │   ├── schema.py           # Schema normalization, export_to_goal_schema()
│   │   ├── regex_parser.py     # Core regex engine + RulingRecord dataclass
│   │   ├── document_fetchers.py # 3-tier document download (JSON API / HTML / .doc)
│   │   └── llm.py              # LLM extraction via OpenAI-compatible API
│   └── ca/                     # CA-specific modules (maintained by colleague) — STUB
│       ├── config.py           # TODO: CA-specific constants
│       ├── schema.py           # TODO: CA schema normalization
│       ├── regex_parser.py     # TODO: CA regex extraction
│       ├── document_fetchers.py # TODO: CA document fetching
│       └── llm.py              # TODO: CA LLM extraction
├── shared/                     # Jurisdiction-agnostic utilities
│   ├── utils.py                # first_match(), collapse_ws(), normalize_text()
│   ├── io_inputs.py            # load_ruling_ids(), load_benchmark_spec/values()
│   ├── reports.py              # triage_report_goal(), compare_to_benchmark()
│   ├── excel_export.py         # 4-sheet Excel workbook generator
│   ├── fetchers_report.py      # Tier comparison Excel report
│   ├── llm_config.py           # LLM provider config + pricing table
│   ├── performance_logger.py   # Cost/timing JSONL logger
│   └── clean_cache.py          # Standalone cache-clearing script
├── in/
│   ├── ny/                     # NY-specific inputs
│   │   ├── 01_benchmarks/
│   │   │   ├── 01_benchmark_spec.json   # Field order + format rules
│   │   │   └── 02_benchmark_values.json # Ground-truth records for evaluation
│   │   └── 02_rulings/
│   │       └── 01_ruling_ids.json       # List of ruling IDs to process
│   └── ca/                     # CA-specific inputs (stub)
├── cache/                      # Downloaded ruling texts (auto-created, gitignored)
│   └── {jurisdiction}/         # e.g. cache/ny/N340865.normalized.txt
├── out/                        # Generated outputs (auto-created, gitignored)
│   └── {jurisdiction}/         # e.g. out/ny/04_review/review.xlsx
└── .env                        # API keys — NEVER COMMIT (already in .gitignore)
```

## Key Conventions

### Two-Text Strategy
Every document fetcher returns `(normalized_text, pretty_text, meta)`:
- `normalized`: all whitespace collapsed to single spaces — used for regex body searches
- `pretty`: line-structured, preserves letter layout — used for header/signature parsing

### Caching
All downloaded documents are cached to `cache/{jurisdiction}/`. A cached file is always used on re-runs. Clear with `python shared\clean_cache.py` to force re-download.

### replying_person Field
This field uses `<br>` as a delimiter between signature lines (name, title, division). It is **exempt from whitespace collapsing** in comparisons because line formatting is significant.

### Benchmark Schema
Field order is defined in `in/{jurisdiction}/01_benchmarks/01_benchmark_spec.json`.  
`schema.export_to_goal_schema()` enforces this order on every extraction result before comparison.

### Windows-Only Constraint
The legacy binary `.doc` (CFB format) branch in `document_fetchers.py` uses Microsoft Word COM automation (`win32com`). Requires Windows 10/11 + Word installed.

## Common Tasks

### Add a New Ruling ID (NY)
Edit `in/ny/02_rulings/01_ruling_ids.json` — add the ruling ID string to the JSON array.

### Add a New Benchmark Record (NY)
Edit `in/ny/01_benchmarks/02_benchmark_values.json` — add a new object matching the goal schema field order from `01_benchmark_spec.json`.

### Add a New Extractable Field
1. Add field to `RulingRecord` dataclass in `jurisdictions/ny/regex_parser.py`
2. Write `extract_{field}(text)` function in the same file
3. Call it in `extract_record()` and assign to the dataclass
4. Add field to `in/ny/01_benchmarks/01_benchmark_spec.json` (field_order, types, format_rules)
5. Handle in `jurisdictions/ny/schema.py` if special normalization is needed
6. Update LLM prompt in `jurisdictions/ny/llm.py` to request the new field

### Known TODOs
- `accepted_flag` and `decision_reasoning` are in the benchmark spec but not yet extracted
- CA jurisdiction stubs need full implementation by the CA team member

## Pipeline Flow (Simplified)
```
extract_rulings.py --jurisdiction ny
    → load inputs from in/ny/
    → for each ruling_id:
        → regex_parser.extract_record()
            → document_fetchers.fetch_tier_3() → download + cache .doc
            → regex heuristics → RulingRecord
        → (optional) llm.llm_extract() → OpenAI API → dict
    → triage_report_goal() → compare regex vs LLM vs benchmark
    → (optional) export_to_excel() → out/ny/04_review/review.xlsx
```

## Environment Variables (`.env`)
```
OPENAI_API_KEY=sk-proj-...
OPENAI_ORGANIZATION_ID=org-...
OPENAI_PROJECT_ID=proj_...
```
