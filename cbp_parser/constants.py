"""
CBP Parser - Constants
=====================
Centralized constants used across the CBP ruling extraction pipeline.

This module keeps “configuration-like” values in one place, including:
- Default ruling IDs to run when no input file is provided.
- Candidate years to try when downloading CBP ruling documents.
- The URL template used to fetch .doc files from the CBP rulings site.

Purpose: Avoid scattering relevant values (IDs, year lists, URL patterns) across
multiple modules and CLIs.
"""


# Default ruling IDs used when no ruling-id input file is present.
# This allows a clean out-of-the-box run for quick validation/testing.
FALLBACK_RULING_IDS = ["N340865", "N340183", "N339572", "N275583"]


# Candidate years to try when downloading documents.
# The downloader can attempt these in order until a document is found.
YEAR_CANDIDATES = [2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016, 2015]


# Base document URL pattern (CBP rulings .doc download).
# This pattern was identified via browser DevTools while inspecting document fetches.
# Example:
# https://rulings.cbp.gov/api/getdoc/ny/2024/N340865.doc
DOC_URL_TEMPLATE = "https://rulings.cbp.gov/api/getdoc/ny/{year}/{ruling_id}.doc"
