"""Tests for the evidence-confidence tier classifier and its verdict downgrade.

Problem 5 — Evidence confidence tier:
  A trust score is only as trustworthy as the evidentiary backing behind it.
  The `_evidence_confidence_tier` helper classifies that backing into
  high / medium / low based on four axes:

    1. Dimensional coverage (of 4 answer-truth dimensions)
    2. Claim sample size
    3. Modality diversity (TF-IDF + embedding both present)
    4. Modality agreement (|tfidf − embedding|)

  A "low" tier downgrades an otherwise-trusted verdict to use_caution.
  Medium/high tiers never modify the verdict.
"""

from __future__ import annotations

from trusted_ai_toolkit.reporting import (
    _answer_verdict,
    _evidence_confidence_tier,
)
from trusted_ai_toolkit.schemas import MetricResult


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _m(metric_id: str, value: float, details: dict | None = None) -> MetricResult:
    return MetricResult(
        metric_id=metric_id, value=value,
        threshold=None, passed=True,
        details=details or {},
    )


def _grounding(value: float, claim_count: int) -> MetricResult:
    return _m("claim_support_rate", value, {"claim_count": claim_count})


def _sufficiency(value: float, claim_count: int) -> MetricResult:
    return _m("evidence_sufficiency_score", value, {"claim_count": claim_count})


def _contradiction(value: float, claim_count: int) -> MetricResult:
    return _m("contradiction_rate", value, {"claim_count": claim_count})


def _retrieval_embed(value: float) -> MetricResult:
    return _m("context_relevance_embedding", value)


def _os_tfidf(value: float) -> MetricResult:
    return _m("output_support_tfidf", value)


def _os_embed(value: float) -> MetricResult:
    return _m("output_support_embedding", value)


