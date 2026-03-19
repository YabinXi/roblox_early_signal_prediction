"""
mechanic_dna.py — Game Mechanic DNA System

Replaces the subjective "genre lineage depth" with a computable framework:
  1. Mechanic Maturity: how many predecessors validated this mechanic?
  2. Combination Novelty: has this combo of mechanics been done before?
  3. Combination Momentum: are these mechanics trending up?

Usage: uv run python mechanic_dna.py
"""

import json
import csv
import math
from pathlib import Path
from collections import Counter
from datetime import datetime

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = BASE_DIR / "outputs"

# ============================================================
# 1. MECHANIC TAXONOMY
#
# Cross-platform mechanic tags, each with a definition.
# These are atomic building blocks — a game is a combination.
# Inspired by Steam community tags but adapted for Roblox.
# ============================================================

MECHANIC_CATALOG = {
    # --- Core Loop Mechanics ---
    "tycoon":           {"category": "core_loop", "desc": "Build/manage/earn cycle (place objects, earn currency, expand)"},
    "incremental":      {"category": "core_loop", "desc": "Click/idle to grow numbers; prestige resets; exponential scaling"},
    "collection":       {"category": "core_loop", "desc": "Acquire, catalog, and complete sets of items/creatures/cards"},
    "combat_pve":       {"category": "core_loop", "desc": "Fight AI enemies (melee, ranged, or ability-based)"},
    "combat_pvp":       {"category": "core_loop", "desc": "Fight other players (arena, battleground, FPS)"},
    "fps_shooter":      {"category": "core_loop", "desc": "First-person or third-person shooting as primary mechanic"},
    "tower_defense":    {"category": "core_loop", "desc": "Place towers/units to defend against waves"},
    "obby_platformer":  {"category": "core_loop", "desc": "Obstacle course / precision platforming"},
    "survival":         {"category": "core_loop", "desc": "Stay alive against environmental or AI threats, resource scarcity"},
    "exploration":      {"category": "core_loop", "desc": "Discover areas, secrets, lore; map traversal as reward"},
    "building":         {"category": "core_loop", "desc": "Free-form construction (sandbox, creative)"},
    "racing":           {"category": "core_loop", "desc": "Speed competition (vehicles, running)"},
    "rhythm":           {"category": "core_loop", "desc": "Input timing matched to music/beats"},
    "fishing":          {"category": "core_loop", "desc": "Cast, wait, reel; timing-based catch mechanic"},
    "farming":          {"category": "core_loop", "desc": "Plant, grow, harvest cycle"},
    "puzzle":           {"category": "core_loop", "desc": "Logic/spatial challenges as primary gameplay"},
    "minigame_variety": {"category": "core_loop", "desc": "Rotating set of short distinct games"},

    # --- Progression / Meta Mechanics ---
    "rng_gacha":        {"category": "meta", "desc": "Randomized rewards with rarity tiers; lootbox/gacha pull"},
    "trading":          {"category": "meta", "desc": "Player-to-player item exchange; emergent economy"},
    "leveling_rpg":     {"category": "meta", "desc": "XP, levels, skill trees, stat progression"},
    "crafting":         {"category": "meta", "desc": "Combine materials into items/equipment"},
    "pet_companion":    {"category": "meta", "desc": "Collectible followers that assist gameplay or are cosmetic"},
    "codes_freebie":    {"category": "meta", "desc": "Promotional codes / daily login rewards drive retention"},
    "upgrade_merge":    {"category": "meta", "desc": "Upgrade or merge items/units to higher tiers"},
    "quest_mission":    {"category": "meta", "desc": "Structured objectives that guide play sessions"},
    "leaderboard":      {"category": "meta", "desc": "Competitive ranking; high-score chasing"},
    "permadeath":       {"category": "meta", "desc": "Permanent loss on death; high stakes"},

    # --- Social Mechanics ---
    "roleplay_social":  {"category": "social", "desc": "Act out roles (family, jobs, life sim); social sandbox"},
    "coop_mandatory":   {"category": "social", "desc": "Must cooperate with others to progress/survive"},
    "asymmetric_mp":    {"category": "social", "desc": "Different roles per team (1vAll, killer vs survivors)"},
    "fashion_dress":    {"category": "social", "desc": "Avatar customization as competitive/social expression"},
    "donation_gifting": {"category": "social", "desc": "Give currency/items to others as core interaction"},
    "proximity_voice":  {"category": "social", "desc": "Voice chat proximity creates emergent social dynamics"},
    "open_world_social":{"category": "social", "desc": "Shared open world where social interaction is the content"},

    # --- Aesthetic / Wrapper ---
    "horror_atmosphere":{"category": "aesthetic", "desc": "Fear, tension, jumpscare, dark environments"},
    "anime_ip":         {"category": "aesthetic", "desc": "Anime/manga-inspired characters, abilities, franchises"},
    "retro_pixel":      {"category": "aesthetic", "desc": "Deliberately retro/pixel art visual style"},
    "narrative_story":  {"category": "aesthetic", "desc": "Story-driven progression; chapters/episodes"},
    "vehicle_sim":      {"category": "aesthetic", "desc": "Realistic or semi-realistic vehicle operation"},
}


