"""
evaluate.py — Heuristic + LLM scorer (read-only, never modified by any agent)

6-dimension weighted scoring with enhanced checks for research integrity:
- Clean window methodology detection (+15 logical_rigor)
- Temporal confounder awareness (+12 logical_rigor)
- Penalty: pre/post without confounder discussion (-15 logical_rigor)
- Penalty: excessive hedging language (-10 actionability)
- Incremental vs cannibalization detection (+10 hypothesis_coverage)
- Data window limitation declaration (+8 logical_rigor)
- Domain keywords are configurable via DOMAIN_KEYWORDS

Usage: uv run python evaluate.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPORT_PATH = BASE_DIR / "outputs" / "report.md"
FINDINGS_PATH = BASE_DIR / "outputs" / "findings.json"
SNAPSHOT_PATH = BASE_DIR / "data" / "data_snapshot.json"
EVAL_RESULT_PATH = BASE_DIR / "outputs" / "eval_result.json"

# === Configurable domain keywords ===
# Replace these with domain-specific terms for your research area.
DOMAIN_KEYWORDS = {
    "industry": [r"Roblox", r"UGC", r"平台", r"品类", r"genre", r"category", r"爆款", r"breakout"],
    "behavior": [r"留存", r"retention", r"D7", r"D30", r"engagement", r"CCU", r"DAU", r"session", r"时长"],
    "lifecycle": [r"生命周期", r"lifecycle", r"衰减", r"蜜月期", r"honeymoon", r"trend", r"signal"],
    "external": [r"Steam", r"mobile", r"cross.platform", r"generalizab", r"外部", r"benchmark"],
}

# === Scoring dimensions ===
DIMENSIONS = {
    "data_support": {
        "weight": 0.25,
        "name": "数据支撑度",
        "description": "Data sources, statistical tests, sample sizes",
    },
    "logical_rigor": {
        "weight": 0.20,
        "name": "逻辑严谨性",
        "description": "Causal inference, confounders, counterfactuals, clean window",
    },
    "insight_depth": {
        "weight": 0.20,
        "name": "洞察深度",
        "description": "Beyond descriptive stats; industry logic, behavior",
    },
    "hypothesis_coverage": {
        "weight": 0.15,
        "name": "假设覆盖度",
        "description": "Systematic hypothesis enumeration and exclusion of alternatives",
    },
    "external_validity": {
        "weight": 0.10,
        "name": "外部效度",
        "description": "Generalizability, cross-market/cross-domain evidence",
    },
    "actionability": {
        "weight": 0.10,
        "name": "可操作性",
        "description": "Decision guidance, quantified predictions with evidence",
    },
}

EVAL_PROMPT = """You are a senior research methodology expert. Evaluate the following research report rigorously.

## Research Question
在 Roblox 平台历史数据中，中腰部游戏（排名50-200）出现"DAU偏低但D7留存/平均时长显著高于同品类均值"的异常信号后，该品类在随后3-6个月内产生Top 10爆款的概率是多少？该信号的精确率(Precision)和召回率(Recall)分别是多少？

## Report
{report_content}

## Findings (findings.json)
{findings_content}

## Data Snapshot (data_snapshot.json)
{snapshot_content}

---

## Evaluation Criteria

Score each of the 6 dimensions (0-100) with detailed comments and improvement suggestions.

### Dimensions

1. **Data Support (25%)**: How many data sources? Are statistical tests significant? Sample sizes adequate?
2. **Logical Rigor (20%)**: Causal vs correlation? Confounders discussed? Counterfactual analysis? Clean window methodology?
3. **Insight Depth (20%)**: Beyond "data went up/down"? Industry logic? Behavioral explanations?
4. **Hypothesis Coverage (15%)**: Systematic competing hypotheses? Alternative explanations excluded?
5. **External Validity (10%)**: Generalizability across markets/domains? Cross-validation?
6. **Actionability (10%)**: Can conclusions guide decisions? Quantified predictions with evidence?

