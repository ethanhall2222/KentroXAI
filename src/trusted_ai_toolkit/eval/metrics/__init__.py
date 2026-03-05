"""Metric registry and stub metric implementations."""

from __future__ import annotations

from typing import Callable

from trusted_ai_toolkit.eval.metrics.aif360_compat import (
    average_odds_difference,
    disparate_impact_ratio,
    equal_opportunity_difference,
    statistical_parity_difference,
)
from trusted_ai_toolkit.schemas import MetricResult

MetricFn = Callable[[dict], MetricResult]


def metric_reliability(context: dict) -> MetricResult:
    """Deterministic reliability/consistency stub metric."""

    return MetricResult(metric_id="reliability", value=0.83, details={"method": "consistency_stub_v1"})


def metric_groundedness_stub(context: dict) -> MetricResult:
    """Deterministic groundedness proxy metric."""

    return MetricResult(metric_id="groundedness_stub", value=0.72, details={"method": "retrieval_alignment_stub"})


def metric_fairness_demographic_parity_diff(context: dict) -> MetricResult:
    """Toy demographic parity difference inspired by fairness checks.

    Reference inspiration:
    - https://github.com/Trusted-AI/AIF360
    """

    # Deterministic synthetic cohorts for offline baseline checks.
    # TODO: replace with actual cohort labels from evaluation dataset.
    reference_group_labels = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    comparison_group_labels = [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]
    value = round(statistical_parity_difference(comparison_group_labels, reference_group_labels), 3)
    return MetricResult(
        metric_id="fairness_demographic_parity_diff",
        value=value,
        details={
            "sensitive_features": context.get("sensitive_features", []),
            "reference_group_selection_rate": round(sum(reference_group_labels) / len(reference_group_labels), 3),
            "comparison_group_selection_rate": round(sum(comparison_group_labels) / len(comparison_group_labels), 3),
            "formula": "Pr(Y=1|comparison_group)-Pr(Y=1|reference_group)",
            "reference": "https://github.com/Trusted-AI/AIF360",
        },
    )


def metric_accuracy_stub(context: dict) -> MetricResult:
    """Deterministic performance metric placeholder."""

    return MetricResult(metric_id="accuracy_stub", value=0.81, details={"dataset": context.get("dataset_name", "unknown")})


def metric_fairness_disparate_impact_ratio(context: dict) -> MetricResult:
    """AIF360-inspired disparate impact ratio fairness metric."""

    reference_group_labels = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    comparison_group_labels = [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]
    value = round(disparate_impact_ratio(comparison_group_labels, reference_group_labels), 3)
    return MetricResult(
        metric_id="fairness_disparate_impact_ratio",
        value=value,
        details={
            "formula": "Pr(Y=1|comparison_group)/Pr(Y=1|reference_group)",
            "reference": "https://github.com/Trusted-AI/AIF360",
            "policy_baseline": ">= 0.8 (80% rule heuristic)",
        },
    )


def metric_fairness_equal_opportunity_difference(context: dict) -> MetricResult:
    """AIF360-inspired equal opportunity difference fairness metric."""

    reference_group_true = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    reference_group_pred = [1, 1, 1, 0, 1, 0, 1, 0, 0, 1]
    comparison_group_true = [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]
    comparison_group_pred = [1, 0, 1, 0, 0, 0, 0, 1, 0, 1]
    value = round(
        equal_opportunity_difference(
            comparison_group_true, comparison_group_pred, reference_group_true, reference_group_pred
        ),
        3,
    )
    return MetricResult(
        metric_id="fairness_equal_opportunity_difference",
        value=value,
        details={
            "formula": "TPR(comparison_group)-TPR(reference_group)",
            "reference": "https://github.com/Trusted-AI/AIF360",
        },
    )


def metric_fairness_average_odds_difference(context: dict) -> MetricResult:
    """AIF360-inspired average odds difference fairness metric."""

    reference_group_true = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    reference_group_pred = [1, 1, 1, 0, 1, 0, 1, 0, 0, 1]
    comparison_group_true = [1, 0, 1, 0, 1, 0, 0, 1, 0, 1]
    comparison_group_pred = [1, 0, 1, 0, 0, 0, 0, 1, 0, 1]
    value = round(
        average_odds_difference(
            comparison_group_true, comparison_group_pred, reference_group_true, reference_group_pred
        ),
        3,
    )
    return MetricResult(
        metric_id="fairness_average_odds_difference",
        value=value,
        details={
            "formula": "0.5 * ((FPR(comparison_group)-FPR(reference_group)) + (TPR(comparison_group)-TPR(reference_group)))",
            "reference": "https://github.com/Trusted-AI/AIF360",
        },
    )


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
    "fairness_disparate_impact_ratio": metric_fairness_disparate_impact_ratio,
    "fairness_equal_opportunity_difference": metric_fairness_equal_opportunity_difference,
    "fairness_average_odds_difference": metric_fairness_average_odds_difference,
    "accuracy_stub": metric_accuracy_stub,
    "refusal_correctness": metric_refusal_correctness,
    "unanswerable_handling": metric_unanswerable_handling,
}