# ============================================================
# 2. MECHANIC HISTORY ON ROBLOX
#
# For each mechanic, key milestones on the Roblox platform.
# This tracks how mature/validated each mechanic is.
# "predecessors" = successful games that proved this mechanic works.
# ============================================================

MECHANIC_HISTORY = {
    "tycoon": {
        "first_roblox_hit": 2015,
        "predecessors": ["Lumber Tycoon 2", "Theme Park Tycoon 2", "My Restaurant!", "Retail Tycoon"],
        "steam_equivalent_tag_count": 3500,  # approx games on Steam with Tycoon/Management
    },
    "incremental": {
        "first_roblox_hit": 2017,
        "predecessors": ["Snow Shoveling Simulator", "Bee Swarm Simulator", "Pet Simulator X", "Ninja Legends", "Giant Simulator"],
        "steam_equivalent_tag_count": 1200,
    },
    "collection": {
        "first_roblox_hit": 2017,
        "predecessors": ["Bee Swarm Simulator", "Pet Simulator X", "Adopt Me!", "Dragon Adventures", "Creatures of Sonaria"],
        "steam_equivalent_tag_count": 800,
    },
    "combat_pve": {
        "first_roblox_hit": 2016,
        "predecessors": ["Dungeon Quest!", "Blox Fruits", "Shindo Life", "Deepwoken"],
        "steam_equivalent_tag_count": 15000,
    },
    "combat_pvp": {
        "first_roblox_hit": 2014,
        "predecessors": ["Prison Life", "Jailbreak", "Da Hood", "The Strongest Battlegrounds"],
        "steam_equivalent_tag_count": 8000,
    },
    "fps_shooter": {
        "first_roblox_hit": 2015,
        "predecessors": ["Phantom Forces", "Arsenal", "Bad Business", "RiVALS"],
        "steam_equivalent_tag_count": 12000,
    },
    "tower_defense": {
        "first_roblox_hit": 2017,
        "predecessors": ["Tower Defense Simulator", "All Star Tower Defense", "Skibidi Tower Defense"],
        "steam_equivalent_tag_count": 2500,
    },
    "obby_platformer": {
        "first_roblox_hit": 2006,
        "predecessors": ["Speed Run 4", "Mega Easy Obby", "Tower of Hell"],
        "steam_equivalent_tag_count": 6000,
    },
    "survival": {
        "first_roblox_hit": 2014,
        "predecessors": ["Natural Disaster Survival", "Dead Rails", "99 Nights in the Forest"],
        "steam_equivalent_tag_count": 9000,
    },
    "exploration": {
        "first_roblox_hit": 2018,
        "predecessors": ["DOORS", "a dusty trip", "99 Nights in the Forest"],
        "steam_equivalent_tag_count": 5000,
    },
    "building": {
        "first_roblox_hit": 2015,
        "predecessors": ["Build A Boat For Treasure", "Welcome to Bloxburg"],
        "steam_equivalent_tag_count": 4000,
    },
    "racing": {
        "first_roblox_hit": 2016,
        "predecessors": ["Vehicle Simulator", "Greenville"],
        "steam_equivalent_tag_count": 3000,
    },
    "rhythm": {
        "first_roblox_hit": 2021,
        "predecessors": ["Funky Friday"],
        "steam_equivalent_tag_count": 1500,
    },
    "fishing": {
        "first_roblox_hit": 2024,
        "predecessors": ["Fisch"],
        "steam_equivalent_tag_count": 400,
    },
    "farming": {
        "first_roblox_hit": 2025,
        "predecessors": ["Grow a Garden"],
        "steam_equivalent_tag_count": 1800,
    },
    "puzzle": {
        "first_roblox_hit": 2018,
        "predecessors": ["Flee the Facility", "DOORS"],
        "steam_equivalent_tag_count": 8000,
    },
    "minigame_variety": {
        "first_roblox_hit": 2015,
        "predecessors": ["Epic Minigames"],
        "steam_equivalent_tag_count": 2000,
    },
    "rng_gacha": {
        "first_roblox_hit": 2022,
        "predecessors": ["Sol's RNG", "Pet Simulator X", "Grow a Garden"],
        "steam_equivalent_tag_count": 600,
    },
    "trading": {
        "first_roblox_hit": 2017,
        "predecessors": ["Adopt Me!", "Murder Mystery 2", "Pet Simulator X", "Grow a Garden"],
        "steam_equivalent_tag_count": 1500,
    },
    "leveling_rpg": {
        "first_roblox_hit": 2016,
        "predecessors": ["Blox Fruits", "Shindo Life", "Dungeon Quest!", "Deepwoken"],
        "steam_equivalent_tag_count": 10000,
    },
    "crafting": {
        "first_roblox_hit": 2017,
        "predecessors": ["Lumber Tycoon 2", "Fisch"],
        "steam_equivalent_tag_count": 5000,
    },
    "pet_companion": {
        "first_roblox_hit": 2018,
        "predecessors": ["Adopt Me!", "Pet Simulator X", "Bee Swarm Simulator"],
        "steam_equivalent_tag_count": 800,
    },
    "codes_freebie": {
        "first_roblox_hit": 2019,
        "predecessors": ["Blox Fruits", "All Star Tower Defense", "Shindo Life"],
        "steam_equivalent_tag_count": 100,  # Roblox-specific, rare on Steam
    },
    "upgrade_merge": {
        "first_roblox_hit": 2018,
        "predecessors": ["Pet Simulator X", "Ninja Legends", "Sol's RNG"],
        "steam_equivalent_tag_count": 1000,
    },
    "quest_mission": {
        "first_roblox_hit": 2016,
        "predecessors": ["Blox Fruits", "Royale High", "Bee Swarm Simulator"],
        "steam_equivalent_tag_count": 12000,
    },
    "leaderboard": {
        "first_roblox_hit": 2015,
        "predecessors": ["Phantom Forces", "The Strongest Battlegrounds", "PLS DONATE"],
        "steam_equivalent_tag_count": 4000,
    },
    "permadeath": {
        "first_roblox_hit": 2022,
        "predecessors": ["Deepwoken", "Dead Rails"],
        "steam_equivalent_tag_count": 3000,
    },
    "roleplay_social": {
        "first_roblox_hit": 2016,
        "predecessors": ["MeepCity", "Brookhaven RP", "Welcome to Bloxburg", "Greenville"],
        "steam_equivalent_tag_count": 500,
    },
    "coop_mandatory": {
        "first_roblox_hit": 2025,
        "predecessors": ["Dead Rails", "99 Nights in the Forest"],
        "steam_equivalent_tag_count": 4000,
    },
    "asymmetric_mp": {
        "first_roblox_hit": 2017,
        "predecessors": ["Murder Mystery 2", "Flee the Facility", "Piggy"],
        "steam_equivalent_tag_count": 1500,
    },
    "fashion_dress": {
        "first_roblox_hit": 2017,
        "predecessors": ["Royale High", "Dress to Impress"],
        "steam_equivalent_tag_count": 300,
    },
    "donation_gifting": {
        "first_roblox_hit": 2022,
        "predecessors": ["PLS DONATE"],
        "steam_equivalent_tag_count": 50,  # Almost Roblox-only
    },
    "proximity_voice": {
        "first_roblox_hit": 2025,
        "predecessors": ["Dead Rails", "99 Nights in the Forest"],
        "steam_equivalent_tag_count": 200,
    },
    "open_world_social": {
        "first_roblox_hit": 2014,
        "predecessors": ["Prison Life", "Jailbreak", "Da Hood", "Emergency Response: Liberty County"],
        "steam_equivalent_tag_count": 3000,
    },
    "horror_atmosphere": {
        "first_roblox_hit": 2018,
        "predecessors": ["Camping", "Piggy", "DOORS", "Dead Rails"],
        "steam_equivalent_tag_count": 7000,
    },
    "anime_ip": {
        "first_roblox_hit": 2020,
        "predecessors": ["Shindo Life", "All Star Tower Defense", "Anime Fighters Simulator", "Blox Fruits"],
        "steam_equivalent_tag_count": 2000,
    },
    "retro_pixel": {
        "first_roblox_hit": 2025,
        "predecessors": ["Grow a Garden"],
        "steam_equivalent_tag_count": 5000,
    },
    "narrative_story": {
        "first_roblox_hit": 2018,
        "predecessors": ["Camping", "Piggy", "DOORS"],
        "steam_equivalent_tag_count": 6000,
    },
    "vehicle_sim": {
        "first_roblox_hit": 2016,
        "predecessors": ["Vehicle Simulator", "Greenville", "Emergency Response: Liberty County"],
        "steam_equivalent_tag_count": 2500,
    },
}


