"""Helpers for running Kentro answer-trust workflows inside Databricks.

This module is intentionally lightweight:
- Databricks remains responsible for retrieval and model generation
- Kentro remains responsible for evidence-pack and trust-card generation

The main entrypoint accepts a user question, the final answer text, and the
retrieved chunks that backed the answer. It then reuses the existing workflow
to generate artifacts and returns paths plus parsed scorecard content so a UI
or job can persist the result into Delta.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.cli import _apply_adapter_overrides, _run_prompt_workflow
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.reporting import generate_scorecard
from trusted_ai_toolkit.schemas import ToolkitConfig

_LABEL_KEYS = ("label", "expected_label", "ground_truth", "actual_label", "target")
_PREDICTION_KEYS = ("prediction", "predicted_label", "model_prediction", "answer_label")
_GROUP_KEYS = ("group", "sensitive_group", "cohort", "protected_group", "demographic_group")
_PRIVILEGED_KEYS = ("is_privileged", "privileged")


def _first_present(chunk: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in chunk and chunk[key] is not None:
            return chunk[key]
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        for key in keys:
            if key in metadata and metadata[key] is not None:
                return metadata[key]
    return None


def _coerce_binary_label(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if value in {0, 1}:
            return int(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "pass", "supported", "approved"}:
            return 1
        if normalized in {"0", "false", "no", "fail", "unsupported", "rejected"}:
            return 0
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return None


def _derive_labeled_evaluation(chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    labels: list[int] = []
    predictions: list[int] = []
    dataset_names: set[str] = set()

    for chunk in chunks:
        label = _coerce_binary_label(_first_present(chunk, _LABEL_KEYS))
        prediction = _coerce_binary_label(_first_present(chunk, _PREDICTION_KEYS))
        if label is None or prediction is None:
            continue
        labels.append(label)
        predictions.append(prediction)
        dataset_name = _first_present(chunk, ("dataset_name", "index_name", "source_table", "table_name"))
        if dataset_name:
            dataset_names.add(str(dataset_name))

    if not labels or len(labels) != len(predictions):
        return None

    return {
        "dataset_name": sorted(dataset_names)[0] if dataset_names else "databricks_index_observed_labels",
        "labels": labels,
        "predictions": predictions,
    }


def _derive_fairness_dataset(chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    privileged_labels: list[int] = []
    unprivileged_labels: list[int] = []
    privileged_true: list[int] = []
    privileged_pred: list[int] = []
    unprivileged_true: list[int] = []
    unprivileged_pred: list[int] = []
    sensitive_features: set[str] = set()

    for chunk in chunks:
        label = _coerce_binary_label(_first_present(chunk, _LABEL_KEYS))
        prediction = _coerce_binary_label(_first_present(chunk, _PREDICTION_KEYS))
        privileged = _coerce_bool(_first_present(chunk, _PRIVILEGED_KEYS))
        group = _first_present(chunk, _GROUP_KEYS)
        if privileged is None and group is not None:
            normalized_group = str(group).strip().lower()
            privileged = normalized_group in {"privileged", "control", "reference", "group_a", "a"}
        if privileged is None or label is None:
            continue

        group_name = _first_present(chunk, ("sensitive_feature", "protected_attribute", "group_field"))
        if group_name:
            sensitive_features.add(str(group_name))

        if privileged:
            privileged_labels.append(label)
            if prediction is not None:
                privileged_true.append(label)
                privileged_pred.append(prediction)
        else:
            unprivileged_labels.append(label)
            if prediction is not None:
                unprivileged_true.append(label)
                unprivileged_pred.append(prediction)

    if not privileged_labels or not unprivileged_labels:
        return None

    payload: dict[str, Any] = {
        "privileged_labels": privileged_labels,
        "unprivileged_labels": unprivileged_labels,
        "sensitive_features": sorted(sensitive_features),
    }
    if privileged_true and privileged_pred and unprivileged_true and unprivileged_pred:
        payload.update(
            {
                "privileged_true": privileged_true,
                "privileged_pred": privileged_pred,
                "unprivileged_true": unprivileged_true,
                "unprivileged_pred": unprivileged_pred,
            }
        )
    return payload


def _derive_runtime_metadata(chunks: list[dict[str, Any]], system_context: dict[str, Any] | None) -> dict[str, Any]:
    source_types: set[str] = set()
    owners: set[str] = set()
    classifications: set[str] = set()
    datasets: set[str] = set()

    for chunk in chunks:
        for key in ("source_type", "content_type", "document_type"):
            value = _first_present(chunk, (key,))
            if value:
                source_types.add(str(value))
        for key in ("owner", "data_owner", "document_owner"):
            value = _first_present(chunk, (key,))
            if value:
                owners.add(str(value))
        for key in ("classification", "data_classification", "sensitivity"):
            value = _first_present(chunk, (key,))
            if value:
                classifications.add(str(value))
        for key in ("dataset_name", "index_name", "source_table", "table_name"):
            value = _first_present(chunk, (key,))
            if value:
                datasets.add(str(value))

    return {
        "retrieved_chunk_count": len(chunks),
        "dataset_names": sorted(datasets),
        "owners": sorted(owners),
        "classifications": sorted(classifications),
        "source_types": sorted(source_types),
        "system_context_keys": sorted(system_context.keys()) if system_context else [],
    }


def _normalize_retrieved_chunks(retrieved_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize chunk payloads into the structure used by prompt artifacts.

    Databricks retrieval code often uses keys like ``chunk_id`` and
    ``chunk_text``. Kentro metrics expect context objects with ``id``/``text``.
    We preserve both naming styles so downstream UI, scorecards, and Delta logs
    can still inspect the original retrieval metadata.
    """

    normalized: list[dict[str, Any]] = []
    for index, chunk in enumerate(retrieved_chunks, start=1):
        if not isinstance(chunk, dict):
            raise TypeError("retrieved_chunks items must be dictionaries")

        chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or f"chunk-{index}")
        doc_uri = str(chunk.get("uri") or chunk.get("doc_uri") or "")
        chunk_text = str(
            chunk.get("text")
            or chunk.get("chunk_text")
            or chunk.get("snippet")
            or chunk.get("content")
            or ""
        ).strip()

        normalized_chunk = dict(chunk)
        normalized_chunk.update(
            {
                "id": chunk_id,
                "chunk_id": chunk_id,
                "uri": doc_uri,
                "doc_uri": doc_uri,
                "text": chunk_text,
                "chunk_text": chunk_text,
                "title": str(chunk.get("title") or chunk.get("source") or chunk.get("doc_title") or doc_uri or chunk_id),
                "score": chunk.get("score", chunk.get("retrieval_score")),
                "retrieval_score": chunk.get("retrieval_score", chunk.get("score")),
                "rank": chunk.get("rank", index),
            }
        )
        normalized.append(normalized_chunk)

    return normalized


