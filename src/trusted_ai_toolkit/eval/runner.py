"""Evaluation harness for Measure workflows and score inputs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from trusted_ai_toolkit.eval.metrics import METRICS_REGISTRY
from trusted_ai_toolkit.monitoring import TelemetryLogger
from trusted_ai_toolkit.schemas import EvalResult, MetricResult, ToolkitConfig


def _load_suite_definition(suite_name: str, config_path: Path | None = None) -> dict[str, Any]:
    """Resolve suite YAML from project local suites or package defaults."""

    candidate_paths: list[Path] = []
    if config_path is not None:
        candidate_paths.append(config_path.parent / "suites" / f"{suite_name}.yaml")
    candidate_paths.append(Path.cwd() / "suites" / f"{suite_name}.yaml")
    candidate_paths.append(Path(__file__).resolve().parent / "suites" / f"{suite_name}.yaml")

    for path in candidate_paths:
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data

    raise FileNotFoundError(f"Suite definition not found for '{suite_name}'")


def _metric_passed(metric_id: str, value: float, threshold: float | None) -> bool | None:
    """Apply metric-specific pass/fail semantics."""

    if threshold is None:
        return None
    if metric_id == "fairness_demographic_parity_diff":
        return value <= threshold
    return value >= threshold


def run_eval(
    config: ToolkitConfig,
    run_id: str,
    telemetry: TelemetryLogger | None = None,
    config_path: Path | None = None,
) -> list[EvalResult]:
    """Execute configured evaluation suites and return result payloads."""

    results: list[EvalResult] = []

    for suite_name in config.eval.suites:
        suite_def = _load_suite_definition(suite_name, config_path=config_path)
        metric_ids = suite_def.get("metrics", config.eval.metrics)
        cases = suite_def.get("cases", [])
        unsafe_cases = sum(1 for case in cases if isinstance(case, dict) and case.get("kind") == "unsafe")
        unanswerable_cases = sum(1 for case in cases if isinstance(case, dict) and case.get("kind") == "unanswerable")

        metric_results: list[MetricResult] = []
        started = datetime.now(timezone.utc)
        context = {
            "dataset_name": config.data.dataset_name if config.data else "unknown",
            "sensitive_features": config.data.sensitive_features if config.data else [],
            "risk_tier": config.risk_tier,
            "suite": suite_name,
            "total_cases": len(cases),
            "unsafe_cases": unsafe_cases,
            "unanswerable_cases": unanswerable_cases,
        }

        for metric_id in metric_ids:
            metric_fn = METRICS_REGISTRY.get(metric_id)
            if metric_fn is None:
                continue
            metric_result = metric_fn(context)
            suite_thresholds = suite_def.get("thresholds", {})
            threshold = config.eval.thresholds.get(metric_id, suite_thresholds.get(metric_id))
            metric_result.threshold = threshold
            metric_result.passed = _metric_passed(metric_id, metric_result.value, threshold)
            metric_results.append(metric_result)

            if telemetry:
                telemetry.log_event(
                    "METRIC_COMPUTED",
                    "eval",
                    {
                        "suite": suite_name,
                        "metric_id": metric_id,
                        "value": metric_result.value,
                        "threshold": threshold,
                        "passed": metric_result.passed,
                    },
                )

        notes: list[str] = []
        notes.append(f"Golden cases executed: {len(cases)}")
        if config.risk_tier == "high":
            notes.append("High risk tier: red-team completion is required before final sign-off.")

        completed = datetime.now(timezone.utc)
        overall_passed = all(m.passed is not False for m in metric_results)
        result = EvalResult(
            suite_name=suite_name,
            run_id=run_id,
            started_at=started,
            completed_at=completed,
            metric_results=metric_results,
            overall_passed=overall_passed,
            notes=notes,
        )
        results.append(result)

    return results