def _full_high_confidence_bundle() -> list[MetricResult]:
    """All 4 dimensions, high N, dual modality, modalities agree."""
    return [
        _grounding(0.95, 10),
        _sufficiency(0.90, 10),
        _contradiction(0.0, 10),
        _retrieval_embed(0.85),
        _os_tfidf(0.82),
        _os_embed(0.80),   # |0.82 - 0.80| = 0.02 (agreement)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Axis 1 — Dimensional coverage
# ─────────────────────────────────────────────────────────────────────────────

class TestDimensionalCoverage:

    def test_full_coverage_is_high(self) -> None:
        result = _evidence_confidence_tier(_full_high_confidence_bundle())
        assert result["tier"] == "high"
        assert result["dimensional_coverage"] == 4

    def test_three_dimensions_is_medium(self) -> None:
        # Drop retrieval dimension
        results = [
            _grounding(0.95, 10),
            _sufficiency(0.90, 10),
            _contradiction(0.0, 10),
            _os_tfidf(0.82),
            _os_embed(0.80),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "medium"
        assert result["dimensional_coverage"] == 3

    def test_two_dimensions_is_low(self) -> None:
        results = [
            _grounding(0.95, 10),
            _os_embed(0.80),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "low"
        assert result["dimensional_coverage"] == 2

    def test_one_dimension_is_low(self) -> None:
        result = _evidence_confidence_tier([_grounding(0.95, 10)])
        assert result["tier"] == "low"
        assert result["dimensional_coverage"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Axis 2 — Claim volume
# ─────────────────────────────────────────────────────────────────────────────

class TestClaimVolume:

    def test_below_minimum_forces_low(self) -> None:
        results = [
            _grounding(0.95, 1),           # N=1 < low-max 2
            _sufficiency(0.90, 1),
            _contradiction(0.0, 1),
            _retrieval_embed(0.85),
            _os_tfidf(0.82),
            _os_embed(0.80),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "low"
        assert result["claim_count"] == 1
        assert any("sample size" in r.lower() for r in result["reasons"])

    def test_between_minimum_and_high_is_medium(self) -> None:
        results = [
            _grounding(0.95, 3),           # 2 < 3 < 5
            _sufficiency(0.90, 3),
            _contradiction(0.0, 3),
            _retrieval_embed(0.85),
            _os_tfidf(0.82),
            _os_embed(0.80),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "medium"

    def test_at_high_threshold_stays_high(self) -> None:
        results = _full_high_confidence_bundle()
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "high"


# ─────────────────────────────────────────────────────────────────────────────
# Axis 3 — Modality diversity
# ─────────────────────────────────────────────────────────────────────────────

class TestModalityDiversity:

    def test_single_modality_caps_at_medium(self) -> None:
        # Full coverage otherwise but only one output-support modality
        results = [
            _grounding(0.95, 10),
            _sufficiency(0.90, 10),
            _contradiction(0.0, 10),
            _retrieval_embed(0.85),
            _os_embed(0.80),   # only one side
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "medium"
        assert result["modality_diversity"] is False
        assert any("single output-support modality" in r for r in result["reasons"])

    def test_dual_modality_enables_high(self) -> None:
        result = _evidence_confidence_tier(_full_high_confidence_bundle())
        assert result["modality_diversity"] is True
        assert result["tier"] == "high"


# ─────────────────────────────────────────────────────────────────────────────
# Axis 4 — Modality agreement
# ─────────────────────────────────────────────────────────────────────────────

class TestModalityAgreement:

    def test_tight_agreement_stays_high(self) -> None:
        # |0.82 - 0.80| = 0.02 < 0.15 agreement threshold
        result = _evidence_confidence_tier(_full_high_confidence_bundle())
        assert result["tier"] == "high"
        assert result["modality_disagreement"] == 0.02

    def test_moderate_disagreement_downgrades_to_medium(self) -> None:
        # |0.80 - 0.55| = 0.25 → between agree_max (0.15) and disagree_min (0.30)
        results = [
            _grounding(0.95, 10),
            _sufficiency(0.90, 10),
            _contradiction(0.0, 10),
            _retrieval_embed(0.85),
            _os_tfidf(0.80),
            _os_embed(0.55),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "medium"
        assert result["modality_disagreement"] == 0.25

    def test_large_disagreement_forces_low(self) -> None:
        # |0.90 - 0.50| = 0.40 > 0.30 disagreement threshold
        results = [
            _grounding(0.95, 10),
            _sufficiency(0.90, 10),
            _contradiction(0.0, 10),
            _retrieval_embed(0.85),
            _os_tfidf(0.90),
            _os_embed(0.50),
        ]
        result = _evidence_confidence_tier(results)
        assert result["tier"] == "low"
        assert result["modality_disagreement"] == 0.40
        assert any("disagree" in r.lower() for r in result["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# Verdict downgrade behavior
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictDowngrade:
    """A low-confidence trust signal must downgrade a trusted verdict."""

    def test_low_confidence_downgrades_trusted_to_use_caution(self) -> None:
        # One dimension only → low confidence, but otherwise clean metrics
        results = [_grounding(0.95, 10)]
        low_conf = _evidence_confidence_tier(results)
        assert low_conf["tier"] == "low"

        verdict, reasons = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=low_conf
        )
        assert verdict == "use_caution"
        assert any("evidence confidence is low" in r.lower() for r in reasons)
        assert any("downgraded" in r.lower() for r in reasons)

    def test_high_confidence_leaves_trusted_alone(self) -> None:
        results = _full_high_confidence_bundle()
        high_conf = _evidence_confidence_tier(results)
        assert high_conf["tier"] == "high"

        verdict, _ = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=high_conf
        )
        assert verdict == "trusted"

    def test_medium_confidence_leaves_trusted_alone(self) -> None:
        # Three dimensions → medium confidence
        results = [
            _grounding(0.95, 10),
            _sufficiency(0.90, 10),
            _contradiction(0.0, 10),
            _os_tfidf(0.82),
            _os_embed(0.80),
        ]
        med_conf = _evidence_confidence_tier(results)
        assert med_conf["tier"] == "medium"

        verdict, _ = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=med_conf
        )
        assert verdict == "trusted"

    def test_low_confidence_does_not_upgrade_caution(self) -> None:
        # Force a caution via low support, then attach low confidence —
        # verdict should stay use_caution (not escalate to not_trusted).
        results = [
            _m("claim_support_rate", 0.65, {"claim_count": 1}),   # caution at medium
        ]
        low_conf = _evidence_confidence_tier(results)
        assert low_conf["tier"] == "low"

        verdict, _ = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=low_conf
        )
        assert verdict == "use_caution"

    def test_low_confidence_does_not_override_not_trusted(self) -> None:
        # Hard gate fires first; confidence check never runs.
        results = [
            _contradiction(0.50, 1),   # way above medium gate 0.05
        ]
        low_conf = _evidence_confidence_tier(results)
        verdict, _ = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=low_conf
        )
        assert verdict == "not_trusted"

    def test_absent_confidence_is_backward_compatible(self) -> None:
        # Passing no evidence_confidence keeps old behavior exactly.
        results = _full_high_confidence_bundle()
        v_with_none, _ = _answer_verdict(
            results, risk_tier="medium", evidence_confidence=None
        )
        assert v_with_none == "trusted"


# ─────────────────────────────────────────────────────────────────────────────
# Output shape / audit trail
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputShape:

    def test_result_dict_has_all_keys(self) -> None:
        result = _evidence_confidence_tier(_full_high_confidence_bundle())
        expected = {
            "tier", "dimensional_coverage", "claim_count",
            "modality_diversity", "modality_disagreement", "reasons",
        }
        assert expected <= set(result.keys())

    def test_empty_metrics_is_low(self) -> None:
        result = _evidence_confidence_tier([])
        assert result["tier"] == "low"
        assert result["dimensional_coverage"] == 0
        assert result["claim_count"] is None
        assert result["modality_diversity"] is False
        assert result["modality_disagreement"] is None

    def test_reasons_are_nonempty(self) -> None:
        result = _evidence_confidence_tier(_full_high_confidence_bundle())
        assert len(result["reasons"]) >= 1
