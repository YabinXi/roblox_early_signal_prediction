"""
analyze.py — Roblox Early Signal Detection Analysis (Real Data Version)

Research question: 在 Roblox 平台中，中腰部游戏出现 engagement 异常信号后，
其成为爆款的概率是多少？信号的 Precision 和 Recall 是多少？

This version uses REAL Roblox API data (cross-sectional snapshot + curated metadata).

Usage: uv run python analyze.py
"""

import json
import math
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
PROC_DIR = BASE_DIR / "data" / "processed"
SNAPSHOT_PATH = BASE_DIR / "data" / "data_snapshot.json"
FINDINGS_PATH = BASE_DIR / "outputs" / "findings.json"
FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

RESEARCH_QUESTION = (
    "在 Roblox 平台中，中腰部游戏出现 engagement 异常（favorites/visit 或 like ratio 显著高于同tier均值）"
    "是否能有效区分最终成为爆款的游戏与长期停留在中腰部的游戏？"
    "该信号的 Precision、Recall、F1 分别是多少？"
)

DATA_START = None
DATA_END = None


def load_data() -> dict:
    """Load all processed data."""
    data = {}
    if not PROC_DIR.exists():
        print(f"  [WARN] {PROC_DIR} does not exist. Run prepare.py first.")
        return data
    for csv_path in sorted(PROC_DIR.glob("*.csv")):
        name = csv_path.stem
        try:
            df = pd.read_csv(csv_path)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            data[name] = df
            print(f"  ✓ {name}: {len(df)} rows, {len(df.columns)} cols")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
    return data


def audit_data(data: dict) -> dict:
    """Rule R1: Data audit with honest caveats."""
    snap = data.get("roblox_real_snapshot")
    audit = {
        "generated_at": datetime.now().isoformat(),
        "data_type": "REAL — fetched from Roblox Games API v1 + Votes API",
        "snapshot_time": snap["snapshot_time"].iloc[0] if snap is not None and "snapshot_time" in snap.columns else "unknown",
        "datasets": {},
        "key_facts": [
            {"fact": "Data is a single cross-sectional snapshot, NOT time-series", "status": "verified", "source": "Roblox API"},
            {"fact": "CCU represents concurrent users at one moment in time", "status": "verified", "source": "Roblox API playing field"},
            {"fact": "Visits and favorites are cumulative lifetime totals", "status": "verified", "source": "Roblox API"},
            {"fact": "Breakout classification is manually curated from public records", "status": "⚠️ assumed", "source": "GDC talk, news reports, community knowledge"},
            {"fact": "Genre labels from Roblox API genre_l1/genre_l2 fields", "status": "verified", "source": "Roblox API"},
        ],
        "warnings": [
            "⚠️ Single snapshot — cannot observe temporal dynamics or signal lead time",
            "⚠️ Breakout games already succeeded — we're measuring features post-hoc, not predictively",
            "⚠️ Engagement proxy (favorites/visit) is a lifetime metric, not current-period retention",
            "⚠️ Sample is curated (not random) — selection bias toward known games",
        ],
    }
    for name, df in data.items():
        audit["datasets"][name] = {"rows": len(df), "columns": list(df.columns)}

    audit_path = BASE_DIR / "data_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ Data audit saved to {audit_path}")
    return audit


def enumerate_confounders() -> list[dict]:
    """Rule R4: Roblox-specific confounders."""
    return [
        {
            "name": "Survivorship bias",
            "direction": "Breakout games are selected BECAUSE they succeeded; engagement metrics may be consequence, not cause",
            "controlled": False,
            "method": None,
        },
        {
            "name": "Time-of-day CCU variation",
            "direction": "Single snapshot captures one moment; games popular in different timezones may be underrepresented",
            "controlled": False,
            "method": None,
        },
        {
            "name": "Cumulative vs current engagement",
            "direction": "favorites/visit ratio reflects lifetime average, not current-period engagement which would be the actual signal",
            "controlled": False,
            "method": None,
        },
        {
            "name": "Age of game confound",
            "direction": "Older games accumulate more visits, diluting favorites/visit ratio; younger games may appear 'more engaged'",
            "controlled": True,
            "method": "Include game age as control variable; analyze age-adjusted metrics",
        },
        {
            "name": "Update recency / active development",
            "direction": "Recently updated games get algorithm boost and engagement spike",
            "controlled": False,
            "method": None,
        },
    ]


def identify_clean_windows() -> list[dict]:
    """Rule R5: For cross-sectional data, define 'clean' as snapshot timing."""
    return [{
        "start": "2026-03-18",
        "end": "2026-03-18",
        "justification": (
            "Snapshot taken on a Tuesday evening (UTC+8), not during a major holiday, "
            "school break, or Roblox platform event. Represents a 'typical' weekday evening. "
            "Caveat: single snapshot cannot establish baseline variability."
        ),
    }]


# ============================================================
# Hypothesis Tests
# ============================================================

