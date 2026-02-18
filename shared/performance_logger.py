"""
Performance Logger
==================
Tracks execution metrics across fetch, regex, and LLM phases.
Writes 4 crash-safe JSON Lines files, all linked by session_id.

Log files (all in out/<jurisdiction>/06_performance_logs/):
  log_session.jsonl  - One row per full run (summary)
  log_fetch.jsonl    - One row per ruling document fetch
  log_regex.jsonl    - One row per ruling regex parse
  log_llm.jsonl      - One row per ruling LLM call
"""

import json
import os
from datetime import datetime
from typing import Optional
from shared.llm_config import LLM_PRICING


class PerformanceLogger:
    """Collects and logs performance metrics for ruling extraction runs."""

    def __init__(self, log_dir: str):
        """
        Initialize logger with output directory (not a single file path).

        Args:
            log_dir: Directory where all 4 log files will be written.
        """
        self.log_dir = log_dir
        self.session_start = datetime.now()
        self.session_id = self.session_start.strftime("%Y%m%d_%H%M%S")

        # Session-level counters
        self.total_rulings = 0
        self.new_rulings = 0
        self.cached_rulings = 0

        # Phase-level totals (for session summary)
        self.total_fetch_sec = 0.0
        self.total_rx_sec = 0.0
        self.total_llm_sec = 0.0

        # LLM metrics
        self.llm_enabled = False
        self.llm_provider = None
        self.llm_model = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # ------------------------------------------------------------------
    # Per-ruling tracking methods
    # ------------------------------------------------------------------

    def track_ruling(self, is_cached: bool):
        """Track a processed ruling."""
        self.total_rulings += 1
        if is_cached:
            self.cached_rulings += 1
        else:
            self.new_rulings += 1

    def track_fetch(self, ruling_id: str, start: datetime, end: datetime, status: str, cache_hit: bool):
        """Log one document fetch event to log_fetch.jsonl."""
        elapsed = (end - start).total_seconds()
        self.total_fetch_sec += elapsed
        entry = {
            "session_id": self.session_id,
            "ruling_id": ruling_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "elapsed_sec": round(elapsed, 4),
            "status": status,
            "cache_hit": cache_hit,
        }
        self._append("log_fetch.jsonl", entry)

    def track_regex(self, ruling_id: str, start: datetime, end: datetime, status: str):
        """Log one regex parse event to log_regex.jsonl."""
        elapsed = (end - start).total_seconds()
        self.total_rx_sec += elapsed
        entry = {
            "session_id": self.session_id,
            "ruling_id": ruling_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "elapsed_sec": round(elapsed, 4),
            "status": status,
        }
        self._append("log_regex.jsonl", entry)

    def track_llm_call(self, provider: str, model: str, input_tokens: int, output_tokens: int,
                       ruling_id: str = "", start: Optional[datetime] = None, end: Optional[datetime] = None,
                       status: str = "Complete"):
        """Log one LLM call event to log_llm.jsonl."""
        self.llm_enabled = True
        self.llm_provider = provider
        self.llm_model = model
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        pricing = LLM_PRICING.get(provider, {}).get(model, {"input_per_1k": 0.0, "output_per_1k": 0.0})
        cost = (input_tokens / 1000 * pricing["input_per_1k"]) + (output_tokens / 1000 * pricing["output_per_1k"])

        elapsed = (end - start).total_seconds() if start and end else None
        if elapsed is not None:
            self.total_llm_sec += elapsed

        entry = {
            "session_id": self.session_id,
            "ruling_id": ruling_id,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "elapsed_sec": round(elapsed, 4) if elapsed is not None else None,
            "status": status,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }
        self._append("log_llm.jsonl", entry)

    # ------------------------------------------------------------------
    # Session summary
    # ------------------------------------------------------------------

    def calculate_cost(self) -> float:
        """Calculate total LLM cost in USD."""
        if not self.llm_enabled or not self.llm_provider or not self.llm_model:
            return 0.0
        pricing = LLM_PRICING.get(self.llm_provider, {}).get(self.llm_model)
        if not pricing:
            return 0.0
        input_cost = (self.total_input_tokens / 1000) * pricing["input_per_1k"]
        output_cost = (self.total_output_tokens / 1000) * pricing["output_per_1k"]
        return input_cost + output_cost

    def write_log(self, jurisdiction: str):
        """Write session summary to log_session.jsonl and print console summary."""
        n = self.total_rulings
        total_cost = self.calculate_cost()

        log_entry = {
            "session_id": self.session_id,
            "timestamp": self.session_start.isoformat(),
            "jurisdiction": jurisdiction,
            "total_rulings": n,
            "new_rulings": self.new_rulings,
            "cached_rulings": self.cached_rulings,
            "cache_hit_rate": round(self.cached_rulings / n, 4) if n > 0 else 0.0,
            "llm_enabled": self.llm_enabled,
            "timing": {
                "total_fetch_sec": round(self.total_fetch_sec, 2),
                "avg_fetch_sec": round(self.total_fetch_sec / n, 4) if n > 0 else 0.0,
                "total_rx_sec": round(self.total_rx_sec, 2),
                "avg_rx_sec": round(self.total_rx_sec / n, 4) if n > 0 else 0.0,
                "total_llm_sec": round(self.total_llm_sec, 2),
                "avg_llm_sec": round(self.total_llm_sec / n, 4) if n > 0 else 0.0,
            },
        }

        if self.llm_enabled:
            log_entry["llm_provider"] = self.llm_provider
            log_entry["llm_model"] = self.llm_model
            log_entry["llm_metrics"] = {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "avg_input_tokens_per_ruling": round(self.total_input_tokens / n, 0) if n > 0 else 0,
                "avg_output_tokens_per_ruling": round(self.total_output_tokens / n, 0) if n > 0 else 0,
                "total_cost_usd": round(total_cost, 4),
                "avg_cost_per_ruling_usd": round(total_cost / n, 4) if n > 0 else 0.0,
            }

        self._append("log_session.jsonl", log_entry)

        # Console summary
        session_log_path = os.path.join(self.log_dir, "log_session.jsonl")
        print(f"\n✓ Performance log written: {session_log_path}")
        print(f"  - Session ID:            {self.session_id}")
        print(f"  - Total tokens:          {self.total_input_tokens:,} in / {self.total_output_tokens:,} out")
        print(f"  - Fetch time:            {self.total_fetch_sec:.2f}s total  (avg {log_entry['timing']['avg_fetch_sec']:.2f}s/ruling)")
        print(f"  - Regex time:            {self.total_rx_sec:.2f}s total  (avg {log_entry['timing']['avg_rx_sec']:.2f}s/ruling)")
        if self.llm_enabled:
            print(f"  - LLM time:              {self.total_llm_sec:.2f}s total  (avg {log_entry['timing']['avg_llm_sec']:.2f}s/ruling)")
            print(f"  - Total cost:            ${log_entry['llm_metrics']['total_cost_usd']:.4f}")
            print(f"  - Avg cost per ruling:   ${log_entry['llm_metrics']['avg_cost_per_ruling_usd']:.4f}")

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _append(self, filename: str, entry: dict):
        """Append one JSON entry to a log file in log_dir."""
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