def build_prompt_bundle(
    question: str,
    answer: str,
    retrieved_chunks: list[dict[str, Any]],
    *,
    system_context: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the prompt bundle shape used by Kentro scoring and reporting."""

    normalized_chunks = _normalize_retrieved_chunks(retrieved_chunks)
    payload = {
        "prompt": question,
        "model_output": answer,
        "retrieved_contexts": normalized_chunks,
    }
    if system_context:
        payload["system_context"] = system_context
    if labeled_evaluation := _derive_labeled_evaluation(normalized_chunks):
        payload["labeled_evaluation"] = labeled_evaluation
    if fairness_dataset := _derive_fairness_dataset(normalized_chunks):
        payload["fairness_dataset"] = fairness_dataset
    payload["runtime_metadata"] = _derive_runtime_metadata(normalized_chunks, system_context)
    if extra_context:
        payload.update(extra_context)
    return payload


def _write_context_payload(prompt_bundle: dict[str, Any]) -> str:
    """Persist a temporary context payload for reuse by the existing workflow."""

    context_payload = dict(prompt_bundle)
    context_payload.pop("prompt", None)
    context_payload.pop("model_output", None)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(context_payload, handle)
        return handle.name


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _refresh_scorecard_outputs(cfg: ToolkitConfig, run_dir: Path) -> dict[str, Any]:
    """Regenerate scorecard artifacts from the current source tree.

    Databricks jobs can end up with a stale first-pass scorecard when the job
    environment has cached an older package version. Re-rendering here from the
    active repo code ensures the returned JSON/HTML use the latest scoring and
    template contract before the job hands results back to the UI.
    """

    store = ArtifactStore(run_dir.parent, run_dir.name)
    generate_scorecard(cfg, store)
    return _load_json(run_dir / "scorecard.json")


def _apply_runtime_overrides(
    cfg: ToolkitConfig,
    *,
    output_dir: str | None = None,
    run_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    request_format: str | None = None,
) -> ToolkitConfig:
    """Apply Databricks runtime overrides without mutating the base config."""

    if output_dir:
        cfg = cfg.model_copy(update={"output_dir": output_dir})
    if run_id:
        cfg = cfg.model_copy(update={"monitoring": cfg.monitoring.model_copy(update={"run_id": run_id})})

    return _apply_adapter_overrides(
        cfg,
        provider=provider,
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        request_format=request_format,
    )


def run_databricks_answer_pipeline(
    *,
    config_path: str | Path,
    question: str,
    answer: str,
    retrieved_chunks: list[dict[str, Any]],
    system_context: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
    output_dir: str | None = None,
    run_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    request_format: str | None = None,
    model_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Kentro workflow for a Databricks-generated answer.

    This expects the caller to handle retrieval and generation first, then pass
    the final answer plus the exact retrieved chunks used to produce it.
    """

    resolved_config_path = Path(config_path)
    cfg = _apply_runtime_overrides(
        load_config(resolved_config_path),
        output_dir=output_dir,
        run_id=run_id,
        provider=provider,
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        request_format=request_format,
    )

    prompt_bundle = build_prompt_bundle(
        question,
        answer,
        retrieved_chunks,
        system_context=system_context,
        extra_context=extra_context,
    )
    context_file = _write_context_payload(prompt_bundle)

    try:
        run_dir = _run_prompt_workflow(
            cfg,
            str(resolved_config_path),
            question,
            model_output=answer,
            context_file=context_file,
            invocation_mode="databricks_rag",
            model_details=model_details,
        )
    finally:
        Path(context_file).unlink(missing_ok=True)

    run_dir = Path(run_dir)
    scorecard_path = run_dir / "scorecard.json"
    prompt_run_path = run_dir / "prompt_run.json"
    eval_results_path = run_dir / "eval_results.json"

    scorecard_payload = _refresh_scorecard_outputs(cfg, run_dir)

    return {
        "run_dir": str(run_dir),
        "scorecard_json_path": str(scorecard_path),
        "scorecard_html_path": str(run_dir / "scorecard.html"),
        "prompt_run_json_path": str(prompt_run_path),
        "eval_results_json_path": str(eval_results_path),
        "scorecard": scorecard_payload,
        "prompt_bundle": _load_json(prompt_run_path),
    }


def build_governance_run_row(
    *,
    run_id: str,
    question: str,
    answer: str,
    retrieved_chunks: list[dict[str, Any]],
    artifact_dir: str | Path,
    scorecard_json_path: str | Path,
    scorecard_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a Delta-friendly governance summary row for Databricks."""

    normalized_chunks = _normalize_retrieved_chunks(retrieved_chunks)

    return {
        "run_id": str(run_id),
        "query_text": question,
        "retrieved_chunk_count": len(normalized_chunks),
        "top_doc_uris": [str(chunk.get("doc_uri") or chunk.get("uri") or "") for chunk in normalized_chunks[:3]],
        "overall_status": scorecard_payload.get("overall_status"),
        "go_no_go": scorecard_payload.get("go_no_go"),
        "answer_verdict": scorecard_payload.get("answer_verdict"),
        "answer_trust_score": scorecard_payload.get("answer_trust_score"),
        "governance_score": scorecard_payload.get("governance_score"),
        "trust_score": scorecard_payload.get("trust_score"),
        "evidence_completeness": scorecard_payload.get("evidence_completeness"),
        "artifact_dir": str(artifact_dir),
        "scorecard_json_path": str(scorecard_json_path),
        "answer_text": answer,
        "retrieved_chunks_json": json.dumps(normalized_chunks),
    }
