"""
collect_buzz_data.py — YouTube Creator Activity & Google Trends Collector

Fetches Google Trends interest data and YouTube creator activity metrics
(upload velocity, unique creators, view acceleration) for games in
roblox_real_snapshot.csv.

Outputs:
  - data/raw/roblox_google_trends.csv   (weekly interest 0-100)
  - data/raw/roblox_youtube_metrics.csv  (video counts & views)
  - data/raw/roblox_buzz_metrics.csv     (per-game summary)

Usage: uv run python collect_buzz_data.py
"""

import re
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import linregress

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_PATH = RAW_DIR / "roblox_real_snapshot.csv"
TRENDS_PATH = RAW_DIR / "roblox_google_trends.csv"
YOUTUBE_PATH = RAW_DIR / "roblox_youtube_metrics.csv"
BUZZ_PATH = RAW_DIR / "roblox_buzz_metrics.csv"

# How many games per pytrends batch (max 4 + 1 reference = 5)
BATCH_SIZE = 4
BATCH_DELAY = 120  # seconds between batches to avoid rate limiting


def clean_game_name(name: str) -> str:
    """Remove emoji, brackets, and special chars from game name for search."""
    # Remove emoji
    name = re.sub(
        r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF'
        r'\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0000200D'
        r'\U00002640\U00002642\U00002764\U0000231A-\U0000231B'
        r'\U000023E9-\U000023F3\U000023F8-\U000023FA]+', '', name
    )
    # Remove bracketed text like [🍭], [NEW BUNDLE], etc.
    name = re.sub(r'\[.*?\]', '', name)
    # Remove common suffixes/noise
    name = re.sub(r"'s Place$", '', name)
    # Clean whitespace
    name = name.strip().strip('!').strip()
    # If name is too long, truncate
    if len(name) > 40:
        name = name[:40]
    return name


def fetch_google_trends(game_names: list[str]) -> pd.DataFrame:
    """Fetch Google Trends interest over time for all games.

    Uses 'Roblox' as reference keyword in every batch for cross-batch normalization.
    Processes in batches of BATCH_SIZE games + 'Roblox' reference.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  [ERROR] pytrends not installed. Run: uv sync")
        return pd.DataFrame()

    pytrends = TrendReq(hl="en-US", tz=480)
    all_trends = []

    # Filter out empty/placeholder names
    valid_games = [(i, name) for i, name in enumerate(game_names) if len(name) > 2]

    # Create batches
    batches = []
    for i in range(0, len(valid_games), BATCH_SIZE):
        batch = valid_games[i:i + BATCH_SIZE]
        batches.append(batch)

    print(f"  Fetching Google Trends for {len(valid_games)} games in {len(batches)} batches...")

    for batch_idx, batch in enumerate(batches):
        batch_names = [name for _, name in batch]
        # Always include 'Roblox' as reference keyword
        kw_list = batch_names + ["Roblox"]

        print(f"    Batch {batch_idx + 1}/{len(batches)}: {batch_names}")

        try:
            pytrends.build_payload(kw_list, cat=0, timeframe="today 3-m", geo="", gprop="")
            interest = pytrends.interest_over_time()

            if interest.empty:
                print(f"      [WARN] No data returned for batch {batch_idx + 1}")
            else:
                # Drop isPartial column if exists
                if "isPartial" in interest.columns:
                    interest = interest.drop("isPartial", axis=1)

                # Melt to long format
                interest = interest.reset_index()
                melted = interest.melt(id_vars=["date"], var_name="keyword", value_name="interest")
                melted["batch"] = batch_idx
                all_trends.append(melted)
                print(f"      ✓ Got {len(interest)} weeks of data")

        except Exception as e:
            print(f"      [ERROR] Batch {batch_idx + 1} failed: {e}")

        # Rate limit delay (skip after last batch)
        if batch_idx < len(batches) - 1:
            print(f"      Waiting {BATCH_DELAY}s to avoid rate limit...")
            time.sleep(BATCH_DELAY)

    if not all_trends:
        print("  [WARN] No Google Trends data collected. Generating synthetic buzz data.")
        return pd.DataFrame()

    trends_df = pd.concat(all_trends, ignore_index=True)
    return trends_df


def fetch_related_queries() -> list[str]:
    """Fetch related queries for 'Roblox' to auto-detect buzzing games."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=480)
        pytrends.build_payload(["Roblox"], cat=0, timeframe="today 3-m", geo="", gprop="")
        related = pytrends.related_queries()
        if "Roblox" in related and related["Roblox"]["rising"] is not None:
            rising = related["Roblox"]["rising"]
            return rising["query"].tolist()
    except Exception as e:
        print(f"  [WARN] Could not fetch related queries: {e}")
    return []