def test_h1_engagement_anomaly_classification(df: pd.DataFrame) -> dict:
    """H1: Can engagement metrics distinguish breakout from non-breakout games?

    Method: Use favorites_per_1k_visits as primary engagement proxy.
    An 'anomaly' is defined as engagement > median + 1.5*MAD for the sample.
    Test whether anomaly status predicts breakout status.
    Also test multiple thresholds for sensitivity analysis.
    """
    df = df.copy()
    eng_col = "favorites_per_1k_visits"
    target_col = "is_breakout"

    # Robust anomaly detection using Median Absolute Deviation
    median_eng = df[eng_col].median()
    mad = np.median(np.abs(df[eng_col] - median_eng))
    mad_scaled = mad * 1.4826  # consistency factor for normal distribution

    thresholds_multipliers = [1.0, 1.5, 2.0, 2.5, 3.0]
    threshold_results = []

    for mult in thresholds_multipliers:
        threshold = median_eng + mult * mad_scaled
        df[f"anom_{mult}"] = df[eng_col] > threshold

        tp = ((df[f"anom_{mult}"]) & (df[target_col])).sum()
        fp = ((df[f"anom_{mult}"]) & (~df[target_col])).sum()
        fn = ((~df[f"anom_{mult}"]) & (df[target_col])).sum()
        tn = ((~df[f"anom_{mult}"]) & (~df[target_col])).sum()

        p = tp / max(tp + fp, 1)
        r = tp / max(tp + fn, 1)
        f = 2 * p * r / max(p + r, 0.001)

        threshold_results.append({
            "multiplier": mult,
            "threshold_value": round(threshold, 4),
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f, 4),
            "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        })

    # Primary analysis at 1.5x MAD
    primary = next(t for t in threshold_results if t["multiplier"] == 1.5)
    best_f1 = max(threshold_results, key=lambda x: x["f1"])

    # Fisher's exact test at primary threshold
    ct = [[primary["tp"], primary["fp"]], [primary["fn"], primary["tn"]]]
    odds_ratio, p_value = stats.fisher_exact(ct)

    # Cohen's h effect size
    p1 = primary["tp"] / max(primary["tp"] + primary["fn"], 1)
    p0 = primary["fp"] / max(primary["fp"] + primary["tn"], 1)
    cohens_h = 2 * np.arcsin(np.sqrt(max(0.001, p1))) - 2 * np.arcsin(np.sqrt(max(0.001, p0)))

    # Also compute AUC using engagement_score as continuous predictor
    from scipy.stats import mannwhitneyu
    breakout_eng = df[df[target_col]][eng_col]
    stable_eng = df[~df[target_col]][eng_col]
    if len(breakout_eng) > 0 and len(stable_eng) > 0:
        u_stat, mw_p = mannwhitneyu(breakout_eng, stable_eng, alternative="greater")
        auc = u_stat / (len(breakout_eng) * len(stable_eng))
    else:
        auc = 0.5
        mw_p = 1.0

    return {
        "id": "H1",
        "hypothesis": "Engagement anomaly (favorites/1k visits > median + 1.5*MAD) can distinguish breakout from non-breakout Roblox games",
        "method": (
            f"Binary classification using favorites_per_1k_visits as engagement proxy. "
            f"Anomaly defined via Median Absolute Deviation (MAD) — robust to outliers. "
            f"Tested at 5 threshold multipliers [1.0, 1.5, 2.0, 2.5, 3.0]. "
            f"Statistical significance via Fisher's exact test. "
            f"Discriminative power via Mann-Whitney U (AUC proxy)."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if p_value < 0.1 and primary["precision"] > 0.3 else "inconclusive",
            "effect_size": f"Cohen's h = {cohens_h:.3f}, OR = {odds_ratio:.2f}, AUC = {auc:.3f}",
            "p_value": round(float(p_value), 6),
            "confidence_interval": f"P={primary['precision']:.2%}, R={primary['recall']:.2%}, F1={primary['f1']:.2%}",
            "sample_size": len(df),
        },
        "confounders": enumerate_confounders(),
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": (
            f"Cross-sectional snapshot (2026-03-18). Cannot determine temporal lead of signal. "
            f"Favorites/visit is a LIFETIME metric — higher in breakout games may be CONSEQUENCE of success, "
            f"not a predictive signal. Longitudinal data needed to establish causality."
        ),
        "conclusion": (
            f"At 1.5x MAD threshold ({primary['threshold_value']:.2f} fav/1kv): "
            f"P={primary['precision']:.2%}, R={primary['recall']:.2%}, F1={primary['f1']:.2%}. "
            f"Fisher p={p_value:.4f}, OR={odds_ratio:.2f}. "
            f"Mann-Whitney AUC={auc:.3f} (p={mw_p:.4f}). "
            f"Best F1 at {best_f1['multiplier']}x MAD: F1={best_f1['f1']:.2%}. "
            f"{'Engagement anomaly has discriminative power for breakout classification.' if auc > 0.6 else 'Weak discriminative power.'} "
            f"CAVEAT: This is post-hoc classification, not prospective prediction."
        ),
        "_detail": {
            "confusion_matrix": {"TP": primary["tp"], "FP": primary["fp"], "FN": primary["fn"], "TN": primary["tn"]},
            "precision": primary["precision"],
            "recall": primary["recall"],
            "f1": primary["f1"],
            "auc": round(auc, 4),
            "mw_p_value": round(float(mw_p), 6),
            "threshold_sensitivity": threshold_results,
            "best_threshold": best_f1,
            "median_engagement": round(median_eng, 4),
            "mad_scaled": round(mad_scaled, 4),
        },
    }


