"""
Performance Logger
==================

Tracks execution metrics for cost monitoring and performance optimization.
Logs to crash-safe JSON Lines format with optional Excel export.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from shared.llm_config import LLM_PRICING


class PerformanceLogger:
    """
    Collects and logs performance metrics for ruling extraction runs.
    """
    
    def __init__(self, log_path: str):
        """
        Initialize logger with output path.
        
        Args:
            log_path: Path to .jsonl file for append-safe logging
        """
        self.log_path = log_path
        self.session_start = datetime.now()
        self.session_id = self.session_start.strftime("%Y%m%d_%H%M%S")
        
        # Metrics storage
        self.total_rulings = 0
        self.new_rulings = 0
        self.cached_rulings = 0
        
        # LLM metrics
        self.llm_enabled = False
        self.llm_provider = None
        self.llm_model = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        
    def track_ruling(self, is_cached: bool):
        """Track a processed ruling."""
        self.total_rulings += 1
        if is_cached:
            self.cached_rulings += 1
        else:
            self.new_rulings += 1
    
    def track_llm_call(self, provider: str, model: str, input_tokens: int, output_tokens: int):
        """Track LLM API call metrics."""
        self.llm_enabled = True
        self.llm_provider = provider
        self.llm_model = model
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
    
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
        """
        Write performance metrics to JSON Lines log file.
        
        Args:
            jurisdiction: Jurisdiction code (e.g., "ny", "ca")
        """
        elapsed = (datetime.now() - self.session_start).total_seconds()
        
        log_entry = {
            "timestamp": self.session_start.isoformat(),
            "session_id": self.session_id,
            "jurisdiction": jurisdiction,
            "total_rulings_processed": self.total_rulings,
            "new_rulings": self.new_rulings,
            "cached_rulings": self.cached_rulings,
            "cache_hit_rate": self.cached_rulings / self.total_rulings if self.total_rulings > 0 else 0.0,
            "llm_enabled": self.llm_enabled,
            "total_time_elapsed_seconds": round(elapsed, 2),
            "avg_time_per_ruling_seconds": round(elapsed / self.total_rulings, 2) if self.total_rulings > 0 else 0.0
        }
        
        # Add LLM metrics if LLM was used
        if self.llm_enabled:
            total_cost = self.calculate_cost()
            log_entry["llm_provider"] = self.llm_provider
            log_entry["llm_model"] = self.llm_model
            log_entry["llm_metrics"] = {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "avg_input_tokens_per_ruling": round(self.total_input_tokens / self.total_rulings, 0) if self.total_rulings > 0 else 0,
                "avg_output_tokens_per_ruling": round(self.total_output_tokens / self.total_rulings, 0) if self.total_rulings > 0 else 0,
                "total_cost_usd": round(total_cost, 4),
                "avg_cost_per_ruling_usd": round(total_cost / self.total_rulings, 4) if self.total_rulings > 0 else 0.0
            }
        
        # Append to JSON Lines file (crash-safe)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        
        print(f"\n✓ Performance log written: {self.log_path}")
        if self.llm_enabled:
            print(f"  - Total cost: ${log_entry['llm_metrics']['total_cost_usd']:.4f}")
            print(f"  - Avg cost per ruling: ${log_entry['llm_metrics']['avg_cost_per_ruling_usd']:.4f}")