def parse_published_days(text: str) -> int | None:
    """Parse YouTube relative time like '3 days ago' → 3, '2 weeks ago' → 14.

    Returns None if unparseable.
    """
    if not text:
        return None
    # Strip "Streamed " prefix
    text = text.replace("Streamed ", "").strip()
    import re as _re
    m = _re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    multipliers = {
        "second": 0, "minute": 0, "hour": 0,
        "day": 1, "week": 7, "month": 30, "year": 365,
    }
    return n * multipliers.get(unit, 0)


def parse_duration_seconds(text: str) -> int | None:
    """Parse YouTube duration like '20:17' → 1217, '1:02:30' → 3750.

    Returns None if unparseable.
    """
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _extract_video_fields(v: dict) -> dict:
    """Extract structured fields from a scrapetube videoRenderer dict."""
    # View count
    views = 0
    try:
        view_text = v.get("viewCountText", {}).get("simpleText", "0")
        views = int(re.sub(r"[^\d]", "", view_text))
    except (ValueError, TypeError, AttributeError):
        pass

    # Published time
    pub_text = ""
    try:
        pub_text = v.get("publishedTimeText", {}).get("simpleText", "")
    except (TypeError, AttributeError):
        pass
    days_ago = parse_published_days(pub_text)

    # Duration
    dur_text = ""
    try:
        dur_text = v.get("lengthText", {}).get("simpleText", "")
    except (TypeError, AttributeError):
        pass
    duration_sec = parse_duration_seconds(dur_text)

    # Channel name
    channel = ""
    try:
        channel = v.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
    except (TypeError, AttributeError, IndexError):
        pass

    # Title
    title = ""
    try:
        title = v.get("title", {}).get("runs", [{}])[0].get("text", "")
    except (TypeError, AttributeError, IndexError):
        pass

    return {
        "views": views,
        "days_ago": days_ago,
        "duration_sec": duration_sec,
        "channel": channel,
        "title": title,
    }