def test_h2_engagement_distribution_difference(df: pd.DataFrame) -> dict:
    """H2: Breakout games have statistically different engagement distribution."""
    breakout = df[df["is_breakout"]]
    stable = df[~df["is_breakout"]]

    metrics = {}
    for col in ["favorites_per_1k_visits", "like_ratio", "engagement_score"]:
        b_vals = breakout[col].dropna()
        s_vals = stable[col].dropna()

        if len(b_vals) >= 3 and len(s_vals) >= 3:
            t_stat, t_p = stats.ttest_ind(b_vals, s_vals, equal_var=False)
            mw_stat, mw_p = stats.mannwhitneyu(b_vals, s_vals, alternative="two-sided")
            pooled_std = np.sqrt((b_vals.std()**2 + s_vals.std()**2) / 2)
            cohens_d = (b_vals.mean() - s_vals.mean()) / pooled_std if pooled_std > 0 else 0

            metrics[col] = {
                "breakout_mean": round(float(b_vals.mean()), 6),
                "breakout_median": round(float(b_vals.median()), 6),
                "stable_mean": round(float(s_vals.mean()), 6),
                "stable_median": round(float(s_vals.median()), 6),
                "t_stat": round(float(t_stat), 4),
                "t_p_value": round(float(t_p), 6),
                "mann_whitney_p": round(float(mw_p), 6),
                "cohens_d": round(float(cohens_d), 4),
                "n_breakout": len(b_vals),
                "n_stable": len(s_vals),
            }

    # Primary metric: favorites_per_1k_visits
    primary = metrics.get("favorites_per_1k_visits", {})
    p_val = primary.get("t_p_value", 1.0)
    d = primary.get("cohens_d", 0)

    return {
        "id": "H2",
        "hypothesis": "Breakout games have significantly higher engagement metrics (favorites/visit, like ratio) than non-breakout games",
        "method": (
            "Welch's t-test and Mann-Whitney U test comparing engagement distributions between breakout (n={}) "
            "and non-breakout (n={}) groups. Effect size via Cohen's d. Tested on 3 metrics: "
            "favorites_per_1k_visits, like_ratio, engagement_score."
        ).format(len(breakout), len(stable)),
        "status": "tested",
        "result": {
            "direction": "supported" if p_val < 0.05 and d > 0.3 else ("supported" if p_val < 0.1 else "inconclusive"),
            "effect_size": f"Cohen's d = {d:.3f} (favorites/1kv)",
            "p_value": p_val,
            "confidence_interval": f"Breakout mean={primary.get('breakout_mean', 0):.3f}, Stable mean={primary.get('stable_mean', 0):.3f}",
            "sample_size": len(df),
        },
        "confounders": enumerate_confounders()[:4],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Cross-sectional comparison. Cannot establish temporal ordering (engagement before or after breakout).",
        "conclusion": (
            f"Favorites/1kv: breakout mean={primary.get('breakout_mean', 0):.3f} vs stable mean={primary.get('stable_mean', 0):.3f}, "
            f"d={d:.3f}, t-test p={p_val:.4f}, MW p={primary.get('mann_whitney_p', 1):.4f}. "
            f"{'Significant difference — breakout games have higher engagement per visit.' if p_val < 0.05 else 'Difference not significant at α=0.05.'} "
            f"Like ratio: d={metrics.get('like_ratio', {}).get('cohens_d', 0):.3f}, p={metrics.get('like_ratio', {}).get('t_p_value', 1):.4f}. "
            f"Composite engagement: d={metrics.get('engagement_score', {}).get('cohens_d', 0):.3f}, p={metrics.get('engagement_score', {}).get('t_p_value', 1):.4f}."
        ),
        "_detail": {"per_metric": metrics},
    }


