"""
collect_youtube_timeseries.py — Weekly YouTube signal collector for time-series analysis

Reuses YouTube scraping logic from collect_buzz_data.py. Each run appends one week's
YouTube signals per game to data/timeseries/youtube_weekly.csv.
Idempotent: skips if this ISO week already collected (unless --force).

Usage:
    uv run python collect_youtube_timeseries.py          # collect this week's snapshot
    uv run python collect_youtube_timeseries.py --force   # re-collect even if week exists

Output:
    data/timeseries/youtube_weekly.csv          — append-only weekly YouTube signals
    data/timeseries/youtube_collection_log.json — collection run log
"""

import csv
import json
import sys
import time as _time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# Reuse YouTube helpers from collect_buzz_data
from collect_buzz_data import (
    clean_game_name,
    _extract_video_fields,
    _compute_youtube_signals,
)

BASE_DIR = Path(__file__).parent
TIMESERIES_DIR = BASE_DIR / "data" / "timeseries"
TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_PATH = BASE_DIR / "data" / "processed" / "roblox_real_snapshot.csv"
YOUTUBE_CSV = TIMESERIES_DIR / "youtube_weekly.csv"
COLLECTION_LOG = TIMESERIES_DIR / "youtube_collection_log.json"

CSV_FIELDS = [
    "snapshot_week",
    "game_name",
    "youtube_video_count",
    "upload_velocity_7d",
    "upload_velocity_30d",
    "unique_creators",
    "recent_video_avg_views",
    "view_acceleration",
    "short_video_ratio",
    "title_update_freq",
    "youtube_total_views",
    "youtube_avg_views",
]


def current_iso_week() -> str:
    """Return current ISO week string like '2026-W12'."""
    today = date.today()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_already_collected(week_str: str) -> bool:
    """Check if the given ISO week already has data in the CSV."""
    if not YOUTUBE_CSV.exists():
        return False
    with open(YOUTUBE_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("snapshot_week") == week_str:
                return True
    return False


def append_rows(rows: list[dict]):
    """Append rows to the YouTube weekly CSV. Creates file with header if missing."""
    write_header = not YOUTUBE_CSV.exists() or YOUTUBE_CSV.stat().st_size == 0
    with open(YOUTUBE_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def update_log(entry: dict):
    """Append an entry to the YouTube collection log JSON."""
    log = []
    if COLLECTION_LOG.exists():
        try:
            log = json.loads(COLLECTION_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            log = []
    log.append(entry)
    COLLECTION_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


def load_game_list() -> list[str]:
    """Load game names from snapshot, filter out player places, return cleaned names."""
    if not SNAPSHOT_PATH.exists():
        print(f"  [ERROR] {SNAPSHOT_PATH} not found!")
        return []

    snap = pd.read_csv(SNAPSHOT_PATH)
    raw_names = snap["game_name"].tolist()

    # Filter out player places (e.g. "'s Place" pattern)
    filtered = []
    for name in raw_names:
        if "'s Place" in str(name):
            continue
        clean = clean_game_name(str(name))
        if len(clean) > 2:
            filtered.append(clean)

    return filtered


def collect(force: bool = False) -> dict:
    """Run the full weekly YouTube collection pipeline. Returns a log entry dict."""
    week_str = current_iso_week()
    start = _time.time()
    errors = []

    print("=" * 60)
    print("YouTube Weekly Time-Series Collector")
    print(f"Week: {week_str}  ({date.today().isoformat()})")
    print("=" * 60)

    # Idempotency check
    if not force and week_already_collected(week_str):
        print(f"\n[SKIP] Week {week_str} already collected. Use --force to re-collect.")
        return {"week": week_str, "status": "skipped"}

    # Load game list
    print("\n[1/2] Loading game list...")
    game_names = load_game_list()
    if not game_names:
        print("  [ERROR] No games found!")
        return {"week": week_str, "status": "error", "errors": ["No games found"]}
    print(f"  Found {len(game_names)} games")

    # Fetch YouTube data
    print(f"\n[2/2] Fetching YouTube signals ({len(game_names)} games, ~50 videos each)...")
    try:
        import scrapetube
    except ImportError:
        print("  [ERROR] scrapetube not installed. Run: uv add scrapetube")
        return {"week": week_str, "status": "error", "errors": ["scrapetube not installed"]}

    rows = []
    for idx, name in enumerate(game_names):
        query = f"Roblox {name}"
        print(f"  [{idx + 1}/{len(game_names)}] Fetching {name}...")
        try:
            videos = list(scrapetube.get_search(query=query, limit=50))
            video_fields = [_extract_video_fields(v) for v in videos]
            signals = _compute_youtube_signals(video_fields)

            row = {
                "snapshot_week": week_str,
                "game_name": name,
                "youtube_video_count": signals["youtube_video_count"],
                "upload_velocity_7d": signals["upload_velocity_7d"],
                "upload_velocity_30d": signals["upload_velocity_30d"],
                "unique_creators": signals["unique_creators"],
                "recent_video_avg_views": signals["recent_video_avg_views"],
                "view_acceleration": signals["view_acceleration"],
                "short_video_ratio": signals["short_video_ratio"],
                "title_update_freq": signals["title_update_freq"],
                "youtube_total_views": signals["youtube_total_views"],
                "youtube_avg_views": signals["youtube_avg_views"],
            }
            rows.append(row)
        except Exception as e:
            err_msg = f"{name}: {e}"
            errors.append(err_msg)
            print(f"    [ERROR] {err_msg}")
            # Write a zero-row so we know we attempted this game
            row = {
                "snapshot_week": week_str,
                "game_name": name,
                "youtube_video_count": 0,
                "upload_velocity_7d": 0,
                "upload_velocity_30d": 0,
                "unique_creators": 0,
                "recent_video_avg_views": 0.0,
                "view_acceleration": 0.0,
                "short_video_ratio": 0.0,
                "title_update_freq": 0.0,
                "youtube_total_views": 0,
                "youtube_avg_views": 0.0,
            }
            rows.append(row)

    # Append to CSV
    if rows:
        append_rows(rows)

    duration = round(_time.time() - start, 1)
    n_success = len(rows) - len(errors)

    log_entry = {
        "week": week_str,
        "date": date.today().isoformat(),
        "n_games": len(rows),
        "n_success": n_success,
        "n_errors": len(errors),
        "errors": errors if errors else [],
        "duration_seconds": duration,
        "status": "ok",
    }
    update_log(log_entry)

    # Summary
    print("\n" + "=" * 60)
    print("YouTube Weekly Collection Summary:")
    print(f"  Week:      {week_str}")
    print(f"  Games:     {n_success}/{len(rows)} succeeded")
    print(f"  Errors:    {len(errors)}")
    print(f"  Duration:  {duration}s")
    print(f"  Output:    {YOUTUBE_CSV}")
    if rows:
        # Top 5 by upload velocity
        top = sorted(rows, key=lambda r: r["upload_velocity_7d"], reverse=True)[:5]
        print(f"  Top 5 by upload_velocity_7d:")
        for r in top:
            print(f"    {r['game_name']}: {r['upload_velocity_7d']} uploads/7d, "
                  f"{r['unique_creators']} creators")
    print("=" * 60)

    return log_entry


def main():
    force = "--force" in sys.argv
    collect(force=force)


if __name__ == "__main__":
    main()