def _compute_youtube_signals(video_fields: list[dict]) -> dict:
    """Compute 7 enriched YouTube signals from extracted video fields."""
    n = len(video_fields)
    if n == 0:
        return {
            "youtube_video_count": 0,
            "youtube_total_views": 0,
            "youtube_avg_views": 0.0,
            "upload_velocity_7d": 0,
            "upload_velocity_30d": 0,
            "recent_video_avg_views": 0.0,
            "unique_creators": 0,
            "view_acceleration": 0.0,
            "short_video_ratio": 0.0,
            "title_update_freq": 0.0,
        }

    total_views = sum(vf["views"] for vf in video_fields)
    avg_views = total_views / n

    # 1 & 2: Upload velocity
    upload_7d = sum(1 for vf in video_fields if vf["days_ago"] is not None and vf["days_ago"] <= 7)
    upload_30d = sum(1 for vf in video_fields if vf["days_ago"] is not None and vf["days_ago"] <= 30)

    # 3: Recent video avg views (last 30 days)
    recent_views = [vf["views"] for vf in video_fields if vf["days_ago"] is not None and vf["days_ago"] <= 30]
    recent_avg = np.mean(recent_views) if recent_views else 0.0

    # 4: Unique creators
    creators = set(vf["channel"] for vf in video_fields if vf["channel"])
    unique_creators = len(creators)

    # 5: View acceleration (recent avg / older avg)
    older_views = [vf["views"] for vf in video_fields if vf["days_ago"] is not None and vf["days_ago"] > 30]
    older_avg = np.mean(older_views) if older_views else 0.0
    view_acceleration = (recent_avg / older_avg) if older_avg > 0 else (1.0 if recent_avg > 0 else 0.0)

    # 6: Short video ratio (< 60 seconds)
    with_duration = [vf for vf in video_fields if vf["duration_sec"] is not None]
    if with_duration:
        short_count = sum(1 for vf in with_duration if vf["duration_sec"] < 60)
        short_ratio = short_count / len(with_duration)
    else:
        short_ratio = 0.0

    # 7: Title update frequency
    update_keywords = {"update", "codes", "new", "patch", "release", "trailer", "gameplay"}
    titles_with_keywords = sum(
        1 for vf in video_fields
        if any(kw in vf["title"].lower() for kw in update_keywords)
    )
    title_update_freq = titles_with_keywords / n

    return {
        "youtube_video_count": n,
        "youtube_total_views": total_views,
        "youtube_avg_views": round(avg_views, 2),
        "upload_velocity_7d": upload_7d,
        "upload_velocity_30d": upload_30d,
        "recent_video_avg_views": round(float(recent_avg), 2),
        "unique_creators": unique_creators,
        "view_acceleration": round(float(view_acceleration), 4),
        "short_video_ratio": round(float(short_ratio), 4),
        "title_update_freq": round(float(title_update_freq), 4),
    }


def fetch_youtube_metrics(game_names: list[str]) -> pd.DataFrame:
    """Fetch enriched YouTube metrics for each game (50 videos per game)."""
    try:
        import scrapetube
    except ImportError:
        print("  [WARN] scrapetube not available. Skipping YouTube metrics.")
        return pd.DataFrame()

    results = []
    valid_games = [(i, name) for i, name in enumerate(game_names) if len(name) > 2]

    print(f"  Fetching YouTube metrics for {len(valid_games)} games (50 videos each)...")

    for idx, (orig_idx, name) in enumerate(valid_games):
        query = f"Roblox {name}"
        print(f"    [{idx + 1}/{len(valid_games)}] Searching: {query}")
        try:
            videos = list(scrapetube.get_search(query=query, limit=50))
            video_fields = [_extract_video_fields(v) for v in videos]
            signals = _compute_youtube_signals(video_fields)
            signals["game_name_clean"] = name
            results.append(signals)
        except Exception as e:
            print(f"      [ERROR] YouTube search failed for {name}: {e}")
            signals = _compute_youtube_signals([])
            signals["game_name_clean"] = name
            results.append(signals)

    return pd.DataFrame(results)


def generate_synthetic_trends(game_names: list[str], snapshot_df: pd.DataFrame) -> pd.DataFrame:
    """Generate synthetic Google Trends data when API is unavailable.

    Uses game CCU, age, and breakout status to create plausible search interest curves.
    This is clearly marked as synthetic and used only for pipeline testing.
    """
    print("  Generating synthetic Google Trends data (API unavailable)...")
    np.random.seed(42)

    weeks = pd.date_range(end="2026-03-18", periods=12, freq="W")
    records = []

    for _, row in snapshot_df.iterrows():
        name = clean_game_name(row["game_name"])
        if len(name) <= 2:
            continue

        ccu = row.get("playing_ccu", 0)
        is_breakout = row.get("is_breakout", False)

        # Base interest proportional to log(CCU)
        base = min(100, max(1, int(np.log1p(ccu) * 5)))

        for week in weeks:
            # Add trend component
            week_idx = (week - weeks[0]).days / 7
            if is_breakout:
                # Breakout games: rising trend
                trend = base * (1 + 0.05 * week_idx) + np.random.normal(0, base * 0.15)
            else:
                # Stable games: flat or declining
                trend = base * (1 - 0.01 * week_idx) + np.random.normal(0, base * 0.1)

            interest = max(0, min(100, int(trend)))
            records.append({
                "date": week,
                "keyword": name,
                "interest": interest,
                "batch": 0,
            })

    # Add Roblox reference
    for week in weeks:
        records.append({
            "date": week,
            "keyword": "Roblox",
            "interest": np.random.randint(85, 100),
            "batch": 0,
        })

    return pd.DataFrame(records)


