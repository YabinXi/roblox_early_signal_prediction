"""
collect_genre_opportunity.py — Genre Opportunity Scanner

Maps Roblox API genre_l1 to lineage genres and computes per-genre
opportunity metrics based on genre evolution depth, saturation, and breakout history.

Output: data/raw/roblox_genre_opportunity.csv

Usage: uv run python collect_genre_opportunity.py
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_PATH = RAW_DIR / "roblox_real_snapshot.csv"
LINEAGE_PATH = RAW_DIR / "roblox_genre_lineage.csv"
OUTPUT_PATH = RAW_DIR / "roblox_genre_opportunity.csv"

# Manual mapping from Roblox API genre_l1 to lineage genre families
# This bridges the API taxonomy to our genre evolution tree
GENRE_L1_TO_LINEAGE = {
    "Shooter": "FPS",
    "Action": "FPS",  # Many action games are combat-oriented
    "Survival": "Co-op Survival",
    "Horror": "Horror Story",
    "Roleplay & Avatar Sim": "Social/RP",
    "Simulation": "Collection Simulator",
    "RPG": "Collection Simulator",  # RPG on Roblox often follows collector pattern
    "Strategy": "Collection Simulator",
    "Obby & Platformer": "Physics Survival",
    "Adventure": "Co-op Survival",
    "Party & Casual": "Social/RP",
    "Sports & Racing": "Physics Survival",
    "Social": "Social/RP",
}


def compute_lineage_depth(lineage_df: pd.DataFrame) -> dict[str, int]:
    """Compute the depth (number of era transitions) for each lineage genre.

    Depth = number of distinct eras in the lineage.
    A deeper lineage means the genre has evolved more, creating precedent for innovation.
    """
    depths = {}
    for genre, group in lineage_df.groupby("genre"):
        depths[genre] = len(group["era"].unique())
    return depths


def main():
    print("=" * 60)
    print("Genre Opportunity Scanner")
    print("=" * 60)

    # Load data
    print("\n[1/3] Loading data...")
    if not SNAPSHOT_PATH.exists():
        print(f"  [ERROR] {SNAPSHOT_PATH} not found!")
        return

    snap = pd.read_csv(SNAPSHOT_PATH)
    print(f"  ✓ Snapshot: {len(snap)} games")

    lineage_df = pd.DataFrame()
    if LINEAGE_PATH.exists():
        lineage_df = pd.read_csv(LINEAGE_PATH)
        print(f"  ✓ Lineage: {len(lineage_df)} entries across {lineage_df['genre'].nunique()} genre families")
    else:
        print("  [WARN] Genre lineage file not found. Using mapping-only approach.")

    # Map genre_l1 → lineage genre
    print("\n[2/3] Mapping genres and computing metrics...")
    snap["lineage_genre"] = snap["genre_l1"].map(GENRE_L1_TO_LINEAGE).fillna("Other")

    # Compute lineage depths
    lineage_depths = {}
    if not lineage_df.empty:
        lineage_depths = compute_lineage_depth(lineage_df)
    print(f"  Lineage depths: {lineage_depths}")

    # Per-genre opportunity metrics
    genre_records = []
    for lineage_genre, group in snap.groupby("lineage_genre"):
        n_total = len(group)
        n_breakout = int(group["is_breakout"].sum())
        breakout_rate = n_breakout / n_total if n_total > 0 else 0

        # Lineage depth from lineage tree
        depth = lineage_depths.get(lineage_genre, 1)

        # Top-10 saturation: what fraction of this genre's games are in top 10 CCU?
        top10_ids = snap.nlargest(10, "playing_ccu")["universe_id"]
        n_in_top10 = group["universe_id"].isin(top10_ids).sum()
        top10_saturation = n_in_top10 / max(n_total, 1)

        # Engagement variance: high variance = more room for anomaly
        eng_variance = group["favorites_per_1k_visits"].var()
        if np.isnan(eng_variance):
            eng_variance = 0.0

        # Mean engagement and CCU
        mean_eng = group["favorites_per_1k_visits"].mean()
        mean_ccu = group["playing_ccu"].mean()
        median_ccu = group["playing_ccu"].median()

        # Genre-level API categories present
        api_genres = group["genre_l1"].unique().tolist()

        genre_records.append({
            "lineage_genre": lineage_genre,
            "n_games": n_total,
            "n_breakout": n_breakout,
            "breakout_rate": round(breakout_rate, 4),
            "lineage_depth": depth,
            "top10_saturation": round(top10_saturation, 4),
            "engagement_variance": round(eng_variance, 4),
            "mean_engagement": round(mean_eng, 4),
            "mean_ccu": round(mean_ccu, 1),
            "median_ccu": round(median_ccu, 1),
            "api_genres_mapped": ", ".join(str(g) for g in api_genres if pd.notna(g)),
        })

    genre_df = pd.DataFrame(genre_records)

    # Also produce per-game genre opportunity scores
    print("\n[3/3] Computing per-game genre opportunity scores...")
    game_records = []
    genre_lookup = {r["lineage_genre"]: r for r in genre_records}

    for _, row in snap.iterrows():
        lineage_genre = GENRE_L1_TO_LINEAGE.get(row["genre_l1"], "Other")
        genre_info = genre_lookup.get(lineage_genre, {})

        game_records.append({
            "universe_id": row["universe_id"],
            "game_name": row["game_name"],
            "genre_l1": row["genre_l1"],
            "lineage_genre": lineage_genre,
            "lineage_depth": genre_info.get("lineage_depth", 1),
            "top10_saturation": genre_info.get("top10_saturation", 0),
            "engagement_variance": genre_info.get("engagement_variance", 0),
            "genre_breakout_rate": genre_info.get("breakout_rate", 0),
            "genre_n_breakout": genre_info.get("n_breakout", 0),
            "is_breakout": row["is_breakout"],
        })

    game_genre_df = pd.DataFrame(game_records)

    # Save outputs
    genre_df.to_csv(OUTPUT_PATH, index=False)
    print(f"\n  ✓ Genre opportunity summary: {len(genre_df)} genres → {OUTPUT_PATH}")

    # Also save per-game version for merging in analyze.py
    game_genre_path = RAW_DIR / "roblox_game_genre_opportunity.csv"
    game_genre_df.to_csv(game_genre_path, index=False)
    print(f"  ✓ Per-game genre scores: {len(game_genre_df)} games → {game_genre_path}")

    # Print summary
    print("\n  Genre Opportunity Summary:")
    print(f"  {'Genre':<25} {'N':>4} {'Brk':>4} {'Rate':>6} {'Depth':>5} {'Sat':>5} {'EngVar':>8}")
    print(f"  {'-'*25} {'---':>4} {'---':>4} {'----':>6} {'----':>5} {'----':>5} {'------':>8}")
    for _, r in genre_df.sort_values("breakout_rate", ascending=False).iterrows():
        print(
            f"  {r['lineage_genre']:<25} {r['n_games']:>4} {r['n_breakout']:>4} "
            f"{r['breakout_rate']:>6.2%} {r['lineage_depth']:>5} {r['top10_saturation']:>5.2f} "
            f"{r['engagement_variance']:>8.2f}"
        )

    print("\n" + "=" * 60)
    print("Genre opportunity scan complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
