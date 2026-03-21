# Roblox Early Signal Prediction

**Can we predict Roblox breakout games before they blow up?**

This project builds an early warning system for Roblox breakout games, using two types of observable signals:
1. **Structural**: Mechanic DNA — whether a game's feature combination is rich and novel
2. **Dynamic**: YouTube creator activity — whether upload velocity and creator diversity are accelerating

## Project Goal

Detect potential breakouts **4-8 weeks before** they happen, based on data that's available *before* the CCU spike.

---

## Hypothesis System

### Core Hypotheses (H1–H5): Signal Discovery

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|---------|
| H1 | Platform engagement metrics (CCU, favorites, likes) predict breakouts | ❌ Rejected | AUC 0.428, worse than random |
| H2 | YouTube creator activity acceleration is a **leading** indicator of breakout | ⏳ Pending | Simulated backtest shows 52-day lead; awaiting real timeseries validation |
| H3 | Structural + dynamic signals combined improve precision | ⏳ Partial | Decision matrix 6/6 in backtest, but all on simulated data |
| H4 | YouTube enriched signals quantify creator activity | ✅ Supported | 7 dimensions, AUC 0.608→0.740 |
| H5 | Google Trends search interest velocity distinguishes breakouts | ✅ Weak signal | Mostly synthetic data; needs real Trends validation |

**Key finding**: Platform-internal data (H1) has almost no predictive power → external signals (YouTube/Trends) are the breakthrough.

### Genre Rotation Hypotheses (HR1–HR4): Signal Structure

H4/H5 confirmed YouTube/Trends have signal, but a deeper question: **do breakout signals rotate across genres, or emerge independently?** This determines whether we can use genre-level shortcuts or must monitor every game individually.

| # | Hypothesis | Status | Evidence |
|---|-----------|--------|---------|
| HR1 | Breakout games concentrate in specific mechanic categories | ✅ Supported | χ²=8.50, p=0.037 — breakouts over-index on `meta` mechanics (33% vs 16%), under-index on `core_loop` (38% vs 54%) |
| HR2 | Same-mechanic breakouts cluster in time ("genre waves") | ✅ Supported | Mantel r=0.111, p=0.049 — 18 waves identified (e.g. PvP: TSB→Blade Ball→RiVALS; Horror: Dead Rails→99 Nights; Collection: Bee Swarm→Adopt Me→Pet Sim X) |
| HR3 | Mechanic-similar games share correlated YouTube signals | ❌ Inconclusive | Mantel r=0.056, p=0.069 — creator attention does NOT follow mechanic families in current cross-section |
| HR4 | Google Trends peaks stagger across genres (rotation) | 🟡 Partial | Peak dispersion 18.6d (not significant vs random, p=0.50), but 14/21 genre pairs show lagged cross-correlation |

**Verdict: MIXED** (rotation 2/4, independence 1/4)

- **What rotates**: Breakout *structure* — mechanic categories and temporal waves clearly exist (HR1 ✅, HR2 ✅). Horror wave, PvP wave, Collection wave are real patterns.
- **What doesn't rotate**: *Current* creator/search attention — YouTube signals are game-specific, not genre-spillover (HR3 ❌). Trends show some lag structure but not statistically significant rotation (HR4 🟡).
- **Implication**: Genre-level monitoring helps identify *where* the next breakout might come from, but the actual signal (YouTube acceleration) must still be tracked per-game. **Strategy: genre watchlist + individual game scanner.**

---

## System Architecture

```
Data Collection              Analysis                  Early Warning
──────────────              ────────                  ─────────────
collect_real_data.py        analyze.py                scanner.py
  └→ 74 games, Roblox API    └→ H1-H8 hypothesis       ├→ Layer 1: Mechanic DNA
                                testing                 │   (structural screen, monthly)
collect_daily_snapshot.py   predict_breakout.py        │
  └→ daily CCU/favs/votes     └→ ML predict AUC 0.740  └→ Layer 2: YouTube acceleration
                                                           (dynamic monitor, weekly)
collect_buzz_data.py        mechanic_dna.py
  └→ YouTube + Trends          └→ 53 games DNA          combined_assessment()
     cross-section                                       └→ decision matrix → ACT/ALERT/WATCH

collect_youtube_timeseries.py   analyze_genre_rotation.py
  └→ YouTube weekly timeseries    └→ HR1-HR4: genre rotation
                                     vs independent emergence
```