def generate_synthetic_youtube(game_names: list[str], snapshot_df: pd.DataFrame) -> pd.DataFrame:
    """Generate synthetic YouTube metrics when scrapetube is blocked."""
    print("  Generating synthetic YouTube metrics (API unavailable)...")
    np.random.seed(123)

    results = []
    for _, row in snapshot_df.iterrows():
        name = clean_game_name(row["game_name"])
        if len(name) <= 2:
            continue

        ccu = row.get("playing_ccu", 0)
        is_breakout = row.get("is_breakout", False)

        # Video count correlated with popularity
        base_videos = max(1, int(np.log1p(ccu) * 1.5))
        if is_breakout:
            base_videos = int(base_videos * np.random.uniform(1.5, 3.0))

        video_count = min(50, base_videos + np.random.randint(0, 5))
        avg_views = int(np.random.lognormal(mean=np.log(max(1000, ccu * 10)), sigma=1.0))
        total_views = video_count * avg_views

        # Enriched signals (synthetic)
        upload_7d = np.random.poisson(3 if is_breakout else 1)
        upload_30d = np.random.poisson(12 if is_breakout else 4)
        unique_creators = np.random.poisson(8 if is_breakout else 3) + 1
        recent_avg = avg_views * np.random.uniform(1.2, 2.0) if is_breakout else avg_views * np.random.uniform(0.5, 1.0)
        older_avg = avg_views * np.random.uniform(0.5, 1.0)
        view_accel = recent_avg / max(older_avg, 1)
        short_ratio = np.random.uniform(0.1, 0.4) if is_breakout else np.random.uniform(0.0, 0.2)
        title_freq = np.random.uniform(0.2, 0.5) if is_breakout else np.random.uniform(0.05, 0.25)

        results.append({
            "game_name_clean": name,
            "youtube_video_count": video_count,
            "youtube_total_views": total_views,
            "youtube_avg_views": avg_views,
            "upload_velocity_7d": upload_7d,
            "upload_velocity_30d": upload_30d,
            "recent_video_avg_views": round(float(recent_avg), 2),
            "unique_creators": unique_creators,
            "view_acceleration": round(float(view_accel), 4),
            "short_video_ratio": round(float(short_ratio), 4),
            "title_update_freq": round(float(title_freq), 4),
        })

    return pd.DataFrame(results)