# ============================================================
# 3. GAME → MECHANIC DNA MAPPING
#
# Each game gets 3-7 mechanic tags (its "DNA").
# Order: primary mechanic first, then secondary/meta/social/aesthetic.
# ============================================================

GAME_DNA = {
    # --- Breakout Games ---
    "Adopt Me!": {
        "mechanics": ["collection", "pet_companion", "trading", "roleplay_social", "codes_freebie"],
        "is_breakout": True, "year": 2019,
    },
    "Blox Fruits": {
        "mechanics": ["combat_pve", "leveling_rpg", "exploration", "anime_ip", "codes_freebie", "quest_mission"],
        "is_breakout": True, "year": 2021,
    },
    "Brookhaven RP": {
        "mechanics": ["roleplay_social", "open_world_social", "vehicle_sim"],
        "is_breakout": True, "year": 2020,
    },
    "RiVALS": {
        "mechanics": ["fps_shooter", "combat_pvp", "leaderboard"],
        "is_breakout": True, "year": 2025,
    },
    "Murder Mystery 2": {
        "mechanics": ["asymmetric_mp", "trading", "survival"],
        "is_breakout": True, "year": 2017,
    },
    "The Strongest Battlegrounds": {
        "mechanics": ["combat_pvp", "anime_ip", "leaderboard"],
        "is_breakout": True, "year": 2024,
    },
    "Bee Swarm Simulator": {
        "mechanics": ["incremental", "collection", "pet_companion", "quest_mission", "exploration"],
        "is_breakout": True, "year": 2018,
    },
    "Sol's RNG": {
        "mechanics": ["rng_gacha", "incremental", "trading", "leaderboard", "codes_freebie"],
        "is_breakout": True, "year": 2024,
    },
    "Fisch": {
        "mechanics": ["fishing", "collection", "crafting", "trading", "exploration"],
        "is_breakout": True, "year": 2025,
    },
    "PLS DONATE": {
        "mechanics": ["donation_gifting", "roleplay_social", "leaderboard"],
        "is_breakout": True, "year": 2022,
    },
    "Blade Ball": {
        "mechanics": ["combat_pvp", "minigame_variety", "leaderboard"],
        "is_breakout": True, "year": 2024,
    },
    "Build A Boat For Treasure": {
        "mechanics": ["building", "survival", "exploration", "quest_mission"],
        "is_breakout": True, "year": 2017,
    },
    "DOORS": {
        "mechanics": ["horror_atmosphere", "exploration", "survival", "puzzle", "narrative_story", "coop_mandatory"],
        "is_breakout": True, "year": 2022,
    },
    "Jailbreak": {
        "mechanics": ["open_world_social", "combat_pvp", "vehicle_sim", "roleplay_social"],
        "is_breakout": True, "year": 2017,
    },
    "Royale High": {
        "mechanics": ["fashion_dress", "roleplay_social", "quest_mission", "collection", "trading"],
        "is_breakout": True, "year": 2017,
    },
    "Natural Disaster Survival": {
        "mechanics": ["survival", "minigame_variety"],
        "is_breakout": True, "year": 2014,
    },
    "Pet Simulator X": {
        "mechanics": ["incremental", "collection", "pet_companion", "rng_gacha", "trading", "upgrade_merge"],
        "is_breakout": True, "year": 2022,
    },
    "Ninja Legends": {
        "mechanics": ["incremental", "combat_pve", "pet_companion", "upgrade_merge"],
        "is_breakout": True, "year": 2019,
    },
    "MeepCity": {
        "mechanics": ["roleplay_social", "minigame_variety", "fashion_dress"],
        "is_breakout": True, "year": 2016,
    },
    "Dead Rails": {
        "mechanics": ["coop_mandatory", "survival", "horror_atmosphere", "proximity_voice", "combat_pve", "permadeath"],
        "is_breakout": True, "year": 2025,
    },
    "99 Nights in the Forest": {
        "mechanics": ["coop_mandatory", "exploration", "horror_atmosphere", "survival", "proximity_voice", "narrative_story"],
        "is_breakout": True, "year": 2026,
    },
    "Dress to Impress": {
        "mechanics": ["fashion_dress", "roleplay_social", "leaderboard", "minigame_variety"],
        "is_breakout": True, "year": 2024,
    },
    "Grow a Garden": {
        "mechanics": ["farming", "rng_gacha", "trading", "tycoon", "retro_pixel", "codes_freebie"],
        "is_breakout": True, "year": 2025,
    },

    # --- Non-Breakout Games ---
    "Creatures of Sonaria": {
        "mechanics": ["collection", "roleplay_social", "survival", "pet_companion"],
        "is_breakout": False, "year": 2020,
    },
    "All Star Tower Defense": {
        "mechanics": ["tower_defense", "anime_ip", "collection", "codes_freebie"],
        "is_breakout": False, "year": 2020,
    },
    "Dragon Adventures": {
        "mechanics": ["collection", "pet_companion", "exploration", "trading"],
        "is_breakout": False, "year": 2019,
    },
    "Flee the Facility": {
        "mechanics": ["asymmetric_mp", "survival", "puzzle"],
        "is_breakout": False, "year": 2017,
    },
    "Welcome to Bloxburg": {
        "mechanics": ["roleplay_social", "building", "tycoon"],
        "is_breakout": False, "year": 2016,
    },
    "Tower Defense Simulator": {
        "mechanics": ["tower_defense", "coop_mandatory", "collection"],
        "is_breakout": False, "year": 2019,
    },
    "a dusty trip": {
        "mechanics": ["exploration", "survival", "vehicle_sim", "coop_mandatory"],
        "is_breakout": False, "year": 2024,
    },
    "Prison Life": {
        "mechanics": ["open_world_social", "combat_pvp", "roleplay_social"],
        "is_breakout": False, "year": 2014,
    },
    "Work at a Pizza Place": {
        "mechanics": ["roleplay_social", "tycoon", "coop_mandatory"],
        "is_breakout": False, "year": 2007,
    },
    "Piggy": {
        "mechanics": ["horror_atmosphere", "asymmetric_mp", "narrative_story", "puzzle"],
        "is_breakout": False, "year": 2020,
    },
    "Emergency Response: Liberty County": {
        "mechanics": ["roleplay_social", "open_world_social", "vehicle_sim"],
        "is_breakout": False, "year": 2018,
    },
    "Theme Park Tycoon 2": {
        "mechanics": ["tycoon", "building"],
        "is_breakout": False, "year": 2015,
    },
    "Deepwoken": {
        "mechanics": ["combat_pve", "combat_pvp", "leveling_rpg", "permadeath", "exploration"],
        "is_breakout": False, "year": 2022,
    },
    "Arsenal": {
        "mechanics": ["fps_shooter", "combat_pvp", "minigame_variety"],
        "is_breakout": False, "year": 2018,
    },
    "Greenville": {
        "mechanics": ["roleplay_social", "vehicle_sim", "open_world_social"],
        "is_breakout": False, "year": 2018,
    },
    "Phantom Forces": {
        "mechanics": ["fps_shooter", "combat_pvp", "leaderboard"],
        "is_breakout": False, "year": 2015,
    },
    "Shindo Life": {
        "mechanics": ["combat_pve", "combat_pvp", "anime_ip", "leveling_rpg", "codes_freebie"],
        "is_breakout": False, "year": 2020,
    },
    "Lumber Tycoon 2": {
        "mechanics": ["tycoon", "building", "trading"],
        "is_breakout": False, "year": 2009,
    },
    "Da Hood": {
        "mechanics": ["open_world_social", "combat_pvp", "roleplay_social"],
        "is_breakout": False, "year": 2019,
    },
    "Dungeon Quest!": {
        "mechanics": ["combat_pve", "leveling_rpg", "collection", "quest_mission"],
        "is_breakout": False, "year": 2019,
    },
    "Epic Minigames": {
        "mechanics": ["minigame_variety"],
        "is_breakout": False, "year": 2015,
    },
    "Funky Friday": {
        "mechanics": ["rhythm", "combat_pvp", "leaderboard"],
        "is_breakout": False, "year": 2021,
    },
    "My Restaurant!": {
        "mechanics": ["tycoon", "roleplay_social"],
        "is_breakout": False, "year": 2020,
    },
    "Speed Run 4": {
        "mechanics": ["obby_platformer", "racing", "leaderboard"],
        "is_breakout": False, "year": 2014,
    },
    "Super Golf!": {
        "mechanics": ["racing", "minigame_variety"],
        "is_breakout": False, "year": 2020,
    },
    "Bad Business": {
        "mechanics": ["fps_shooter", "combat_pvp"],
        "is_breakout": False, "year": 2018,
    },
    "Anime Fighters Simulator": {
        "mechanics": ["incremental", "anime_ip", "collection", "combat_pve"],
        "is_breakout": False, "year": 2021,
    },
    "Giant Simulator": {
        "mechanics": ["incremental", "combat_pvp", "pet_companion"],
        "is_breakout": False, "year": 2019,
    },
    "Vehicle Simulator": {
        "mechanics": ["vehicle_sim", "racing", "open_world_social"],
        "is_breakout": False, "year": 2017,
    },
    "Skibidi Tower Defense": {
        "mechanics": ["tower_defense", "anime_ip"],
        "is_breakout": False, "year": 2024,
    },
}


