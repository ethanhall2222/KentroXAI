"""Show the verdict + score-formula impact against realistic chat scenarios.

For each scenario, computes the answer trust score and verdict twice:
  * OLD — pre-change thresholds and pre-change Stage-2 weights / ceiling
  * NEW — current (toned-down) thresholds and current score formula

Both are run from this file so the comparison stays honest even after future
edits to the production code paths.

Usage:
    python scripts/verdict_impact_demo.py
"""

from __future__ import annotations

import copy
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trusted_ai_toolkit.reporting import (
    _answer_trust_score as _answer_trust_score_new,
    _answer_verdict,
    _VERDICT_THRESHOLDS,
)
from trusted_ai_toolkit.schemas import MetricResult


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot of pre-change thresholds (verdict gating).
# ─────────────────────────────────────────────────────────────────────────────

OLD_THRESHOLDS: dict[str, dict[str, Any]] = {
    "low": {
        "not_trusted_contradiction":  0.10,
        "not_trusted_unsupported":    0.50,
        "not_trusted_answer_score":   None,
        "caution_support_below":      0.50,
        "caution_sufficiency_below":  0.45,
        "caution_answer_score":       0.30,
        "bias_not_trusted":           False,
        "bias_caution_min_count":     3,
        "escalate_multi_caution":     False,
    },
    "medium": {
        "not_trusted_contradiction":  0.05,
        "not_trusted_unsupported":    0.35,
        "not_trusted_answer_score":   None,
        "caution_support_below":      0.70,
        "caution_sufficiency_below":  0.60,
        "caution_answer_score":       None,
        "bias_not_trusted":           False,
        "bias_caution_min_count":     1,
        "escalate_multi_caution":     False,
    },
    "high": {
        "not_trusted_contradiction":  0.02,
        "not_trusted_unsupported":    0.20,
        "not_trusted_answer_score":   0.40,
        "caution_support_below":      0.80,
        "caution_sufficiency_below":  0.72,
        "caution_answer_score":       0.60,
        "bias_not_trusted":           True,
        "bias_caution_min_count":     1,
        "escalate_multi_caution":     True,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Pre-change answer_trust_score formula (Stage-2 weights 0.70/0.30, ceiling 0.30).
# Replicated here so the comparison is independent of future production edits.
# ─────────────────────────────────────────────────────────────────────────────

def _answer_trust_score_old(metric_results: list[MetricResult]) -> float | None:
    """Pre-change three-stage formula."""
    _CONTRADICTION_CEILING = 0.30
    lookup = {m.metric_id: m for m in metric_results}

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    def _get(metric_id: str) -> float | None:
        m = lookup.get(metric_id)
        if m is None or m.value is None:
            return None
        return _clamp(float(m.value))

    csr = _get("claim_support_rate")
    ess = _get("evidence_sufficiency_score")
    if csr is not None and ess is not None:
        grounding_sub = math.sqrt(csr * ess)
    elif csr is not None:
        grounding_sub = csr
    elif ess is not None:
        grounding_sub = ess
    else:
        grounding_sub = None

    sem_metric = lookup.get("output_support_embedding") or lookup.get("output_support_tfidf")
    semantic_sub = (
        _clamp(float(sem_metric.value))
        if sem_metric is not None and sem_metric.value is not None
        else None
    )

    base_slots: list[tuple[float | None, float]] = [
        (grounding_sub, 0.70),
        (semantic_sub,  0.30),
    ]
    present_base = [(v, w) for v, w in base_slots if v is not None]
    if not present_base:
        return None

    total_w = sum(w for _, w in present_base)
    base_score = sum(v * w for v, w in present_base) / total_w

    contradiction_rate = _get("contradiction_rate")
    if contradiction_rate is not None:
        penalty = max(0.0, 1.0 - contradiction_rate / _CONTRADICTION_CEILING)
        trust_score = base_score * penalty
    else:
        trust_score = base_score

    return round(trust_score, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _m(metric_id: str, value: float, details: dict | None = None) -> MetricResult:
    return MetricResult(
        metric_id=metric_id, value=value,
        threshold=None, passed=True,
        details=details or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios — each represents a realistic chat-RAG response with its eval
# metrics.  Includes output_support_embedding and context_relevance_embedding
# so both Stage-2 changes (weight rebalance + new retrieval slot) are visible,
# plus contradiction values that exercise the new Stage-3 deadband.  The first
# three scenarios are the "directly related question, low score" pattern that
# motivated this PR.
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "Direct Q on uploaded doc, paraphrased",
        "description": "User asks an in-doc Q; LLM rephrases. Embedding sees the match; TF-IDF underweights it.",
        "tier": "medium",
        "metrics": [
            _m("claim_support_rate",            0.62),  # TF-IDF: paraphrasing pulls this down
            _m("evidence_sufficiency_score",    0.55),  # short retrieved chunk
            _m("output_support_embedding",      0.88),  # semantic match strong
            _m("context_relevance_embedding",   0.92),  # retriever found the right doc
            _m("contradiction_rate",            0.03),  # within new deadband => no penalty
            _m("unsupported_claim_rate",        0.30),
        ],
    },
    {
        "name": "Direct Q, exact-quote answer",
        "description": "Best case for current scoring — answer verbatim from doc.",
        "tier": "medium",
        "metrics": [
            _m("claim_support_rate",            0.95),
            _m("evidence_sufficiency_score",    0.90),
            _m("output_support_embedding",      0.92),
            _m("context_relevance_embedding",   0.95),
            _m("contradiction_rate",            0.00),
            _m("unsupported_claim_rate",        0.05),
        ],
    },
    {
        "name": "Direct Q, multi-hop summary",
        "description": "Pulls 2 doc sections, synthesises one summary sentence.",
        "tier": "medium",
        "metrics": [
            _m("claim_support_rate",            0.55),
            _m("evidence_sufficiency_score",    0.50),
            _m("output_support_embedding",      0.82),
            _m("context_relevance_embedding",   0.85),
            _m("contradiction_rate",            0.05),  # just past deadband
            _m("unsupported_claim_rate",        0.35),
        ],
    },
    {
        "name": "High-tier legal answer, minor negation noise",
        "description": "Mostly clean; 4 % contradiction signal from negation parsing.",
        "tier": "high",
        "metrics": [
            _m("claim_support_rate",            0.86),
            _m("evidence_sufficiency_score",    0.78),
            _m("output_support_embedding",      0.83),
            _m("context_relevance_embedding",   0.85),
            _m("contradiction_rate",            0.03),  # within deadband
            _m("unsupported_claim_rate",        0.12),
        ],
    },
    {
        "name": "High-tier borderline composite",
        "description": "All gates clean; composite lands in the 0.30–0.40 band under old formula.",
        "tier": "high",
        "metrics": [
            _m("claim_support_rate",            0.72),
            _m("evidence_sufficiency_score",    0.55),
            _m("output_support_embedding",      0.70),
            _m("context_relevance_embedding",   0.65),
            _m("contradiction_rate",            0.04),  # at deadband edge
            _m("unsupported_claim_rate",        0.20),
        ],
    },
    {
        "name": "Genuinely contradictory answer",
        "description": "Says the opposite of the source — should still be not_trusted, low score.",
        "tier": "medium",
        "metrics": [
            _m("claim_support_rate",            0.40),
            _m("evidence_sufficiency_score",    0.55),
            _m("output_support_embedding",      0.45),
            _m("context_relevance_embedding",   0.55),
            _m("contradiction_rate",            0.35),
            _m("unsupported_claim_rate",        0.30),
        ],
    },
    {
        "name": "Mostly hallucinated answer",
        "description": "Plausible-sounding but few claims trace to evidence.",
        "tier": "medium",
        "metrics": [
            _m("claim_support_rate",            0.30),
            _m("evidence_sufficiency_score",    0.40),
            _m("output_support_embedding",      0.35),
            _m("context_relevance_embedding",   0.40),
            _m("contradiction_rate",            0.04),
            _m("unsupported_claim_rate",        0.62),
        ],
    },
    {
        "name": "Low-tier internal Q&A, thin evidence",
        "description": "Internal lookup; modest noise tolerated at low tier.",
        "tier": "low",
        "metrics": [
            _m("claim_support_rate",            0.55),
            _m("evidence_sufficiency_score",    0.50),
            _m("output_support_embedding",      0.70),
            _m("context_relevance_embedding",   0.65),
            _m("contradiction_rate",            0.12),
            _m("unsupported_claim_rate",        0.55),
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Verdict-with-thresholds runner
# ─────────────────────────────────────────────────────────────────────────────

def _verdict_with(
    thresholds: dict[str, dict[str, Any]],
    scenario: dict[str, Any],
    answer_trust_score: float | None,
) -> str | None:
    saved = copy.deepcopy(_VERDICT_THRESHOLDS)
    try:
        for tier in ("low", "medium", "high"):
            _VERDICT_THRESHOLDS[tier].clear()
            _VERDICT_THRESHOLDS[tier].update(thresholds[tier])
        verdict, _ = _answer_verdict(
            scenario["metrics"],
            risk_tier=scenario["tier"],
            answer_trust_score=answer_trust_score,
        )
        return verdict
    finally:
        for tier in ("low", "medium", "high"):
            _VERDICT_THRESHOLDS[tier].clear()
            _VERDICT_THRESHOLDS[tier].update(saved[tier])


def _short(verdict: str | None) -> str:
    return {
        "trusted":      "TRUSTED     ",
        "use_caution":  "use_caution ",
        "not_trusted":  "NOT_TRUSTED ",
        None:           "(none)      ",
    }[verdict]


def _new_thresholds() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(_VERDICT_THRESHOLDS)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    new_thresholds = _new_thresholds()
    assert new_thresholds["medium"]["not_trusted_contradiction"] == 0.08, (
        "Run after the threshold-toning change is in place."
    )

    print("=" * 116)
    print(
        f"{'Scenario':<46} {'tier':<7} "
        f"{'OLD score':<10} {'NEW score':<10} "
        f"{'OLD verdict':<13} {'NEW verdict':<13} flipped?"
    )
    print("-" * 116)

    score_lifts: list[tuple[str, float, float]] = []
    verdict_flips: list[tuple[str, str, str]] = []

    for sc in SCENARIOS:
        old_score = _answer_trust_score_old(sc["metrics"])
        new_score = _answer_trust_score_new(sc["metrics"])

        old_verdict = _verdict_with(OLD_THRESHOLDS,    sc, old_score)
        new_verdict = _verdict_with(new_thresholds,    sc, new_score)

        flag = ""
        if old_verdict != new_verdict:
            flag = "  <-- verdict flip"
            verdict_flips.append((sc["name"], old_verdict or "(none)", new_verdict or "(none)"))
        if old_score is not None and new_score is not None and (new_score - old_score) >= 0.05:
            score_lifts.append((sc["name"], old_score, new_score))

        old_str = f"{old_score:.3f}" if old_score is not None else " — "
        new_str = f"{new_score:.3f}" if new_score is not None else " — "
        print(
            f"{sc['name'][:44]:<46} {sc['tier']:<7} "
            f"{old_str:<10} {new_str:<10} "
            f"{_short(old_verdict)} {_short(new_verdict)} {flag}"
        )

    print("-" * 116)
    print(f"\n{len(verdict_flips)} verdict flip(s); {len(score_lifts)} scenario(s) with score lift >= 0.05.\n")

    if verdict_flips:
        print("Verdict changes (old -> new):")
        for name, old_v, new_v in verdict_flips:
            print(f"  - {name}:  {old_v} -> {new_v}")
        print()

    if score_lifts:
        print("Score lifts >= 0.05 (old -> new):")
        for name, old_s, new_s in score_lifts:
            print(f"  - {name}:  {old_s:.3f} -> {new_s:.3f}  (+{new_s - old_s:.3f})")
        print()

    print("Formula deltas applied (cumulative across this PR):")
    print("  Stage 2 weights (grounding / out_emb / ctx_emb):")
    print("                                            0.70 / 0.30 / 0.00  ->  0.45 / 0.40 / 0.15")
    print("  Stage 3 contradiction deadband:           0.00         ->  0.04 (no penalty within)")
    print("  Stage 3 contradiction ceiling:            0.30         ->  0.50")
    print("  Verdict not_trusted_contradiction (l/m/h): 0.10/0.05/0.02 -> 0.15/0.08/0.04")
    print("  Verdict not_trusted_unsupported   (l/m/h): 0.50/0.35/0.20 -> 0.65/0.50/0.30")
    print("  Verdict not_trusted_answer_score (high):   0.40         ->  0.30")


if __name__ == "__main__":
    main()
