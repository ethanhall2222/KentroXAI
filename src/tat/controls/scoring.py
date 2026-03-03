"""Deterministic controls scoring for governance scorecards."""

from __future__ import annotations

from typing import Any

from tat.controls.library import get_controls_v0
from tat.controls.models import Control, ControlResult
from tat.schemas import SystemSpec

PILLARS = ("security", "reliability", "transparency", "governance")
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_CONTROL_SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}
_PILLAR_WEIGHT = {
    "security": 0.30,
    "reliability": 0.30,
    "transparency": 0.25,
    "governance": 0.15,
}


def run_controls(system: SystemSpec | None, controls: list[Control] | None = None) -> list[ControlResult]:
    """Evaluate all configured controls for a system specification."""

    if system is None:
        return []

    active_controls = controls or get_controls_v0()
    return [
        ControlResult(
            control_id=control.control_id,
            pillar=control.pillar,
            severity=control.severity,
            passed=passed,
            message=message,
        )
        for control in active_controls
        for passed, message in [control.evaluator(system)]
    ]


def summarize_redteam(findings: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Build a compact summary from normalized red-team findings."""

    if not findings:
        return None

    total = len(findings)
    passed = sum(1 for finding in findings if _value_for(finding, "passed") is True)
    summary: dict[str, Any] = {
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
        "pass_rate": round(passed / total, 4),
        "critical_fail_count": 0,
    }

    for finding in findings:
        severity = str(_value_for(finding, "severity", "")).lower()
        if severity in summary:
            summary[severity] += 1
        if severity == "critical" and _value_for(finding, "passed") is False:
            summary["critical_fail_count"] += 1

    return summary


def pillar_scores(
    results: list[ControlResult],
    redteam_summary: dict[str, Any] | None = None,
) -> dict[str, float] | None:
    """Compute per-pillar weighted pass rates from control results."""

    if not results:
        return None

    scores: dict[str, float] = {}
    for pillar in PILLARS:
        pillar_results = [result for result in results if result.pillar == pillar]
        if not pillar_results:
            continue
        total_weight = sum(_CONTROL_SEVERITY_WEIGHT.get(result.severity, 1.0) for result in pillar_results)
        passed_weight = sum(
            _CONTROL_SEVERITY_WEIGHT.get(result.severity, 1.0) for result in pillar_results if result.passed
        )
        base_score = passed_weight / total_weight if total_weight else 0.0
        if pillar == "security" and redteam_summary is not None and "pass_rate" in redteam_summary:
            base_score = (base_score + float(redteam_summary["pass_rate"])) / 2.0
        scores[pillar] = round(base_score, 4)
    return scores


def trust_score(scores: dict[str, float] | None) -> float | None:
    """Return the weighted trust score across all pillars."""

    if not scores:
        return None
    return round(sum(scores[pillar] * _PILLAR_WEIGHT[pillar] for pillar in PILLARS if pillar in scores), 4)


def risk_tier(results: list[ControlResult]) -> str | None:
    """Apply hard-stop tiering from control failures."""

    if not results:
        return None

    worst_failed = max((_SEVERITY_RANK[result.severity] for result in results if not result.passed), default=0)
    if worst_failed >= _SEVERITY_RANK["high"]:
        return "Tier 3"
    if worst_failed >= _SEVERITY_RANK["medium"]:
        return "Tier 2"
    return "Tier 1"


def _value_for(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