### Automated Collection (GitHub Actions)

| Workflow | Schedule | What |
|----------|----------|------|
| `collect-daily-snapshot.yml` | Every day 08:43 UTC | Roblox API → daily CCU/engagement snapshot |
| `collect-youtube-weekly.yml` | Every Monday 09:07 UTC | scrapetube → YouTube creator activity signals |

Both auto-commit results and support manual `workflow_dispatch` trigger.

---

## Scanner: Breakout Early Warning

The scanner combines two independent signal layers:

**Layer 1 — Mechanic DNA (structural screen)**
- Encodes each game's feature combination (e.g., `[farming, rng_gacha, trading, tycoon, codes_freebie]`)
- Computes mechanic richness, maturity, and combination novelty
- Primary rule: **≥4 mechanics + novel pair → OR 4.38** for breakout

**Layer 2 — YouTube acceleration (dynamic monitor)**
- Tracks week-over-week upload velocity and unique creator count
- Alerts on: consecutive velocity doublings, >100% acceleration with ≥5 videos/week, or high velocity + creator growth

**Decision matrix** combines DNA tier (STRONG/MODERATE/WATCH/LOW) × YouTube tier (CRITICAL/WARNING/WATCH/NORMAL) → action (ACT/ALERT/WATCH/IGNORE).

### Backtest Results

```
Game                         DNA     YT Alert  Action  Lead   Breakout
Grow a Garden              MODERATE  2025-03-24 ALERT   83d   2025-06-15
Fisch                      STRONG    2024-12-30 ALERT   61d   2025-03-01
DOORS                      STRONG    2022-07-01 ALERT   45d   2022-08-15
Sol's RNG                  STRONG    2024-06-01 ALERT   44d   2024-07-15
Dead Rails                 STRONG    2025-02-17 ALERT   43d   2025-04-01
99 Nights in the Forest    STRONG    2025-12-15 ALERT   36d   2026-01-20

Caught: 6/6 breakouts | Avg lead time: 52 days
```

**⚠️ Caveat**: YouTube timelines in backtest are **simulated** based on typical acceleration patterns. Real validation requires accumulated weekly data (≥3 weeks, in progress).

---

## Running the System

```bash
# Install dependencies
uv sync

# === Data Collection ===
uv run python collect_real_data.py              # One-time Roblox API snapshot
uv run python collect_daily_snapshot.py          # Daily snapshot (idempotent)
uv run python collect_youtube_timeseries.py      # Weekly YouTube signals (idempotent)
uv run python collect_buzz_data.py               # YouTube + Trends cross-section

# === Analysis ===
uv run python prepare.py                         # Data standardization
uv run python analyze.py                         # Statistical hypothesis testing
uv run python analyze_genre_rotation.py          # Genre rotation analysis (HR1-HR4)
uv run python report.py                          # Report & visualization

# === Scanner ===
uv run python scanner.py                         # Scan current + backtest
uv run python scanner.py --backtest              # Backtest only
```

---

## What's Done

**Data infrastructure**
- ✅ 74-game Roblox API collection pipeline
- ✅ Daily snapshot auto-collection (GitHub Actions)
- ✅ YouTube weekly timeseries collector (47 games, W12 collected)
- ✅ GitHub Actions automation (daily + weekly)
- ✅ Idempotent collection with ISO-week dedup

**Analysis & modeling**
- ✅ 8 hypotheses statistical testing framework
- ✅ Genre rotation analysis: 4 hypotheses → mixed verdict (rotation in structure, independence in signals)
- ✅ YouTube enriched signals: 7 dimensions, AUC 0.740
- ✅ Mechanic DNA: 53 games encoded, maturity/novelty scoring
- ✅ Primary rule: ≥4 mechanics + novel pair → OR 4.38