# ============================================================
# 4. COMPUTE MECHANIC MATURITY (per mechanic)
# ============================================================

def compute_mechanic_maturity(mechanic: str, as_of_year: int = 2026) -> dict:
    """
    Mechanic maturity = how validated is this mechanic on Roblox?
    Higher = more proven, lower learning curve for players.
    """
    hist = MECHANIC_HISTORY.get(mechanic, {})
    first_year = hist.get("first_roblox_hit", as_of_year)
    predecessors = hist.get("predecessors", [])
    steam_count = hist.get("steam_equivalent_tag_count", 0)

    years_on_platform = max(0, as_of_year - first_year)
    n_predecessors = len(predecessors)

    # Composite: years active (log scale) + predecessor count + cross-platform presence
    platform_score = min(1.0, math.log(years_on_platform + 1) / math.log(15))  # cap at ~15 years
    predecessor_score = min(1.0, n_predecessors / 5)  # cap at 5 predecessors
    crossplatform_score = min(1.0, math.log(steam_count + 1) / math.log(15000))  # cap at 15k

    maturity = (platform_score * 0.3 + predecessor_score * 0.4 + crossplatform_score * 0.3)

    return {
        "mechanic": mechanic,
        "years_on_platform": years_on_platform,
        "n_predecessors": n_predecessors,
        "steam_tag_count": steam_count,
        "maturity_score": round(maturity, 3),
    }


