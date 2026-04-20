"""Tests for the tier-aware _answer_verdict function.

Problem 3 — Differentiated card penalties:
  The TYPE of consequence for the same metric failure differs by risk tier.
  Bias at high risk is a hard block; at medium it is caution; at low it needs
  multiple signals.  Multiple simultaneous caution signals escalate to
  not_trusted at high risk.

Problem 4 — Adaptive verdict thresholds:
  All numeric boundaries (contradiction, unsupported, support, sufficiency,
  composite score) scale with risk tier.  A reading that is "trusted" at low
  risk may be "not_trusted" at high risk.
"""

from __future__ import annotations

import pytest

from trusted_ai_toolkit.reporting import (
    _answer_verdict,
    _normalize_risk_tier,
    _RISK_TIER_ALIASES,
    _VERDICT_THRESHOLDS,
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


def _bias(count: int) -> MetricResult:
    return MetricResult(
        metric_id="bias_signal_score",
        value=1.0 if count == 0 else max(0.0, 1.0 - count * 0.1),
        threshold=None, passed=True,
        details={"signal_count": count},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Problem 4 — Adaptive numeric thresholds
# ─────────────────────────────────────────────────────────────────────────────

class TestAdaptiveThresholds:
    """The same metric value produces different verdicts across risk tiers."""

    # ── Contradiction rate ────────────────────────────────────────────────────

    def test_contradiction_0_04_trusted_at_low(self) -> None:
        """0.04 < low limit 0.10 → no hard gate fires."""
        verdict, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="low"
        )
        assert verdict != "not_trusted"

    def test_contradiction_0_04_trusted_at_medium(self) -> None:
        """0.04 < medium limit 0.05 → no hard gate fires."""
        verdict, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="medium"
        )
        assert verdict != "not_trusted"

    def test_contradiction_0_04_not_trusted_at_high(self) -> None:
        """0.04 > high limit 0.02 → hard gate fires."""
        verdict, reasons = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="high"
        )
        assert verdict == "not_trusted"
        assert any("contradiction" in r.lower() for r in reasons)

    def test_contradiction_threshold_ordering_preserved(self) -> None:
        """low limit > medium limit > high limit (thresholds get stricter)."""
        t = _VERDICT_THRESHOLDS
        assert (
            t["low"]["not_trusted_contradiction"]
            > t["medium"]["not_trusted_contradiction"]
            > t["high"]["not_trusted_contradiction"]
        )

    # ── Unsupported claim rate ────────────────────────────────────────────────

    def test_unsupported_0_25_all_tiers(self) -> None:
        """0.25 is below medium (0.35) and low (0.50) limits → no hard gate.
        But exceeds high limit (0.20) → not_trusted at high."""
        results = [_m("unsupported_claim_rate", 0.25)]
        v_low,    _ = _answer_verdict(results, risk_tier="low")
        v_medium, _ = _answer_verdict(results, risk_tier="medium")
        v_high,   _ = _answer_verdict(results, risk_tier="high")
        assert v_low    != "not_trusted"
        assert v_medium != "not_trusted"
        assert v_high   == "not_trusted"

    # ── Support rate caution ─────────────────────────────────────────────────

    def test_support_0_55_only_caution_at_medium_not_low(self) -> None:
        """0.55 is above low caution bar (0.50) but below medium (0.70)."""
        results = [_m("claim_support_rate", 0.55)]
        v_low,    _ = _answer_verdict(results, risk_tier="low")
        v_medium, _ = _answer_verdict(results, risk_tier="medium")
        assert v_low    == "trusted"
        assert v_medium == "use_caution"

    def test_support_0_75_caution_at_high_only(self) -> None:
        """0.75 passes medium (needs ≥0.70) but is below high bar (0.80)."""
        results = [_m("claim_support_rate", 0.75)]
        v_medium, _ = _answer_verdict(results, risk_tier="medium")
        v_high,   _ = _answer_verdict(results, risk_tier="high")
        assert v_medium == "trusted"
        assert v_high   == "use_caution"

    # ── Evidence sufficiency caution ─────────────────────────────────────────

    def test_sufficiency_0_50_caution_at_medium_not_low(self) -> None:
        """0.50 is above low bar (0.45) but below medium (0.60)."""
        results = [_m("evidence_sufficiency_score", 0.50)]
        v_low,    _ = _answer_verdict(results, risk_tier="low")
        v_medium, _ = _answer_verdict(results, risk_tier="medium")
        assert v_low    == "trusted"
        assert v_medium == "use_caution"

    def test_sufficiency_caution_threshold_ordering_preserved(self) -> None:
        t = _VERDICT_THRESHOLDS
        assert (
            t["low"]["caution_sufficiency_below"]
            < t["medium"]["caution_sufficiency_below"]
            < t["high"]["caution_sufficiency_below"]
        )

    # ── Composite answer_trust_score gate ────────────────────────────────────

    def test_low_answer_score_not_trusted_at_high_only(self) -> None:
        """answer_trust_score=0.35 is below high not_trusted gate (0.40)
        but no gate applies at medium/low."""
        results = [_m("claim_support_rate", 0.9)]   # passing metric to enter logic
        v_low,    _ = _answer_verdict(results, risk_tier="low",    answer_trust_score=0.35)
        v_medium, _ = _answer_verdict(results, risk_tier="medium", answer_trust_score=0.35)
        v_high,   _ = _answer_verdict(results, risk_tier="high",   answer_trust_score=0.35)
        assert v_low    != "not_trusted"
        assert v_medium != "not_trusted"
        assert v_high   == "not_trusted"

    def test_medium_answer_score_caution_at_high(self) -> None:
        """answer_trust_score=0.55 is between high caution gate (0.60) and
        not_trusted gate (0.40) → use_caution at high (assuming no other gates)."""
        # Use passing individual metrics so no other signal fires
        results = [_m("claim_support_rate", 0.9), _m("evidence_sufficiency_score", 0.85)]
        v_high, _ = _answer_verdict(results, risk_tier="high", answer_trust_score=0.55)
        # 0.55 < caution_answer_score=0.60 → caution fires, but only 1 caution signal
        assert v_high == "use_caution"

    def test_absent_answer_score_does_not_trigger_gate(self) -> None:
        """None answer_trust_score means the composite gate is skipped entirely."""
        results = [_m("claim_support_rate", 0.9)]
        v, _ = _answer_verdict(results, risk_tier="high", answer_trust_score=None)
        # Only the composite gate would fire; since it's None the result should be trusted
        assert v == "trusted"


