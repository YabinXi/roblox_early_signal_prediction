"""
collect_real_data.py — Roblox real data collector via official API

Strategy:
1. Start with a curated list of ~80 known game place IDs (top + mid-tier + breakout)
2. Convert place IDs → universe IDs via Roblox API
3. Batch-fetch game details (CCU, visits, favorites, likes) for all universe IDs
4. Fetch votes (likes/dislikes) for all games
5. Compute engagement proxy metrics:
   - favorites_per_visit = favoritedCount / visits
   - like_ratio = upVotes / (upVotes + downVotes)
   - engagement_score = favorites_per_visit * like_ratio * log(playing + 1)
6. Classify games: breakout vs stable vs declining
7. Output CSVs to data/raw/

Usage: uv run python collect_real_data.py
"""

import json
import csv
import time
import math
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Curated game list: place IDs of Roblox games across tiers
# Sources: Roblox Discover page, GDC talk mentions, public records
# ============================================================

KNOWN_GAMES = {
    # === Current/Recent Top 10 (2025-2026 verified breakouts) ===
    "Adopt Me!": {"place_id": 920587237, "tier": "top", "is_breakout": True, "breakout_year": 2019},
    "Brookhaven RP": {"place_id": 4924922222, "tier": "top", "is_breakout": True, "breakout_year": 2020},
    "Blox Fruits": {"place_id": 2753915549, "tier": "top", "is_breakout": True, "breakout_year": 2021},
    "Murder Mystery 2": {"place_id": 142823291, "tier": "top", "is_breakout": True, "breakout_year": 2017},
    "Tower of Hell": {"place_id": 3956818381, "tier": "top", "is_breakout": True, "breakout_year": 2020},
    "MeepCity": {"place_id": 370731277, "tier": "top", "is_breakout": True, "breakout_year": 2016},
    "Royal High": {"place_id": 735030788, "tier": "top", "is_breakout": True, "breakout_year": 2018},
    "Bee Swarm Simulator": {"place_id": 1537690962, "tier": "top", "is_breakout": True, "breakout_year": 2018},
    "Jailbreak": {"place_id": 606849621, "tier": "top", "is_breakout": True, "breakout_year": 2017},
    "Natural Disaster Survival": {"place_id": 189707, "tier": "top", "is_breakout": True, "breakout_year": 2014},

    # === 2024-2026 Breakout Games (from GDC talk + public records) ===
    "Dress to Impress": {"place_id": 15800556674, "tier": "breakout", "is_breakout": True, "breakout_year": 2024},
    "Fisch": {"place_id": 16732694052, "tier": "breakout", "is_breakout": True, "breakout_year": 2025},
    "Rivals (FPS)": {"place_id": 17625359962, "tier": "breakout", "is_breakout": True, "breakout_year": 2025},
    "The Strongest Battlegrounds": {"place_id": 10449761463, "tier": "breakout", "is_breakout": True, "breakout_year": 2024},
    "Doors": {"place_id": 6516141723, "tier": "breakout", "is_breakout": True, "breakout_year": 2022},
    "Pet Simulator X": {"place_id": 6284583030, "tier": "breakout", "is_breakout": True, "breakout_year": 2022},
    "Pet Simulator 99": {"place_id": 8737602449, "tier": "breakout", "is_breakout": True, "breakout_year": 2024},
    "King Legacy": {"place_id": 3526622498, "tier": "breakout", "is_breakout": True, "breakout_year": 2021},
    "Anime Defenders": {"place_id": 16257008507, "tier": "breakout", "is_breakout": True, "breakout_year": 2024},
    "Build a Boat for Treasure": {"place_id": 537413528, "tier": "top", "is_breakout": True, "breakout_year": 2017},

    # === Established Mid-to-High Tier (stable, not recent breakout) ===
    "Phantom Forces": {"place_id": 292439477, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Arsenal": {"place_id": 286090429, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Work at a Pizza Place": {"place_id": 192800, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Theme Park Tycoon 2": {"place_id": 69184822, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Welcome to Bloxburg": {"place_id": 185655149, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Shindo Life": {"place_id": 4616652839, "tier": "established", "is_breakout": False, "breakout_year": None},
    "All Star Tower Defense": {"place_id": 4996049426, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Da Hood": {"place_id": 2788229376, "tier": "established", "is_breakout": False, "breakout_year": None},
    "My Restaurant": {"place_id": 4490140733, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Piggy": {"place_id": 4623386862, "tier": "established", "is_breakout": False, "breakout_year": None},

    # === Mid-tier (rank ~50-200, some with engagement anomalies) ===
    "Survive the Killer": {"place_id": 4010583755, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Super Golf!": {"place_id": 4468711919, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Mega Easy Obby": {"place_id": 4833958586, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Speed Run 4": {"place_id": 183364845, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Ninja Legends": {"place_id": 3956853860, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Vehicle Simulator": {"place_id": 171391948, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Zombie Rush": {"place_id": 227951958, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Bubble Gum Simulator": {"place_id": 2132891063, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Islands": {"place_id": 4985380759, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Dragon Adventures": {"place_id": 3475397644, "tier": "mid", "is_breakout": False, "breakout_year": None},

    # === Lower mid-tier / niche (rank ~150-500) ===
    "Super Bomb Survival!!": {"place_id": 143920996, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Epic Minigames": {"place_id": 277751860, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Lumber Tycoon 2": {"place_id": 13822889, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Flee the Facility": {"place_id": 893973440, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Treasure Quest": {"place_id": 3022176498, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Mining Simulator 2": {"place_id": 8637389500, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Be a Parkour Ninja": {"place_id": 5765454932, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Wacky Wizards": {"place_id": 7118833702, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Creatures of Sonaria": {"place_id": 5233782396, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Funky Friday": {"place_id": 6447798030, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},

    # === Recent newcomers / trending (2025-2026, various tiers) ===
    "Deepwoken": {"place_id": 4111023553, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Sols RNG": {"place_id": 15532962292, "tier": "breakout", "is_breakout": True, "breakout_year": 2025},
    "Type Soul": {"place_id": 13026738541, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "A Dusty Trip": {"place_id": 16389395869, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Arm Wrestle Simulator": {"place_id": 12839050781, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Blade Ball": {"place_id": 13772394625, "tier": "breakout", "is_breakout": True, "breakout_year": 2024},
    "Toilet Tower Defense": {"place_id": 13677275753, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Anime Adventures": {"place_id": 8304191830, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Muscle Legends": {"place_id": 4700513434, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Military Tycoon": {"place_id": 5765852312, "tier": "mid", "is_breakout": False, "breakout_year": None},

    # === Additional mid/low tier for larger sample ===
    "Mad City": {"place_id": 1224539657, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Dungeon Quest": {"place_id": 2414851778, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Giant Simulator": {"place_id": 2986677229, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Ro-Ghoul": {"place_id": 914010486, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Tower Defense Simulator": {"place_id": 3260590327, "tier": "established", "is_breakout": False, "breakout_year": None},
    "Greenville": {"place_id": 891852901, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Emergency Response Liberty County": {"place_id": 2534724415, "tier": "mid", "is_breakout": False, "breakout_year": None},
    "Bad Business": {"place_id": 3233893879, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Club Roblox": {"place_id": 6564677218, "tier": "lower_mid", "is_breakout": False, "breakout_year": None},
    "Prison Life": {"place_id": 155615604, "tier": "established", "is_breakout": False, "breakout_year": None},
}


def resolve_universe_ids(place_ids: list[int]) -> dict[int, int]:
    """Convert place IDs to universe IDs via Roblox API."""
    mapping = {}
    for pid in place_ids:
        try:
            url = f"https://apis.roblox.com/universes/v1/places/{pid}/universe"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                uid = data.get("universeId")
                if uid:
                    mapping[pid] = uid
                    print(f"    {pid} → {uid}")
        except Exception as e:
            print(f"    {pid} → ERROR: {e}")
        time.sleep(0.3)  # Rate limit courtesy
    return mapping


def fetch_game_details(universe_ids: list[int]) -> list[dict]:
    """Batch-fetch game details from Roblox API (up to 100 per request)."""
    all_data = []
    batch_size = 50

    for i in range(0, len(universe_ids), batch_size):
        batch = universe_ids[i:i + batch_size]
        ids_str = ",".join(str(uid) for uid in batch)
        url = f"https://games.roblox.com/v1/games?universeIds={ids_str}"

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                games = data.get("data", [])
                all_data.extend(games)
                print(f"    Batch {i//batch_size + 1}: {len(games)} games fetched")
        except Exception as e:
            print(f"    Batch {i//batch_size + 1}: ERROR: {e}")

        time.sleep(0.5)

    return all_data


def fetch_votes(universe_ids: list[int]) -> dict[int, dict]:
    """Fetch votes (likes/dislikes) for each game."""
    votes = {}
    for uid in universe_ids:
        try:
            url = f"https://games.roblox.com/v1/games/{uid}/votes"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                votes[uid] = {
                    "upVotes": data.get("upVotes", 0),
                    "downVotes": data.get("downVotes", 0),
                }
        except Exception as e:
            votes[uid] = {"upVotes": 0, "downVotes": 0}
        time.sleep(0.2)

        if len(votes) % 20 == 0:
            print(f"    Votes fetched: {len(votes)}/{len(universe_ids)}")

    return votes


def compute_engagement_metrics(games: list[dict], votes: dict, game_meta: dict) -> list[dict]:
    """Compute engagement proxy metrics for all games."""
    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    for game in games:
        uid = game["id"]
        v = votes.get(uid, {"upVotes": 0, "downVotes": 0})

        visits = game.get("visits", 0)
        favorites = game.get("favoritedCount", 0)
        playing = game.get("playing", 0)
        up = v["upVotes"]
        down = v["downVotes"]

        # Engagement proxies
        favorites_per_visit = favorites / max(visits, 1)
        like_ratio = up / max(up + down, 1)
        favorites_per_1k_visits = (favorites / max(visits, 1)) * 1000

        # Composite engagement score
        # Higher = more engaged per user
        engagement_score = (
            favorites_per_visit
            * like_ratio
            * math.log1p(playing)
        )

        # Find metadata
        meta = {}
        for name, m in game_meta.items():
            if m.get("_universe_id") == uid:
                meta = m
                break

        created = game.get("created", "")
        age_days = 0
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (datetime.now(created_dt.tzinfo) - created_dt).days
            except Exception:
                pass

        rows.append({
            "snapshot_time": now,
            "universe_id": uid,
            "game_name": game.get("name", "Unknown"),
            "genre": game.get("genre", "Unknown"),
            "genre_l1": game.get("genre_l1", ""),
            "genre_l2": game.get("genre_l2", ""),
            "playing_ccu": playing,
            "total_visits": visits,
            "favorited_count": favorites,
            "up_votes": up,
            "down_votes": down,
            "like_ratio": round(like_ratio, 4),
            "favorites_per_1k_visits": round(favorites_per_1k_visits, 4),
            "favorites_per_visit": round(favorites_per_visit, 8),
            "engagement_score": round(engagement_score, 8),
            "created_date": created[:10] if created else "",
            "age_days": age_days,
            "max_players": game.get("maxPlayers", 0),
            "creator_name": game.get("creator", {}).get("name", ""),
            "creator_type": game.get("creator", {}).get("type", ""),
            "has_verified_badge": game.get("creator", {}).get("hasVerifiedBadge", False),
            # Metadata from our curated list
            "tier": meta.get("tier", "unknown"),
            "is_breakout": meta.get("is_breakout", False),
            "breakout_year": meta.get("breakout_year"),
        })

    return rows


def save_csv(rows: list[dict], filename: str):
    if not rows:
        print(f"  [SKIP] {filename}: no data")
        return
    path = RAW_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ Saved {filename}: {len(rows)} rows")


def main():
    print("=" * 60)
    print("Roblox REAL Data Collector")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Games in curated list: {len(KNOWN_GAMES)}")
    print("=" * 60)

    # Filter out invalid place IDs
    valid_games = {}
    for name, meta in KNOWN_GAMES.items():
        pid = meta.get("place_id")
        if isinstance(pid, int) and pid > 0:
            valid_games[name] = meta
        else:
            print(f"  [SKIP] {name}: invalid place_id")

    print(f"\nValid games: {len(valid_games)}")

    # Step 1: Resolve universe IDs
    print(f"\n[1/4] Resolving place IDs → universe IDs ({len(valid_games)} games)...")
    place_ids = [m["place_id"] for m in valid_games.values()]
    pid_to_uid = resolve_universe_ids(place_ids)
    print(f"  Resolved: {len(pid_to_uid)}/{len(place_ids)}")

    # Attach universe IDs to metadata
    for name, meta in valid_games.items():
        pid = meta["place_id"]
        if pid in pid_to_uid:
            meta["_universe_id"] = pid_to_uid[pid]

    universe_ids = list(pid_to_uid.values())

    # Step 2: Fetch game details
    print(f"\n[2/4] Fetching game details ({len(universe_ids)} games)...")
    game_details = fetch_game_details(universe_ids)
    print(f"  Fetched: {len(game_details)} games")

    # Step 3: Fetch votes
    print(f"\n[3/4] Fetching votes...")
    votes = fetch_votes(universe_ids)
    print(f"  Votes fetched: {len(votes)}")

    # Step 4: Compute metrics and save
    print(f"\n[4/4] Computing engagement metrics...")
    rows = compute_engagement_metrics(game_details, votes, valid_games)

    # Sort by CCU descending
    rows.sort(key=lambda x: x["playing_ccu"], reverse=True)

    # Add rank
    for i, row in enumerate(rows):
        row["ccu_rank"] = i + 1

    save_csv(rows, "roblox_real_snapshot.csv")

    # Also save the genre lineage data (keep from before)
    # And save a summary
    print("\n" + "=" * 60)
    print("Collection Summary:")
    print(f"  Total games: {len(rows)}")
    print(f"  Breakout games: {sum(1 for r in rows if r['is_breakout'])}")
    print(f"  Non-breakout: {sum(1 for r in rows if not r['is_breakout'])}")
    print(f"  Top 10 by CCU:")
    for r in rows[:10]:
        print(f"    #{r['ccu_rank']} {r['game_name']}: {r['playing_ccu']:,} CCU, eng={r['engagement_score']:.6f}")
    print(f"\n  Engagement extremes:")
    by_eng = sorted(rows, key=lambda x: x["engagement_score"], reverse=True)
    for r in by_eng[:5]:
        print(f"    {r['game_name']}: eng={r['engagement_score']:.6f}, CCU={r['playing_ccu']:,}, fav/1kv={r['favorites_per_1k_visits']:.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