# ============================================================
# 5. COMPUTE CO-OCCURRENCE & NOVELTY
# ============================================================

def build_cooccurrence_matrix(as_of_year: int = None) -> dict:
    """
    Count how often each pair of mechanics appears together in existing games.
    If as_of_year is set, only count games released before that year.
    """
    pair_counts = Counter()
    triple_counts = Counter()

    for game, data in GAME_DNA.items():
        if as_of_year and data["year"] >= as_of_year:
            continue
        mechs = sorted(data["mechanics"])
        # All pairs
        for i in range(len(mechs)):
            for j in range(i + 1, len(mechs)):
                pair_counts[tuple(sorted([mechs[i], mechs[j]]))] += 1
        # All triples
        for i in range(len(mechs)):
            for j in range(i + 1, len(mechs)):
                for k in range(j + 1, len(mechs)):
                    triple_counts[tuple(sorted([mechs[i], mechs[j], mechs[k]]))] += 1

    return {"pairs": pair_counts, "triples": triple_counts}


def compute_combination_novelty(mechanics: list[str], cooccurrence: dict) -> dict:
    """
    Novelty = inverse of how common this combination of mechanics is.
    Higher = more novel (these mechanics haven't been combined before).
    """
    mechs = sorted(mechanics)
    pair_counts = cooccurrence["pairs"]
    triple_counts = cooccurrence["triples"]

    # Pair novelty: average inverse log of pair co-occurrence
    pair_scores = []
    rarest_pair = None
    rarest_pair_count = float("inf")
    for i in range(len(mechs)):
        for j in range(i + 1, len(mechs)):
            pair = tuple(sorted([mechs[i], mechs[j]]))
            count = pair_counts.get(pair, 0)
            score = 1.0 / math.log(count + 2)  # +2 to avoid div by 0, log(1)
            pair_scores.append(score)
            if count < rarest_pair_count:
                rarest_pair_count = count
                rarest_pair = pair

    # Triple novelty: check all triples
    triple_scores = []
    rarest_triple = None
    rarest_triple_count = float("inf")
    for i in range(len(mechs)):
        for j in range(i + 1, len(mechs)):
            for k in range(j + 1, len(mechs)):
                triple = tuple(sorted([mechs[i], mechs[j], mechs[k]]))
                count = triple_counts.get(triple, 0)
                score = 1.0 / math.log(count + 2)
                triple_scores.append(score)
                if count < rarest_triple_count:
                    rarest_triple_count = count
                    rarest_triple = triple

    avg_pair_novelty = sum(pair_scores) / len(pair_scores) if pair_scores else 0
    avg_triple_novelty = sum(triple_scores) / len(triple_scores) if triple_scores else 0

    # Combined novelty: weight triple novelty higher (rarer = more interesting)
    novelty = avg_pair_novelty * 0.4 + avg_triple_novelty * 0.6

    return {
        "novelty_score": round(novelty, 4),
        "avg_pair_novelty": round(avg_pair_novelty, 4),
        "avg_triple_novelty": round(avg_triple_novelty, 4),
        "rarest_pair": rarest_pair,
        "rarest_pair_count": rarest_pair_count,
        "rarest_triple": rarest_triple,
        "rarest_triple_count": rarest_triple_count,
    }