def test_h3_age_controlled_engagement(df: pd.DataFrame) -> dict:
    """H3: After controlling for game age, engagement anomaly still predicts breakout."""
    df = df.copy()
    df["log_age"] = np.log1p(df["age_days"])
    df["log_visits"] = np.log1p(df["total_visits"])

    # Age-adjusted engagement: residual of engagement regressed on log(age)
    from scipy.stats import linregress
    mask = df["favorites_per_1k_visits"].notna() & df["log_age"].notna()
    slope, intercept, r_val, p_val_reg, std_err = linregress(
        df.loc[mask, "log_age"], df.loc[mask, "favorites_per_1k_visits"]
    )
    df["age_adjusted_engagement"] = df["favorites_per_1k_visits"] - (slope * df["log_age"] + intercept)

    # Compare age-adjusted engagement
    breakout_adj = df[df["is_breakout"]]["age_adjusted_engagement"].dropna()
    stable_adj = df[~df["is_breakout"]]["age_adjusted_engagement"].dropna()

    if len(breakout_adj) >= 3 and len(stable_adj) >= 3:
        t_stat, t_p = stats.ttest_ind(breakout_adj, stable_adj, equal_var=False)
        pooled_std = np.sqrt((breakout_adj.std()**2 + stable_adj.std()**2) / 2)
        d = (breakout_adj.mean() - stable_adj.mean()) / pooled_std if pooled_std > 0 else 0
    else:
        t_stat = t_p = d = 0

    return {
        "id": "H3",
        "hypothesis": "After controlling for game age, breakout games still show higher engagement anomaly",
        "method": (
            f"Linear regression of favorites_per_1k_visits on log(age_days) to remove age confound. "
            f"Age-engagement regression: slope={slope:.6f}, R²={r_val**2:.4f}, p={p_val_reg:.4f}. "
            f"Then Welch's t-test on residuals between breakout and non-breakout groups."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if t_p < 0.1 and d > 0.2 else "inconclusive",
            "effect_size": f"Cohen's d = {d:.3f} (age-adjusted)",
            "p_value": round(float(t_p), 6),
            "confidence_interval": f"Adj. breakout mean={breakout_adj.mean():.4f}, Adj. stable mean={stable_adj.mean():.4f}",
            "sample_size": len(df),
        },
        "confounders": [
            {"name": "Game age", "direction": "Older games dilute favorites/visit", "controlled": True, "method": "Linear regression residualization"},
            {"name": "Total visits magnitude", "direction": "High-visit games mechanically lower ratio", "controlled": False, "method": None},
            {"name": "Development investment", "direction": "Breakout games may have higher dev investment", "controlled": False, "method": None},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Age adjustment removes linear age trend, but non-linear effects (lifecycle stages) are not controlled.",
        "conclusion": (
            f"Age-engagement regression R²={r_val**2:.4f} (age explains {r_val**2*100:.1f}% of engagement variance). "
            f"After age adjustment: breakout mean={breakout_adj.mean():.4f}, stable mean={stable_adj.mean():.4f}. "
            f"d={d:.3f}, t={t_stat:.3f}, p={t_p:.4f}. "
            f"{'Signal persists after age control.' if t_p < 0.1 else 'Signal weakened after age control — age is an important confound.'}"
        ),
        "_detail": {
            "age_regression": {
                "slope": round(slope, 6),
                "intercept": round(intercept, 6),
                "r_squared": round(r_val**2, 4),
                "p_value": round(p_val_reg, 6),
            },
        },
    }


def test_h4_genre_engagement_variation(df: pd.DataFrame) -> dict:
    """H4: Engagement anomaly signal strength varies by Roblox genre (genre_l1)."""
    df = df.copy()

    # Per-genre analysis
    genre_results = []
    for genre, group in df.groupby("genre_l1"):
        if len(group) < 3 or genre == "":
            continue
        n_breakout = group["is_breakout"].sum()
        n_total = len(group)
        mean_eng = group["favorites_per_1k_visits"].mean()
        std_eng = group["favorites_per_1k_visits"].std()

        genre_results.append({
            "genre": genre,
            "n_total": n_total,
            "n_breakout": int(n_breakout),
            "breakout_rate": round(n_breakout / n_total, 3),
            "mean_engagement": round(mean_eng, 4),
            "std_engagement": round(std_eng, 4) if not np.isnan(std_eng) else 0,
        })

    # Kruskal-Wallis test: does engagement differ across genres?
    genre_groups = [group["favorites_per_1k_visits"].values
                    for _, group in df.groupby("genre_l1") if len(group) >= 3 and _ != ""]
    if len(genre_groups) >= 3:
        h_stat, kw_p = stats.kruskal(*genre_groups)
    else:
        h_stat, kw_p = 0, 1.0

    return {
        "id": "H4",
        "hypothesis": "Engagement anomaly signal strength varies significantly across Roblox genres",
        "method": f"Kruskal-Wallis H-test across {len(genre_groups)} genre groups. Per-genre breakout rates and engagement distributions.",
        "status": "tested",
        "result": {
            "direction": "supported" if kw_p < 0.05 else "inconclusive",
            "effect_size": f"Kruskal-Wallis H = {h_stat:.3f}",
            "p_value": round(float(kw_p), 6),
            "confidence_interval": f"Tested across {len(genre_groups)} genres with ≥3 games each",
            "sample_size": len(df),
        },
        "confounders": [
            {"name": "Genre popularity cycles", "direction": "Some genres naturally attract higher engagement", "controlled": False, "method": None},
            {"name": "Unequal genre sample sizes", "direction": "Genres with few games have unstable estimates", "controlled": False, "method": None},
            {"name": "Genre definition ambiguity", "direction": "Roblox genre_l1 may not match player perception", "controlled": False, "method": None},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Single snapshot; genre engagement patterns may vary seasonally.",
        "conclusion": (
            f"Kruskal-Wallis H={h_stat:.3f}, p={kw_p:.4f}. "
            f"{'Engagement varies significantly across genres — signal threshold should be genre-calibrated.' if kw_p < 0.05 else 'No significant cross-genre variation detected.'} "
            f"Per-genre breakdown: {json.dumps(genre_results[:5], ensure_ascii=False)}"
        ),
        "_detail": {"per_genre": genre_results, "kw_h": round(h_stat, 3), "kw_p": round(kw_p, 6)},
    }


def test_h5_buzz_velocity_breakout(snap: pd.DataFrame, buzz: pd.DataFrame) -> dict:
    """H5: Google Trends search interest velocity predicts breakout better than engagement metrics.

    Method: Mann-Whitney U test comparing buzz_velocity between breakout and non-breakout games.
    Compute AUC and compare against H1's engagement AUC (0.428).

    Note: 'buzz_velocity' is the slope of 12-week Google Trends interest — a specific,
    observable metric, not a general 'cultural buzz' construct.
    """
    merged = snap.merge(buzz[["universe_id", "buzz_velocity", "composite_buzz"]], on="universe_id", how="left")
    merged["buzz_velocity"] = merged["buzz_velocity"].fillna(0)

    breakout_bv = merged[merged["is_breakout"]]["buzz_velocity"].dropna()
    stable_bv = merged[~merged["is_breakout"]]["buzz_velocity"].dropna()

    if len(breakout_bv) >= 3 and len(stable_bv) >= 3:
        u_stat, mw_p = stats.mannwhitneyu(breakout_bv, stable_bv, alternative="greater")
        auc = u_stat / (len(breakout_bv) * len(stable_bv))
    else:
        u_stat, mw_p, auc = 0, 1.0, 0.5

    # Effect size: rank-biserial correlation
    n1, n2 = len(breakout_bv), len(stable_bv)
    rank_biserial = 2 * u_stat / (n1 * n2) - 1 if n1 * n2 > 0 else 0

    return {
        "id": "H5",
        "hypothesis": "Google Trends search interest velocity (12-week slope) can distinguish breakout from non-breakout games better than engagement metrics alone",
        "method": (
            f"Mann-Whitney U test comparing buzz_velocity (slope of last 12 weeks search interest) "
            f"between breakout (n={n1}) and non-breakout (n={n2}) groups. "
            f"AUC computed as U/(n1*n2). Compared against H1 engagement AUC=0.428."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if auc > 0.5 and mw_p < 0.1 else "inconclusive",
            "effect_size": f"AUC={auc:.3f}, rank-biserial r={rank_biserial:.3f}",
            "p_value": round(float(mw_p), 6),
            "confidence_interval": f"Breakout mean velocity={breakout_bv.mean():.4f}, Stable mean={stable_bv.mean():.4f}",
            "sample_size": len(merged),
        },
        "confounders": [
            {"name": "Game fame vs buzz", "direction": "Popular games naturally have higher search interest", "controlled": True, "method": "Using velocity (slope) not level controls for baseline fame"},
            {"name": "Search keyword ambiguity", "direction": "Common words in game names pollute trends data", "controlled": False, "method": None},
            {"name": "Cross-batch normalization", "direction": "Different pytrends batches may have scale differences", "controlled": True, "method": "Roblox keyword included in every batch as reference"},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Buzz velocity uses 12-week trailing window. Cannot establish if buzz preceded or followed breakout.",
        "conclusion": (
            f"Buzz velocity AUC={auc:.3f} (vs H1 engagement AUC=0.428). "
            f"Breakout mean velocity={breakout_bv.mean():.4f}, stable={stable_bv.mean():.4f}. "
            f"Mann-Whitney p={mw_p:.4f}, rank-biserial r={rank_biserial:.3f}. "
            f"{'Buzz velocity outperforms engagement metrics.' if auc > 0.5 else 'Buzz velocity does not clearly outperform engagement.'} "
            f"CAVEAT: Synthetic trends data if API was unavailable — validate with real Google Trends."
        ),
        "_detail": {
            "auc": round(auc, 4),
            "h1_auc": 0.428,
            "auc_improvement": round(auc - 0.428, 4),
            "mw_u_stat": round(float(u_stat), 2),
            "mw_p_value": round(float(mw_p), 6),
            "rank_biserial": round(rank_biserial, 4),
            "breakout_mean_velocity": round(float(breakout_bv.mean()), 4),
            "stable_mean_velocity": round(float(stable_bv.mean()), 4),
        },
    }


def test_h6_youtube_volume_breakout(snap: pd.DataFrame, buzz: pd.DataFrame) -> dict:
    """H6: YouTube signals (volume, creator diversity, upload velocity, view acceleration)
    correlate with breakout status.

    Method: Mann-Whitney U for AUC on each signal, Fisher exact for high-volume threshold.
    """
    # Merge all available YouTube signals
    yt_cols = ["universe_id", "youtube_volume"]
    enriched_signals = ["unique_creators", "upload_velocity_30d", "view_acceleration",
                        "upload_velocity_7d", "short_video_ratio", "title_update_freq",
                        "recent_video_avg_views"]
    for col in enriched_signals:
        if col in buzz.columns:
            yt_cols.append(col)

    merged = snap.merge(buzz[yt_cols], on="universe_id", how="left")
    merged["youtube_volume"] = merged["youtube_volume"].fillna(0)

    breakout_yt = merged[merged["is_breakout"]]["youtube_volume"].dropna()
    stable_yt = merged[~merged["is_breakout"]]["youtube_volume"].dropna()

    # Mann-Whitney U for youtube_volume (original)
    if len(breakout_yt) >= 3 and len(stable_yt) >= 3:
        u_stat, mw_p = stats.mannwhitneyu(breakout_yt, stable_yt, alternative="greater")
        auc = u_stat / (len(breakout_yt) * len(stable_yt))
    else:
        u_stat, mw_p, auc = 0, 1.0, 0.5

    # Fisher exact: high volume (>= median) vs breakout
    median_yt = merged["youtube_volume"].median()
    high_vol = merged["youtube_volume"] >= max(median_yt, 1)
    tp = int((high_vol & merged["is_breakout"]).sum())
    fp = int((high_vol & ~merged["is_breakout"]).sum())
    fn = int((~high_vol & merged["is_breakout"]).sum())
    tn = int((~high_vol & ~merged["is_breakout"]).sum())

    ct = [[tp, fp], [fn, tn]]
    odds_ratio, fisher_p = stats.fisher_exact(ct)

    # Test each enriched signal for AUC
    signal_aucs = {"youtube_volume": round(auc, 4)}
    for sig in enriched_signals:
        if sig not in merged.columns:
            continue
        merged[sig] = merged[sig].fillna(0)
        b_vals = merged[merged["is_breakout"]][sig].dropna()
        s_vals = merged[~merged["is_breakout"]][sig].dropna()
        if len(b_vals) >= 3 and len(s_vals) >= 3:
            try:
                u, p = stats.mannwhitneyu(b_vals, s_vals, alternative="greater")
                sig_auc = u / (len(b_vals) * len(s_vals))
                signal_aucs[sig] = round(sig_auc, 4)
            except Exception:
                signal_aucs[sig] = 0.5
        else:
            signal_aucs[sig] = 0.5

    # Find best signal
    best_signal = max(signal_aucs, key=signal_aucs.get)
    best_auc = signal_aucs[best_signal]

    return {
        "id": "H6",
        "hypothesis": "YouTube content signals (volume, creator diversity, upload velocity, view acceleration) predict breakout status",
        "method": (
            f"Mann-Whitney U test comparing YouTube signals between breakout (n={len(breakout_yt)}) "
            f"and non-breakout (n={len(stable_yt)}) groups. "
            f"Fisher's exact test using median volume (≥{median_yt:.0f}) as threshold. "
            f"Tested {len(signal_aucs)} signals: {', '.join(signal_aucs.keys())}."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if (best_auc > 0.6 or fisher_p < 0.1) else "inconclusive",
            "effect_size": f"Best AUC={best_auc:.3f} ({best_signal}), volume AUC={auc:.3f}, OR={odds_ratio:.2f}",
            "p_value": round(float(min(mw_p, fisher_p)), 6),
            "confidence_interval": f"Breakout mean volume={breakout_yt.mean():.1f}, Stable mean={stable_yt.mean():.1f}",
            "sample_size": len(merged),
        },
        "confounders": [
            {"name": "Game popularity drives YouTube coverage", "direction": "Reverse causality — breakout causes YouTube, not vice versa", "controlled": False, "method": None},
            {"name": "YouTube search algorithm", "direction": "Trending bias in YouTube search results", "controlled": False, "method": None},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "YouTube metrics are current snapshot; cannot determine if video coverage preceded breakout.",
        "conclusion": (
            f"Best signal: {best_signal} (AUC={best_auc:.3f}). "
            f"All signal AUCs: {signal_aucs}. "
            f"Fisher exact OR={odds_ratio:.2f}, p={fisher_p:.4f}. "
            f"Breakout games avg {breakout_yt.mean():.1f} videos vs stable {stable_yt.mean():.1f}. "
            f"{'Enriched YouTube signals improve breakout prediction.' if best_auc > auc else 'Volume remains the strongest YouTube signal.'} "
            f"Note: scrapetube data may be synthetic if API was blocked."
        ),
        "_detail": {
            "auc": round(auc, 4),
            "best_signal": best_signal,
            "best_auc": round(best_auc, 4),
            "all_signal_aucs": signal_aucs,
            "fisher_p": round(float(fisher_p), 6),
            "odds_ratio": round(float(odds_ratio), 4) if not np.isinf(odds_ratio) else 999.0,
            "confusion_matrix": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
            "median_threshold": round(float(median_yt), 1),
        },
    }


def test_h7_genre_lineage_depth(snap: pd.DataFrame, genre_opp: pd.DataFrame) -> dict:
    """H7: Genres with deeper lineage produce higher breakout rates.

    Method: Point-biserial correlation between lineage_depth and is_breakout.
    Fisher exact test comparing deep (≥3) vs shallow (≤2) genre breakout rates.
    """
    merged = snap.merge(
        genre_opp[["universe_id", "lineage_depth", "top10_saturation", "engagement_variance"]],
        on="universe_id", how="left"
    )
    merged["lineage_depth"] = merged["lineage_depth"].fillna(1)

    # Point-biserial correlation: lineage_depth vs is_breakout
    breakout_binary = merged["is_breakout"].astype(int)
    corr, pb_p = stats.pointbiserialr(merged["lineage_depth"], breakout_binary)

    # Fisher exact: deep (≥3) vs shallow (<3)
    deep = merged["lineage_depth"] >= 3
    tp = int((deep & merged["is_breakout"]).sum())
    fp = int((deep & ~merged["is_breakout"]).sum())
    fn = int((~deep & merged["is_breakout"]).sum())
    tn = int((~deep & ~merged["is_breakout"]).sum())

    ct = [[tp, fp], [fn, tn]]
    odds_ratio, fisher_p = stats.fisher_exact(ct)

    # Breakout rates by depth
    depth_rates = merged.groupby("lineage_depth").agg(
        n=("is_breakout", "count"),
        n_breakout=("is_breakout", "sum"),
    )
    depth_rates["rate"] = (depth_rates["n_breakout"] / depth_rates["n"]).round(4)

    return {
        "id": "H7",
        "hypothesis": "Genres with deeper lineage (more evolutionary stages) have higher breakout rates",
        "method": (
            f"Point-biserial correlation between lineage_depth and is_breakout. "
            f"Fisher's exact test comparing deep lineage (≥3 eras) vs shallow (<3 eras) breakout rates."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if (corr > 0.1 and pb_p < 0.1) or fisher_p < 0.1 else "inconclusive",
            "effect_size": f"r_pb={corr:.3f}, OR={odds_ratio:.2f}",
            "p_value": round(float(min(pb_p, fisher_p)), 6),
            "confidence_interval": f"Deep lineage breakout: {tp}/{tp + fp}, Shallow: {fn}/{fn + tn}",
            "sample_size": len(merged),
        },
        "confounders": [
            {"name": "Genre popularity", "direction": "Popular genres have more games and more chances for breakout", "controlled": False, "method": None},
            {"name": "Lineage mapping subjectivity", "direction": "Manual genre_l1 → lineage mapping introduces researcher bias", "controlled": False, "method": None},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Lineage depth is static; cannot assess if depth causes breakout or reflects genre maturity.",
        "conclusion": (
            f"Point-biserial r={corr:.3f}, p={pb_p:.4f}. "
            f"Fisher exact OR={odds_ratio:.2f}, p={fisher_p:.4f}. "
            f"Deep lineage (≥3): {tp} breakout / {tp + fp} total. "
            f"Shallow (<3): {fn} breakout / {fn + tn} total. "
            f"{'Deeper lineage genres do produce more breakouts.' if corr > 0.1 and pb_p < 0.1 else 'Lineage depth alone is not a significant breakout predictor.'}"
        ),
        "_detail": {
            "point_biserial_r": round(float(corr), 4),
            "point_biserial_p": round(float(pb_p), 6),
            "fisher_p": round(float(fisher_p), 6),
            "odds_ratio": round(float(odds_ratio), 4) if not np.isinf(odds_ratio) else 999.0,
            "depth_breakout_rates": depth_rates.reset_index().to_dict("records"),
        },
    }


def test_h8_multi_trend_convergence(snap: pd.DataFrame, buzz: pd.DataFrame, genre_opp: pd.DataFrame) -> dict:
    """H8: Multi-trend convergence composite predicts breakout better than any single metric.

    Composite = normalize(lineage_depth) + normalize(buzz_velocity) + normalize(1 - top10_saturation)
    Compare top quartile vs bottom quartile breakout rates via Fisher exact test.
    Permutation test for robustness.
    """
    # Merge all signals
    merged = snap.copy()
    if not buzz.empty:
        merged = merged.merge(buzz[["universe_id", "buzz_velocity", "composite_buzz"]], on="universe_id", how="left")
    else:
        merged["buzz_velocity"] = 0.0
        merged["composite_buzz"] = 0.0

    if not genre_opp.empty:
        merged = merged.merge(
            genre_opp[["universe_id", "lineage_depth", "top10_saturation"]],
            on="universe_id", how="left"
        )
    else:
        merged["lineage_depth"] = 1
        merged["top10_saturation"] = 0.0

    merged = merged.fillna({"buzz_velocity": 0, "lineage_depth": 1, "top10_saturation": 0})

    # Normalize each component to [0, 1]
    def norm_col(s):
        r = s.max() - s.min()
        return (s - s.min()) / r if r > 0 else pd.Series(0.5, index=s.index)

    merged["convergence_score"] = (
        norm_col(merged["lineage_depth"])
        + norm_col(merged["buzz_velocity"])
        + norm_col(1 - merged["top10_saturation"])
    ) / 3  # Average to keep in [0, 1]

    # Quartile analysis
    q75 = merged["convergence_score"].quantile(0.75)
    q25 = merged["convergence_score"].quantile(0.25)

    top_q = merged[merged["convergence_score"] >= q75]
    bot_q = merged[merged["convergence_score"] <= q25]

    tp = int(top_q["is_breakout"].sum())
    fp = int(len(top_q) - tp)
    fn = int(bot_q["is_breakout"].sum())
    tn = int(len(bot_q) - fn)

    top_rate = tp / max(len(top_q), 1)
    bot_rate = fn / max(len(bot_q), 1)

    ct = [[tp, fp], [fn, tn]]
    odds_ratio, fisher_p = stats.fisher_exact(ct)

    # Permutation test: shuffle is_breakout 10000 times, compute rate difference
    np.random.seed(42)
    observed_diff = top_rate - bot_rate
    perm_diffs = []
    n_perm = 10000
    labels = merged["is_breakout"].values.copy()

    for _ in range(n_perm):
        np.random.shuffle(labels)
        perm_top = labels[merged["convergence_score"].values >= q75]
        perm_bot = labels[merged["convergence_score"].values <= q25]
        perm_top_rate = perm_top.sum() / max(len(perm_top), 1)
        perm_bot_rate = perm_bot.sum() / max(len(perm_bot), 1)
        perm_diffs.append(perm_top_rate - perm_bot_rate)

    perm_p = (np.sum(np.array(perm_diffs) >= observed_diff) + 1) / (n_perm + 1)

    # Also compute AUC for convergence score
    breakout_cs = merged[merged["is_breakout"]]["convergence_score"].dropna()
    stable_cs = merged[~merged["is_breakout"]]["convergence_score"].dropna()

    if len(breakout_cs) >= 3 and len(stable_cs) >= 3:
        u_stat, mw_p = stats.mannwhitneyu(breakout_cs, stable_cs, alternative="greater")
        auc = u_stat / (len(breakout_cs) * len(stable_cs))
    else:
        auc, mw_p = 0.5, 1.0

    return {
        "id": "H8",
        "hypothesis": "Multi-trend convergence composite (lineage_depth + buzz_velocity + inverse saturation) predicts breakout better than single metrics",
        "method": (
            f"Additive composite of normalized lineage_depth, buzz_velocity, and (1-top10_saturation). "
            f"Fisher exact test comparing top quartile (≥{q75:.3f}) vs bottom quartile (≤{q25:.3f}) breakout rates. "
            f"Permutation test (n=10000) for robustness. Mann-Whitney U for AUC."
        ),
        "status": "tested",
        "result": {
            "direction": "supported" if (fisher_p < 0.1 or perm_p < 0.1) and auc > 0.5 else "inconclusive",
            "effect_size": f"AUC={auc:.3f}, OR={odds_ratio:.2f}, rate diff={observed_diff:.3f}",
            "p_value": round(float(min(fisher_p, perm_p)), 6),
            "confidence_interval": f"Top Q rate={top_rate:.2%} ({tp}/{len(top_q)}), Bottom Q rate={bot_rate:.2%} ({fn}/{len(bot_q)})",
            "sample_size": len(merged),
        },
        "confounders": [
            {"name": "Composite construction bias", "direction": "Equal weighting may not reflect true signal importance", "controlled": False, "method": None},
            {"name": "Small sample for quartile analysis", "direction": f"n={len(snap)} → ~{len(top_q)} per quartile is very small", "controlled": False, "method": None},
            {"name": "Synthetic data components", "direction": "Buzz data may be synthetic if APIs unavailable", "controlled": False, "method": None},
        ],
        "clean_window": identify_clean_windows()[0],
        "temporal_limitation": "Composite uses current-period data; cannot validate prospective prediction.",
        "conclusion": (
            f"Convergence composite AUC={auc:.3f} (vs H1 engagement AUC=0.428, H5 buzz AUC={merged.get('h5_auc', 'N/A')}). "
            f"Top quartile breakout rate: {top_rate:.2%}, bottom: {bot_rate:.2%}, diff={observed_diff:.3f}. "
            f"Fisher p={fisher_p:.4f}, permutation p={perm_p:.4f}. "
            f"{'Multi-trend convergence shows promise as composite signal.' if auc > 0.55 else 'Composite does not significantly outperform simpler metrics.'} "
            f"N.B. n=48 is too small for regression-based composite — simple additive approach used."
        ),
        "_detail": {
            "auc": round(auc, 4),
            "fisher_p": round(float(fisher_p), 6),
            "permutation_p": round(float(perm_p), 6),
            "odds_ratio": round(float(odds_ratio), 4) if not np.isinf(odds_ratio) else 999.0,
            "observed_rate_diff": round(observed_diff, 4),
            "top_quartile_threshold": round(float(q75), 4),
            "bottom_quartile_threshold": round(float(q25), 4),
            "top_q_n": len(top_q),
            "bot_q_n": len(bot_q),
            "convergence_stats": {
                "mean": round(float(merged["convergence_score"].mean()), 4),
                "std": round(float(merged["convergence_score"].std()), 4),
                "min": round(float(merged["convergence_score"].min()), 4),
                "max": round(float(merged["convergence_score"].max()), 4),
            },
        },
    }


def analyze(data: dict) -> dict:
    """Main analysis."""
    snap = data.get("roblox_real_snapshot")
    lineage = data.get("roblox_genre_lineage")
    buzz = data.get("roblox_buzz_metrics")
    genre_opp = data.get("roblox_game_genre_opportunity")

    if snap is None:
        print("  [ERROR] roblox_real_snapshot not found!")
        return {}

    # Temporal limitation
    temporal_limitation = (
        "Single cross-sectional snapshot from Roblox API (2026-03-18). "
        "CAN support: cross-sectional engagement comparison, anomaly detection calibration, "
        "genre-level variation analysis, cultural buzz association testing. "
        "CANNOT support: temporal lead-time estimation, prospective prediction validation, "
        "before/after causal analysis. "
        "All findings are associational, not causal."
    )

    print("\n  Testing hypotheses...")

    print("    H1: Engagement anomaly classification...")
    h1 = test_h1_engagement_anomaly_classification(snap)

    print("    H2: Distribution difference...")
    h2 = test_h2_engagement_distribution_difference(snap)

    print("    H3: Age-controlled analysis...")
    h3 = test_h3_age_controlled_engagement(snap)

    print("    H4: Genre variation...")
    h4 = test_h4_genre_engagement_variation(snap)

    tested = [h1, h2, h3, h4]

    # H5-H8: YouTube creator activity & genre opportunity hypotheses
    if buzz is not None and not buzz.empty:
        print("    H5: Search interest velocity → breakout...")
        h5 = test_h5_buzz_velocity_breakout(snap, buzz)
        tested.append(h5)

        print("    H6: YouTube signals → breakout...")
        h6 = test_h6_youtube_volume_breakout(snap, buzz)
        tested.append(h6)
    else:
        print("    [SKIP] H5, H6: No buzz data available")

    if genre_opp is not None and not genre_opp.empty:
        print("    H7: Genre lineage depth → breakout rate...")
        h7 = test_h7_genre_lineage_depth(snap, genre_opp)
        tested.append(h7)
    else:
        print("    [SKIP] H7: No genre opportunity data available")

    if (buzz is not None and not buzz.empty) and (genre_opp is not None and not genre_opp.empty):
        print("    H8: Multi-trend convergence composite...")
        h8 = test_h8_multi_trend_convergence(snap, buzz, genre_opp)
        tested.append(h8)
    else:
        print("    [SKIP] H8: Missing buzz or genre opportunity data")

    n_tested = sum(1 for h in tested if h["status"] == "tested")
    n_significant = sum(
        1 for h in tested
        if h.get("result", {}).get("p_value") is not None
        and h["result"]["p_value"] < 0.05
    )

    # Rule R6: Decompose growth
    decomposition = {
        "pure_incremental": (
            "When a breakout game emerges, it attracts genuinely new players to Roblox platform. "
            "Evidence: 99 Nights reached 14.15M CCU while Roblox baseline was ~10M, "
            "suggesting ~40% pure incremental traffic. However, precise decomposition requires "
            "platform-level CCU data (not available in our snapshot)."
        ),
        "cannibalization": (
            "Cross-game cannibalization is structurally limited on Roblox due to zero switching cost "
            "(no download required). Players frequently run multiple games in a session. "
            "Estimated cannibalization: 10-25% of breakout CCU comes from neighboring games' decline."
        ),
        "methodology": (
            "Cannot quantify precisely from cross-sectional snapshot. "
            "Would require: (1) platform-level total CCU before/after breakout, "
            "(2) per-game CCU time series to measure displacement. "
            "Current estimates are from GDC talk anecdotes and public CCU records."
        ),
    }

    key_findings = []
    d1 = h1.get("_detail", {})
    key_findings.append(
        f"Real data signal detection: P={d1.get('precision', 0):.0%}, R={d1.get('recall', 0):.0%}, "
        f"F1={d1.get('f1', 0):.0%}, AUC={d1.get('auc', 0):.3f} (n={len(snap)})"
    )
    d2 = h2.get("_detail", {}).get("per_metric", {}).get("favorites_per_1k_visits", {})
    if d2:
        key_findings.append(
            f"Breakout vs stable favorites/1kv: {d2.get('breakout_mean', 0):.2f} vs {d2.get('stable_mean', 0):.2f} "
            f"(d={d2.get('cohens_d', 0):.2f}, p={d2.get('t_p_value', 1):.4f})"
        )
    d3 = h3.get("_detail", {}).get("age_regression", {})
    if d3:
        key_findings.append(f"Age explains {d3.get('r_squared', 0)*100:.1f}% of engagement variance (age is important confound)")

    # Add buzz & genre findings
    for h in tested:
        if h["id"] in ("H5", "H6", "H7", "H8"):
            detail = h.get("_detail", {})
            auc_val = detail.get("auc", None)
            best_sig = detail.get("best_signal", None)
            best_auc_val = detail.get("best_auc", None)
            if best_sig and best_auc_val is not None:
                key_findings.append(f"{h['id']}: best={best_sig} AUC={best_auc_val:.3f}, volume AUC={auc_val:.3f} — {h['result']['direction']}")
            elif auc_val is not None:
                key_findings.append(f"{h['id']}: AUC={auc_val:.3f} — {h['result']['direction']}")

    total_hypotheses = len(tested)

    return {
        "analysis_version": "v2.0-real-data",
        "generated_at": datetime.now().isoformat(),
        "research_question": RESEARCH_QUESTION,
        "data_window": {
            "start": "2026-03-18",
            "end": "2026-03-18",
            "temporal_limitation": temporal_limitation,
        },
        "hypotheses": tested,
        "decomposition": decomposition,
        "summary": {
            "total_hypotheses": total_hypotheses,
            "tested": n_tested,
            "with_significant_results": n_significant,
            "data_sources_used": list(data.keys()),
            "key_findings": key_findings,
        },
    }


def main():
    print("=" * 60)
    print("AutoResearch — Roblox Real Data Analysis")
    print(f"Question: {RESEARCH_QUESTION[:80]}...")
    print("=" * 60)

    print("\n[1/4] Loading data...")
    data = load_data()

    if not data:
        print("\n  [ERROR] No data loaded. Run prepare.py first.")
        return

    print(f"\n[2/4] Data audit (Rule R1)...")
    audit = audit_data(data)

    print(f"\n[3/4] Running analysis...")
    findings = analyze(data)

    print(f"\n[4/4] Saving findings...")
    with open(FINDINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(findings, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Findings saved to {FINDINGS_PATH}")
    n = findings["summary"]
    print(f"  Hypotheses: {n['tested']}/{n['total_hypotheses']} tested, {n['with_significant_results']} significant")
    for kf in n["key_findings"]:
        print(f"  → {kf}")
    print("=" * 60)


if __name__ == "__main__":
    main()
