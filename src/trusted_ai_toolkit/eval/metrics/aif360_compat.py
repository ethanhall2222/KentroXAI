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


def statistical_parity_difference(unprivileged_labels: list[int], privileged_labels: list[int]) -> float:
    """Compute SPD = Pr(Y=1 | unprivileged) - Pr(Y=1 | privileged)."""

    return _selection_rate(unprivileged_labels) - _selection_rate(privileged_labels)


def disparate_impact_ratio(unprivileged_labels: list[int], privileged_labels: list[int]) -> float:
    """Compute DIR = Pr(Y=1 | unprivileged) / Pr(Y=1 | privileged)."""

    privileged_rate = _selection_rate(privileged_labels)
    if privileged_rate == 0:
        return 0.0
    return _selection_rate(unprivileged_labels) / privileged_rate


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
    unprivileged_true: list[int],
    unprivileged_pred: list[int],
    privileged_true: list[int],
    privileged_pred: list[int],
) -> float:
    """Compute EOD = TPR(unprivileged) - TPR(privileged)."""

    return _true_positive_rate(unprivileged_true, unprivileged_pred) - _true_positive_rate(
        privileged_true, privileged_pred
    )


def average_odds_difference(
    unprivileged_true: list[int],
    unprivileged_pred: list[int],
    privileged_true: list[int],
    privileged_pred: list[int],
) -> float:
    """Compute AOD = 0.5 * ((FPR_u - FPR_p) + (TPR_u - TPR_p))."""

    fpr_delta = _false_positive_rate(unprivileged_true, unprivileged_pred) - _false_positive_rate(
        privileged_true, privileged_pred
    )
    tpr_delta = _true_positive_rate(unprivileged_true, unprivileged_pred) - _true_positive_rate(
        privileged_true, privileged_pred
    )
    return 0.5 * (fpr_delta + tpr_delta)
