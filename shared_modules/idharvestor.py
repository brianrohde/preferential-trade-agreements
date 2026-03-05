# shared/idharvestor.py
import requests, time, json
from datetime import datetime
from pathlib import Path
import math

BASE_URL = "https://rulings.cbp.gov/api/search"
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "referer": "https://rulings.cbp.gov/search",
}

def _append_jsonl(path: Path, entry: dict) -> None:
    # Appends a single entry as one line to the .jsonl log file
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def harvest_year(
    session: requests.Session,
    year: int,
    collection: str,
    session_id: str,
    ruling_data_path: Path,
    max_rulings: int = None,
) -> int:
    """
    Fetches rulings for a single year, writing each as a JSONL line to ruling_data_path.
    Returns the count of rulings harvested for this year.
    """
    from_date = f"{year}-01-01"
    to_date   = f"{year}-12-31"
    year_count = 0
    page = 1

    while True:
        params = {
            "term": "N",
            "collection": collection,
            "commodityGrouping": "ALL",
            "fromDate": from_date,
            "toDate": to_date,
            "sortBy": "DATE_DESC",
            "pageSize": 100,
            "page": page,
        }

        page_start = datetime.now()
        resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        page_elapsed = round((datetime.now() - page_start).total_seconds(), 4)

        data = resp.json()
        rulings = data.get("rulings", [])
        total_hits = data.get("totalHits", 0)
        total_pages = math.ceil(total_hits / 100) if total_hits else 1

        # Limit rulings on this page if the cap would be reached mid-page
        remaining = (max_rulings - year_count) if max_rulings else len(rulings)
        rulings_to_write = rulings[:remaining]

        for page_index, ruling in enumerate(rulings_to_write, start=1):
            entry = {
                "session_id":     session_id,
                "year":           year,
                "page":           page,
                "page_index":     page_index,
                "ruling_number":  ruling.get("rulingNumber"),
                "ruling_id":      ruling.get("id"),
                "subject":        ruling.get("subject"),
                "categories":     ruling.get("categories"),
                "ruling_date":    ruling.get("rulingDate", "")[:10],
                "tariffs":        ruling.get("tariffs", []),
                "related_rulings": ruling.get("relatedRulings", []),
                "status":         "Complete",
            }
            _append_jsonl(ruling_data_path, entry)

        year_count += len(rulings_to_write)
        print(f"  Year {year} | Page {page}/{total_pages} | This page: {len(rulings_to_write)} | Year total: {year_count} | ({page_elapsed}s)")

        if max_rulings and year_count >= max_rulings:
            break
        if page >= total_pages:
            break

        page += 1
        time.sleep(0.4)

    return year_count


def harvest_range(
    start_year: int,
    end_year: int,
    collection: str = "NY",
    ruling_data_path: Path = None,
    session_log_path: Path = None,
    max_per_year: int = None,
) -> int:
    """
    Harvests rulings across multiple years.

    Ruling data (one JSONL line per ruling) is appended to ruling_data_path:
      input_data/{collection_lower}/ruling_ids/ruling_ids_scraper.jsonl

    Session summary (one JSONL line per run) is appended to session_log_path:
      output_data/{collection_lower}/performance_logs/log_id_fetch_session.jsonl

    Returns total rulings harvested.
    """
    collection_lower = collection.lower()

    if ruling_data_path is None:
        ruling_data_path = Path(f"input_data/{collection_lower}/ruling_ids/ruling_ids_scraper.jsonl")

    if session_log_path is None:
        session_log_path = Path(f"output_data/{collection_lower}/performance_logs/log_id_fetch_session.jsonl")

    ruling_data_path.parent.mkdir(parents=True, exist_ok=True)
    session_log_path.parent.mkdir(parents=True, exist_ok=True)

    session_id    = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_start = datetime.now()

    session = requests.Session()
    session.get("https://rulings.cbp.gov", headers=HEADERS, timeout=30)

    total_harvested = 0

    for year in range(start_year, end_year + 1):
        print(f"Harvesting year {year}...")
        year_count = harvest_year(session, year, collection, session_id, ruling_data_path, max_per_year)
        total_harvested += year_count
        print(f"  Year {year} done: {year_count} rulings | Running total: {total_harvested}")

    session_elapsed = round((datetime.now() - session_start).total_seconds(), 2)

    summary = {
        "session_id":      session_id,
        "type":            "session_summary",
        "collection":      collection,
        "start_year":      start_year,
        "end_year":        end_year,
        "max_per_year":    max_per_year,
        "total_harvested": total_harvested,
        "timing": {
            "total_elapsed_sec": session_elapsed,
        },
    }
    _append_jsonl(session_log_path, summary)

    print(f"\nDone. Total rulings harvested: {total_harvested} | Time: {session_elapsed}s")
    print(f"Ruling data written to: {ruling_data_path}")
    print(f"Session log written to: {session_log_path}")

    return total_harvested


# ====================
# ENTRY POINT
# ====================
if __name__ == "__main__":
    harvest_range(
        start_year=2015,
        end_year=2024,
        collection="NY",
        max_per_year=10,  # remove this line for full harvest
    )
