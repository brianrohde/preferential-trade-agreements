"""
CBP Parser - LLM Extraction (Provider Agnostic)
==============================================

LLM-assisted field extraction for CBP ruling documents using OpenAI-compatible
Chat Completions APIs (OpenAI, DeepInfra, Together.ai, etc.).

This module is intended as an optional alternative to regex heuristics:
- Regex extraction provides a deterministic baseline.
- LLM extraction fills the same field set using a strict JSON-only prompt.

Purpose: Call any OpenAI-compatible provider with a constrained schema prompt,
then defensively parse response into stable Python dict for downstream use.

Flexible: Defaults to OpenAI gpt-5-nano. Override with provider/model parameters.
"""

import re
import os
import json
import requests
from typing import Optional


# Provider configuration - extend as needed
PROVIDERS = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
    },
    "deepinfra": {
        "api_key_env": "DEEPINFRA_API_KEY", 
        "base_url": "https://api.deepinfra.com/v1/openai",
    },
    # Add more providers here
}


def llm_extract(
    text: str, 
    model: str = "gpt-5-nano-2025-08-07",
    provider: str = "openai",
    ruling_id: Optional[str] = None
) -> dict:
    """
    Run LLM extraction on a CBP ruling document.
    
    Args:
        text: Full ruling text (pretty/normalized form).
        model: Model name (default: "gpt-5-nano"). 
        provider: Provider key ("openai", "deepinfra", etc.).
        ruling_id: Optional ruling ID for logging/tracking.
    
    Returns:
        Python dict with extracted fields.
    
    Raises:
        RuntimeError: Missing API key, API errors, or JSON parsing failures.
    """
    
    # Get provider configuration
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}. Available: {list(PROVIDERS.keys())}")
    
    provider_config = PROVIDERS[provider]
    api_key = os.getenv(provider_config["api_key_env"])
    
    if not api_key:
        raise RuntimeError(
            f"Missing {provider_config['api_key_env']}. "
            f"Set it as env var before running with --llm."
        )
    
    # Build request
    url = f"{provider_config['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json", 
        "Accept": "application/json",
        "OpenAI-Organization": os.getenv("OPENAI_ORGANIZATION_ID", ""),
        "OpenAI-Project": os.getenv("OPENAI_PROJECT_ID", ""),
    }

    
    # Universal schema prompt (works across all OpenAI-compatible providers)
    schema = """
You will be given the full text of a CBP customs classification ruling letter. Return ONLY valid JSON with EXACTLY these keys:
ruling_id, submitting_firm, submitter, importer, date_submitted, date_replied, replying_person, case_handler, hts_suggestion, hts_decision, duty_rate, product_description.

Use null when unknown. Do not add extra keys. No commentary.

DATA DICTIONARY DEFINITIONS (use these strictly):
- ruling_id: The ruling control number like N340865.
- submitting_firm: The firm/company submitting the request, often a law firm.
- submitter: The person submitting the request, e.g., "Ms. Kristina Barry".
- importer: The client/on-behalf-of entity, e.g., "Toby Company".
- date_submitted: The date in "In your letter dated Month DD, YYYY ...."
- date_replied: Reply date near top (before "Dear ..."), format "Month DD, YYYY".
- replying_person: Signature lines after "Sincerely,". Use "<br>" between lines.
- case_handler: National Import Specialist name only (no email).
- hts_suggestion: Requester's proposed HTS code.
- hts_decision: CBP final HTS code.
- duty_rate: After "The rate of duty will be ...".
- product_description: Paragraph starting "The sample," describing merchandise.

OUTPUT RULES:
- dates must be "Month DD, YYYY" (not ISO).
- HTS codes must look like ####.##.#### when present.
- Do not invent values; only extract from given text.
"""
    
    # Universal payload structure
    payload = {
        "model": model,
        # "temperature": 0.0, # Not supported by gpt-5-nano
        "service_tier": "flex",
        "messages": [
            {"role": "system", "content": "You extract structured fields from customs ruling letters. Output JSON only."},
            {"role": "user", "content": schema + "\nTEXT:\n" + text},
        ],
    }
    
    # Execute request
    resp = requests.post(url, headers=headers, json=payload, timeout=90)
    print(f"DEBUG: Status={resp.status_code}, Response={resp.text[:500]}")
    resp.raise_for_status()
    
    # Extract content (OpenAI-compatible response format)
    content = resp.json()["choices"][0]["message"]["content"]
    
    # Defensive parsing (unchanged)
    if content is None:
        raise RuntimeError("LLM returned null content")
    
    content = content.strip()
    if not content:
        raise RuntimeError(f"LLM returned empty content. Raw: {resp.text[:500]}")
    
    # Handle markdown fences
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content).strip()
    
    # Extract JSON object if wrapped in prose
    if not content.startswith("{"):
        m = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not m:
            raise RuntimeError(f"LLM content is not JSON. Head: {content[:200]}")
        content = m.group(0).strip()
    
    # Parse JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse LLM JSON: {e}. Head: {content[:200]}") from e