**Early warning system**
- ✅ Two-layer scanner (DNA + YouTube acceleration)
- ✅ 4×4 decision matrix
- ✅ Backtest: 6/6 breakouts caught, avg 52 days lead
- ✅ Real data auto-integration with simulated fallback
- ✅ Fuzzy name matching (87%, 46/53 games)

---

## Known Gaps

| Gap | Nature | When Resolved |
|-----|--------|---------------|
| G1: Only 1 week YouTube timeseries | Waiting | W14 (~2 weeks), acceleration signals activate at ≥3 weeks |
| G2: Leading indicator causality unproven | Waiting | 6-8 weeks of real data for prospective validation |
| G4: False positive rate unknown | Waiting | Need months of scan accumulation |
| G5: Google Trends unreliable | Low priority | Could switch to SerpAPI |
| G6: Daily snapshot only 2 days | Waiting | Auto-collecting daily |
| G7: No automated alert notifications | Can do | Add Actions scanner + Slack/email |

---

## Honest Assessment

**Strengths**:
- Complete pipeline from collection to early warning
- Automation in place — data accumulates on its own
- Structural signal (Mechanic DNA) is grounded in objective feature encoding
- Terminology is specific: every metric has a clear operational definition

**Weaknesses**:
- **Core hypothesis H2 is unvalidated** — the 52-day lead time comes from hand-crafted simulated timeseries, not real observations
- **AUC 0.740 may be overfit** — YouTube enriched signals were tuned on known labels, no out-of-sample test
- **Small sample** — 53 games (~25 breakouts), limited statistical power
- **Selection bias** — game list is hand-curated, not randomly sampled

**Bottom line**: The architecture and pipeline are solid, but **predictive power has not been truly proven yet**. The next 6-8 weeks of real data accumulation are the critical validation window.

---

## Data Sources

| Source | Description | Size |
|--------|-------------|------|
| Roblox Games API v1 | 74 games: CCU, visits, favorites, votes | 56 resolved |
| YouTube (scrapetube) | Weekly: upload velocity, creators, views, acceleration | 47 games/week |
| Google Trends (pytrends) | 12-week search interest slopes | ~1,400 records |
| Mechanic DNA | Hand-coded feature combinations per game | 53 games |
| Breakout ground truth | Curated known breakout events with dates | ~25 games |

## Project Structure

```
roblox_early_signal_prediction/
├── collect_real_data.py              # Roblox API snapshot (74 games)
├── collect_daily_snapshot.py         # Daily time-series collector
├── collect_youtube_timeseries.py     # Weekly YouTube signals collector
├── collect_buzz_data.py              # YouTube + Trends cross-section
├── collect_genre_opportunity.py      # Genre lineage & opportunity scanner
├── mechanic_dna.py                   # Game mechanic DNA encoding
├── scanner.py                        # Breakout early warning scanner
├── prepare.py                        # Data standardization
├── analyze.py                        # Statistical hypothesis testing (H1-H8)
├── analyze_genre_rotation.py         # Genre rotation analysis (HR1-HR4)
├── predict_breakout.py               # ML prediction
├── report.py                         # Report & visualization generator
├── evaluate.py                       # Research quality scorer
├── test_daily_snapshot.py            # Tests (13 tests)
├── .github/workflows/
│   ├── collect-daily-snapshot.yml    # Daily auto-collection
│   └── collect-youtube-weekly.yml    # Weekly auto-collection
├── data/
│   ├── raw/                          # API snapshots, trends, YouTube
│   ├── processed/                    # Standardized CSVs
│   └── timeseries/                   # Time-series data
│       ├── roblox_daily_snapshot.csv
│       ├── youtube_weekly.csv
│       ├── collection_log.json
│       └── youtube_collection_log.json
└── outputs/
    ├── scanner_results.json          # Latest scanner output
    ├── findings.json                 # Statistical results (H1-H8)
    ├── genre_rotation_findings.json  # Genre rotation results (HR1-HR4)
    ├── report.md                     # Research report
    └── figures/                      # Visualizations
```

## Requirements

- Python >= 3.11
- Key dependencies: pandas, numpy, scipy, matplotlib, seaborn, scrapetube
- No API keys required (scrapetube is keyless)

## License

Research project — not intended for production use.