# ─────────────────────────────────────────────────────────────────────────────
# Problem 3 — Differentiated card penalties
# ─────────────────────────────────────────────────────────────────────────────

class TestDifferentiatedPenalties:
    """The CONSEQUENCE of the same failure differs by tier."""

    # ── Bias signal policy ───────────────────────────────────────────────────

    def test_bias_is_not_trusted_at_high_risk(self) -> None:
        """Any bias signal triggers not_trusted at high risk (hard block)."""
        results = [
            _m("claim_support_rate", 0.9),
            _bias(1),
        ]
        verdict, reasons = _answer_verdict(results, risk_tier="high")
        assert verdict == "not_trusted"
        assert any("bias" in r.lower() or "signal" in r.lower() for r in reasons)

    def test_bias_is_use_caution_at_medium_risk(self) -> None:
        """A single bias signal is only a caution at medium risk."""
        results = [
            _m("claim_support_rate", 0.9),
            _m("evidence_sufficiency_score", 0.85),
            _bias(1),
        ]
        verdict, _ = _answer_verdict(results, risk_tier="medium")
        assert verdict == "use_caution"

    def test_bias_below_threshold_ignored_at_low_risk(self) -> None:
        """Fewer than 3 bias signals do not trigger caution at low risk."""
        results = [
            _m("claim_support_rate", 0.9),
            _m("evidence_sufficiency_score", 0.85),
            _bias(2),
        ]
        verdict, _ = _answer_verdict(results, risk_tier="low")
        assert verdict == "trusted"

    def test_bias_above_threshold_triggers_caution_at_low_risk(self) -> None:
        """3+ bias signals are enough to trigger caution at low risk."""
        results = [
            _m("claim_support_rate", 0.9),
            _m("evidence_sufficiency_score", 0.85),
            _bias(3),
        ]
        verdict, _ = _answer_verdict(results, risk_tier="low")
        assert verdict == "use_caution"

    # ── Multi-caution escalation ──────────────────────────────────────────────

    def test_two_caution_signals_escalate_to_not_trusted_at_high(self) -> None:
        """support < 0.80 AND sufficiency < 0.72 simultaneously → not_trusted at high."""
        results = [
            _m("claim_support_rate",        0.72),   # below high caution bar 0.80
            _m("evidence_sufficiency_score", 0.65),  # below high caution bar 0.72
        ]
        verdict, reasons = _answer_verdict(results, risk_tier="high")
        assert verdict == "not_trusted"
        assert any("escalat" in r.lower() or "compounding" in r.lower() for r in reasons)

    def test_two_caution_signals_stay_use_caution_at_medium(self) -> None:
        """Same two caution signals do NOT escalate at medium risk."""
        results = [
            _m("claim_support_rate",        0.60),   # below medium caution bar 0.70
            _m("evidence_sufficiency_score", 0.55),  # below medium caution bar 0.60
        ]
        verdict, _ = _answer_verdict(results, risk_tier="medium")
        assert verdict == "use_caution"

    def test_single_caution_stays_use_caution_at_high(self) -> None:
        """Only ONE caution signal at high risk stays use_caution (not escalated)."""
        results = [
            _m("claim_support_rate",        0.72),   # below high bar 0.80
            _m("evidence_sufficiency_score", 0.85),  # above high bar 0.72 ✓
        ]
        verdict, _ = _answer_verdict(results, risk_tier="high")
        assert verdict == "use_caution"

    def test_three_caution_signals_escalate_at_high(self) -> None:
        """Three simultaneous caution signals also escalate (≥2 rule)."""
        results = [
            _m("claim_support_rate",        0.72),   # caution
            _m("evidence_sufficiency_score", 0.65),  # caution
            _bias(1),  # bias is a hard block at high risk (fires first)
        ]
        # Bias alone causes not_trusted at high; still confirms not_trusted
        verdict, _ = _answer_verdict(results, risk_tier="high")
        assert verdict == "not_trusted"

    def test_escalation_reason_message_identifies_tier(self) -> None:
        """Escalation reason must mention the risk tier for auditability."""
        results = [
            _m("claim_support_rate",        0.72),
            _m("evidence_sufficiency_score", 0.65),
        ]
        _, reasons = _answer_verdict(results, risk_tier="high")
        assert any("high" in r.lower() for r in reasons)


