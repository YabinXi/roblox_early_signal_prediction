"""
analyze_genre_rotation.py — Genre Rotation vs Independent Emergence Analysis

Research Question:
  爆款信号是在题材间轮动（farming 热完换 horror），还是从不同方向独立冒出来？

Hypotheses:
  HR1: 爆款题材集中度 — 爆款游戏是否集中在少数机制主题里？
  HR2: 时间聚类 — 同一机制家族的爆款在时间上是否扎堆？
  HR3: YouTube 创作者溢出效应 — 共享机制 DNA 的游戏，YouTube 信号是否相关？
  HR4: Google Trends 题材轮动 — 不同题材的搜索兴趣峰值是否错开？

Usage: uv run python analyze_genre_rotation.py
"""

import json
import math
import warnings
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import pdist, squareform

# Suppress warnings for clean output
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ============================================================
# Paths
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# Import from mechanic_dna.py
from mechanic_dna import GAME_DNA, MECHANIC_CATALOG


# ============================================================
# Data Loading
# ============================================================

def load_data() -> dict:
    """Load all required datasets and build name-matching lookups."""
    data = {}

    # 1. Snapshot (genre_l1, is_breakout, total_visits)
    snap = pd.read_csv(DATA_DIR / "processed" / "roblox_real_snapshot.csv")
    # Filter out placeholder games (0 visits)
    snap = snap[snap["total_visits"] > 0].copy()
    data["snapshot"] = snap

    # 2. YouTube weekly
    yt = pd.read_csv(DATA_DIR / "timeseries" / "youtube_weekly.csv")
    data["youtube"] = yt

    # 3. Buzz metrics
    buzz = pd.read_csv(DATA_DIR / "raw" / "roblox_buzz_metrics.csv")
    data["buzz"] = buzz

    # 4. Google Trends
    trends = pd.read_csv(DATA_DIR / "raw" / "roblox_google_trends.csv")
    trends["date"] = pd.to_datetime(trends["date"])
    data["trends"] = trends

    # 5. Build name mapping: GAME_DNA name → clean CSV name
    # We need to match mechanic_dna game names to CSV game_name_clean / keyword
    data["name_map"] = _build_name_map(snap, yt, buzz, trends)

    return data