# ============================================================
# 6. COMPUTE GAME DNA SCORE
# ============================================================

def compute_game_dna(game_name: str, as_of_year: int = None) -> dict:
    """
    Compute the full DNA analysis for a game:
      - mechanic_maturity: avg maturity of its mechanics (higher = proven)
      - combination_novelty: how rare is this combo (higher = fresher)
      - sweet_spot_score: maturity × novelty (the "proven parts, new combo" signal)
    """
    data = GAME_DNA.get(game_name)
    if not data:
        return None

    mechanics = data["mechanics"]
    year = as_of_year or 2026

    # Maturity per mechanic
    maturities = [compute_mechanic_maturity(m, as_of_year=year) for m in mechanics]
    avg_maturity = sum(m["maturity_score"] for m in maturities) / len(maturities)
    min_maturity = min(m["maturity_score"] for m in maturities)
    max_maturity = max(m["maturity_score"] for m in maturities)

    # Novelty (exclude this game's own year from co-occurrence)
    cooccurrence = build_cooccurrence_matrix(as_of_year=data["year"])
    novelty = compute_combination_novelty(mechanics, cooccurrence)

    # Sweet spot: high maturity × high novelty
    sweet_spot = avg_maturity * novelty["novelty_score"]

    return {
        "game": game_name,
        "mechanics": mechanics,
        "n_mechanics": len(mechanics),
        "is_breakout": data["is_breakout"],
        "year": data["year"],
        "avg_maturity": round(avg_maturity, 3),
        "min_maturity": round(min_maturity, 3),
        "max_maturity": round(max_maturity, 3),
        "novelty_score": novelty["novelty_score"],
        "rarest_pair": " × ".join(novelty["rarest_pair"]) if novelty["rarest_pair"] else None,
        "rarest_pair_count": novelty["rarest_pair_count"],
        "rarest_triple": " × ".join(novelty["rarest_triple"]) if novelty["rarest_triple"] else None,
        "rarest_triple_count": novelty["rarest_triple_count"],
        "sweet_spot_score": round(sweet_spot, 4),
        "maturity_details": maturities,
    }