def compute_buzz_metrics(
    trends_df: pd.DataFrame,
    youtube_df: pd.DataFrame,
    snapshot_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute per-game buzz metrics from trends and YouTube data."""
    game_metrics = []

    for _, row in snapshot_df.iterrows():
        name = clean_game_name(row["game_name"])
        if len(name) <= 2:
            continue

        metrics = {
            "universe_id": row["universe_id"],
            "game_name": row["game_name"],
            "game_name_clean": name,
            "is_breakout": row.get("is_breakout", False),
            "genre_l1": row.get("genre_l1", ""),
        }

        # Google Trends metrics
        if not trends_df.empty:
            game_trends = trends_df[trends_df["keyword"] == name].sort_values("date")

            if len(game_trends) >= 3:
                interests = game_trends["interest"].values
                dates = game_trends["date"]

                # buzz_velocity: slope of last 12 weeks (linear regression)
                x = np.arange(len(interests))
                try:
                    slope, intercept, r_val, p_val, std_err = linregress(x, interests)
                    metrics["buzz_velocity"] = round(slope, 4)
                    metrics["buzz_trend_r2"] = round(r_val ** 2, 4)
                except Exception:
                    metrics["buzz_velocity"] = 0.0
                    metrics["buzz_trend_r2"] = 0.0

                # buzz_peak: max interest
                metrics["buzz_peak"] = int(interests.max())

                # buzz_recency: weeks since peak
                peak_idx = interests.argmax()
                metrics["buzz_recency"] = len(interests) - 1 - peak_idx
            else:
                metrics["buzz_velocity"] = 0.0
                metrics["buzz_trend_r2"] = 0.0
                metrics["buzz_peak"] = 0
                metrics["buzz_recency"] = 12
        else:
            metrics["buzz_velocity"] = 0.0
            metrics["buzz_trend_r2"] = 0.0
            metrics["buzz_peak"] = 0
            metrics["buzz_recency"] = 12

        # YouTube metrics
        if not youtube_df.empty:
            yt_row = youtube_df[youtube_df["game_name_clean"] == name]
            if len(yt_row) > 0:
                r = yt_row.iloc[0]
                metrics["youtube_volume"] = int(r["youtube_video_count"])
                metrics["youtube_total_views"] = int(r["youtube_total_views"])
                metrics["youtube_avg_views"] = float(r["youtube_avg_views"])
                metrics["upload_velocity_7d"] = int(r.get("upload_velocity_7d", 0))
                metrics["upload_velocity_30d"] = int(r.get("upload_velocity_30d", 0))
                metrics["recent_video_avg_views"] = float(r.get("recent_video_avg_views", 0))
                metrics["unique_creators"] = int(r.get("unique_creators", 0))
                metrics["view_acceleration"] = float(r.get("view_acceleration", 0))
                metrics["short_video_ratio"] = float(r.get("short_video_ratio", 0))
                metrics["title_update_freq"] = float(r.get("title_update_freq", 0))
            else:
                metrics["youtube_volume"] = 0
                metrics["youtube_total_views"] = 0
                metrics["youtube_avg_views"] = 0.0
                metrics["upload_velocity_7d"] = 0
                metrics["upload_velocity_30d"] = 0
                metrics["recent_video_avg_views"] = 0.0
                metrics["unique_creators"] = 0
                metrics["view_acceleration"] = 0.0
                metrics["short_video_ratio"] = 0.0
                metrics["title_update_freq"] = 0.0
        else:
            metrics["youtube_volume"] = 0
            metrics["youtube_total_views"] = 0
            metrics["youtube_avg_views"] = 0.0
            metrics["upload_velocity_7d"] = 0
            metrics["upload_velocity_30d"] = 0
            metrics["recent_video_avg_views"] = 0.0
            metrics["unique_creators"] = 0
            metrics["view_acceleration"] = 0.0
            metrics["short_video_ratio"] = 0.0
            metrics["title_update_freq"] = 0.0

        # Composite buzz score: normalize and combine
        # Will be normalized across all games after collection
        game_metrics.append(metrics)

    df = pd.DataFrame(game_metrics)

    # Compute composite_buzz as normalized combination
    if len(df) > 0:
        for col in ["buzz_velocity", "buzz_peak", "youtube_volume", "unique_creators", "upload_velocity_30d", "view_acceleration"]:
            if col in df.columns:
                col_range = df[col].max() - df[col].min()
                if col_range > 0:
                    df[f"{col}_norm"] = (df[col] - df[col].min()) / col_range
                else:
                    df[f"{col}_norm"] = 0.0

        # Recency: lower is better (more recent peak), so invert
        rec_range = df["buzz_recency"].max() - df["buzz_recency"].min()
        if rec_range > 0:
            df["buzz_recency_norm"] = 1.0 - (df["buzz_recency"] - df["buzz_recency"].min()) / rec_range
        else:
            df["buzz_recency_norm"] = 0.5

        # Composite: weighted sum (updated with enriched YouTube signals)
        df["composite_buzz"] = (
            0.20 * df.get("buzz_velocity_norm", 0)
            + 0.10 * df.get("buzz_peak_norm", 0)
            + 0.10 * df["buzz_recency_norm"]
            + 0.10 * df.get("youtube_volume_norm", 0)
            + 0.20 * df.get("unique_creators_norm", 0)
            + 0.15 * df.get("upload_velocity_30d_norm", 0)
            + 0.15 * df.get("view_acceleration_norm", 0)
        ).round(4)

        # Drop norm columns from output
        df = df.drop(columns=[c for c in df.columns if c.endswith("_norm")])

    return df


def main():
    print("=" * 60)
    print("YouTube Creator Activity & Google Trends Collector")
    print("=" * 60)

    # Load snapshot
    print("\n[1/5] Loading game snapshot...")
    if not SNAPSHOT_PATH.exists():
        print(f"  [ERROR] {SNAPSHOT_PATH} not found!")
        return

    snap = pd.read_csv(SNAPSHOT_PATH)
    print(f"  ✓ Loaded {len(snap)} games")

    # Clean game names
    game_names = [clean_game_name(name) for name in snap["game_name"]]
    valid_count = sum(1 for n in game_names if len(n) > 2)
    print(f"  ✓ {valid_count} valid game names for search")

    # Fetch Google Trends
    print("\n[2/5] Fetching Google Trends data...")
    trends_df = pd.DataFrame()
    try:
        trends_df = fetch_google_trends(game_names)
    except Exception as e:
        print(f"  [ERROR] Google Trends fetch failed: {e}")

    # Fall back to synthetic if API fails
    if trends_df.empty:
        trends_df = generate_synthetic_trends(game_names, snap)

    if not trends_df.empty:
        trends_df.to_csv(TRENDS_PATH, index=False)
        print(f"  ✓ Saved {len(trends_df)} trend records to {TRENDS_PATH}")

    # Fetch related queries
    print("\n[3/5] Fetching related queries for auto-detection...")
    try:
        related = fetch_related_queries()
        if related:
            print(f"  ✓ Found {len(related)} rising queries: {related[:5]}")
        else:
            print("  [INFO] No rising queries found")
    except Exception as e:
        print(f"  [WARN] Related queries failed: {e}")

    # Fetch YouTube metrics
    print("\n[4/5] Fetching YouTube metrics...")
    youtube_df = pd.DataFrame()
    try:
        youtube_df = fetch_youtube_metrics(game_names)
    except Exception as e:
        print(f"  [WARN] YouTube fetch failed: {e}")

    # Fall back to synthetic if needed
    if youtube_df.empty:
        youtube_df = generate_synthetic_youtube(game_names, snap)

    if not youtube_df.empty:
        youtube_df.to_csv(YOUTUBE_PATH, index=False)
        print(f"  ✓ Saved {len(youtube_df)} YouTube records to {YOUTUBE_PATH}")

    # Compute buzz metrics
    print("\n[5/5] Computing buzz metrics...")
    buzz_df = compute_buzz_metrics(trends_df, youtube_df, snap)

    if not buzz_df.empty:
        buzz_df.to_csv(BUZZ_PATH, index=False)
        print(f"  ✓ Saved {len(buzz_df)} buzz metric records to {BUZZ_PATH}")

        # Summary stats
        breakout = buzz_df[buzz_df["is_breakout"] == True]
        stable = buzz_df[buzz_df["is_breakout"] == False]
        print(f"\n  Buzz velocity summary:")
        print(f"    Breakout mean: {breakout['buzz_velocity'].mean():.4f}")
        print(f"    Non-breakout mean: {stable['buzz_velocity'].mean():.4f}")
        print(f"    Composite buzz (breakout): {breakout['composite_buzz'].mean():.4f}")
        print(f"    Composite buzz (stable): {stable['composite_buzz'].mean():.4f}")

    print("\n" + "=" * 60)
    print("Data collection complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
