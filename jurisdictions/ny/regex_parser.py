"""
CBP Parser - Regex Extraction Engine
===================================
Rule-based (regex + heuristic) field extraction for CBP ruling documents.

This module is responsible for:
- Downloading a ruling document (via cbp_download).
- Extracting core benchmark fields (dates, HTS codes, duty rate, product description).
- Extracting parties/people (submitter, submitting firm, importer, signature, case handler).
- Returning a structured internal record (`RulingRecord`) plus the raw document text.

Purpose: Provide deterministic baseline extraction that can be compared against
LLM-assisted extraction and normalized into the benchmark “goal schema”.
"""


import re
from dataclasses import dataclass
from typing import Optional, Tuple


from .document_fetchers import fetch_tier_3
from shared.utils import first_match, collapse_ws



# =========================
# RECORD ASSEMBLY
# =========================
# Orchestrates download + per-field parsers to produce one consolidated record.


@dataclass
class RulingRecord:
    """
    Container for all fields extracted from a single CBP ruling.

    Notes:
    - Fields are intentionally Optional: not every ruling includes every signal.
    - Downstream normalization (schema ordering, whitespace rules, etc.) should
      be handled outside this module.
    """
    ruling_id: str
    submitting_firm: Optional[str] = None
    submitter: Optional[str] = None
    importer: Optional[str] = None
    date_submitted: Optional[str] = None
    date_replied: Optional[str] = None
    replying_person: Optional[str] = None
    case_handler: Optional[str] = None
    hts_suggestion: Optional[str] = None
    hts_decision: Optional[str] = None
    duty_rate: Optional[str] = None
    product_description: Optional[str] = None


def extract_record(ruling_id: str, cache_dir: str) -> Tuple[RulingRecord, str]:
    """
    Download a CBP ruling document and extract a complete `RulingRecord`.

    Returns:
        (rec, text)
        - rec: The extracted record (regex heuristics only).
        - text: The raw-ish document text returned by the downloader (useful for saving artifacts).

    Notes:
    - Some parsers run on "pretty" text (line-structured, letter-like formatting).
    - Other parsers run on "text" (better for free-form body searching).
    """
    # The downloader returns:
    # - text: raw-ish text used for broad regex searches.
    # - pretty: a cleaned/line-structured variant that preserves letter layout.
    text, pretty, meta = fetch_tier_3(ruling_id, cache_dir=cache_dir)

    # Dates commonly appear in the header and in “your letter dated ...” phrasing.
    date_submitted, date_replied = extract_dates(pretty)

    # HTS codes and duty rates are typically stated in body paragraphs.
    hts_suggestion, hts_decision = extract_hts_codes(text)
    duty_rate = extract_duty_rate(text)

    # Product description tends to be a narrative “sample” paragraph near the top.
    product_description = extract_product_description(text)

    # Parties/people are usually easiest to capture from the formatted “pretty” view.
    submitting_firm, submitter, importer, replying_person, case_handler = extract_parties_people(pretty)

    rec = RulingRecord(
        ruling_id=ruling_id,
        submitting_firm=submitting_firm,
        submitter=submitter,
        importer=importer,
        date_submitted=date_submitted,
        date_replied=date_replied,
        replying_person=replying_person,
        case_handler=case_handler,
        hts_suggestion=hts_suggestion,
        hts_decision=hts_decision,
        duty_rate=duty_rate,
        product_description=product_description,
    )
    return rec, text


# =========================
# FIELD parserS (REGEX HEURISTICS)
# =========================
# Each function targets one benchmark field (or a small related group of fields).
# Heuristics are intentionally conservative: return None rather than guess.


