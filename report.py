"""
report.py — Report generator template (Agent 3 modifies this file)

Converts findings.json into a structured markdown report with visualizations.
Enforces required sections from SKILL.md output contract.

Research question: 在 Roblox 平台历史数据中，中腰部游戏（排名50-200）出现"DAU偏低但D7留存/平均时长显著高于同品类均值"的异常信号后，该品类在随后3-6个月内产生Top 10爆款的概率是多少？该信号的精确率(Precision)和召回率(Recall)分别是多少？
Usage: uv run python report.py
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Try to set CJK fonts; fall back gracefully
try:
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
except Exception:
    pass
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = Path(__file__).parent
PROC_DIR = BASE_DIR / "data" / "processed"
FINDINGS_PATH = BASE_DIR / "outputs" / "findings.json"
REPORT_PATH = BASE_DIR / "outputs" / "report.md"
FIGURES_DIR = BASE_DIR / "outputs" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


def load_findings() -> dict:
    with open(FINDINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_processed_data() -> dict:
    """Load all processed CSVs."""
    data = {}
    if not PROC_DIR.exists():
        return data
    for csv_path in sorted(PROC_DIR.glob("*.csv")):
        name = csv_path.stem
        try:
            df = pd.read_csv(csv_path)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            data[name] = df
        except Exception:
            pass
    return data


# === Report generation ===

def generate_report(findings: dict, data: dict) -> str:
    """Generate structured markdown report enforcing all required sections."""
    hypotheses = findings.get("hypotheses", [])
    summary = findings.get("summary", {})
    data_window = findings.get("data_window", {})
    decomposition = findings.get("decomposition", {})

    n_tested = summary.get("tested", 0)
    n_total = summary.get("total_hypotheses", 0)
    n_significant = summary.get("with_significant_results", 0)

    report = f"""# Research Report: {{在 Roblox 平台历史数据中，中腰部游戏（排名50-200）出现"DAU偏低但D7留存/平均时长显著高于同品类均值"的异常信号后，该品类在随后3-6个月内产生Top 10爆款的概率是多少？该信号的精确率(Precision)和召回率(Recall)分别是多少？}}

> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
> **Version**: {findings.get('analysis_version', 'unknown')}
> **Data sources**: {len(summary.get('data_sources_used', []))}
> **Hypotheses**: {n_tested}/{n_total} tested, {n_significant} significant

---

## 1. Executive Summary

"""
    # Per-hypothesis summary bullets
    for h in hypotheses:
        status = h.get("status", "pending")
        conclusion = h.get("conclusion", "Analysis pending")
        if status == "tested":
            report += f"- ✅ **{h.get('hypothesis', 'Unknown')}**: {conclusion}\n"
        else:
            report += f"- ⏳ **{h.get('hypothesis', 'Unknown')}**: {status}\n"

    # Key findings
    key_findings = summary.get("key_findings", [])
    if key_findings:
        report += "\n### Key Findings\n\n"
        for kf in key_findings:
            report += f"- {kf}\n"

    report += """
---

## 2. Core Judgments

| Judgment | Confidence | Evidence |
|---|---|---|
| TODO: Add core judgments with confidence levels | | |

---

## 3. Research Methods & Data

### Data Matrix

| Source | Description | Frequency | Period |
|---|---|---|---|
"""
    for src in summary.get("data_sources_used", []):
        report += f"| {src} | TODO | TODO | TODO |\n"

    report += f"""
### Data Window Limitations (Rule R2)

{data_window.get('temporal_limitation', 'Not yet assessed')}

- **Data start**: {data_window.get('start', 'Unknown')}
- **Data end**: {data_window.get('end', 'Unknown')}

---

## 4. Detailed Analysis

"""
    for i, h in enumerate(hypotheses, 1):
        report += f"### 4.{i} {h.get('hypothesis', 'Unknown')}\n\n"
        report += f"**Method**: {h.get('method', 'N/A')}\n\n"

        # Result
        result = h.get("result", {})
        if result.get("p_value") is not None:
            report += f"**Result**: direction={result.get('direction')}, "
            report += f"effect_size={result.get('effect_size')}, "
            report += f"p={result.get('p_value')}, "
            report += f"CI={result.get('confidence_interval')}, "
            report += f"n={result.get('sample_size')}\n\n"

        # Confounders (Rule R4)
        confounders = h.get("confounders", [])
        if confounders:
            report += "**Confounders**:\n\n"
            report += "| Confounder | Direction | Controlled | Method |\n|---|---|---|---|\n"
            for c in confounders:
                report += f"| {c.get('name', 'Unknown')} | {c.get('direction', '?')} | {'Yes' if c.get('controlled') else 'No'} | {c.get('method', 'N/A')} |\n"
            report += "\n"

        # Clean window (Rule R5)
        cw = h.get("clean_window", {})
        if cw.get("start"):
            report += f"**Clean Window**: {cw['start']} to {cw.get('end', '?')} — {cw.get('justification', '')}\n\n"

        # Temporal limitation (Rule R2)
        tl = h.get("temporal_limitation", "")
        if tl:
            report += f"**Temporal Limitation**: {tl}\n\n"

        report += f"**Conclusion**: {h.get('conclusion', 'Analysis pending')}\n\n"

    # Decomposition (Rule R6)
    report += f"""---

## 5. Growth Decomposition (Rule R6)

| Component | Estimate | Methodology |
|---|---|---|
| Pure incremental | {decomposition.get('pure_incremental', 'Not quantified')} | {decomposition.get('methodology', 'TODO')} |
| Cannibalization | {decomposition.get('cannibalization', 'Not quantified')} | |

---

## 6. Visualizations

"""
    # Check for generated figures
    for fig_path in sorted(FIGURES_DIR.glob("*.png")):
        rel_path = fig_path.relative_to(BASE_DIR)
        report += f"### {fig_path.stem}\n\n![{fig_path.stem}]({rel_path})\n\n"

    if not list(FIGURES_DIR.glob("*.png")):
        report += "_No visualizations generated yet. Add plotting code to report.py._\n\n"

    report += """---

## 7. Limitations & Confounders (Rule R4)

### Known Confounders

| Confounder | Impact Direction | Control Method |
|---|---|---|
| TODO: List all confounders | | |

### Data Limitations

1. TODO: List data limitations

---

## 8. Actionable Recommendations

### Decision Framework

| Scenario | Probability | Impact | Recommended Action |
|---|---|---|---|
| TODO | | | |

---

## 9. Forward-Looking Judgments

| Time Horizon | Prediction | Confidence | Key Validation Metric |
|---|---|---|---|
| TODO | | | |

---

*Generated by AutoResearch autonomous analysis system*
"""
    return report


def main():
    print("=" * 60)
    print("AutoResearch — Report Generator")
    print("=" * 60)

    print("\nLoading findings...")
    findings = load_findings()

    print("Loading processed data...")
    data = load_processed_data()

    print("\nGenerating report...")
    report_text = generate_report(findings, data)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n✓ Report saved to {REPORT_PATH}")
    print(f"  Length: {len(report_text)} chars")
    print("=" * 60)


if __name__ == "__main__":
    main()