# ─────────────────────────────────────────────────────────────────────────────
# Reason message quality
# ─────────────────────────────────────────────────────────────────────────────

class TestReasonMessages:
    """Reason messages must include tier context and specific numeric values
    for governance audit trails."""

    def test_contradiction_reason_includes_tier_and_threshold(self) -> None:
        _, reasons = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="high"
        )
        text = " ".join(reasons).lower()
        assert "high" in text
        assert "0.02" in text or "2%" in text   # the tier limit must be stated

    def test_unsupported_reason_includes_tier_and_threshold(self) -> None:
        _, reasons = _answer_verdict(
            [_m("unsupported_claim_rate", 0.25)], risk_tier="high"
        )
        text = " ".join(reasons).lower()
        assert "high" in text

    def test_support_caution_reason_includes_requirement(self) -> None:
        _, reasons = _answer_verdict(
            [_m("claim_support_rate", 0.72)], risk_tier="high"
        )
        text = " ".join(reasons).lower()
        assert "80%" in text or "0.80" in text   # the required threshold

    def test_trusted_verdict_provides_positive_reason(self) -> None:
        results = [
            _m("claim_support_rate", 0.95),
            _m("evidence_sufficiency_score", 0.90),
            _m("contradiction_rate", 0.0),
        ]
        verdict, reasons = _answer_verdict(results, risk_tier="high")
        assert verdict == "trusted"
        assert len(reasons) == 1
        assert "well supported" in reasons[0].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Backward compatibility and edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    """Medium-tier behaviour must exactly match the old hardcoded logic."""

    def test_medium_contradiction_hard_gate(self) -> None:
        verdict, _ = _answer_verdict(
            [_m("contradiction_rate", 0.06)], risk_tier="medium"
        )
        assert verdict == "not_trusted"

    def test_medium_unsupported_hard_gate(self) -> None:
        verdict, _ = _answer_verdict(
            [_m("unsupported_claim_rate", 0.36)], risk_tier="medium"
        )
        assert verdict == "not_trusted"

    def test_medium_low_support_is_caution(self) -> None:
        verdict, _ = _answer_verdict(
            [_m("claim_support_rate", 0.65)], risk_tier="medium"
        )
        assert verdict == "use_caution"

    def test_medium_thin_evidence_is_caution(self) -> None:
        verdict, _ = _answer_verdict(
            [_m("evidence_sufficiency_score", 0.55)], risk_tier="medium"
        )
        assert verdict == "use_caution"

    def test_default_tier_is_medium(self) -> None:
        """Omitting risk_tier defaults to medium behaviour."""
        r1 = _answer_verdict([_m("contradiction_rate", 0.06)])
        r2 = _answer_verdict([_m("contradiction_rate", 0.06)], risk_tier="medium")
        assert r1[0] == r2[0]

    def test_unknown_tier_falls_back_to_medium(self) -> None:
        """Unrecognised tier values fall back to medium thresholds."""
        r_unknown = _answer_verdict(
            [_m("contradiction_rate", 0.06)], risk_tier="enterprise"
        )
        r_medium = _answer_verdict(
            [_m("contradiction_rate", 0.06)], risk_tier="medium"
        )
        assert r_unknown[0] == r_medium[0]

    def test_no_metrics_falls_through_to_trusted(self) -> None:
        """Empty metric_results is vacuously trusted — there is nothing to
        flag.  The end-to-end path through generate_scorecard then downgrades
        to use_caution via the Problem 5 evidence-confidence gate (see
        test_evidence_confidence.py), but the bare verdict layer with no
        confidence dict returns trusted with the standard positive reason."""
        verdict, reasons = _answer_verdict([], risk_tier="medium")
        assert verdict == "trusted"
        assert len(reasons) == 1
        assert "well supported" in reasons[0].lower()

    def test_no_metrics_with_low_confidence_downgrades_to_caution(self) -> None:
        """End-to-end: empty metrics + low confidence dict (which is what
        generate_scorecard always passes) should downgrade to use_caution."""
        verdict, reasons = _answer_verdict(
            [],
            risk_tier="medium",
            evidence_confidence={"tier": "low", "reasons": ["no metrics measured"]},
        )
        assert verdict == "use_caution"
        assert any("evidence confidence is low" in r.lower() for r in reasons)

    def test_tier_1_alias_maps_to_low(self) -> None:
        """`controls_risk_tier()` returns "Tier 1" when no high-severity controls
        failed; this should resolve to the low-risk threshold table."""
        # 0.04 contradiction: trusted at low (limit 0.10), not_trusted at high (0.02)
        v_tier1, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="Tier 1"
        )
        v_low, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="low"
        )
        assert v_tier1 == v_low
        assert v_tier1 != "not_trusted"

    def test_tier_2_alias_maps_to_medium(self) -> None:
        """Tier 2 (medium-severity failed control) → medium thresholds."""
        v_tier2, _ = _answer_verdict(
            [_m("contradiction_rate", 0.06)], risk_tier="Tier 2"
        )
        v_medium, _ = _answer_verdict(
            [_m("contradiction_rate", 0.06)], risk_tier="medium"
        )
        assert v_tier2 == v_medium == "not_trusted"

    def test_tier_3_alias_maps_to_high(self) -> None:
        """Tier 3 (high-severity failed control) → high (strict) thresholds."""
        # 0.04 is below medium gate 0.05 but above high gate 0.02
        v_tier3, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="Tier 3"
        )
        v_high, _ = _answer_verdict(
            [_m("contradiction_rate", 0.04)], risk_tier="high"
        )
        assert v_tier3 == v_high == "not_trusted"

    def test_alias_dict_pinned(self) -> None:
        """Pinned mapping — flipping these values silently inverts every
        verdict for Tier-N inputs.  Any change must be deliberate."""
        assert _RISK_TIER_ALIASES == {
            "Tier 1": "low",
            "Tier 2": "medium",
            "Tier 3": "high",
        }

    def test_normalize_helper_handles_all_inputs(self) -> None:
        # Aliases
        assert _normalize_risk_tier("Tier 1") == "low"
        assert _normalize_risk_tier("Tier 2") == "medium"
        assert _normalize_risk_tier("Tier 3") == "high"
        # Pass-through canonicals
        assert _normalize_risk_tier("low") == "low"
        assert _normalize_risk_tier("medium") == "medium"
        assert _normalize_risk_tier("high") == "high"
        # Robustness — unknowns and None remain backward-compatible (medium)
        assert _normalize_risk_tier("enterprise") == "medium"
        assert _normalize_risk_tier(None) == "medium"

    def test_fully_trusted_at_all_tiers_with_perfect_metrics(self) -> None:
        """Perfect metrics should be 'trusted' regardless of risk tier."""
        perfect = [
            _m("claim_support_rate", 1.0),
            _m("evidence_sufficiency_score", 1.0),
            _m("contradiction_rate", 0.0),
            _m("unsupported_claim_rate", 0.0),
        ]
        for tier in ("low", "medium", "high"):
            verdict, _ = _answer_verdict(perfect, risk_tier=tier, answer_trust_score=0.95)
            assert verdict == "trusted", f"Expected trusted at {tier}, got {verdict}"