# ============================================================
# 7. MAIN: Run analysis on all games
# ============================================================

def main():
    print("=" * 70)
    print("MECHANIC DNA ANALYSIS — Roblox Game Breakout Prediction")
    print("=" * 70)

    results = []
    for game_name in GAME_DNA:
        dna = compute_game_dna(game_name)
        if dna:
            results.append(dna)

    # Sort by sweet_spot_score descending
    results.sort(key=lambda x: x["sweet_spot_score"], reverse=True)

    # Print results table
    print(f"\n{'Rank':<5} {'Game':<35} {'Breakout':>8} {'Maturity':>9} {'Novelty':>8} {'Sweet':>7} {'Rarest Combo':<40}")
    print("-" * 120)
    for i, r in enumerate(results, 1):
        bo = "✅" if r["is_breakout"] else "—"
        rarest = r.get("rarest_pair", "—") or "—"
        print(f"{i:<5} {r['game']:<35} {bo:>8} {r['avg_maturity']:>9.3f} {r['novelty_score']:>8.4f} {r['sweet_spot_score']:>7.4f} {rarest:<40}")

    # Breakout vs non-breakout comparison
    breakouts = [r for r in results if r["is_breakout"]]
    non_breakouts = [r for r in results if not r["is_breakout"]]

    print(f"\n{'=' * 70}")
    print("BREAKOUT vs NON-BREAKOUT COMPARISON")
    print(f"{'=' * 70}")

    for label, group in [("Breakout", breakouts), ("Non-Breakout", non_breakouts)]:
        avg_mat = sum(r["avg_maturity"] for r in group) / len(group)
        avg_nov = sum(r["novelty_score"] for r in group) / len(group)
        avg_ss = sum(r["sweet_spot_score"] for r in group) / len(group)
        print(f"  {label:<15} n={len(group):<3}  maturity={avg_mat:.3f}  novelty={avg_nov:.4f}  sweet_spot={avg_ss:.4f}")

    # Statistical test: Mann-Whitney U on sweet_spot_score
    from scipy import stats
    bo_scores = [r["sweet_spot_score"] for r in breakouts]
    nb_scores = [r["sweet_spot_score"] for r in non_breakouts]
    u_stat, p_value = stats.mannwhitneyu(bo_scores, nb_scores, alternative="greater")
    auc = u_stat / (len(bo_scores) * len(nb_scores))
    print(f"\n  Mann-Whitney U: AUC={auc:.3f}, p={p_value:.4f}")
    print(f"  {'SIGNIFICANT ✅' if p_value < 0.05 else 'NOT SIGNIFICANT ⏳'} at α=0.05")

    # Grow a Garden deep dive
    print(f"\n{'=' * 70}")
    print("DEEP DIVE: Grow a Garden")
    print(f"{'=' * 70}")
    gag = compute_game_dna("Grow a Garden")
    if gag:
        print(f"  Mechanics: {', '.join(gag['mechanics'])}")
        print(f"  Avg Maturity: {gag['avg_maturity']:.3f}")
        print(f"  Novelty Score: {gag['novelty_score']:.4f}")
        print(f"  Sweet Spot: {gag['sweet_spot_score']:.4f}")
        print(f"  Rarest pair: {gag['rarest_pair']} (seen {gag['rarest_pair_count']}x before)")
        print(f"  Rarest triple: {gag['rarest_triple']} (seen {gag['rarest_triple_count']}x before)")
        print(f"\n  Per-mechanic maturity:")
        for m in gag["maturity_details"]:
            print(f"    {m['mechanic']:<20} maturity={m['maturity_score']:.3f}  "
                  f"(years={m['years_on_platform']}, predecessors={m['n_predecessors']}, "
                  f"steam={m['steam_tag_count']})")

    # Save results
    output_path = OUTPUT_DIR / "mechanic_dna_results.json"
    save_results = []
    for r in results:
        r_copy = r.copy()
        r_copy.pop("maturity_details", None)
        save_results.append(r_copy)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(save_results, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Results saved to {output_path}")

    # Also save as CSV for easy analysis
    csv_path = DATA_DIR / "processed" / "mechanic_dna.csv"
    fields = ["game", "is_breakout", "year", "n_mechanics", "avg_maturity",
              "novelty_score", "sweet_spot_score", "rarest_pair", "rarest_pair_count",
              "rarest_triple", "rarest_triple_count"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in save_results:
            writer.writerow({k: r.get(k) for k in fields})
    print(f"✓ CSV saved to {csv_path}")

    # Save mechanic catalog for reference
    catalog_path = DATA_DIR / "processed" / "mechanic_catalog.json"
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump({
            "mechanic_catalog": MECHANIC_CATALOG,
            "mechanic_history": MECHANIC_HISTORY,
            "game_dna": {k: {"mechanics": v["mechanics"], "is_breakout": v["is_breakout"], "year": v["year"]}
                         for k, v in GAME_DNA.items()},
        }, f, ensure_ascii=False, indent=2)
    print(f"✓ Catalog saved to {catalog_path}")


if __name__ == "__main__":
    main()
