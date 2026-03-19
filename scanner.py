"""
scanner.py — Breakout Early Warning Scanner

Integrates two signal layers:
  Layer 1 (Structural): Mechanic DNA — richness + novelty screening (monthly)
  Layer 2 (Dynamic): YouTube upload acceleration monitoring (weekly)

Usage: uv run python scanner.py [--scan | --backtest]
"""

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
YOUTUBE_WEEKLY_CSV = DATA_DIR / "timeseries" / "youtube_weekly.csv"

# Import mechanic DNA system
from mechanic_dna import (
    GAME_DNA, MECHANIC_CATALOG, MECHANIC_HISTORY,
    compute_mechanic_maturity, build_cooccurrence_matrix,
    compute_combination_novelty,
)


# ============================================================
# LAYER 1: STRUCTURAL SCREEN (Mechanic DNA)
# ============================================================

def screen_mechanic_dna(game_name: str, mechanics: list[str],
                        as_of_year: int = 2026) -> dict:
    """
    Screen a game's mechanic combination for breakout potential.
    Returns a structured assessment with scores and flags.
    """
    # Maturity per mechanic
    mats = [compute_mechanic_maturity(m, as_of_year=as_of_year) for m in mechanics]
    mat_scores = [m["maturity_score"] for m in mats]
    avg_maturity = sum(mat_scores) / len(mat_scores)
    n_mature = sum(1 for s in mat_scores if s > 0.6)
    n_fresh = sum(1 for s in mat_scores if s < 0.4)

    # Novelty (exclude games from this year)
    cooc = build_cooccurrence_matrix(as_of_year=as_of_year)
    nov = compute_combination_novelty(mechanics, cooc)

    n_mechanics = len(mechanics)
    has_novel_pair = nov["rarest_pair_count"] == 0

    # Primary rule: ≥4 mechanics + novel pair → AUC 0.676, OR 4.38
    hits_primary_rule = n_mechanics >= 4 and has_novel_pair

    # Signal strength tiers
    if n_mechanics >= 5 and has_novel_pair and n_mature >= 3:
        tier = "STRONG"
        tier_desc = "High mechanic richness + novel combination + proven components"
    elif hits_primary_rule:
        tier = "MODERATE"
        tier_desc = "Meets primary rule (≥4 mechanics + novel pair)"
    elif n_mechanics >= 4 or has_novel_pair:
        tier = "WATCH"
        tier_desc = "Partial signal — either rich or novel, not both"
    else:
        tier = "LOW"
        tier_desc = "Standard combination, low structural differentiation"

    return {
        "game": game_name,
        "mechanics": mechanics,
        "n_mechanics": n_mechanics,
        "n_mature": n_mature,
        "n_fresh": n_fresh,
        "avg_maturity": round(avg_maturity, 3),
        "has_novel_pair": has_novel_pair,
        "rarest_pair": " × ".join(nov["rarest_pair"]) if nov["rarest_pair"] else None,
        "rarest_pair_count": nov["rarest_pair_count"],
        "rarest_triple": " × ".join(nov["rarest_triple"]) if nov["rarest_triple"] else None,
        "rarest_triple_count": nov["rarest_triple_count"],
        "hits_primary_rule": hits_primary_rule,
        "tier": tier,
        "tier_desc": tier_desc,
        "maturity_breakdown": [
            {"mechanic": m["mechanic"], "score": m["maturity_score"]}
            for m in mats
        ],
    }


# ============================================================
# LAYER 2: YOUTUBE ACCELERATION MONITOR (stub for weekly runs)
# ============================================================

