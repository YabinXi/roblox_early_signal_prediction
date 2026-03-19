"""
collect_daily_snapshot.py — Daily Roblox metrics collector for time-series analysis

Reuses API logic from collect_real_data.py. Each run appends one day's snapshot
to data/timeseries/roblox_daily_snapshot.csv. Idempotent: skips if today's
snapshot already exists.

Usage:
    uv run python collect_daily_snapshot.py          # collect today's snapshot
    uv run python collect_daily_snapshot.py --force   # re-collect even if today exists

After 6-8 weeks of daily collection you'll have real temporal data to test
whether engagement signals precede breakout events.
"""

import csv
import json
import sys
import time as _time
from datetime import datetime, date
from pathlib import Path

# Reuse everything from collect_real_data
from collect_real_data import (
    KNOWN_GAMES,
    resolve_universe_ids,
    fetch_game_details,
    fetch_votes,
    compute_engagement_metrics,
)

BASE_DIR = Path(__file__).parent
TIMESERIES_DIR = BASE_DIR / "data" / "timeseries"
TIMESERIES_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_CSV = TIMESERIES_DIR / "roblox_daily_snapshot.csv"
COLLECTION_LOG = TIMESERIES_DIR / "collection_log.json"

# Schema for the daily snapshot CSV (matches roblox_real_snapshot.csv + snapshot_date)
CSV_FIELDS = [
    "snapshot_date",
    "universe_id",
    "game_name",
    "genre",
    "genre_l1",
    "genre_l2",
    "playing_ccu",
    "total_visits",
    "favorited_count",
    "up_votes",
    "down_votes",
    "like_ratio",
    "favorites_per_1k_visits",
    "favorites_per_visit",
    "engagement_score",
    "created_date",
    "age_days",
    "tier",
    "is_breakout",
    "breakout_year",
    "ccu_rank",
]


def today_already_collected() -> bool:
    """Check if today's snapshot already exists in the CSV."""
    today_str = date.today().isoformat()
    if not SNAPSHOT_CSV.exists():
        return False
    with open(SNAPSHOT_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("snapshot_date") == today_str:
                return True
    return False


def append_rows(rows: list[dict]):
    """Append rows to the snapshot CSV. Creates file with header if missing."""
    write_header = not SNAPSHOT_CSV.exists() or SNAPSHOT_CSV.stat().st_size == 0
    with open(SNAPSHOT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def update_log(entry: dict):
    """Append an entry to the collection log JSON."""
    log = []
    if COLLECTION_LOG.exists():
        try:
            log = json.loads(COLLECTION_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            log = []
    log.append(entry)
    COLLECTION_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")


def collect() -> dict:
    """Run the full collection pipeline. Returns a log entry dict."""
    today_str = date.today().isoformat()
    start = _time.time()
    errors = []

    print("=" * 60)
    print("Roblox Daily Snapshot Collector")
    print(f"Date: {today_str}")
    print(f"Games in curated list: {len(KNOWN_GAMES)}")
    print("=" * 60)

    # Validate games
    valid_games = {}
    for name, meta in KNOWN_GAMES.items():
        pid = meta.get("place_id")
        if isinstance(pid, int) and pid > 0:
            valid_games[name] = dict(meta)  # copy so we don't mutate original
        else:
            errors.append(f"Invalid place_id for {name}")

    print(f"\nValid games: {len(valid_games)}")

    # Step 1: Resolve universe IDs
    print(f"\n[1/4] Resolving place IDs -> universe IDs ({len(valid_games)} games)...")
    place_ids = [m["place_id"] for m in valid_games.values()]
    pid_to_uid = resolve_universe_ids(place_ids)
    n_resolved = len(pid_to_uid)
    n_failed = len(place_ids) - n_resolved
    if n_failed > 0:
        errors.append(f"Failed to resolve {n_failed} place IDs")
    print(f"  Resolved: {n_resolved}/{len(place_ids)}")

    # Attach universe IDs to metadata
    for name, meta in valid_games.items():
        pid = meta["place_id"]
        if pid in pid_to_uid:
            meta["_universe_id"] = pid_to_uid[pid]

    universe_ids = list(pid_to_uid.values())

    if not universe_ids:
        errors.append("No universe IDs resolved — aborting")
        duration = round(_time.time() - start, 1)
        log_entry = {
            "date": today_str,
            "n_games": 0,
            "n_errors": len(errors),
            "errors": errors,
            "duration_seconds": duration,
        }
        update_log(log_entry)
        print(f"\n[ERROR] No data collected. Errors: {errors}")
        return log_entry

    # Step 2: Fetch game details
    print(f"\n[2/4] Fetching game details ({len(universe_ids)} games)...")
    game_details = fetch_game_details(universe_ids)
    if len(game_details) < len(universe_ids):
        errors.append(f"Only fetched {len(game_details)}/{len(universe_ids)} game details")
    print(f"  Fetched: {len(game_details)} games")

    # Step 3: Fetch votes
    print(f"\n[3/4] Fetching votes...")
    votes = fetch_votes(universe_ids)
    print(f"  Votes fetched: {len(votes)}")

    # Step 4: Compute metrics
    print(f"\n[4/4] Computing engagement metrics...")
    rows = compute_engagement_metrics(game_details, votes, valid_games)

    # Sort by CCU descending and add rank
    rows.sort(key=lambda x: x["playing_ccu"], reverse=True)
    for i, row in enumerate(rows):
        row["ccu_rank"] = i + 1
        # Replace snapshot_time with snapshot_date
        row["snapshot_date"] = today_str

    # Append to CSV (don't overwrite previous data)
    append_rows(rows)

    duration = round(_time.time() - start, 1)
    log_entry = {
        "date": today_str,
        "n_games": len(rows),
        "n_errors": len(errors),
        "errors": errors if errors else [],
        "duration_seconds": duration,
    }
    update_log(log_entry)

    # Print summary
    print("\n" + "=" * 60)
    print("Daily Snapshot Summary:")
    print(f"  Date: {today_str}")
    print(f"  Games collected: {len(rows)}")
    print(f"  Errors: {len(errors)}")
    print(f"  Duration: {duration}s")
    print(f"  Output: {SNAPSHOT_CSV}")
    if rows:
        print(f"  Top 5 by CCU:")
        for r in rows[:5]:
            print(f"    #{r['ccu_rank']} {r['game_name']}: {r['playing_ccu']:,} CCU")
    print("=" * 60)

    return log_entry


def main():
    force = "--force" in sys.argv

    if not force and today_already_collected():
        today_str = date.today().isoformat()
        print(f"[SKIP] Snapshot for {today_str} already collected. Use --force to re-collect.")
        return

    collect()


if __name__ == "__main__":
    main()