def extract_dates(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract the submitted date and reply date from the ruling letter.

    Strategy:
    - date_submitted: look for “(in) your letter dated <Month D, YYYY>”.
    - date_replied: usually appears in the header (before “Dear ...”).

    Returns:
        (date_submitted, date_replied) as strings like “January 2, 2024”, or (None, None).
    """
    submitted = first_match(
        [
            r"in your letter dated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            r"your letter dated\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        ],
        text,
        flags=re.IGNORECASE,
    )

    # Reply date: usually in the header, before "Dear".
    # If “Dear” is missing, fall back to scanning the early lines.
    header = text.split("Dear", 1)[0] if "Dear" in text else "\n".join(text.splitlines()[:40])
    replied = first_match(
        [r"\b([A-Za-z]+\s+\d{1,2},\s+\d{4})\b"],
        header,
        flags=re.IGNORECASE,
    )

    return submitted, replied


def extract_hts_codes(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract HTS codes for:
    - hts_suggestion: requester-proposed code (when explicitly attributed to the requester).
    - hts_decision: CBP’s final classification (when explicitly stated).

    Fallback behavior:
    - Only the decision uses a fallback scan (last HTS-like code found) if the
      explicit decision patterns do not match.
    - Avoid inferring suggestion from the first code found; that tends to create
      false positives when rulings mention multiple codes.
    """
    # Suggested HTS (requester-proposed).
    suggestion = first_match(
        [
            # "In your ruling request, you suggest ... under 6301.90.0010"
            r"\byou suggest\b.*?\bunder\s+(\d{4}\.\d{2}\.\d{4})\b",
            r"\bin your ruling request\b.*?\bunder\s+(\d{4}\.\d{2}\.\d{4})\b",

            # "You have suggested classification in subheading 1902.19.2090"
            r"\byou have suggested\b.*?\bsubheading\s+(\d{4}\.\d{2}\.\d{4})\b",

            # "You proposed classification ... in subheading 7326.19.0080"
            r"\byou proposed\b.*?\bsubheading\s+(\d{4}\.\d{2}\.\d{4})\b",

            # "you propose classifying ... under subheading 8479.81.0000"
            r"\byou propose classifying\b.*?\bsubheading\s+(\d{4}\.\d{2}\.\d{4})\b",
        ],
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # CBP decision HTS.
    decision = first_match(
        [
            r"\bthe applicable subheading\b.*?\bwill be\s+(\d{4}\.\d{2}\.\d{4})\b",
            r"\bthe applicable subheading\b.*?\bis\s+(\d{4}\.\d{2}\.\d{4})\b",
            r"\bthe applicable tariff classification\b.*?\bwill be\s+(\d{4}\.\d{2}\.\d{4})\b",
            r"\bthe applicable tariff classification\b.*?\bis\s+(\d{4}\.\d{2}\.\d{4})\b",
            r"\bthe applicable subheading for\b.*?\bwill be\s+(\d{4}\.\d{2}\.\d{4})\b",
        ],
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Conservative fallback: only fill decision (last unique code) if still missing.
    # Do NOT guess suggestion from the first code; that caused wrong results.
    if not decision:
        codes = re.findall(r"\b\d{4}\.\d{2}\.\d{4}\b", text)
        codes = list(dict.fromkeys(codes))
        decision = codes[-1] if codes else None

    return suggestion, decision

    # Fallback heuristic (only if needed)
    # NOTE: This block is currently unreachable due to the return above.
    # It is kept as-is to avoid any logic/behavior change in this comment-only pass.
    if not suggestion or not decision:
        codes = re.findall(r"\b\d{4}\.\d{2}\.\d{4}\b", text)
        codes = list(dict.fromkeys(codes))
        if codes:
            suggestion = suggestion or (codes[0] if len(codes) > 1 else None)
            decision = decision or codes[-1]

    return suggestion, decision


def extract_duty_rate(text: str) -> Optional[str]:
    """
    Extract the duty rate (e.g., “free” or “7.5 percent ad valorem”).

    Strategy:
    - Prefer the canonical phrase “the rate of duty will be ...”.
    - Fall back to any “X percent ad valorem”.
    - Otherwise, treat presence of “free” as a valid duty rate signal.
    """
    val = first_match(
        [r"the rate of duty will be\s+(\d+(?:\.\d+)?\s*percent\s+ad\s+valorem|free)\b"],
        text,
        flags=re.IGNORECASE,
    )

    if val:
        return val.strip()

    m = re.search(r"\b(\d+(?:\.\d+)?)\s*percent\s+ad\s+valorem\b", text, flags=re.IGNORECASE)
    if m:
        return f"{m.group(1)} percent ad valorem"
    if re.search(r"\bfree\b", text, flags=re.IGNORECASE):
        return "free"
    return None


def extract_product_description(text: str) -> Optional[str]:
    """
    Extract a single cleaned product description chunk from the ruling.

    Heuristic:
    - Start at common description openers (The sample / The subject merchandise / The articles under consideration / etc.)
    - Stop before typical classification/analysis triggers.
    - Collapse whitespace.
    """

    # Common openers seen across rulings (HTML/PDF/legacy .doc)
    start = first_match(
        [
            r"\b(The sample,.*)",
            r"\b(The subject merchandise is\b.*)",
            r"\b(The articles under consideration\b.*)",
            r"\b(The product under consideration\b.*)",
            r"\b(The item under consideration\b.*)",
        ],
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not start:
        return None

    tail = start

    # Stop before analysis/classification sections
    stop = re.search(
        r"(?:"
        # cut on paragraph break before analysis
        r"\n\s*\n\s*(?=("
            r"In your ruling request|"
            r"In your letter,\s+you propose|"
            r"You\s+(?:have\s+)?(?:suggested|proposed)\b|"
            r"This office\s+(?:agrees|disagree[s]?)|"
            r"Heading\s+\d{4}|"
            r"The applicable\s+(?:subheading|tariff classification)|"
            r"The rate of duty|"
            r"Duty rates are provided|"
            r"This ruling is being issued|"
            r"A copy of the ruling|"
            r"If you have any questions|"
            r"Sincerely,"
        r"))"
        r"|"
        # cut on sentence boundary before analysis
        r"(?:\.\s+)(?=("
            r"In your ruling request|"
            r"In your letter,\s+you propose|"
            r"You\s+(?:have\s+)?(?:suggested|proposed)\b|"
            r"This office\s+(?:agrees|disagree[s]?)|"
            r"Heading\s+\d{4}|"
            r"The applicable\s+(?:subheading|tariff classification)|"
            r"The rate of duty|"
            r"Duty rates are provided|"
            r"This ruling is being issued|"
            r"A copy of the ruling|"
            r"If you have any questions|"
            r"Sincerely,"
        r"))"
        r")",
        tail,
        flags=re.IGNORECASE,
    )



    chunk = tail[: stop.start()] if stop else tail
    chunk = re.sub(r"\s+", " ", chunk).strip()
    # Normalize typographic quotes/apostrophes to ASCII for stable comparisons
    chunk = (chunk.replace("“", '"').replace("”", '"')
                .replace("‘", "'").replace("’", "'"))
    # Normalize terminal punctuation (helps bench/regex exact-match)
    if chunk and chunk[-1].isalnum():   # ends with letter/number
        chunk += "."
    return chunk if len(chunk) > 30 else None

# def extract_decision_reason(text: str) # Here I still want to implement the decision reasoning 

def extract_parties_people(text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extract parties/people fields from header, body, and signature blocks.

    Returns:
        (submitting_firm, submitter, importer, replying_person, case_handler)

    Notes:
    - Header parsing is heuristic and tries to avoid address lines.
    - `replying_person` is stored as HTML-ish `<br>` joined lines to preserve
      multi-line signature formatting used elsewhere in the pipeline.
    """
    # Keep a trimmed, non-empty line list; parties/people are typically in the early header.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = lines[:200]
    head_text = " ".join(head)

    def is_address_line(s: str) -> bool:
        """Return True if a line looks like a postal address fragment."""
        if not s:
            return False
        if re.search(r"\b(Street|St\.|Avenue|Ave\.|Road|Rd\.|Boulevard|Blvd\.|Suite|Ste\.|Floor|FL)\b", s, re.I):
            return True
        if re.search(r"\b[A-Z]{2}\s+\d{5}(-\d{4})?\b", s):  # NY 10001
            return True
        if re.search(r"\bP\.?\s*O\.?\s*Box\b", s, re.I):
            return True
        if re.search(r"\b\d{1,6}\b", s) and "," in s:
            return True
        return False

    def looks_like_firm(s: str) -> bool:
        """Return True if a line resembles an organization/firm name (not an address)."""
        if not s:
            return False
        if is_address_line(s):
            return False
        return bool(re.search(r"\b(LLP|LLC|L\.L\.C\.|Inc\.|Incorporated|Company|Co\.|Corp\.|Corporation|Brokers|Customs|Law|Partners)\b", s, re.I) or "&" in s)

    # --- 1) Header recipient block parse ---
    # Goal: identify a submitter (person) and submitting firm (organization) near the top.
    submitter = None
    submitting_firm = None

    # Find line index of "TARIFF NO" then read until RE: or Dear.
    tariff_idx = next((i for i, ln in enumerate(head) if re.search(r"\bTARIFF\s+NO\.?\b", ln, re.I)), None)
    if tariff_idx is not None:
        block = []
        for ln in head[tariff_idx + 1 : tariff_idx + 25]:
            if re.match(r"^RE\s*:", ln, re.I) or re.match(r"^Dear\b", ln, re.I):
                break
            block.append(ln)

        # First non-address line is submitter; next "firm-like" line is submitting firm.
        for ln in block:
            if not submitter and not is_address_line(ln):
                submitter = ln
                continue
            if submitter and not submitting_firm and looks_like_firm(ln):
                submitting_firm = ln
                break

    # --- 2) Fallback submitter detection ---
    # If the header block heuristic fails, fall back to honorific-based detection.
    if not submitter:
        for ln in head:
            m = re.match(r"^(Mr\.|Ms\.|Mrs\.)\s+([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){0,3})\b", ln)
            if m:
                submitter = f"{m.group(1)} {m.group(2)}".strip()
                break

    # --- 3) Importer (client) ---
    importer = first_match(
        [
            r"\bon behalf of\s+(?:your\s+client,?\s*)?(.+?)(?:\.\s|\.?$)",
            r"\bon behalf of\s+(.+?)(?:\.\s|\.?$)",
        ],
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if isinstance(importer, str):
        importer = collapse_ws(importer).strip().rstrip(",")
        # Keep common legal suffix if it appears immediately after a line break/comma.
        importer = importer.replace("\n", " ")
        importer = re.sub(r"\s+,", ",", importer)

    # --- 4) Replying person + case handler ---
    def _looks_like_name(s: str) -> bool:
        # allow initials, periods, hyphens, apostrophes
        return bool(re.match(r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,4}$", s))

    def _looks_like_office(s: str) -> bool:
        # common org-ish words seen in CBP signatures
        return bool(re.search(r"\b(Division|Branch|Office|Center|Directorate|Team|Unit|Commodity|Specialist)\b", s))

    def _looks_like_title(s: str) -> bool:
        # job-ish words; keep broad but not too broad
        return bool(re.search(r"\b(Director|Chief|Specialist|Supervisor|Manager|Officer|Attorney|Analyst|Coordinator|Executive|Acting|Deputy|Assistant)\b", s))

    replying_person = None
    m = re.search(r"\bSincerely\b[:,]?\s*(.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        tail = m.group(1)

        stop_markers = ("If you have any questions", "National Import Specialist", "cc:", "Enclosure")
        for sm in stop_markers:
            if sm in tail:
                tail = tail.split(sm, 1)[0]

        tail_lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]

        sig_lines = []

        # Treat as "collapsed" if the first line contains both a title-ish keyword and an office-ish keyword
        collapsed = False
        if tail_lines:
            collapsed = _looks_like_title(tail_lines[0]) and _looks_like_office(tail_lines[0])

        if len(tail_lines) >= 2 and not collapsed:
            # merge “broken name” like ["Steven A.", "Mack", "Director", ...]
            if len(tail_lines) >= 3 and (_looks_like_title(tail_lines[2]) or _looks_like_office(tail_lines[2])):
                # common case: line1+line2 is name
                if _looks_like_name(tail_lines[0]) and _looks_like_name(tail_lines[1]):
                    tail_lines = [f"{tail_lines[0]} {tail_lines[1]}", *tail_lines[2:]]

            name_line = tail_lines[0]

            # If the first line contains a title, split it into: name / title.
            # Fixes: "Deborah C. Marinucci Acting Director" staying glued together.
            m_nt = re.match(
                r"^(.*?)\s+((?:Acting|Deputy|Assistant|Associate|Executive)\s+)?"
                r"(Director|Chief|Manager|Officer|Specialist|Supervisor|Attorney|Analyst|Coordinator)\s*$",
                name_line
            )
            if m_nt:
                name_only = m_nt.group(1).strip()
                title_prefix = (m_nt.group(2) or "")
                title_only = (title_prefix + m_nt.group(3)).strip()
                sig_lines.append(name_only)
                sig_lines.append(title_only)
            else:
                sig_lines.append(name_line)


            # then add next lines that look like title/office (up to 2 more lines)
            for ln in tail_lines[1:]:
                if len(sig_lines) >= 3:
                    break
                # stop if it’s clearly not signature content
                if ln.lower().startswith("sincerely"):
                    continue
                sig_lines.append(ln)

            if sig_lines:
                replying_person = "<br>".join(sig_lines[:3])

        else:
            # Case B: everything collapsed into one line -> reconstruct
            one = tail_lines[0] if tail_lines else ""
            one = re.sub(r"\s+", " ", one).strip()

            # 1) Peel OFF office from the end (greedy)
            office = None
            m_off = re.search(
                r"^(.*\S)\s+((?:[A-Z][A-Za-z&.\-]+\s+){0,6}"
                r"(?:Division|Branch|Office|Center|Directorate|Laboratory|Port))\s*$",
                one
            )
            if m_off:
                one = m_off.group(1).strip()
                office = m_off.group(2).strip()

            # 2) Peel OFF title from the end (handles multi-word titles like “Acting Director”)
            title = None
            m_title = re.search(
                r"^(.*\S)\s+((?:Acting|Deputy|Assistant|Associate|Executive)\s+)?"
                r"(Director|Chief|Manager|Officer|Specialist|Supervisor|Attorney|Analyst|Coordinator)\s*$",
                one
            )
            if m_title:
                one = m_title.group(1).strip()
                # rebuild full title string
                prefix = (m_title.group(2) or "")
                title = (prefix + m_title.group(3)).strip()

            # 3) Remaining is name
            name = one.strip()

            sig = [x for x in (name, title, office) if x][:3]
            if sig:
                replying_person = "<br>".join(sig)



    # Case handler is typically an Import Specialist referenced in the closing paragraph.
    case_handler = first_match(
        [
            # "National Import Specialist Kim Wachtel at kimberly.a.wachtel@..."
            r"\bNational Import Specialist\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})(?=\s+(?:at\b|,|\.|\)|$))",
            # Sometimes appears without "National"
            r"\bImport Specialist\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3})(?=\s+(?:at\b|,|\.|\)|$))",
        ],
        text,
        flags=re.IGNORECASE,
    )

    return submitting_firm, submitter, importer, replying_person, case_handler
