"""Evaluation harness for Measure workflows and score inputs."""

# Design inspiration for fairness-oriented evaluation patterns:
# https://github.com/Trusted-AI/AIF360

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from trusted_ai_toolkit.eval.metrics import METRICS_REGISTRY
from trusted_ai_toolkit.model_client import ModelInvocationError, embed_texts, resolve_embedding_model_name
from trusted_ai_toolkit.monitoring import TelemetryLogger
from trusted_ai_toolkit.schemas import EvalResult, MetricResult, ToolkitConfig

_CONTEXTUAL_METRICS = {
    "groundedness_stub",
    "context_relevance_tfidf",
    "output_support_tfidf",
    "lexical_grounding_precision",
    "claim_coverage_recall",
    "claim_support_rate",
    "unsupported_claim_rate",
    "contradiction_rate",
    "evidence_sufficiency_score",
    "context_relevance_embedding",
    "output_support_embedding",
}
_EMBEDDING_METRICS = {
    "context_relevance_embedding",
    "output_support_embedding",
}
_FAIRNESS_METRICS = {
    "fairness_demographic_parity_diff",
    "fairness_disparate_impact_ratio",
    "fairness_equal_opportunity_difference",
    "fairness_average_odds_difference",
}


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
    if metric_id in {
        "fairness_demographic_parity_diff",
        "fairness_equal_opportunity_difference",
        "fairness_average_odds_difference",
        "unsupported_claim_rate",
        "contradiction_rate",
    }:
        return abs(value) <= threshold
    return value >= threshold


def _load_prompt_bundle(output_dir: str, run_id: str) -> dict[str, Any]:
    path = Path(output_dir) / run_id / "prompt_run.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def compute_embedding_features(config: ToolkitConfig, prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    prompt_text = str(prompt_bundle.get("prompt", ""))
    output_text = str(prompt_bundle.get("model_output", ""))
    contexts = prompt_bundle.get("retrieved_contexts", [])
    context_texts: list[str] = []
    if isinstance(contexts, list):
        for item in contexts:
            if not isinstance(item, dict):
                continue
            merged = " ".join(
                part.strip()
                for part in (
                    str(item.get("title", "")),
                    str(item.get("snippet", "")),
                    str(item.get("text", "")),
                    str(item.get("content", "")),
                )
                if part and part.strip()
            )
            if merged:
                context_texts.append(merged)

    if not prompt_text or not output_text or not context_texts:
        return {"embedding_available": False, "context_count": len(context_texts)}

    try:
        result = embed_texts(
            [prompt_text, output_text, *context_texts],
            config,
            model_name=resolve_embedding_model_name(config),
        )
    except ModelInvocationError as exc:
        return {
            "embedding_available": False,
            "context_count": len(context_texts),
            "error": str(exc),
        }

    vectors = result.embeddings
    if len(vectors) < 2:
        return {"embedding_available": False, "context_count": len(context_texts)}

    return {
        "embedding_available": True,
        "embedding_model": result.model,
        "provider": result.provider,
        "request_url": result.request_url,
        "prompt_vector": vectors[0],
        "output_vector": vectors[1],
        "context_vectors": vectors[2:],
        "request_payload": result.request_payload,
        "response_payload": result.response_payload,
        "context_count": len(context_texts),
    }


def run_eval(
    config: ToolkitConfig,
    run_id: str,
    telemetry: TelemetryLogger | None = None,
    config_path: Path | None = None,
    prompt_bundle: dict[str, Any] | None = None,
    embedding_features: dict[str, Any] | None = None,
) -> list[EvalResult]:
    """Execute configured evaluation suites and return result payloads."""

    results: list[EvalResult] = []

    for suite_name in config.eval.suites:
        suite_def = _load_suite_definition(suite_name, config_path=config_path)
        metric_ids = suite_def.get("metrics", config.eval.metrics)
        cases = suite_def.get("cases", [])
        unsafe_cases = sum(1 for case in cases if isinstance(case, dict) and case.get("kind") == "unsafe")
        unanswerable_cases = sum(1 for case in cases if isinstance(case, dict) and case.get("kind") == "unanswerable")
        active_prompt_bundle = prompt_bundle or _load_prompt_bundle(config.output_dir, run_id)
        active_embedding_features = embedding_features
        if active_embedding_features is None:
            if set(metric_ids).intersection(_EMBEDDING_METRICS):
                active_embedding_features = compute_embedding_features(config, active_prompt_bundle)
            else:
                active_embedding_features = {
                    "embedding_available": False,
                    "reason": "embedding metrics not configured for this suite",
                }

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
            "prompt": str(active_prompt_bundle.get("prompt", "")),
            "model_output": str(active_prompt_bundle.get("model_output", "")),
            "retrieved_contexts": active_prompt_bundle.get("retrieved_contexts", []),
            "fairness_dataset": active_prompt_bundle.get("fairness_dataset"),
            "labeled_evaluation": active_prompt_bundle.get("labeled_evaluation"),
            "embedding_features": active_embedding_features,
        }

        for metric_id in metric_ids:
            metric_fn = METRICS_REGISTRY.get(metric_id)
            if metric_fn is None:
                continue
            metric_result = metric_fn(context)
            suite_thresholds = suite_def.get("thresholds", {})
            threshold = config.eval.thresholds.get(metric_id, suite_thresholds.get(metric_id))
            if metric_id in _CONTEXTUAL_METRICS and not context.get("retrieved_contexts"):
                threshold = None
            if metric_id == "accuracy_stub" and not context.get("labeled_evaluation"):
                threshold = None
            if metric_id in _FAIRNESS_METRICS and not context.get("fairness_dataset"):
                threshold = None
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