def _build_name_map(snap, yt, buzz, trends) -> dict:
    """Build flexible name matching between GAME_DNA keys and CSV columns."""
    mapping = {}

    # Collect all available names from CSVs
    csv_names = set()
    if "game_name_clean" in buzz.columns:
        csv_names.update(buzz["game_name_clean"].dropna().unique())
    csv_names.update(yt["game_name"].dropna().unique())
    csv_names.update(trends["keyword"].dropna().unique())

    for dna_name in GAME_DNA:
        # Try exact match first
        if dna_name in csv_names:
            mapping[dna_name] = dna_name
            continue

        # Try common transformations
        candidates = [
            dna_name,
            dna_name.replace("!", ""),
            dna_name.replace("'s RNG", "'s RNG"),
        ]

        matched = False
        for csv_name in csv_names:
            # Fuzzy: check if one contains the other (case-insensitive)
            dn = dna_name.lower().strip()
            cn = csv_name.lower().strip()
            if dn == cn or dn in cn or cn in dn:
                mapping[dna_name] = csv_name
                matched = True
                break
            # Handle specific known mismatches
            if dn.replace(" ", "") == cn.replace(" ", ""):
                mapping[dna_name] = csv_name
                matched = True
                break

        if not matched:
            # Last resort: substring match on significant words
            dna_words = set(dna_name.lower().replace("!", "").replace("'", "").split())
            best_score = 0
            best_match = None
            for csv_name in csv_names:
                csv_words = set(csv_name.lower().replace("!", "").replace("'", "").split())
                overlap = len(dna_words & csv_words)
                if overlap > best_score and overlap >= 1:
                    best_score = overlap
                    best_match = csv_name
            if best_match and best_score >= max(1, len(dna_words) // 2):
                mapping[dna_name] = best_match

    return mapping


def get_game_category_profile(mechanics: list) -> dict:
    """Get the category distribution for a game's mechanics."""
    cats = Counter()
    for m in mechanics:
        cat = MECHANIC_CATALOG.get(m, {}).get("category", "unknown")
        cats[cat] += 1
    total = sum(cats.values())
    return {cat: count / total for cat, count in cats.items()}


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def shannon_entropy(dist: dict) -> float:
    """Compute Shannon entropy of a distribution dict."""
    h = 0.0
    for p in dist.values():
        if p > 0:
            h -= p * math.log2(p)
    return h


# ============================================================
# HR1: 爆款题材集中度
# ============================================================

def test_hr1_genre_concentration(data: dict) -> dict:
    """
    HR1: Are breakout games concentrated in a few mechanic categories,
    or evenly distributed?
    """
    print("\n" + "=" * 70)
    print("HR1: 爆款题材集中度 — Genre Concentration of Breakout Games")
    print("=" * 70)

    # Separate breakout vs non-breakout
    breakout_games = {k: v for k, v in GAME_DNA.items() if v["is_breakout"]}
    non_breakout_games = {k: v for k, v in GAME_DNA.items() if not v["is_breakout"]}

    print(f"  Breakout: {len(breakout_games)}, Non-breakout: {len(non_breakout_games)}")

    # 1. Category distribution comparison
    categories = ["core_loop", "meta", "social", "aesthetic"]

    def count_category_mechanics(games):
        cats = Counter()
        for g, d in games.items():
            for m in d["mechanics"]:
                cat = MECHANIC_CATALOG.get(m, {}).get("category", "unknown")
                cats[cat] += 1
        return cats

    bo_cats = count_category_mechanics(breakout_games)
    nbo_cats = count_category_mechanics(non_breakout_games)

    print("\n  Category distribution (mechanic counts):")
    print(f"  {'Category':<15} {'Breakout':>10} {'Non-Break':>10} {'BO %':>8} {'NBO %':>8}")
    bo_total = sum(bo_cats[c] for c in categories)
    nbo_total = sum(nbo_cats[c] for c in categories)

    contingency = []
    for cat in categories:
        bo_pct = bo_cats[cat] / bo_total * 100
        nbo_pct = nbo_cats[cat] / nbo_total * 100
        contingency.append([bo_cats[cat], nbo_cats[cat]])
        print(f"  {cat:<15} {bo_cats[cat]:>10} {nbo_cats[cat]:>10} {bo_pct:>7.1f}% {nbo_pct:>7.1f}%")

    # Chi-squared test on category distribution
    contingency_arr = np.array(contingency)
    chi2, chi2_p, dof, expected = stats.chi2_contingency(contingency_arr)
    print(f"\n  Chi-squared test: χ²={chi2:.3f}, df={dof}, p={chi2_p:.4f}")

    # 2. Shannon entropy comparison
    bo_entropies = []
    nbo_entropies = []
    for g, d in breakout_games.items():
        profile = get_game_category_profile(d["mechanics"])
        bo_entropies.append(shannon_entropy(profile))
    for g, d in non_breakout_games.items():
        profile = get_game_category_profile(d["mechanics"])
        nbo_entropies.append(shannon_entropy(profile))

    bo_ent_mean = np.mean(bo_entropies)
    nbo_ent_mean = np.mean(nbo_entropies)
    u_ent, p_ent = stats.mannwhitneyu(bo_entropies, nbo_entropies, alternative="two-sided")

    print(f"\n  Shannon entropy of category distribution:")
    print(f"    Breakout mean:     {bo_ent_mean:.3f}")
    print(f"    Non-breakout mean: {nbo_ent_mean:.3f}")
    print(f"    Mann-Whitney U p:  {p_ent:.4f}")
    entropy_direction = "lower" if bo_ent_mean < nbo_ent_mean else "higher"
    print(f"    → Breakout games have {entropy_direction} entropy (more {'concentrated' if entropy_direction == 'lower' else 'diverse'})")

    # 3. Per-mechanic breakout rate + Fisher exact test
    mechanic_breakout_rates = {}
    significant_mechanics = []
    all_mechanics = set()
    for d in GAME_DNA.values():
        all_mechanics.update(d["mechanics"])

    n_tests = len(all_mechanics)
    bonferroni_alpha = 0.05 / n_tests

    print(f"\n  Per-mechanic breakout rate (Bonferroni α={bonferroni_alpha:.4f}):")
    print(f"  {'Mechanic':<25} {'BO':>4} {'NBO':>4} {'Rate':>8} {'Fisher p':>10} {'Sig':>5}")

    for mech in sorted(all_mechanics):
        bo_has = sum(1 for d in breakout_games.values() if mech in d["mechanics"])
        nbo_has = sum(1 for d in non_breakout_games.values() if mech in d["mechanics"])
        bo_not = len(breakout_games) - bo_has
        nbo_not = len(non_breakout_games) - nbo_has
        total_has = bo_has + nbo_has
        rate = bo_has / total_has if total_has > 0 else 0

        if total_has >= 2:  # Only test mechanics appearing in ≥2 games
            _, fisher_p = stats.fisher_exact([[bo_has, nbo_has], [bo_not, nbo_not]])
            sig = "✅" if fisher_p < bonferroni_alpha else ""
            print(f"  {mech:<25} {bo_has:>4} {nbo_has:>4} {rate:>7.1%} {fisher_p:>10.4f} {sig:>5}")
            mechanic_breakout_rates[mech] = {
                "breakout_count": bo_has, "non_breakout_count": nbo_has,
                "breakout_rate": round(rate, 3), "fisher_p": round(fisher_p, 4),
                "significant": fisher_p < bonferroni_alpha,
            }
            if fisher_p < bonferroni_alpha:
                significant_mechanics.append(mech)

    # Determine direction
    # If chi2 is significant → categories are NOT evenly distributed → supports concentration
    concentration_supported = chi2_p < 0.05
    entropy_supports = bo_ent_mean < nbo_ent_mean  # lower entropy = more concentrated

    if concentration_supported:
        direction = "supported"
        narrative = f"Chi-squared significant (p={chi2_p:.4f}): breakout games cluster in specific categories."
    elif len(significant_mechanics) > 0:
        direction = "partial"
        narrative = f"Chi-squared not significant, but {len(significant_mechanics)} mechanic(s) show significant breakout enrichment."
    else:
        direction = "inconclusive"
        narrative = "No significant concentration pattern detected."

    # For rotation vs independence scoring
    rotation_point = 1 if concentration_supported else 0
    independence_point = 1 if not concentration_supported else 0

    result = {
        "id": "HR1",
        "hypothesis": "爆款游戏集中在少数机制主题里（题材集中度）",
        "method": "Chi-squared test on category distribution, Shannon entropy comparison, per-mechanic Fisher exact test with Bonferroni correction",
        "status": "tested",
        "result": {
            "direction": direction,
            "effect_size": f"χ²={chi2:.3f}, entropy_diff={bo_ent_mean - nbo_ent_mean:.3f}",
            "p_value": round(chi2_p, 6),
            "confidence_interval": f"BO entropy={bo_ent_mean:.3f}, NBO entropy={nbo_ent_mean:.3f}",
            "sample_size": len(GAME_DNA),
        },
        "confounders": [
            {"name": "Sample size", "direction": "57 games may lack power for chi-squared across 4 categories", "controlled": False, "method": None},
            {"name": "Mechanic labeling subjectivity", "direction": "DNA mapping is hand-coded; different taggers might produce different distributions", "controlled": False, "method": None},
        ],
        "conclusion": narrative,
        "rotation_signal": rotation_point,
        "independence_signal": independence_point,
        "_detail": {
            "chi2": round(chi2, 3),
            "chi2_p": round(chi2_p, 6),
            "chi2_dof": dof,
            "bo_entropy_mean": round(bo_ent_mean, 3),
            "nbo_entropy_mean": round(nbo_ent_mean, 3),
            "entropy_test_p": round(p_ent, 4),
            "significant_mechanics": significant_mechanics,
            "mechanic_breakout_rates": mechanic_breakout_rates,
            "category_contingency": {cat: {"breakout": int(contingency_arr[i, 0]), "non_breakout": int(contingency_arr[i, 1])}
                                     for i, cat in enumerate(categories)},
        },
    }

    print(f"\n  → HR1 verdict: {direction.upper()} — {narrative}")
    print(f"  → Rotation signal: {rotation_point}, Independence signal: {independence_point}")
    return result


# ============================================================
# HR2: 时间聚类 — Temporal Clustering
# ============================================================

def test_hr2_temporal_clustering(data: dict) -> dict:
    """
    HR2: Do breakout games with similar mechanics cluster in time?
    (i.e., do "genre waves" exist?)
    """
    print("\n" + "=" * 70)
    print("HR2: 时间聚类 — Temporal Clustering of Mechanic Families")
    print("=" * 70)

    breakout_games = {k: v for k, v in GAME_DNA.items() if v["is_breakout"]}
    game_names = sorted(breakout_games.keys())
    n = len(game_names)

    # Build mechanic similarity matrix (Jaccard) and time distance matrix
    mech_sim = np.zeros((n, n))
    time_dist = np.zeros((n, n))

    for i in range(n):
        for j in range(n):
            si = set(breakout_games[game_names[i]]["mechanics"])
            sj = set(breakout_games[game_names[j]]["mechanics"])
            mech_sim[i, j] = jaccard_similarity(si, sj)
            time_dist[i, j] = abs(breakout_games[game_names[i]]["year"] - breakout_games[game_names[j]]["year"])

    # Convert time distance to proximity (inverse)
    max_time = time_dist.max()
    time_prox = 1 - (time_dist / max_time) if max_time > 0 else np.zeros_like(time_dist)

    # Mantel test: correlation between mechanic similarity and temporal proximity
    # Use upper triangle (excluding diagonal)
    sim_vec = squareform(mech_sim, checks=False)
    prox_vec = squareform(time_prox, checks=False)

    # Observed Pearson correlation
    observed_r, _ = stats.pearsonr(sim_vec, prox_vec)

    # Permutation test (10,000 permutations)
    n_perm = 10000
    perm_r = np.zeros(n_perm)
    rng = np.random.default_rng(42)
    for p in range(n_perm):
        perm_idx = rng.permutation(n)
        perm_sim = mech_sim[np.ix_(perm_idx, perm_idx)]
        perm_sim_vec = squareform(perm_sim, checks=False)
        perm_r[p], _ = stats.pearsonr(perm_sim_vec, prox_vec)

    mantel_p = np.mean(perm_r >= observed_r)

    print(f"\n  Mantel test (mechanic similarity ~ temporal proximity):")
    print(f"    Observed r:     {observed_r:.4f}")
    print(f"    Permutation p:  {mantel_p:.4f} (n_perm={n_perm})")
    print(f"    {'SIGNIFICANT ✅' if mantel_p < 0.05 else 'Not significant'}")

    # Identify specific "waves": same core mechanic, ≥2 breakouts within 2 years
    print("\n  Identified Genre Waves (same mechanic, ≥2 breakouts within 2 years):")
    waves = []
    mechanic_games = defaultdict(list)
    for g, d in breakout_games.items():
        for m in d["mechanics"]:
            mechanic_games[m].append((g, d["year"]))

    for mech, games in sorted(mechanic_games.items()):
        if len(games) < 2:
            continue
        games_sorted = sorted(games, key=lambda x: x[1])
        # Find clusters within 2-year windows
        for i in range(len(games_sorted)):
            cluster = [games_sorted[i]]
            for j in range(i + 1, len(games_sorted)):
                if games_sorted[j][1] - games_sorted[i][1] <= 2:
                    cluster.append(games_sorted[j])
            if len(cluster) >= 2:
                wave_key = f"{mech}: " + " → ".join(f"{g[0]} ({g[1]})" for g in cluster)
                if wave_key not in [w["description"] for w in waves]:
                    waves.append({
                        "mechanic": mech,
                        "games": [(g[0], g[1]) for g in cluster],
                        "span_years": cluster[-1][1] - cluster[0][1],
                        "description": wave_key,
                    })

    # Deduplicate waves (keep longest per mechanic)
    unique_waves = {}
    for w in waves:
        key = w["mechanic"]
        if key not in unique_waves or len(w["games"]) > len(unique_waves[key]["games"]):
            unique_waves[key] = w

    for w in sorted(unique_waves.values(), key=lambda x: len(x["games"]), reverse=True)[:15]:
        print(f"    {w['description']}")

    n_waves = len(unique_waves)
    print(f"\n  Total unique waves found: {n_waves}")

    # Direction
    temporal_clustering = mantel_p < 0.05
    if temporal_clustering:
        direction = "supported"
        narrative = f"Mantel test significant (r={observed_r:.3f}, p={mantel_p:.4f}): mechanic-similar games cluster in time → genre waves exist."
    elif n_waves >= 5:
        direction = "partial"
        narrative = f"Mantel test not significant (p={mantel_p:.4f}), but {n_waves} genre waves identified descriptively."
    else:
        direction = "inconclusive"
        narrative = f"No significant temporal clustering (r={observed_r:.3f}, p={mantel_p:.4f})."

    rotation_point = 1 if temporal_clustering or n_waves >= 5 else 0
    independence_point = 1 if not temporal_clustering and n_waves < 3 else 0

    result = {
        "id": "HR2",
        "hypothesis": "同一机制家族的爆款在时间上扎堆（题材浪潮存在）",
        "method": f"Mantel test ({n_perm} permutations) comparing Jaccard mechanic similarity matrix vs temporal proximity matrix. Wave detection: same mechanic, ≥2 breakouts within 2-year window.",
        "status": "tested",
        "result": {
            "direction": direction,
            "effect_size": f"Mantel r={observed_r:.4f}",
            "p_value": round(float(mantel_p), 6),
            "confidence_interval": f"n_waves={n_waves}, n_breakout={n}",
            "sample_size": n,
        },
        "confounders": [
            {"name": "Year granularity", "direction": "Breakout year is integer; sub-year timing lost", "controlled": False, "method": None},
            {"name": "Platform growth", "direction": "More games launch each year; later years may show more clusters by chance", "controlled": False, "method": None},
        ],
        "conclusion": narrative,
        "rotation_signal": rotation_point,
        "independence_signal": independence_point,
        "_detail": {
            "mantel_r": round(observed_r, 4),
            "mantel_p": round(float(mantel_p), 6),
            "n_permutations": n_perm,
            "n_waves": n_waves,
            "waves": [
                {"mechanic": w["mechanic"], "games": w["games"], "span_years": w["span_years"]}
                for w in sorted(unique_waves.values(), key=lambda x: len(x["games"]), reverse=True)[:10]
            ],
        },
    }

    print(f"\n  → HR2 verdict: {direction.upper()} — {narrative}")
    print(f"  → Rotation signal: {rotation_point}, Independence signal: {independence_point}")
    return result


# ============================================================
# HR3: YouTube 创作者溢出效应
# ============================================================

def test_hr3_youtube_spillover(data: dict) -> dict:
    """
    HR3: Do games sharing mechanic DNA have correlated YouTube signals?
    (cross-sectional spillover evidence)
    """
    print("\n" + "=" * 70)
    print("HR3: YouTube 创作者溢出效应 — Creator Spillover by Mechanic DNA")
    print("=" * 70)

    yt = data["youtube"]
    buzz = data["buzz"]
    name_map = data["name_map"]

    # Build YouTube signal vectors for games in GAME_DNA
    yt_signals = {}
    signal_cols = ["upload_velocity_30d", "unique_creators", "view_acceleration"]

    # Use buzz metrics (has game_name_clean)
    for dna_name, dna_data in GAME_DNA.items():
        csv_name = name_map.get(dna_name)
        if csv_name is None:
            continue

        # Try buzz first (game_name_clean)
        row = buzz[buzz["game_name_clean"] == csv_name]
        if row.empty:
            # Try youtube (game_name)
            row = yt[yt["game_name"] == csv_name]
        if row.empty:
            # Fuzzy match
            for col_name in ["game_name_clean", "game_name"]:
                df = buzz if col_name == "game_name_clean" else yt
                if col_name in df.columns:
                    for idx, r in df.iterrows():
                        if csv_name.lower() in str(r.get(col_name, "")).lower():
                            row = df.iloc[[idx]]
                            break
                if not row.empty:
                    break

        if not row.empty:
            row = row.iloc[0]
            vals = []
            for sc in signal_cols:
                v = row.get(sc, 0)
                vals.append(float(v) if pd.notna(v) else 0.0)
            yt_signals[dna_name] = np.array(vals)

    matched_games = sorted(yt_signals.keys())
    n = len(matched_games)
    print(f"  Matched {n} games with both DNA and YouTube data")

    if n < 5:
        print("  ⚠️ Too few matched games for meaningful analysis")
        return _empty_hr3_result()

    # Build mechanic similarity matrix
    mech_sim = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            si = set(GAME_DNA[matched_games[i]]["mechanics"])
            sj = set(GAME_DNA[matched_games[j]]["mechanics"])
            mech_sim[i, j] = jaccard_similarity(si, sj)

    # Build YouTube signal distance matrix (Euclidean on z-scored signals)
    signal_matrix = np.array([yt_signals[g] for g in matched_games])

    # Z-score normalize each signal dimension
    means = signal_matrix.mean(axis=0)
    stds = signal_matrix.std(axis=0)
    stds[stds == 0] = 1  # avoid div by zero
    signal_z = (signal_matrix - means) / stds

    yt_dist = squareform(pdist(signal_z, metric="euclidean"))
    # Convert distance to similarity (inverse)
    max_dist = yt_dist.max()
    yt_sim = 1 - (yt_dist / max_dist) if max_dist > 0 else np.zeros_like(yt_dist)

    # Mantel test: mechanic similarity ~ YouTube signal similarity
    sim_vec = squareform(mech_sim, checks=False)
    yt_sim_vec = squareform(yt_sim, checks=False)

    observed_r, _ = stats.pearsonr(sim_vec, yt_sim_vec)

    n_perm = 10000
    perm_r = np.zeros(n_perm)
    rng = np.random.default_rng(42)
    for p in range(n_perm):
        perm_idx = rng.permutation(n)
        perm_sim = mech_sim[np.ix_(perm_idx, perm_idx)]
        perm_sim_vec = squareform(perm_sim, checks=False)
        perm_r[p], _ = stats.pearsonr(perm_sim_vec, yt_sim_vec)

    mantel_p = np.mean(perm_r >= observed_r)

    print(f"\n  Mantel test (mechanic similarity ~ YouTube signal similarity):")
    print(f"    Observed r:     {observed_r:.4f}")
    print(f"    Permutation p:  {mantel_p:.4f}")

    # Kruskal-Wallis: group by primary mechanic category, test YouTube signals
    print(f"\n  Kruskal-Wallis by primary mechanic category:")
    primary_categories = {}
    for g in matched_games:
        first_mech = GAME_DNA[g]["mechanics"][0]
        cat = MECHANIC_CATALOG.get(first_mech, {}).get("category", "unknown")
        primary_categories[g] = cat

    kw_results = {}
    for sig_name, sig_idx in zip(signal_cols, range(len(signal_cols))):
        groups = defaultdict(list)
        for g in matched_games:
            groups[primary_categories[g]].append(signal_z[matched_games.index(g), sig_idx])

        # Need at least 2 groups with 2+ members
        valid_groups = [v for v in groups.values() if len(v) >= 2]
        if len(valid_groups) >= 2:
            h_stat, kw_p = stats.kruskal(*valid_groups)
            kw_results[sig_name] = {"H": round(h_stat, 3), "p": round(kw_p, 4)}
            print(f"    {sig_name:<25} H={h_stat:.3f}, p={kw_p:.4f} {'✅' if kw_p < 0.05 else ''}")
        else:
            kw_results[sig_name] = {"H": None, "p": None}
            print(f"    {sig_name:<25} insufficient group sizes")

    # Partial Mantel: control for game scale (total_visits)
    snap = data["snapshot"]
    visits = {}
    for g in matched_games:
        csv_name = name_map.get(g)
        if csv_name:
            # Match on game_name_clean in buzz
            row = buzz[buzz["game_name_clean"] == csv_name]
            if not row.empty:
                visits[g] = float(row.iloc[0].get("youtube_total_views", 1))
            else:
                visits[g] = 1.0
        else:
            visits[g] = 1.0

    visit_vec = np.array([np.log1p(visits.get(g, 1)) for g in matched_games])
    visit_dist = squareform(pdist(visit_vec.reshape(-1, 1), metric="euclidean"))
    max_vd = visit_dist.max()
    visit_sim = 1 - (visit_dist / max_vd) if max_vd > 0 else np.zeros_like(visit_dist)
    visit_sim_vec = squareform(visit_sim, checks=False)

    # Partial correlation: r(mech_sim, yt_sim | visit_sim)
    # Using residuals method
    if len(sim_vec) > 3:
        slope1, intercept1, _, _, _ = stats.linregress(visit_sim_vec, sim_vec)
        resid_mech = sim_vec - (slope1 * visit_sim_vec + intercept1)
        slope2, intercept2, _, _, _ = stats.linregress(visit_sim_vec, yt_sim_vec)
        resid_yt = yt_sim_vec - (slope2 * visit_sim_vec + intercept2)
        partial_r, partial_p = stats.pearsonr(resid_mech, resid_yt)
        print(f"\n  Partial Mantel (controlling game scale):")
        print(f"    Partial r:  {partial_r:.4f}, p={partial_p:.4f}")
    else:
        partial_r, partial_p = 0.0, 1.0

    # Direction
    spillover_found = mantel_p < 0.05
    any_kw_sig = any(v["p"] is not None and v["p"] < 0.05 for v in kw_results.values())

    if spillover_found:
        direction = "supported"
        narrative = f"Mantel test significant (r={observed_r:.3f}, p={mantel_p:.4f}): mechanic-similar games show correlated YouTube signals → creator spillover exists."
    elif any_kw_sig:
        direction = "partial"
        narrative = f"Mantel test not significant (p={mantel_p:.4f}), but Kruskal-Wallis shows category-level YouTube differences."
    else:
        direction = "inconclusive"
        narrative = f"No evidence of YouTube signal correlation with mechanic similarity (r={observed_r:.3f}, p={mantel_p:.4f})."

    rotation_point = 1 if spillover_found else 0
    independence_point = 1 if not spillover_found and not any_kw_sig else 0

    result = {
        "id": "HR3",
        "hypothesis": "共享机制 DNA 的游戏，YouTube 信号相关（创作者溢出效应）",
        "method": f"Mantel test ({n_perm} permutations) comparing Jaccard mechanic similarity vs YouTube signal (Euclidean z-score) similarity. Kruskal-Wallis by primary category. Partial Mantel controlling game scale.",
        "status": "tested",
        "result": {
            "direction": direction,
            "effect_size": f"Mantel r={observed_r:.4f}, partial r={partial_r:.4f}",
            "p_value": round(float(mantel_p), 6),
            "confidence_interval": f"KW significant: {sum(1 for v in kw_results.values() if v['p'] is not None and v['p'] < 0.05)}/{len(kw_results)}",
            "sample_size": n,
        },
        "confounders": [
            {"name": "Game scale", "direction": "Larger games naturally have more YouTube coverage", "controlled": True, "method": "Partial Mantel test controlling log(total_views)"},
            {"name": "YouTube search algorithm", "direction": "YouTube may recommend similar-looking games together regardless of actual mechanic overlap", "controlled": False, "method": None},
        ],
        "conclusion": narrative,
        "rotation_signal": rotation_point,
        "independence_signal": independence_point,
        "_detail": {
            "mantel_r": round(observed_r, 4),
            "mantel_p": round(float(mantel_p), 6),
            "partial_r": round(partial_r, 4),
            "partial_p": round(partial_p, 4),
            "n_matched_games": n,
            "kruskal_wallis": kw_results,
            "signal_columns": signal_cols,
        },
    }

    print(f"\n  → HR3 verdict: {direction.upper()} — {narrative}")
    print(f"  → Rotation signal: {rotation_point}, Independence signal: {independence_point}")
    return result


def _empty_hr3_result():
    return {
        "id": "HR3",
        "hypothesis": "共享机制 DNA 的游戏，YouTube 信号相关（创作者溢出效应）",
        "method": "Insufficient matched data",
        "status": "skipped",
        "result": {"direction": "inconclusive", "effect_size": "N/A", "p_value": None, "sample_size": 0},
        "confounders": [],
        "conclusion": "Too few games matched between DNA and YouTube data.",
        "rotation_signal": 0,
        "independence_signal": 0,
        "_detail": {},
    }


# ============================================================
# HR4: Google Trends 题材轮动
# ============================================================

def test_hr4_trends_rotation(data: dict) -> dict:
    """
    HR4: In 91-day Trends data, do different genres' search peaks
    stagger (rotation) or co-move (independent/simultaneous)?
    """
    print("\n" + "=" * 70)
    print("HR4: Google Trends 题材轮动 — Search Interest Peak Rotation")
    print("=" * 70)

    trends = data["trends"]
    snap = data["snapshot"]
    buzz = data["buzz"]
    name_map = data["name_map"]

    # Map each trends keyword to genre_l1 via snapshot/buzz
    keyword_genre = {}
    for dna_name, dna_data in GAME_DNA.items():
        csv_name = name_map.get(dna_name)
        if csv_name is None:
            continue

        # Get genre_l1 from buzz metrics (has game_name_clean)
        genre = None
        row = buzz[buzz["game_name_clean"] == csv_name]
        if not row.empty:
            genre = row.iloc[0].get("genre_l1")

        if genre and pd.notna(genre) and genre != "":
            # Find matching keyword in trends
            matching_kw = trends[trends["keyword"] == csv_name]["keyword"].unique()
            if len(matching_kw) > 0:
                keyword_genre[csv_name] = genre

    print(f"  Mapped {len(keyword_genre)} games to genre_l1")
    print(f"  Genres: {dict(Counter(keyword_genre.values()))}")

    if len(keyword_genre) < 5:
        print("  ⚠️ Too few mapped games")
        return _empty_hr4_result()

    # Filter trends to only mapped keywords, exclude 'Roblox' generic
    valid_keywords = set(keyword_genre.keys())
    trends_filtered = trends[trends["keyword"].isin(valid_keywords)].copy()

    # Filter out games with zero/constant interest (no signal)
    kw_variance = trends_filtered.groupby("keyword")["interest"].var()
    active_keywords = set(kw_variance[kw_variance > 0].index)
    print(f"  Active keywords (non-constant interest): {len(active_keywords)} / {len(valid_keywords)}")
    trends_active = trends_filtered[trends_filtered["keyword"].isin(active_keywords)].copy()

    if len(active_keywords) < 5:
        print("  ⚠️ Too few active keywords for meaningful time series analysis")
        return _empty_hr4_result()

    # Update keyword_genre to only active keywords
    keyword_genre_active = {k: v for k, v in keyword_genre.items() if k in active_keywords}
    print(f"  Active genre distribution: {dict(Counter(keyword_genre_active.values()))}")

    # Normalize each game to [0,1]
    def normalize_01(series):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return series * 0
        return (series - mn) / (mx - mn)

    trends_active["interest_norm"] = trends_active.groupby("keyword")["interest"].transform(normalize_01)

    # Aggregate by genre_l1: mean of normalized interest per day
    trends_active["genre_l1"] = trends_active["keyword"].map(keyword_genre_active)
    trends_active = trends_active.dropna(subset=["genre_l1"])
    genre_ts = trends_active.groupby(["date", "genre_l1"])["interest_norm"].mean().reset_index()
    genre_pivot = genre_ts.pivot(index="date", columns="genre_l1", values="interest_norm").dropna(axis=1)

    # Filter out genres with near-zero variance (all games in that genre are flat)
    genre_vars = genre_pivot.var()
    active_genres = genre_vars[genre_vars > 1e-6].index.tolist()
    genre_pivot = genre_pivot[active_genres]
    print(f"  Active genres (non-flat time series): {len(active_genres)} / {len(genre_pivot.columns) + len(genre_vars) - len(active_genres)}")

    genres = list(genre_pivot.columns)
    n_genres = len(genres)
    print(f"\n  Genre-level time series: {n_genres} genres × {len(genre_pivot)} days")

    if n_genres < 2:
        print("  ⚠️ Too few genres for rotation analysis")
        return _empty_hr4_result()

    # 1. Cross-correlation analysis between genre pairs
    print(f"\n  Cross-correlation analysis (max lag ±14 days):")
    max_lag = 14
    cross_corr_results = []

    for i in range(n_genres):
        for j in range(i + 1, n_genres):
            g1, g2 = genres[i], genres[j]
            s1 = genre_pivot[g1].values
            s2 = genre_pivot[g2].values

            best_corr = 0
            best_lag = 0
            for lag in range(-max_lag, max_lag + 1):
                if lag >= 0:
                    x = s1[lag:]
                    y = s2[:len(x)]
                else:
                    x = s1[:lag]
                    y = s2[-lag:]
                if len(x) < 10:
                    continue
                # Skip if either series has zero variance
                if np.std(x) < 1e-10 or np.std(y) < 1e-10:
                    continue
                r, _ = stats.pearsonr(x, y)
                if abs(r) > abs(best_corr):
                    best_corr = r
                    best_lag = lag

            cross_corr_results.append({
                "genre_pair": f"{g1} × {g2}",
                "max_corr": round(best_corr, 3),
                "optimal_lag_days": best_lag,
            })
            print(f"    {g1:<30} × {g2:<30} r={best_corr:+.3f} lag={best_lag:+d}d")

    # 2. Peak date analysis
    print(f"\n  Peak date analysis:")
    peak_dates = {}
    for g in genres:
        series = genre_pivot[g]
        peak_idx = series.idxmax()
        peak_dates[g] = peak_idx
        print(f"    {g:<30} peak={peak_idx.strftime('%Y-%m-%d')}")

    # Peak dispersion: std of peak dates in days
    peak_days = [(d - min(peak_dates.values())).days for d in peak_dates.values()]
    peak_std = np.std(peak_days)
    peak_range = max(peak_days) - min(peak_days)
    print(f"\n  Peak date dispersion: std={peak_std:.1f} days, range={peak_range} days")

    # 3. Permutation test: shuffle genre labels, recompute peak dispersion
    print(f"\n  Permutation test on peak dispersion:")
    n_perm = 10000
    observed_dispersion = peak_std
    perm_dispersions = np.zeros(n_perm)
    rng = np.random.default_rng(42)

    # Build game-level peak dates for permutation (only active keywords)
    game_peaks = {}
    for kw in active_keywords:
        game_series = trends_active[trends_active["keyword"] == kw].set_index("date")["interest"]
        if len(game_series) > 0 and game_series.max() > 0:
            game_peaks[kw] = game_series.idxmax()

    game_list = list(game_peaks.keys())
    genre_list = [keyword_genre_active[g] for g in game_list if g in keyword_genre_active]
    game_list = [g for g in game_list if g in keyword_genre_active]

    for p in range(n_perm):
        shuffled_genres = rng.permutation(genre_list)
        shuffled_genre_peaks = defaultdict(list)
        for g_idx, game in enumerate(game_list):
            shuffled_genre_peaks[shuffled_genres[g_idx]].append(game_peaks[game])

        # Compute genre-level peak as median of game peaks
        perm_peak_days = []
        min_date = min(game_peaks.values())
        for genre, dates in shuffled_genre_peaks.items():
            median_days = np.median([(d - min_date).days for d in dates])
            perm_peak_days.append(median_days)

        perm_dispersions[p] = np.std(perm_peak_days)

    # Two-sided test: is observed dispersion significantly different from random?
    # High dispersion → rotation (peaks spread out)
    # Low dispersion → co-movement (peaks cluster)
    p_greater = np.mean(perm_dispersions >= observed_dispersion)
    p_less = np.mean(perm_dispersions <= observed_dispersion)

    print(f"    Observed peak std: {observed_dispersion:.1f} days")
    print(f"    Permutation mean:  {perm_dispersions.mean():.1f} days")
    print(f"    P(perm ≥ obs):     {p_greater:.4f} (rotation signal)")
    print(f"    P(perm ≤ obs):     {p_less:.4f} (co-movement signal)")

    # 4. Average cross-correlation level
    avg_cross_corr = np.mean([r["max_corr"] for r in cross_corr_results])
    avg_lag = np.mean([abs(r["optimal_lag_days"]) for r in cross_corr_results])
    print(f"\n  Average cross-correlation: {avg_cross_corr:.3f}")
    print(f"  Average absolute lag: {avg_lag:.1f} days")

    # Direction
    rotation_evidence = p_greater < 0.05  # Peaks significantly more spread than random
    comovement_evidence = p_less < 0.05 or avg_cross_corr > 0.5  # Peaks cluster or high sync

    # Additional check: if many genre pairs show high absolute lag with moderate correlation
    high_lag_pairs = sum(1 for r in cross_corr_results if abs(r["optimal_lag_days"]) >= 7 and abs(r["max_corr"]) > 0.2)
    lag_rotation_hint = high_lag_pairs >= n_genres  # At least as many lagged pairs as genres

    if rotation_evidence:
        direction = "supported"
        narrative = f"Peak dispersion significantly high (p={p_greater:.4f}), avg lag={avg_lag:.1f}d → genre rotation pattern."
    elif lag_rotation_hint and not comovement_evidence:
        direction = "partial"
        narrative = f"Permutation test not significant (p={p_greater:.4f}), but {high_lag_pairs} genre pairs show lagged correlation → weak rotation signal."
    elif comovement_evidence:
        direction = "unsupported"
        narrative = f"High cross-correlation ({avg_cross_corr:.3f}) and/or clustered peaks → co-movement, not rotation."
    else:
        direction = "inconclusive"
        narrative = f"No clear rotation or co-movement pattern (peak std={observed_dispersion:.1f}d, avg r={avg_cross_corr:.3f}, p_rotation={p_greater:.4f})."

    rotation_point = 1 if rotation_evidence else 0
    independence_point = 1 if not rotation_evidence and not lag_rotation_hint else 0

    result = {
        "id": "HR4",
        "hypothesis": "在 91 天 Trends 数据中，不同题材的搜索兴趣峰值错开（题材轮动）",
        "method": f"Genre-level time series aggregation, pairwise cross-correlation (max lag ±14d), peak date dispersion permutation test ({n_perm} permutations).",
        "status": "tested",
        "result": {
            "direction": direction,
            "effect_size": f"peak_std={observed_dispersion:.1f}d, avg_xcorr={avg_cross_corr:.3f}, avg_lag={avg_lag:.1f}d",
            "p_value": round(float(min(p_greater, p_less)), 6),
            "confidence_interval": f"peak_range={peak_range}d, n_genres={n_genres}",
            "sample_size": len(valid_keywords),
        },
        "confounders": [
            {"name": "12-week window", "direction": "Short window may not capture full rotation cycle", "controlled": False, "method": None},
            {"name": "Google Trends normalization", "direction": "Batch normalization across keywords may distort relative magnitudes", "controlled": True, "method": "Per-game [0,1] normalization before genre aggregation"},
            {"name": "Unequal genre sizes", "direction": "Genres with more games have smoother averages", "controlled": False, "method": None},
        ],
        "conclusion": narrative,
        "rotation_signal": rotation_point,
        "independence_signal": independence_point,
        "_detail": {
            "cross_correlations": cross_corr_results,
            "peak_dates": {g: d.strftime("%Y-%m-%d") for g, d in peak_dates.items()},
            "peak_std_days": round(observed_dispersion, 1),
            "peak_range_days": peak_range,
            "perm_mean_std": round(float(perm_dispersions.mean()), 1),
            "p_rotation": round(float(p_greater), 4),
            "p_comovement": round(float(p_less), 4),
            "avg_cross_corr": round(avg_cross_corr, 3),
            "avg_abs_lag": round(avg_lag, 1),
            "n_genres": n_genres,
            "genre_game_counts": dict(Counter(keyword_genre.values())),
        },
    }

    print(f"\n  → HR4 verdict: {direction.upper()} — {narrative}")
    print(f"  → Rotation signal: {rotation_point}, Independence signal: {independence_point}")
    return result


def _empty_hr4_result():
    return {
        "id": "HR4",
        "hypothesis": "在 91 天 Trends 数据中，不同题材的搜索兴趣峰值错开（题材轮动）",
        "method": "Insufficient data for analysis",
        "status": "skipped",
        "result": {"direction": "inconclusive", "effect_size": "N/A", "p_value": None, "sample_size": 0},
        "confounders": [],
        "conclusion": "Too few games with both Trends data and genre mapping.",
        "rotation_signal": 0,
        "independence_signal": 0,
        "_detail": {},
    }


# ============================================================
# Synthesis
# ============================================================

def synthesize_rotation_verdict(hr1, hr2, hr3, hr4) -> dict:
    """
    Combine all 4 hypotheses into a rotation vs independence verdict.
    Each hypothesis contributes a rotation_signal (0/1) and independence_signal (0/1).
    """
    hypotheses = [hr1, hr2, hr3, hr4]
    rotation_score = sum(h["rotation_signal"] for h in hypotheses)
    independence_score = sum(h["independence_signal"] for h in hypotheses)

    if rotation_score > independence_score + 1:
        direction = "rotation"
    elif independence_score > rotation_score + 1:
        direction = "independent"
    else:
        direction = "mixed"

    # Build narrative
    parts = []
    for h in hypotheses:
        hid = h["id"]
        d = h["result"]["direction"]
        parts.append(f"{hid}: {d}")

    detail_parts = []
    if hr1["rotation_signal"]:
        detail_parts.append("HR1: breakout games concentrate in specific mechanic categories")
    if hr2["rotation_signal"]:
        detail_parts.append("HR2: temporal genre waves exist (mechanic-similar games cluster in time)")
    if hr3["rotation_signal"]:
        detail_parts.append("HR3: YouTube creator attention spills over within mechanic families")
    if hr4["rotation_signal"]:
        detail_parts.append("HR4: Google Trends peaks stagger across genres (rotation)")

    if hr1["independence_signal"]:
        detail_parts.append("HR1: breakouts are evenly distributed across categories")
    if hr2["independence_signal"]:
        detail_parts.append("HR2: no temporal clustering by mechanic family")
    if hr3["independence_signal"]:
        detail_parts.append("HR3: YouTube signals are independent of mechanic similarity")
    if hr4["independence_signal"]:
        detail_parts.append("HR4: genre peaks co-move or show no rotation pattern")

    narrative_map = {
        "rotation": "Evidence favors genre rotation: breakout signals tend to follow mechanic-family patterns, "
                    "suggesting tracking 'hot genres' can identify emerging games. "
                    "Implication: monitor mechanic families, not just individual games.",
        "independent": "Evidence favors independent emergence: breakout signals arise from diverse directions "
                       "without clear genre cycling. "
                       "Implication: must monitor individual games; no genre-level shortcut.",
        "mixed": "Mixed evidence: some rotation patterns exist (especially temporal waves), "
                 "but breakouts also emerge independently. "
                 "Implication: genre-level monitoring helps but is not sufficient; "
                 "combine genre tracking with individual game signals.",
    }

    return {
        "direction": direction,
        "rotation_score": rotation_score,
        "independence_score": independence_score,
        "hypothesis_summary": ", ".join(parts),
        "evidence": detail_parts,
        "narrative": narrative_map[direction],
    }


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("GENRE ROTATION ANALYSIS")
    print("题材轮动 vs 独立涌现 — Are breakout signals rotating or independent?")
    print("=" * 70)

    data = load_data()
    print(f"\nData loaded:")
    print(f"  Snapshot:  {len(data['snapshot'])} games")
    print(f"  YouTube:   {len(data['youtube'])} rows")
    print(f"  Buzz:      {len(data['buzz'])} rows")
    print(f"  Trends:    {len(data['trends'])} rows")
    print(f"  Name map:  {len(data['name_map'])} matched games")
    print(f"  GAME_DNA:  {len(GAME_DNA)} games ({sum(1 for v in GAME_DNA.values() if v['is_breakout'])} breakout)")

    # Run all 4 hypothesis tests
    hr1 = test_hr1_genre_concentration(data)
    hr2 = test_hr2_temporal_clustering(data)
    hr3 = test_hr3_youtube_spillover(data)
    hr4 = test_hr4_trends_rotation(data)

    # Synthesize verdict
    verdict = synthesize_rotation_verdict(hr1, hr2, hr3, hr4)

    print("\n" + "=" * 70)
    print("SYNTHESIS: ROTATION vs INDEPENDENCE VERDICT")
    print("=" * 70)
    print(f"  Direction: {verdict['direction'].upper()}")
    print(f"  Rotation score:     {verdict['rotation_score']}/4")
    print(f"  Independence score: {verdict['independence_score']}/4")
    print(f"  Summary: {verdict['hypothesis_summary']}")
    print(f"\n  Narrative: {verdict['narrative']}")
    print(f"\n  Evidence:")
    for e in verdict["evidence"]:
        print(f"    • {e}")

    # Build output JSON
    output = {
        "analysis_version": "v1.0-genre-rotation",
        "generated_at": datetime.now().isoformat(),
        "research_question": "爆款信号是在题材间轮动（farming 热完换 horror），还是从不同方向独立冒出来？这直接影响预警策略：轮动→追踪热门题材，独立→逐个游戏监控。",
        "data_window": {
            "start": "2025-12-19",
            "end": "2026-03-18",
            "temporal_limitation": "Google Trends covers 91 days; YouTube is single-week snapshot (W12); GAME_DNA breakout years are annual granularity. Cross-sectional analysis with limited temporal depth.",
        },
        "hypotheses": [hr1, hr2, hr3, hr4],
        "rotation_verdict": verdict,
        "summary": {
            "total_hypotheses": 4,
            "tested": sum(1 for h in [hr1, hr2, hr3, hr4] if h["status"] == "tested"),
            "with_significant_results": sum(1 for h in [hr1, hr2, hr3, hr4]
                                            if h["result"]["direction"] in ("supported", "partial")),
            "rotation_conclusion": verdict["narrative"],
        },
    }

    # Save
    output_path = OUTPUT_DIR / "genre_rotation_findings.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✓ Results saved to {output_path}")


if __name__ == "__main__":
    main()
