"""AIF360-inspired fairness metric helpers.

This module adapts core fairness metric formulas from AIF360 concepts
(Statistical Parity Difference and Disparate Impact Ratio) into a
lightweight, dependency-free implementation.

Reference:
- https://github.com/Trusted-AI/AIF360
- Apache-2.0 licensed project
"""

from __future__ import annotations


def _selection_rate(labels: list[int]) -> float:
    """Compute selection rate Pr(Y=1) for binary labels."""

    if not labels:
        return 0.0
    positives = sum(1 for value in labels if int(value) == 1)
    return positives / len(labels)


def statistical_parity_difference(comparison_group_labels: list[int], reference_group_labels: list[int]) -> float:
    """Compute SPD = Pr(Y=1 | comparison group) - Pr(Y=1 | reference group)."""

    return _selection_rate(comparison_group_labels) - _selection_rate(reference_group_labels)


def disparate_impact_ratio(comparison_group_labels: list[int], reference_group_labels: list[int]) -> float:
    """Compute DIR = Pr(Y=1 | comparison group) / Pr(Y=1 | reference group)."""

    reference_rate = _selection_rate(reference_group_labels)
    if reference_rate == 0:
        return 0.0
    return _selection_rate(comparison_group_labels) / reference_rate


def _true_positive_rate(y_true: list[int], y_pred: list[int]) -> float:
    positives = [idx for idx, label in enumerate(y_true) if int(label) == 1]
    if not positives:
        return 0.0
    tp = sum(1 for idx in positives if int(y_pred[idx]) == 1)
    return tp / len(positives)


def _false_positive_rate(y_true: list[int], y_pred: list[int]) -> float:
    negatives = [idx for idx, label in enumerate(y_true) if int(label) == 0]
    if not negatives:
        return 0.0
    fp = sum(1 for idx in negatives if int(y_pred[idx]) == 1)
    return fp / len(negatives)


def equal_opportunity_difference(
    comparison_group_true: list[int],
    comparison_group_pred: list[int],
    reference_group_true: list[int],
    reference_group_pred: list[int],
) -> float:
    """Compute EOD = TPR(comparison group) - TPR(reference group)."""

    return _true_positive_rate(comparison_group_true, comparison_group_pred) - _true_positive_rate(
        reference_group_true, reference_group_pred
    )


def average_odds_difference(
    comparison_group_true: list[int],
    comparison_group_pred: list[int],
    reference_group_true: list[int],
    reference_group_pred: list[int],
) -> float:
    """Compute AOD = 0.5 * ((FPR comparison - FPR reference) + (TPR comparison - TPR reference))."""

    fpr_delta = _false_positive_rate(comparison_group_true, comparison_group_pred) - _false_positive_rate(
        reference_group_true, reference_group_pred
    )
    tpr_delta = _true_positive_rate(comparison_group_true, comparison_group_pred) - _true_positive_rate(
        reference_group_true, reference_group_pred
    )
    return 0.5 * (fpr_delta + tpr_delta)