### Output Format

Return ONLY this JSON (no other text):

```json
{{
    "dimensions": {{
        "data_support": {{"score": 0, "comment": "..."}},
        "logical_rigor": {{"score": 0, "comment": "..."}},
        "insight_depth": {{"score": 0, "comment": "..."}},
        "hypothesis_coverage": {{"score": 0, "comment": "..."}},
        "external_validity": {{"score": 0, "comment": "..."}},
        "actionability": {{"score": 0, "comment": "..."}}
    }},
    "overall_feedback": "...",
    "key_gaps": ["gap1", "gap2", "gap3"],
    "strengths": ["strength1", "strength2"],
    "priority_improvements": ["priority1", "priority2"]
}}
```
"""


# ============================================================
# Heuristic scorer — content-based rule scoring
# ============================================================

def _count_occurrences(text: str, patterns: list[str]) -> int:
    """Count occurrences of multiple patterns in text."""
    return sum(len(re.findall(pat, text, re.IGNORECASE)) for pat in patterns)


def _has_pattern(text: str, patterns: list[str]) -> bool:
    """Check if any pattern matches."""
    return _count_occurrences(text, patterns) > 0


def heuristic_evaluate(report: str, findings_raw: str, snapshot_raw: str) -> dict:
    """
    Enhanced heuristic scorer with research integrity checks.
    Rewards clean window methodology, temporal awareness, decomposition.
    Penalizes naive pre/post without confounders, excessive hedging.
    """
    try:
        findings = json.loads(findings_raw)
    except Exception:
        findings = {}

    hypotheses = findings.get("hypotheses", [])
    summary = findings.get("summary", {})
    report_lower = report.lower()
    combined = report + "\n" + findings_raw

    # =====================
    # 1. Data Support (0-100)
    # =====================
    ds_score = 20  # baseline

    # Data source count (+5 each, cap +25)
    n_sources = len(summary.get("data_sources_used", []))
    ds_score += min(n_sources * 5, 25)

    # Statistical tests (p-value / t-stat / chi2)
    stat_keywords = [
        r"p[值=<]", r"t[统_]", r"t.stat", r"cohen", r"效应量",
        r"卡方", r"chi2", r"显著", r"significant", r"置信",
    ]
    n_stats = _count_occurrences(combined, stat_keywords)
    ds_score += min(n_stats * 2, 20)

    # Tested hypotheses ratio
    tested = [h for h in hypotheses if h.get("status") == "tested"]
    if hypotheses:
        ds_score += int(len(tested) / len(hypotheses) * 15)

    # Concrete numbers (万人/USD/%)
    n_numbers = len(re.findall(r'\d+\.?\d*\s*[万%M]', combined))
    ds_score += min(n_numbers, 10)

    ds_score = min(ds_score, 95)

    # =====================
    # 2. Logical Rigor (0-100)
    # =====================
    lr_score = 15

    # DID / Difference-in-Differences
    if _has_pattern(combined, [r"DID", r"双重差分", r"difference.in.difference"]):
        lr_score += 20

    # Confounder discussion
    has_confound = _has_pattern(combined, [r"混杂", r"confound", r"控制变量", r"confounder"])
    if has_confound:
        lr_score += 12

    # Counterfactual / control group
    if _has_pattern(combined, [r"对照", r"control", r"反事实", r"counterfactual"]):
        lr_score += 10

    # Causal vs correlation
    if _has_pattern(combined, [r"因果", r"causal", r"相关性", r"correlation"]):
        lr_score += 8

    # RDD / Synthetic control
    if _has_pattern(combined, [r"RDD", r"断点回归", r"合成控制", r"SCM"]):
        lr_score += 10

    # Limitations discussion
    if _has_pattern(report, [r"局限", r"limitation", r"不足"]):
        lr_score += 8

    # Effect size reporting
    if _has_pattern(combined, [r"cohen", r"效应量", r"effect.size"]):
        lr_score += 7

    # === ENHANCED: Clean window methodology (+15) ===
    clean_window_patterns = [
        r"clean.window", r"干净窗口", r"无混杂.*窗口", r"clean.*period",
        r"baseline.*period", r"基线期",
    ]
    if _has_pattern(combined, clean_window_patterns):
        lr_score += 15

    # === ENHANCED: Temporal confounder awareness (+12) ===
    temporal_confounders = [
        r"季节性", r"seasonal", r"春节", r"holiday", r"寒假",
        r"版本更新", r"version.update", r"周期", r"cyclical",
        r"蜜月期", r"honeymoon", r"自然衰减", r"natural.decay",
    ]
    n_temporal = _count_occurrences(combined, temporal_confounders)
    if n_temporal >= 3:
        lr_score += 12
    elif n_temporal >= 1:
        lr_score += 5

    # === ENHANCED: Data window limitation declaration (+8) ===
    if _has_pattern(combined, [r"temporal_limitation", r"数据窗口.*局限", r"data.*window.*limit"]):
        lr_score += 8

    # === PENALTY: Pre/post comparison without confounder discussion (-15) ===
    has_pre_post = _has_pattern(combined, [r"前后对比", r"pre.post", r"before.*after", r"上线前.*上线后"])
    if has_pre_post and not has_confound:
        lr_score -= 15

    lr_score = max(0, min(lr_score, 95))

    # =====================
    # 3. Insight Depth (0-100)
    # =====================
    id_score = 15

    # Industry logic
    if _has_pattern(combined, DOMAIN_KEYWORDS.get("industry", [])):
        id_score += 12

    # User behavior
    if _has_pattern(combined, DOMAIN_KEYWORDS.get("behavior", [])):
        id_score += 12

    # Survey / primary research
    if _has_pattern(combined, [r"调研", r"survey", r"问卷", r"interview"]):
        id_score += 10

    # Category / segmentation analysis
    if _has_pattern(combined, [r"品类", r"category", r"segment", r"分类", r"taxonomy"]):
        id_score += 10

    # Lifecycle / decay
    if _has_pattern(combined, DOMAIN_KEYWORDS.get("lifecycle", [])):
        id_score += 10

    # Report length (proxy for depth)
    report_len = len(report)
    if report_len > 8000:
        id_score += 8
    elif report_len > 5000:
        id_score += 5
    elif report_len > 3000:
        id_score += 2

    # Figures
    n_figures = len(re.findall(r'!\[.*?\]\(.*?\)', report))
    id_score += min(n_figures * 3, 12)

    id_score = min(id_score, 95)

    # =====================
    # 4. Hypothesis Coverage (0-100)
    # =====================
    hc_score = 10

    # Hypothesis count
    n_hyp = len(hypotheses)
    hc_score += min(n_hyp * 10, 40)

    # Tested ratio
    if hypotheses:
        hc_score += int(len(tested) / len(hypotheses) * 20)

    # === ENHANCED: Incremental vs cannibalization decomposition (+10) ===
    decomp_patterns = [
        r"增量.*蚕食", r"蚕食.*增量", r"incremental.*cannibali",
        r"cannibali.*incremental", r"纯增量", r"pure.*incremental",
        r"decompos", r"分解",
    ]
    if _has_pattern(combined, decomp_patterns):
        hc_score += 10

    # Key hypothesis coverage (generic — check findings for hypothesis diversity)
    if n_hyp >= 4:
        hc_score += 10
    elif n_hyp >= 2:
        hc_score += 5

    hc_score = min(hc_score, 95)

    # =====================
    # 5. External Validity (0-100)
    # =====================
    ev_score = 5

    external_kw = DOMAIN_KEYWORDS.get("external", [])
    n_external = _count_occurrences(combined, external_kw)
    ev_score += min(n_external * 4, 40)

    # Cross-validation / robustness checks
    if _has_pattern(combined, [r"robustness", r"稳健性", r"sensitivity", r"敏感性"]):
        ev_score += 15

    # Multiple data sources cross-referenced
    if n_sources >= 3:
        ev_score += 10

    # External benchmarks
    if _has_pattern(combined, [r"benchmark", r"基准", r"对标", r"参照"]):
        ev_score += 10

    ev_score = min(ev_score, 90)

    # =====================
    # 6. Actionability (0-100)
    # =====================
    ac_score = 10

    # Quantified predictions
    n_quant = _count_occurrences(combined, [r"预[估测]", r"forecast", r"测算", r"预测"])
    if n_quant > 0:
        ac_score += min(10 + n_quant, 18)

    # Decision recommendations
    if _has_pattern(report, [r"建议", r"recommend", r"action", r"决策"]):
        ac_score += 10

    # Scenario analysis
    if _has_pattern(report, [r"情景", r"scenario", r"概率", r"乐观", r"悲观", r"基准"]):
        ac_score += 10

    # Time-bounded predictions
    if _has_pattern(report, [r"\d+个月", r"短期", r"中期", r"长期", r"前瞻"]):
        ac_score += 7

    # KPI / monitoring
    if _has_pattern(report, [r"KPI", r"监测", r"验证指标", r"Dashboard", r"monitor"]):
        ac_score += 8

    # Decision framework / table
    if _has_pattern(report, [r"决策", r"framework", r"信号.*判断"]):
        ac_score += 7

    # === PENALTY: Excessive hedging language (-10) ===
    hedging_patterns = [
        r"可能", r"perhaps", r"maybe", r"或许", r"大概",
        r"seems to", r"appears to", r"might", r"could be",
    ]
    n_hedge = _count_occurrences(report, hedging_patterns)
    # Hedging is fine in moderation; penalize only when excessive
    report_sentences = max(1, len(re.findall(r'[。.!！?？]', report)))
    hedge_ratio = n_hedge / report_sentences
    if hedge_ratio > 0.3:  # more than 30% of sentences have hedging
        ac_score -= 10

    ac_score = max(0, min(ac_score, 90))

    # =====================
    # Build result
    # =====================
    scores = {
        "data_support": ds_score,
        "logical_rigor": lr_score,
        "insight_depth": id_score,
        "hypothesis_coverage": hc_score,
        "external_validity": ev_score,
        "actionability": ac_score,
    }

    # Dynamic comments
    comments = {}
    gaps = []
    strengths = []
    priorities = []

    # data_support
    if ds_score >= 70:
        comments["data_support"] = f"Rich data ({n_sources} sources), {len(tested)}/{len(hypotheses)} hypotheses tested with statistical rigor"
        strengths.append(f"Uses {n_sources} data sources with statistical tests")
    elif ds_score >= 50:
        comments["data_support"] = f"Uses {n_sources} data sources, but some hypotheses lack sufficient data support"
        gaps.append("Add cross-validation with more data sources")
    else:
        comments["data_support"] = "Limited data sources; statistical tests insufficient"
        gaps.append("Add more data sources and statistical tests")
        priorities.append("Increase data sources and statistical coverage")

    # logical_rigor
    has_did = _has_pattern(combined, [r"DID", r"双重差分"])
    has_clean_window = _has_pattern(combined, clean_window_patterns)
    if lr_score >= 65:
        parts = []
        if has_did:
            parts.append("DID causal inference")
        if has_clean_window:
            parts.append("clean window methodology")
        if has_confound:
            parts.append("confounder discussion")
        comments["logical_rigor"] = "Strong: " + ", ".join(parts) if parts else "Logical reasoning is rigorous"
        strengths.append("Causal inference methods well applied" if has_did else "Clear analytical logic")
    elif lr_score >= 45:
        comments["logical_rigor"] = "Some causal awareness, but methods can be upgraded"
        if not has_clean_window:
            gaps.append("Adopt clean window methodology for before/after comparisons")
        if not has_did:
            gaps.append("Introduce DID/RDD for stricter causal inference")
            priorities.append("Upgrade statistical methods (DID → RDD/SCM)")
    else:
        comments["logical_rigor"] = "Mostly simple comparisons; lacks causal inference and confounder control"
        gaps.append("Use DID/SCM for causal inference; discuss confounders")
        priorities.append("Introduce causal inference methods")

    # insight_depth
    if id_score >= 65:
        comments["insight_depth"] = "Good depth; covers industry logic and behavioral explanations"
        strengths.append("Analysis goes beyond descriptive statistics")
    elif id_score >= 45:
        comments["insight_depth"] = "Some depth, but room for deeper industry/behavioral analysis"
        gaps.append("Deepen industry logic analysis and behavioral interpretation")
    else:
        comments["insight_depth"] = "Mostly descriptive; lacks industry and behavioral explanations"
        gaps.append("Add industry logic and behavioral analysis")

    # hypothesis_coverage
    has_decomp = _has_pattern(combined, decomp_patterns)
    if hc_score >= 70:
        comments["hypothesis_coverage"] = f"Systematic coverage of {n_hyp} hypotheses"
        if has_decomp:
            strengths.append("Decomposes growth into incremental vs cannibalization")
    elif hc_score >= 45:
        comments["hypothesis_coverage"] = f"Covers {n_hyp} hypotheses but some untested"
        if not has_decomp:
            gaps.append("Decompose growth claims into incremental vs cannibalization")
    else:
        comments["hypothesis_coverage"] = "Insufficient hypothesis coverage"
        priorities.append("Expand hypothesis coverage")

    # external_validity
    if ev_score >= 60:
        comments["external_validity"] = "Good external validation with cross-market/cross-domain evidence"
        strengths.append("Cross-validated with external evidence")
    elif ev_score >= 35:
        comments["external_validity"] = "Some external evidence but lacks systematic cross-validation"
        gaps.append("Add robustness checks and external benchmarks")
    else:
        comments["external_validity"] = "Minimal external validation"
        gaps.append("Add cross-market/cross-domain evidence for generalizability")
        priorities.append("Improve external validity")

    # actionability
    if ac_score >= 60:
        comments["actionability"] = "Actionable conclusions with quantified predictions"
        strengths.append("Conclusions are actionable")
    elif ac_score >= 40:
        comments["actionability"] = "Some decision value, but predictions need stronger evidence"
        gaps.append("Strengthen quantified predictions with data evidence")
    else:
        comments["actionability"] = "Conclusions too vague; lacks quantified predictions"
        gaps.append("Add quantified predictions and decision recommendations")

    # Ensure minimum gaps and priorities
    if not priorities:
        lowest = min(scores, key=scores.get)
        priorities.append(f"Priority: improve {DIMENSIONS[lowest]['name']} (current {scores[lowest]})")
    if len(gaps) < 3:
        if not has_clean_window and lr_score < 70:
            gaps.append("Adopt clean window methodology for temporal comparisons")
        if not has_decomp and hc_score < 70:
            gaps.append("Decompose growth claims: incremental vs cannibalization")

    total_score = sum(scores[k] * DIMENSIONS[k]["weight"] for k in scores)

    return {
        "dimensions": {k: {"score": v, "comment": comments.get(k, "")} for k, v in scores.items()},
        "overall_feedback": (
            f"Total score: {total_score:.1f}/100. "
            f"{n_hyp} hypotheses, {n_sources} data sources, report length {len(report)} chars. "
            f"{'Uses DID causal inference. ' if has_did else 'Consider DID causal inference. '}"
            f"{'Clean window methodology applied. ' if has_clean_window else 'Consider clean window methodology. '}"
            f"{'Confounders discussed. ' if has_confound else 'Needs confounder discussion. '}"
        ),
        "key_gaps": gaps[:5],
        "strengths": strengths[:4],
        "priority_improvements": priorities[:3],
    }


def evaluate() -> dict:
    """Execute evaluation."""
    print("=" * 60)
    print("AutoResearch — Evaluator")
    print("=" * 60)

    # Load inputs
    print("\nLoading inputs...")

    if not REPORT_PATH.exists():
        print(f"  [ERROR] Report not found: {REPORT_PATH}")
        sys.exit(1)

    report_content = REPORT_PATH.read_text(encoding="utf-8")
    print(f"  ✓ Report: {len(report_content)} chars")

    findings_content = "{}"
    if FINDINGS_PATH.exists():
        findings_content = FINDINGS_PATH.read_text(encoding="utf-8")
        print(f"  ✓ Findings: {len(findings_content)} chars")

    snapshot_content = "{}"
    if SNAPSHOT_PATH.exists():
        snapshot_content = SNAPSHOT_PATH.read_text(encoding="utf-8")
        if len(snapshot_content) > 5000:
            snapshot_content = snapshot_content[:5000] + "\n... (truncated)"
        print(f"  ✓ Snapshot: loaded")

    # Choose scoring method
    print("\nEvaluating...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        print("  Using Claude API...")
        prompt = EVAL_PROMPT.replace("{report_content}", report_content).replace(
            "{findings_content}", findings_content
        ).replace("{snapshot_content}", snapshot_content)
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.content[0].text
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "{" in response_text:
                start = response_text.index("{")
                end = response_text.rindex("}") + 1
                json_str = response_text[start:end]
            else:
                json_str = response_text
            eval_data = json.loads(json_str)
            print("  ✓ Claude API evaluation received")
        except Exception as e:
            print(f"  [ERROR] API call failed: {e}")
            print("  Falling back to heuristic evaluation")
            eval_data = heuristic_evaluate(report_content, findings_content, snapshot_content)
    else:
        print("  Using heuristic evaluator (no ANTHROPIC_API_KEY)")
        eval_data = heuristic_evaluate(report_content, findings_content, snapshot_content)

    # Compute weighted total
    total_score = 0
    dimensions = eval_data.get("dimensions", {})
    for dim_key, dim_info in DIMENSIONS.items():
        if dim_key in dimensions:
            score = dimensions[dim_key].get("score", 0)
            total_score += score * dim_info["weight"]

    # Assemble final result
    result = {
        "evaluated_at": datetime.now().isoformat(),
        "total_score": round(total_score, 2),
        "dimensions": {},
        "overall_feedback": eval_data.get("overall_feedback", ""),
        "key_gaps": eval_data.get("key_gaps", []),
        "strengths": eval_data.get("strengths", []),
        "priority_improvements": eval_data.get("priority_improvements", []),
    }

    for dim_key, dim_info in DIMENSIONS.items():
        dim_eval = dimensions.get(dim_key, {})
        result["dimensions"][dim_key] = {
            "name": dim_info["name"],
            "weight": dim_info["weight"],
            "score": dim_eval.get("score", 0),
            "weighted_score": round(dim_eval.get("score", 0) * dim_info["weight"], 2),
            "comment": dim_eval.get("comment", ""),
        }

    # Save
    EVAL_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\n{'=' * 40}")
    print(f"  TOTAL SCORE: {result['total_score']:.1f} / 100")
    print(f"{'=' * 40}")
    for dim_key, dim_data in result["dimensions"].items():
        bar = "█" * int(dim_data["score"] / 5) + "░" * (20 - int(dim_data["score"] / 5))
        print(f"  {dim_data['name']:8s} ({dim_data['weight']*100:.0f}%): {dim_data['score']:5.1f}  {bar}")

    print(f"\nStrengths:")
    for s in result.get("strengths", []):
        print(f"  ✓ {s}")
    print(f"\nKey gaps:")
    for gap in result.get("key_gaps", []):
        print(f"  • {gap}")
    print(f"\nPriority improvements:")
    for p in result.get("priority_improvements", []):
        print(f"  → {p}")

    print(f"\n✓ Evaluation saved to {EVAL_RESULT_PATH}")
    print("=" * 60)

    return result


if __name__ == "__main__":
    evaluate()
