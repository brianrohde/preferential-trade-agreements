"""
Shared LLM Configuration
========================

Provider-agnostic LLM settings including pricing and model definitions.
Used across all jurisdictions for cost calculation and provider management.
"""


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


# LLM pricing configuration (cost per 1K tokens)
LLM_PRICING = {
    "openai": {
        "gpt-5-nano-2025-08-07": {
            "input_per_1k": 0.0002,
            "output_per_1k": 0.0008
        },
        "gpt-4o-mini": {
            "input_per_1k": 0.00015,
            "output_per_1k": 0.0006
        }
    },
    "deepinfra": {
        "meta-llama/Meta-Llama-3.1-8B-Instruct": {
            "input_per_1k": 0.00006,
            "output_per_1k": 0.00006
        }
    }
}
