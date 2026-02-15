import argparse
import os
from pathlib import Path


def _try_delete(path: Path) -> bool:
    try:
        if path.is_dir():
            # remove empty dirs only; files are handled elsewhere
            path.rmdir()
        else:
            path.unlink()
        return True
    except Exception:
        return False


def clean_cache(cache_dir: str) -> int:
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        print(f"[clean_cache] Nothing to do (missing): {cache_path}")
        return 0

    failed = []
    # Delete files first
    for p in sorted(cache_path.rglob("*")):
        if p.is_file():
            if not _try_delete(p):
                failed.append(p)

    # Then delete empty dirs (deepest first)
    for p in sorted([x for x in cache_path.rglob("*") if x.is_dir()], reverse=True):
        _try_delete(p)

    if failed:
        print("[clean_cache] Could not delete (likely locked by Word/WINWORD.exe):")
        for p in failed:
            print(f" - {p}")
        print("\nClose Word (and ensure no WINWORD.exe is lingering), then re-run clean_cache.py.")
        return 1

    print(f"[clean_cache] Cache cleared: {cache_path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", default="cache", help="Cache directory to clear (default: cache)")
    args = ap.parse_args()
    raise SystemExit(clean_cache(args.cache_dir))
