"""Metric registry and stub metric implementations."""

from __future__ import annotations

from typing import Callable

from trusted_ai_toolkit.schemas import MetricResult

MetricFn = Callable[[dict], MetricResult]


def metric_reliability(context: dict) -> MetricResult:
    """Deterministic reliability/consistency stub metric."""

    return MetricResult(metric_id="reliability", value=0.83, details={"method": "consistency_stub_v1"})


def metric_groundedness_stub(context: dict) -> MetricResult:
    """Deterministic groundedness proxy metric."""

    return MetricResult(metric_id="groundedness_stub", value=0.72, details={"method": "retrieval_alignment_stub"})


def metric_fairness_demographic_parity_diff(context: dict) -> MetricResult:
    """Toy demographic parity difference inspired by fairness checks."""

    sensitive_features = context.get("sensitive_features", [])
    penalty = 0.02 * len(sensitive_features)
    value = round(max(0.0, 0.18 - penalty), 3)
    return MetricResult(
        metric_id="fairness_demographic_parity_diff",
        value=value,
        details={
            "sensitive_features": sensitive_features,
            "note": "Lower is better for parity difference",
        },
    )


def metric_accuracy_stub(context: dict) -> MetricResult:
    """Deterministic performance metric placeholder."""

    return MetricResult(metric_id="accuracy_stub", value=0.81, details={"dataset": context.get("dataset_name", "unknown")})


def metric_refusal_correctness(context: dict) -> MetricResult:
    """Deterministic refusal correctness stub based on case mix."""

    unsafe_cases = context.get("unsafe_cases", 0)
    total_cases = max(context.get("total_cases", 1), 1)
    ratio = unsafe_cases / total_cases
    value = round(max(0.65, 0.93 - ratio * 0.1), 3)
    return MetricResult(metric_id="refusal_correctness", value=value, details={"unsafe_cases": unsafe_cases})


def metric_unanswerable_handling(context: dict) -> MetricResult:
    """Deterministic unanswerable handling stub based on case mix."""

    unanswerable_cases = context.get("unanswerable_cases", 0)
    total_cases = max(context.get("total_cases", 1), 1)
    ratio = unanswerable_cases / total_cases
    value = round(max(0.6, 0.9 - ratio * 0.08), 3)
    return MetricResult(
        metric_id="unanswerable_handling",
        value=value,
        details={"unanswerable_cases": unanswerable_cases},
    )


METRICS_REGISTRY: dict[str, MetricFn] = {
    "reliability": metric_reliability,
    "groundedness_stub": metric_groundedness_stub,
    "fairness_demographic_parity_diff": metric_fairness_demographic_parity_diff,
    "accuracy_stub": metric_accuracy_stub,
    "refusal_correctness": metric_refusal_correctness,
    "unanswerable_handling": metric_unanswerable_handling,
}