def load_youtube_history(game_name: str) -> list[dict] | None:
    """
    Load real YouTube weekly history for a game from youtube_weekly.csv.

    Returns a list of weekly snapshots sorted by week, or None if no data found.
    Each entry: {"week": "2026-W12", "upload_velocity_7d": 3, "unique_creators": 2, ...}
    """
    if not YOUTUBE_WEEKLY_CSV.exists():
        return None

    records = []
    with open(YOUTUBE_WEEKLY_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("game_name") == game_name:
                records.append({
                    "week": row["snapshot_week"],
                    "upload_velocity_7d": int(row.get("upload_velocity_7d", 0)),
                    "upload_velocity_30d": int(row.get("upload_velocity_30d", 0)),
                    "unique_creators": int(row.get("unique_creators", 0)),
                    "recent_video_avg_views": float(row.get("recent_video_avg_views", 0)),
                    "view_acceleration": float(row.get("view_acceleration", 0)),
                    "youtube_video_count": int(row.get("youtube_video_count", 0)),
                    "youtube_total_views": int(row.get("youtube_total_views", 0)),
                    "youtube_avg_views": float(row.get("youtube_avg_views", 0)),
                })

    if not records:
        return None

    # Sort by ISO week string (lexicographic sort works for ISO weeks)
    records.sort(key=lambda x: x["week"])
    return records

def check_youtube_acceleration(game_name: str,
                               history: list[dict] = None) -> dict:
    """
    Check YouTube upload velocity acceleration for a game.

    Expects `history` as a list of weekly snapshots:
      [{"week": "2025-03-01", "upload_velocity_7d": 3, "unique_creators": 2}, ...]

    Returns acceleration signals.
    """
    if not history or len(history) < 3:
        return {
            "game": game_name,
            "status": "INSUFFICIENT_DATA",
            "weeks_tracked": len(history) if history else 0,
            "alert": False,
        }

    # Sort by week
    history = sorted(history, key=lambda x: x["week"])

    # Compute week-over-week changes
    velocities = [h.get("upload_velocity_7d", 0) for h in history]
    creators = [h.get("unique_creators", 0) for h in history]

    # Acceleration: compare last 2 weeks vs prior 2 weeks
    recent = velocities[-2:]
    prior = velocities[-4:-2] if len(velocities) >= 4 else velocities[:2]

    recent_avg = sum(recent) / len(recent) if recent else 0
    prior_avg = sum(prior) / len(prior) if prior else 0

    if prior_avg > 0:
        acceleration = (recent_avg - prior_avg) / prior_avg
    elif recent_avg > 0:
        acceleration = float("inf")
    else:
        acceleration = 0.0

    # Creator diversity trend
    recent_creators = creators[-1] if creators else 0
    prior_creators = creators[-3] if len(creators) >= 3 else creators[0] if creators else 0
    creator_growth = recent_creators - prior_creators

    # Alert conditions
    #   - upload velocity doubled week-over-week for 2 consecutive weeks
    #   - OR acceleration > 100% AND at least 5 videos/week
    consecutive_doubles = 0
    for i in range(1, len(velocities)):
        if velocities[i - 1] > 0 and velocities[i] / velocities[i - 1] >= 2.0:
            consecutive_doubles += 1
        else:
            consecutive_doubles = 0

    alert = (
        consecutive_doubles >= 2
        or (acceleration > 1.0 and recent_avg >= 5)
        or (recent_avg >= 15 and creator_growth >= 3)
    )

    # Alert tier
    if consecutive_doubles >= 3 and recent_avg >= 10:
        alert_tier = "CRITICAL"
    elif alert:
        alert_tier = "WARNING"
    elif acceleration > 0.5 and recent_avg >= 3:
        alert_tier = "WATCH"
    else:
        alert_tier = "NORMAL"

    return {
        "game": game_name,
        "status": "OK",
        "weeks_tracked": len(history),
        "current_velocity": recent_avg,
        "prior_velocity": prior_avg,
        "acceleration": round(acceleration, 2) if acceleration != float("inf") else "inf",
        "consecutive_doubles": consecutive_doubles,
        "creator_count": recent_creators,
        "creator_growth": creator_growth,
        "alert": alert,
        "alert_tier": alert_tier,
    }


# ============================================================
# COMBINED ASSESSMENT
# ============================================================

def combined_assessment(dna_result: dict, yt_result: dict) -> dict:
    """
    Combine structural (DNA) and dynamic (YouTube) signals
    into a single actionable recommendation.
    """
    dna_tier = dna_result["tier"]
    yt_tier = yt_result.get("alert_tier", "NORMAL")

    # Decision matrix
    #                    YT:NORMAL  YT:WATCH  YT:WARNING  YT:CRITICAL
    # DNA:STRONG         Watch      Alert     ALERT       🔴 ACT
    # DNA:MODERATE       Watch      Watch     Alert       ALERT
    # DNA:WATCH          —          Watch     Watch       Alert
    # DNA:LOW            —          —         Watch       Watch

    matrix = {
        ("STRONG",   "CRITICAL"):  ("ACT",   "Both structural + dynamic signals aligned — high confidence"),
        ("STRONG",   "WARNING"):   ("ALERT", "Strong DNA + YouTube acceleration detected"),
        ("STRONG",   "WATCH"):     ("ALERT", "Strong DNA + YouTube stirring — monitor closely"),
        ("STRONG",   "NORMAL"):    ("WATCH", "Strong DNA but no dynamic signal yet"),
        ("MODERATE", "CRITICAL"):  ("ALERT", "Moderate DNA + extreme YouTube acceleration"),
        ("MODERATE", "WARNING"):   ("ALERT", "Moderate DNA + YouTube acceleration"),
        ("MODERATE", "WATCH"):     ("WATCH", "Moderate DNA + early YouTube signs"),
        ("MODERATE", "NORMAL"):    ("WATCH", "Moderate DNA — add to scan list"),
        ("WATCH",    "CRITICAL"):  ("ALERT", "Partial DNA but extreme YouTube signal"),
        ("WATCH",    "WARNING"):   ("WATCH", "Partial DNA + YouTube activity"),
        ("WATCH",    "WATCH"):     ("WATCH", "Weak signals — continue monitoring"),
        ("WATCH",    "NORMAL"):    ("IGNORE","No actionable signal"),
        ("LOW",      "CRITICAL"):  ("WATCH", "Low DNA but unexpected YouTube surge"),
        ("LOW",      "WARNING"):   ("WATCH", "Low DNA but YouTube activity"),
        ("LOW",      "WATCH"):     ("IGNORE","No actionable signal"),
        ("LOW",      "NORMAL"):    ("IGNORE","No actionable signal"),
    }

    action, rationale = matrix.get(
        (dna_tier, yt_tier),
        ("IGNORE", "Unknown combination")
    )

    return {
        "game": dna_result["game"],
        "action": action,
        "rationale": rationale,
        "dna_tier": dna_tier,
        "yt_alert_tier": yt_tier,
        "mechanics": dna_result["mechanics"],
        "rarest_pair": dna_result.get("rarest_pair"),
        "yt_acceleration": yt_result.get("acceleration"),
        "yt_velocity": yt_result.get("current_velocity"),
    }


# ============================================================
# BACKTEST: Simulate scanning with historical data
# ============================================================

def backtest():
    """
    Backtest the scanner against known breakouts.
    For each breakout, simulate what the scanner would have flagged
    BEFORE the breakout date, using only data available at that time.
    """
    print("=" * 80)
    print("BACKTEST: Could we have caught these breakouts?")
    print("=" * 80)

    # Simulated YouTube history for backtesting
    # Based on the Grow a Garden timeline reconstruction
    simulated_yt = {
        "Grow a Garden": [
            {"week": "2025-01-06", "upload_velocity_7d": 0, "unique_creators": 0},
            {"week": "2025-01-13", "upload_velocity_7d": 1, "unique_creators": 1},
            {"week": "2025-02-03", "upload_velocity_7d": 1, "unique_creators": 1},
            {"week": "2025-03-03", "upload_velocity_7d": 2, "unique_creators": 2},
            {"week": "2025-03-10", "upload_velocity_7d": 3, "unique_creators": 2},
            {"week": "2025-03-17", "upload_velocity_7d": 5, "unique_creators": 3},
            {"week": "2025-03-24", "upload_velocity_7d": 8, "unique_creators": 5},
            {"week": "2025-04-07", "upload_velocity_7d": 15, "unique_creators": 8},
            {"week": "2025-04-14", "upload_velocity_7d": 22, "unique_creators": 12},
            {"week": "2025-05-05", "upload_velocity_7d": 35, "unique_creators": 18},
            # BREAKOUT: 2025-06-15
        ],
        "Dead Rails": [
            {"week": "2025-01-06", "upload_velocity_7d": 0, "unique_creators": 0},
            {"week": "2025-01-20", "upload_velocity_7d": 1, "unique_creators": 1},
            {"week": "2025-02-03", "upload_velocity_7d": 2, "unique_creators": 2},
            {"week": "2025-02-17", "upload_velocity_7d": 6, "unique_creators": 4},
            {"week": "2025-03-03", "upload_velocity_7d": 14, "unique_creators": 8},
            {"week": "2025-03-17", "upload_velocity_7d": 28, "unique_creators": 15},
            # BREAKOUT: 2025-04-01
        ],
        "99 Nights in the Forest": [
            {"week": "2025-11-03", "upload_velocity_7d": 0, "unique_creators": 0},
            {"week": "2025-11-17", "upload_velocity_7d": 2, "unique_creators": 2},
            {"week": "2025-12-01", "upload_velocity_7d": 5, "unique_creators": 3},
            {"week": "2025-12-15", "upload_velocity_7d": 12, "unique_creators": 7},
            {"week": "2025-12-29", "upload_velocity_7d": 25, "unique_creators": 12},
            {"week": "2026-01-05", "upload_velocity_7d": 50, "unique_creators": 25},
            # BREAKOUT: 2026-01-20
        ],
        "Fisch": [
            {"week": "2024-12-02", "upload_velocity_7d": 1, "unique_creators": 1},
            {"week": "2024-12-16", "upload_velocity_7d": 2, "unique_creators": 2},
            {"week": "2024-12-30", "upload_velocity_7d": 4, "unique_creators": 3},
            {"week": "2025-01-13", "upload_velocity_7d": 10, "unique_creators": 6},
            {"week": "2025-01-27", "upload_velocity_7d": 18, "unique_creators": 10},
            {"week": "2025-02-10", "upload_velocity_7d": 30, "unique_creators": 16},
            # BREAKOUT: 2025-03-01
        ],
        "DOORS": [
            {"week": "2022-06-01", "upload_velocity_7d": 0, "unique_creators": 0},
            {"week": "2022-06-15", "upload_velocity_7d": 3, "unique_creators": 2},
            {"week": "2022-07-01", "upload_velocity_7d": 8, "unique_creators": 5},
            {"week": "2022-07-15", "upload_velocity_7d": 20, "unique_creators": 12},
            {"week": "2022-08-01", "upload_velocity_7d": 45, "unique_creators": 25},
            # BREAKOUT: 2022-08 (Hotel+ update)
        ],
        "Sol's RNG": [
            {"week": "2024-05-01", "upload_velocity_7d": 1, "unique_creators": 1},
            {"week": "2024-05-15", "upload_velocity_7d": 3, "unique_creators": 2},
            {"week": "2024-06-01", "upload_velocity_7d": 8, "unique_creators": 5},
            {"week": "2024-06-15", "upload_velocity_7d": 20, "unique_creators": 11},
            {"week": "2024-07-01", "upload_velocity_7d": 35, "unique_creators": 18},
            # BREAKOUT: 2024-07
        ],
    }

    breakout_dates = {
        "Grow a Garden": "2025-06-15",
        "Dead Rails": "2025-04-01",
        "99 Nights in the Forest": "2026-01-20",
        "Fisch": "2025-03-01",
        "DOORS": "2022-08-15",
        "Sol's RNG": "2024-07-15",
    }

    results = []
    for game_name, yt_history in simulated_yt.items():
        data = GAME_DNA.get(game_name)
        if not data:
            continue

        # Layer 1: DNA screen
        dna = screen_mechanic_dna(game_name, data["mechanics"],
                                  as_of_year=data["year"])

        # Layer 2: YouTube at various time points
        # Find first alert point
        first_alert_week = None
        for i in range(3, len(yt_history) + 1):
            partial = yt_history[:i]
            yt = check_youtube_acceleration(game_name, partial)
            if yt["alert"]:
                first_alert_week = partial[-1]["week"]
                first_yt = yt
                break

        if first_alert_week:
            combined = combined_assessment(dna, first_yt)
            breakout_date = breakout_dates[game_name]
            # Calculate lead time
            from datetime import datetime as dt
            alert_dt = dt.strptime(first_alert_week, "%Y-%m-%d")
            breakout_dt = dt.strptime(breakout_date, "%Y-%m-%d")
            lead_days = (breakout_dt - alert_dt).days
        else:
            combined = combined_assessment(dna, {"alert_tier": "NORMAL"})
            lead_days = 0
            first_alert_week = "—"

        results.append({
            "game": game_name,
            "dna_tier": dna["tier"],
            "rarest_pair": dna.get("rarest_pair", "—"),
            "n_mechanics": dna["n_mechanics"],
            "yt_first_alert": first_alert_week,
            "yt_alert_tier": combined.get("yt_alert_tier", "NORMAL"),
            "combined_action": combined["action"],
            "lead_days": lead_days,
            "breakout_date": breakout_dates[game_name],
        })

    # Print results
    print(f"\n{'Game':<30} {'DNA':>8} {'#M':>3} {'YT Alert':>12} {'Action':>8} {'Lead':>6} {'Breakout':>12}")
    print("-" * 90)
    for r in sorted(results, key=lambda x: x["lead_days"], reverse=True):
        print(f"{r['game']:<30} {r['dna_tier']:>8} {r['n_mechanics']:>3} "
              f"{r['yt_first_alert']:>12} {r['combined_action']:>8} "
              f"{r['lead_days']:>4}d  {r['breakout_date']:>12}")

    # Summary
    caught = sum(1 for r in results if r["combined_action"] in ("ACT", "ALERT"))
    avg_lead = sum(r["lead_days"] for r in results if r["lead_days"] > 0) / max(1, sum(1 for r in results if r["lead_days"] > 0))
    print(f"\nCaught: {caught}/{len(results)} breakouts")
    print(f"Avg lead time: {avg_lead:.0f} days")
    print(f"\nNOTE: YouTube timelines are SIMULATED based on typical patterns.")
    print(f"Real validation requires actual weekly YouTube data collection.")

    return results


# ============================================================
# SCAN MODE: Analyze current watchlist
# ============================================================

def scan_current():
    """Scan all games in GAME_DNA and print current assessment."""
    print("=" * 80)
    print(f"BREAKOUT SCANNER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Check for real YouTube timeseries data
    has_yt_data = YOUTUBE_WEEKLY_CSV.exists()
    if has_yt_data:
        print(f"[INFO] Real YouTube timeseries found: {YOUTUBE_WEEKLY_CSV}")
    else:
        print("[INFO] No YouTube timeseries data — using NORMAL for all games")

    results = []
    for game_name, data in GAME_DNA.items():
        dna = screen_mechanic_dna(game_name, data["mechanics"])

        # Try loading real YouTube history
        yt_result = {"alert_tier": "NORMAL"}
        if has_yt_data:
            history = load_youtube_history(game_name)
            if history:
                yt_result = check_youtube_acceleration(game_name, history)

        combined = combined_assessment(dna, yt_result)
        combined["is_breakout_actual"] = data["is_breakout"]
        combined["yt_data_source"] = "real" if (has_yt_data and yt_result.get("status") != "INSUFFICIENT_DATA") else "none"
        results.append(combined)

    # Sort by action priority
    action_order = {"ACT": 0, "ALERT": 1, "WATCH": 2, "IGNORE": 3}
    results.sort(key=lambda x: (action_order.get(x["action"], 99), x["game"]))

    print(f"\n{'Action':<8} {'Game':<35} {'DNA Tier':>10} {'YT Tier':>10} {'YT Src':>6} {'Actual':>8} {'Rarest Pair':<35}")
    print("-" * 120)
    for r in results:
        actual = "BO" if r.get("is_breakout_actual") else "-"
        rarest = r.get("rarest_pair") or "-"
        src = r.get("yt_data_source", "none")
        print(f"{r['action']:<8} {r['game']:<35} {r['dna_tier']:>10} {r['yt_alert_tier']:>10} {src:>6} {actual:>8} {rarest:<35}")

    # Save
    output_path = OUTPUT_DIR / "scanner_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Saved to {output_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--backtest":
        backtest()
    else:
        scan_current()
        print("\n")
        backtest()


if __name__ == "__main__":
    main()
