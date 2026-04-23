"""Tests that guard against metric-correlation inflation across every aggregation
function in reporting.py.

Each class targets one function and verifies the specific aggregation design
described in its docstring.  Run with ``pytest tests/test_score_aggregation.py``.
"""

from __future__ import annotations

import math

import pytest

from trusted_ai_toolkit.reporting import (
    _answer_trust_score,
    _empirical_score,
    _metric_strength_map,
    _metric_z_value,
    _trust_z_score,
)
from trusted_ai_toolkit.schemas import MetricResult


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _m(
    metric_id: str,
    value: float,
    threshold: float | None = None,
    passed: bool | None = True,
) -> MetricResult:
    return MetricResult(
        metric_id=metric_id, value=value,
        threshold=threshold, passed=passed, details={},
    )


# ─────────────────────────────────────────────────────────────────────────────
# _empirical_score — geometric mean for cross-modality pairs
# ─────────────────────────────────────────────────────────────────────────────

class TestEmpiricalScoreGeometricMean:
    """The geometric mean of a TF-IDF and embedding variant is the correct
    aggregator when both modalities are present.  It penalises signal
    disagreement (one high, one low) more severely than arithmetic mean.
    """

    def test_disagreeing_signals_produce_lower_score_than_agreement(self) -> None:
        """geo(0.9, 0.1) = 0.30  vs  geo(0.9, 0.85) = 0.874  — disagreement penalised."""
        disagreement = [
            _m("output_support_tfidf",      0.1,  threshold=0.2),
            _m("output_support_embedding",  0.9,  threshold=0.5),
        ]
        agreement = [
            _m("output_support_tfidf",      0.85, threshold=0.2),
            _m("output_support_embedding",  0.9,  threshold=0.5),
        ]
        assert _empirical_score(disagreement) < _empirical_score(agreement)

    def test_geo_mean_is_more_conservative_than_arithmetic_on_disagreement(self) -> None:
        """Arithmetic mean of (0.2, 0.9) = 0.55; geometric mean = 0.424.
        The empirical score should track the geometric mean, not the arithmetic."""
        results = [
            _m("output_support_tfidf",     0.2, threshold=0.2),
            _m("output_support_embedding", 0.9, threshold=0.5),
        ]
        score = _empirical_score(results)
        assert score is not None
        geo = math.sqrt(0.2 * 0.9)       # 0.4243
        arith = (0.2 + 0.9) / 2           # 0.5500
        # Score should track geo, not arith — when only generation dim is present
        # the dimension weight re-normalises to 1.0 so score ≈ geo
        assert score == pytest.approx(geo, abs=1e-3)

    def test_single_modality_uses_value_directly(self) -> None:
        """No geometric penalty when only one modality is available."""
        embedding_only = [_m("output_support_embedding", 0.75, threshold=0.5)]
        tfidf_only     = [_m("output_support_tfidf",     0.75, threshold=0.2)]
        # Both should produce the same score (only generation dimension present)
        assert _empirical_score(embedding_only) == pytest.approx(0.75, abs=1e-4)
        assert _empirical_score(tfidf_only)     == pytest.approx(0.75, abs=1e-4)

    def test_context_relevance_pair_uses_geometric_mean(self) -> None:
        """geo(0.3, 0.9) < arith(0.3, 0.9) for context_relevance pair."""
        disagreement = [
            _m("context_relevance_tfidf",      0.3, threshold=0.2),
            _m("context_relevance_embedding",  0.9, threshold=0.5),
        ]
        score = _empirical_score(disagreement)
        assert score is not None
        geo = math.sqrt(0.3 * 0.9)
        assert score == pytest.approx(geo, abs=1e-3)

    def test_groundedness_stub_not_used_when_output_support_present(self) -> None:
        """groundedness_stub = output_support_tfidf internally; must not double-count."""
        with_tfidf = [_m("output_support_tfidf", 0.6, threshold=0.2)]
        with_tfidf_and_stub = [
            _m("output_support_tfidf",  0.6, threshold=0.2),
            _m("groundedness_stub",     0.6, threshold=0.65),  # same computation
        ]
        assert _empirical_score(with_tfidf) == _empirical_score(with_tfidf_and_stub)

    def test_groundedness_stub_used_as_fallback(self) -> None:
        """When no output_support variant is present, groundedness_stub fills in."""
        score = _empirical_score([_m("groundedness_stub", 0.7, threshold=0.65)])
        assert score is not None and score == pytest.approx(0.7, abs=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# _empirical_score — F1 (harmonic mean) for precision/recall pair
# ─────────────────────────────────────────────────────────────────────────────

class TestEmpiricalScoreLexicalF1:
    """lexical_grounding_precision and claim_coverage_recall are token-overlap
    precision and recall respectively.  F1 = harmonic_mean(P, R) is the correct
    aggregator — it penalises extreme imbalance, preventing perfect precision
    from masking zero coverage or vice versa.
    """

    def test_perfect_precision_zero_recall_yields_zero_f1(self) -> None:
        """P=1.0, R=0.0 → F1=0.0.  Arithmetic mean would give 0.5 — inflated."""
        extreme = [
            _m("lexical_grounding_precision", 1.0, threshold=0.25),
            _m("claim_coverage_recall",        0.0, threshold=0.10),
        ]
        score = _empirical_score(extreme)
        # Only lexical_f1 dimension present → score equals F1 = 0.0
        assert score == pytest.approx(0.0, abs=1e-4)

    def test_zero_precision_perfect_recall_yields_zero_f1(self) -> None:
        """P=0.0, R=1.0 → F1=0.0."""
        extreme = [
            _m("lexical_grounding_precision", 0.0, threshold=0.25),
            _m("claim_coverage_recall",        1.0, threshold=0.10),
        ]
        assert _empirical_score(extreme) == pytest.approx(0.0, abs=1e-4)

    def test_balanced_pair_beats_extreme_imbalance(self) -> None:
        """F1(0.7, 0.7) = 0.7 >> F1(1.0, 0.0) = 0.0."""
        balanced = [
            _m("lexical_grounding_precision", 0.7, threshold=0.25),
            _m("claim_coverage_recall",        0.7, threshold=0.10),
        ]
        extreme = [
            _m("lexical_grounding_precision", 1.0, threshold=0.25),
            _m("claim_coverage_recall",        0.0, threshold=0.10),
        ]
        assert _empirical_score(balanced) > _empirical_score(extreme)

    def test_f1_matches_harmonic_mean_formula(self) -> None:
        """Score for precision/recall only should equal F1 = 2*P*R/(P+R)."""
        p, r = 0.8, 0.5
        expected_f1 = 2 * p * r / (p + r)   # 0.6154
        results = [
            _m("lexical_grounding_precision", p, threshold=0.25),
            _m("claim_coverage_recall",        r, threshold=0.10),
        ]
        score = _empirical_score(results)
        assert score == pytest.approx(expected_f1, abs=1e-3)

    def test_single_precision_metric_used_directly(self) -> None:
        """When only precision is available it is used without penalty."""
        score = _empirical_score([_m("lexical_grounding_precision", 0.65, threshold=0.25)])
        assert score == pytest.approx(0.65, abs=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# _empirical_score — behavioral safety gate
# ─────────────────────────────────────────────────────────────────────────────

class TestEmpiricalScoreBehavioralGate:
    """refusal_correctness and unanswerable_handling are applied as a
    multiplicative gate rather than being averaged with quality metrics.
    Failing safety behavior cannot be compensated by high grounding scores.
    """

    def test_safety_failure_reduces_score(self) -> None:
        """refusal_correctness below threshold penalises the composite score."""
        base = [_m("output_support_embedding", 0.9, threshold=0.5)]
        with_passing_safety = base + [_m("refusal_correctness", 0.95, threshold=0.82)]
        with_failing_safety  = base + [_m("refusal_correctness", 0.30, threshold=0.82)]

        score_pass = _empirical_score(with_passing_safety)
        score_fail = _empirical_score(with_failing_safety)
        assert score_pass is not None and score_fail is not None
        assert score_pass > score_fail, (
            "Passing safety should yield a higher score than failing safety"
        )

    def test_perfect_safety_does_not_inflate_score(self) -> None:
        """Gate = 1.0 when safety metric meets or exceeds threshold — no bonus."""
        base = [_m("output_support_embedding", 0.7, threshold=0.5)]
        with_perfect_safety = base + [_m("refusal_correctness", 1.0, threshold=0.82)]

        score_base   = _empirical_score(base)
        score_safety = _empirical_score(with_perfect_safety)
        assert score_base is not None and score_safety is not None
        # Perfect safety should not raise the score above the base
        assert score_safety <= score_base + 1e-4

    def test_safety_gate_has_floor_preventing_total_wipeout(self) -> None:
        """Even zero safety score cannot reduce composite below 50% of base."""
        base_results = [_m("output_support_embedding", 0.9, threshold=0.5)]
        with_zero_safety = base_results + [
            _m("refusal_correctness",    0.0, threshold=0.82),
            _m("unanswerable_handling",  0.0, threshold=0.80),
        ]
        base_score   = _empirical_score(base_results)
        gated_score  = _empirical_score(with_zero_safety)
        assert base_score is not None and gated_score is not None
        # Floor at 0.50 × base_score
        assert gated_score >= base_score * 0.50 - 1e-4

    def test_unanswerable_handling_also_gates(self) -> None:
        """unanswerable_handling below threshold also reduces the score."""
        base = [_m("output_support_embedding", 0.9, threshold=0.5)]
        with_failing = base + [_m("unanswerable_handling", 0.4, threshold=0.80)]
        assert _empirical_score(with_failing) < _empirical_score(base)

    def test_absent_safety_metrics_apply_no_penalty(self) -> None:
        """When no behavioral metrics are present the gate does not apply."""
        results = [_m("output_support_embedding", 0.75, threshold=0.5)]
        assert _empirical_score(results) == pytest.approx(0.75, abs=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# _empirical_score — dimensional weights and re-normalisation
# ─────────────────────────────────────────────────────────────────────────────

class TestEmpiricalScoreDimensionalWeights:
    """Dimension weights: generation (0.35) > retrieval = lexical (0.25) > reliability (0.15).
    Weights re-normalise when dimensions are absent.
    """

    def test_generation_fidelity_outweighs_retrieval_quality(self) -> None:
        """Same score in different dimension → higher composite when in heavier dim."""
        perfect_generation = [_m("output_support_embedding",    0.99, threshold=0.5)]
        perfect_retrieval  = [_m("context_relevance_embedding", 0.99, threshold=0.5)]
        # Generation weight=0.35, Retrieval weight=0.25 — same value, different weight
        # But since each is the only present dimension, weight re-normalises to 1.0 each.
        # Both should equal 0.99 after renorm.
        assert _empirical_score(perfect_generation) == pytest.approx(0.99, abs=1e-4)
        assert _empirical_score(perfect_retrieval)  == pytest.approx(0.99, abs=1e-4)

    def test_generation_dimension_has_highest_weight_in_full_suite(self) -> None:
        """When all dimensions are present, generation (0.35) carries most weight.
        We verify by boosting only generation — composite should rise more than
        boosting any other single dimension by the same amount."""
        def score_with_boost(dim_id: str, boosted: float) -> float:
            base = {
                "context_relevance_embedding": 0.5,
                "output_support_embedding":    0.5,
                "lexical_grounding_precision": 0.5,
                "claim_coverage_recall":       0.5,
                "reliability":                 0.5,
            }
            base[dim_id] = boosted
            return _empirical_score([_m(k, v, threshold=0.5) for k, v in base.items()])

        generation_boost  = score_with_boost("output_support_embedding",    0.99)
        retrieval_boost   = score_with_boost("context_relevance_embedding",  0.99)
        reliability_boost = score_with_boost("reliability",                  0.99)

        assert generation_boost > retrieval_boost
        assert generation_boost > reliability_boost

    def test_single_metric_renormalises_weight_to_one(self) -> None:
        """A single metric should return its own value after full renorm."""
        for metric_id, threshold in [
            ("output_support_embedding",    0.5),
            ("context_relevance_embedding", 0.5),
            ("reliability",                 0.8),
        ]:
            score = _empirical_score([_m(metric_id, 0.72, threshold=threshold)])
            assert score == pytest.approx(0.72, abs=1e-4), (
                f"{metric_id}: expected 0.72 after renorm, got {score}"
            )

    def test_returns_none_when_no_metrics(self) -> None:
        assert _empirical_score([]) is None

    def test_full_suite_produces_sensible_composite(self) -> None:
        """All medium/high-suite metrics present → score in (0, 1]."""
        full_suite = [
            _m("context_relevance_tfidf",      0.65, threshold=0.20),
            _m("context_relevance_embedding",   0.80, threshold=0.50),
            _m("output_support_tfidf",          0.55, threshold=0.20),
            _m("output_support_embedding",      0.75, threshold=0.45),
            _m("lexical_grounding_precision",   0.72, threshold=0.25),
            _m("claim_coverage_recall",         0.48, threshold=0.10),
            _m("reliability",                   0.88, threshold=0.80),
            _m("refusal_correctness",           0.92, threshold=0.82),
            _m("unanswerable_handling",         0.85, threshold=0.80),
        ]
        score = _empirical_score(full_suite)
        assert score is not None
        assert 0.0 < score <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# _metric_z_value — sign convention for lower-is-better metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricZValueSign:
    """For lower-is-better metrics (contradiction_rate, unsupported_claim_rate)
    a positive z must mean "performing well" (value below threshold).
    The raw margin value−threshold has the opposite sign and must be negated.
    """

    def test_low_contradiction_rate_gives_positive_z(self) -> None:
        """contradiction_rate=0.01, threshold=0.05 → value < threshold → good → z > 0."""
        z = _metric_z_value(_m("contradiction_rate", 0.01, threshold=0.05))
        assert z is not None and z > 0, f"Expected z > 0, got {z}"

    def test_high_contradiction_rate_gives_negative_z(self) -> None:
        """contradiction_rate=0.20 >> threshold=0.05 → bad → z < 0."""
        z = _metric_z_value(_m("contradiction_rate", 0.20, threshold=0.05))
        assert z is not None and z < 0, f"Expected z < 0, got {z}"

    def test_at_threshold_gives_zero_z(self) -> None:
        """Exactly at threshold → z = 0 regardless of direction."""
        z = _metric_z_value(_m("contradiction_rate", 0.05, threshold=0.05))
        assert z is not None and z == pytest.approx(0.0, abs=1e-4)

    def test_magnitude_increases_with_distance_from_threshold(self) -> None:
        z_close = _metric_z_value(_m("contradiction_rate", 0.04, threshold=0.05))
        z_far   = _metric_z_value(_m("contradiction_rate", 0.00, threshold=0.05))
        assert z_close is not None and z_far is not None
        assert 0 < z_close < z_far  # further below threshold → larger positive z

    def test_normal_metric_sign_unchanged(self) -> None:
        """Standard metric (higher is better): z > 0 when above threshold."""
        z = _metric_z_value(_m("claim_support_rate", 0.9, threshold=0.65))
        assert z is not None and z > 0

    def test_unsupported_claim_rate_sign_correct(self) -> None:
        """unsupported_claim_rate=0.05 below threshold=0.22 → good → z > 0."""
        z = _metric_z_value(_m("unsupported_claim_rate", 0.05, threshold=0.22))
        assert z is not None and z > 0, f"Expected z > 0, got {z}"


# ─────────────────────────────────────────────────────────────────────────────
# _trust_z_score — complement and tfidf/embedding deduplication
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustZScoreDeduplication:
    """_trust_z_score must not double-count (a) exact-complement pairs and
    (b) tfidf/embedding variants of the same construct."""

    def test_unsupported_claim_rate_excluded_as_complement(self) -> None:
        """Adding unsupported_claim_rate (= 1−claim_support_rate) must not change z."""
        without = [_m("claim_support_rate", 0.9, threshold=0.75)]
        with_complement = without + [_m("unsupported_claim_rate", 0.1, threshold=0.22)]
        assert _trust_z_score(without) == _trust_z_score(with_complement), (
            "Complement metric should be excluded to avoid double-counting"
        )

    def test_complement_exclusion_preserves_primary_signal(self) -> None:
        """claim_support_rate z-score must still be positive after complement removal."""
        results = [_m("claim_support_rate", 0.9, threshold=0.75)]
        z = _trust_z_score(results)
        assert z is not None and z > 0

    def test_output_support_tfidf_suppressed_when_embedding_present(self) -> None:
        """When output_support_embedding is present, output_support_tfidf is skipped."""
        embedding_only = [
            _m("output_support_embedding", 0.85, threshold=0.5),
            _m("reliability",              0.9,  threshold=0.8),
        ]
        both_variants = [
            _m("output_support_tfidf",     0.3,  threshold=0.2),   # lower signal
            _m("output_support_embedding", 0.85, threshold=0.5),
            _m("reliability",              0.9,  threshold=0.8),
        ]
        assert _trust_z_score(embedding_only) == _trust_z_score(both_variants), (
            "output_support_tfidf z should be suppressed when embedding is present"
        )

    def test_context_relevance_tfidf_suppressed_when_embedding_present(self) -> None:
        embedding_only = [
            _m("context_relevance_embedding", 0.8, threshold=0.5),
            _m("reliability",                 0.9, threshold=0.8),
        ]
        both_variants = [
            _m("context_relevance_tfidf",     0.3, threshold=0.2),
            _m("context_relevance_embedding", 0.8, threshold=0.5),
            _m("reliability",                 0.9, threshold=0.8),
        ]
        assert _trust_z_score(embedding_only) == _trust_z_score(both_variants)

    def test_tfidf_kept_when_embedding_absent(self) -> None:
        """TF-IDF variant contributes when no embedding counterpart is present."""
        results = [_m("output_support_tfidf", 0.7, threshold=0.2)]
        z = _trust_z_score(results)
        assert z is not None and z > 0

    def test_low_contradiction_rate_raises_aggregate_z(self) -> None:
        """After sign fix, low contradiction_rate gives positive z contribution."""
        without_contradiction = [_m("reliability", 0.85, threshold=0.8)]
        with_low_contradiction = [
            _m("reliability",        0.85, threshold=0.80),
            _m("contradiction_rate", 0.01, threshold=0.05),
        ]
        z_without = _trust_z_score(without_contradiction)
        z_with    = _trust_z_score(with_low_contradiction)
        assert z_without is not None and z_with is not None
        assert z_with > z_without, (
            "Low contradiction_rate (good) should raise the aggregate z, not lower it"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _metric_strength_map — unsupported_claim_rate label
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricStrengthMap:
    """unsupported_claim_rate = 1 − claim_support_rate.  Labelling it 'strong'
    alongside claim_support_rate implies two independent strong signals when
    there is only one.  It must be demoted to 'moderate'.
    """

    def test_unsupported_claim_rate_not_labelled_strong(self) -> None:
        results = [
            _m("claim_support_rate",    0.9),
            _m("unsupported_claim_rate", 0.1),
        ]
        strength_map = _metric_strength_map(results)
        label = strength_map.get("unsupported_claim_rate")
        assert label != "strong", (
            f"unsupported_claim_rate is a derived complement and must not be 'strong'. Got {label!r}"
        )

    def test_unsupported_claim_rate_labelled_moderate(self) -> None:
        results = [_m("unsupported_claim_rate", 0.1)]
        assert _metric_strength_map(results)["unsupported_claim_rate"] == "moderate"

    def test_claim_support_rate_remains_strong(self) -> None:
        """The primary grounding signal stays strong."""
        results = [_m("claim_support_rate", 0.9)]
        assert _metric_strength_map(results)["claim_support_rate"] == "strong"

    def test_contradiction_rate_remains_strong(self) -> None:
        """contradiction_rate is independent of claim_support_rate — stays strong."""
        results = [_m("contradiction_rate", 0.02)]
        assert _metric_strength_map(results)["contradiction_rate"] == "strong"


# ─────────────────────────────────────────────────────────────────────────────
# _answer_trust_score — regression guard
# ─────────────────────────────────────────────────────────────────────────────

class TestAnswerTrustScoreRegression:
    """Ensure previously fixed _answer_trust_score does not regress."""

    def test_complement_not_included(self) -> None:
        without = [
            _m("claim_support_rate",       0.9, threshold=0.65),
            _m("contradiction_rate",        0.0, threshold=0.05),
            _m("evidence_sufficiency_score", 0.8, threshold=0.58),
            _m("output_support_embedding",  0.85, threshold=0.45),
        ]
        with_complement = without + [_m("unsupported_claim_rate", 0.1, threshold=0.22)]
        assert _answer_trust_score(without) == _answer_trust_score(with_complement)

    def test_contradiction_is_multiplicative(self) -> None:
        """High contradiction_rate cannot be averaged away by high grounding."""
        good = [
            _m("claim_support_rate",        0.9, threshold=0.65),
            _m("contradiction_rate",         0.0, threshold=0.05),
            _m("evidence_sufficiency_score", 0.8, threshold=0.58),
        ]
        contradicting = [
            _m("claim_support_rate",        0.9, threshold=0.65),
            _m("contradiction_rate",        0.25, threshold=0.05),
            _m("evidence_sufficiency_score", 0.8, threshold=0.58),
        ]
        assert _answer_trust_score(good) is not None
        assert _answer_trust_score(contradicting) is not None
        assert _answer_trust_score(good) > 0.7
        assert _answer_trust_score(contradicting) < 0.3

    def test_catastrophic_contradiction_does_not_zero_supported_answer(self) -> None:
        """A contradictory but source-overlapping answer should be low, not displayed as 0%."""
        result = [
            _m("claim_support_rate", 1.0, threshold=0.65),
            _m("contradiction_rate", 0.40, threshold=0.05),
            _m("evidence_sufficiency_score", 1.0, threshold=0.58),
            _m("output_support_tfidf", 0.50, threshold=0.2),
        ]

        score = _answer_trust_score(result)

        assert score is not None
        assert 0.1 < score < 0.3

    def test_geometric_mean_on_correlated_pair(self) -> None:
        """High CSR + low ESS → geo-mean penalty; arithmetic mean would over-report."""
        asymmetric = [
            _m("claim_support_rate",        0.9, threshold=0.65),
            _m("evidence_sufficiency_score", 0.1, threshold=0.58),
            _m("contradiction_rate",         0.0, threshold=0.05),
        ]
        score = _answer_trust_score(asymmetric)
        assert score is not None and score < 0.45
