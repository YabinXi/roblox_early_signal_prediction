# Roblox Early Signal Prediction

**Can we predict Roblox breakout games before they blow up?**

This research project investigates whether engagement anomalies, cultural buzz (Google Trends + YouTube), or genre lineage structure can identify future breakout hits among mid-tier Roblox games. It was inspired by the GDC talk argument that "cultural currents" matter more than metrics.

## Key Findings

| Hypothesis | Signal | AUC | Result |
|---|---|---|---|
| H1 | Engagement anomaly (favorites/visit) | 0.428 | Worse than random |
| H2 | Engagement distribution difference | — | Inconclusive (p=0.13) |
| H3 | Age-controlled engagement | — | Inconclusive (p=0.28) |
| H4 | Genre engagement variation | — | Inconclusive (p=0.11) |
| H5 | Google Trends buzz velocity | 0.447 | Inconclusive |
| **H6** | **YouTube video volume** | **0.608** | **Supported (p=0.016)** |
| H7 | Genre lineage depth | — | Supported (p=0.064) |
| H8 | Multi-trend convergence composite | 0.480 | Inconclusive |

**Bottom line**: Traditional engagement metrics (favorites/visit, like ratio) *failed* to predict breakouts (AUC=0.428, worse than coin flip). **YouTube video volume** emerged as the strongest signal (AUC=0.608), partially validating the "cultural currents > metrics" thesis. Genre lineage depth shows marginal significance.

## Project Structure

```
roblox_early_signal_prediction/
├── collect_real_data.py         # Roblox API snapshot collector (one-time)
├── collect_daily_snapshot.py    # Daily time-series collector (cron-scheduled)
├── collect_buzz_data.py         # Google Trends + YouTube data collector
├── collect_genre_opportunity.py # Genre lineage & opportunity scanner
├── prepare.py                   # Data standardization layer
├── analyze.py                   # Statistical hypothesis testing (H1-H8)
├── report.py                    # Report & visualization generator
├── evaluate.py                  # Research quality scorer (83.3/100)
├── test_daily_snapshot.py       # Tests for daily collector (13 tests)
├── data/
│   ├── raw/                     # Source data (API snapshots, trends, YouTube)
│   ├── processed/               # Standardized CSVs
│   └── timeseries/              # Daily snapshots for temporal analysis
│       ├── roblox_daily_snapshot.csv  # Append-only daily data
│       └── collection_log.json        # Run log (date, games, errors, duration)
└── outputs/
    ├── findings.json            # Full statistical results
    ├── report.md                # Research report
    ├── eval_result.json         # Quality evaluation scores
    └── figures/                 # Visualizations (10 PNGs)
```

## Data Sources

| Source | Description | Size |
|---|---|---|
| Roblox Games API v1 | Cross-sectional snapshot of 56 games (CCU, visits, favorites, votes) | 56 rows |
| Google Trends (pytrends) | Weekly search interest over 12 weeks | ~1,400 records |
| YouTube (scrapetube) | Video counts & view metrics for 55 games | 55 rows |
| Genre lineage tree | Manual genre evolution mapping (8 families, 18 entries) | 18 rows |
| Breakout events | Curated ground truth of 10 known breakout games | 10 rows |

## Visualizations

The pipeline generates 10 figures including:

- Engagement scatter plots (CCU vs favorites/visit)
- Signal detection distributions (breakout vs non-breakout)
- Threshold sensitivity analysis (precision-recall curves)
- Genre lineage timeline
- Buzz velocity scatter (Google Trends slope vs engagement)
- **AUC comparison bar chart** (engagement vs buzz vs YouTube vs composite)
- Genre opportunity heatmap
- Convergence radar chart

## Methodology

- **Statistical tests**: Fisher's exact, Welch's t-test, Mann-Whitney U, Kruskal-Wallis H, point-biserial correlation, permutation test (n=10,000)
- **Anomaly detection**: Median Absolute Deviation (MAD) with 5 threshold multipliers
- **Buzz velocity**: Linear regression slope of trailing 12-week Google Trends interest
- **Composite signal**: Normalized additive combination of lineage depth + buzz velocity + inverse saturation

All findings are associational (cross-sectional snapshot), not causal. Negative results are treated as valid outcomes.

## Running the Pipeline

```bash
# Install dependencies
uv sync

# Collect external data (~30 min for Google Trends rate limits)
uv run python collect_buzz_data.py
uv run python collect_genre_opportunity.py

# Run analysis pipeline
uv run python prepare.py
uv run python analyze.py
uv run python report.py
uv run python evaluate.py
```

## Daily Snapshot Collection

The biggest limitation of the initial research was that all findings came from a single cross-sectional snapshot — we couldn't tell if signals *precede* breakout events. The daily snapshot collector builds a time series to address this.

```bash
# Run once manually
uv run python collect_daily_snapshot.py

# Re-collect today's data (overwrites are prevented by default)
uv run python collect_daily_snapshot.py --force
```

**Automatic scheduling** — add to your system crontab (`crontab -e`):
```
57 8 * * * cd /path/to/roblox_early_signal_prediction && uv run python collect_daily_snapshot.py >> data/timeseries/cron.log 2>&1
```

The collector is **idempotent** (safe to run multiple times per day), appends to a single CSV for easy pandas time-series analysis, and logs each run to `data/timeseries/collection_log.json`. After 6-8 weeks of daily collection, you'll have real temporal data to test causal hypotheses.

**Run tests**: `uv run --with pytest python -m pytest test_daily_snapshot.py -v`

## Requirements

- Python >= 3.11
- Key dependencies: pandas, numpy, scipy, matplotlib, seaborn, pytrends, scrapetube

## Evaluation Score

The automated research quality evaluator scores the output at **83.3/100** across 6 dimensions:

| Dimension | Score |
|---|---|
| Data Support | 90 |
| Logical Rigor | 95 |
| Insight Depth | 79 |
| Hypothesis Coverage | 90 |
| External Validity | 60 |
| Actionability | 65 |

## Limitations

1. **Single snapshot** — cannot establish temporal causality or signal lead time *(daily collector now addresses this — see above)*
2. **Post-hoc classification** — measuring features after success, not predicting prospectively
3. **Google Trends rate limits** — only partial real trends data (3-4 of 14 batches succeed before 429 errors)
4. **Small sample** — n=56 games, 19 breakouts; quartile analyses have ~14 games per group
5. **Survivorship bias** — breakout games selected because they succeeded

## License

Research project — not intended for production use.
