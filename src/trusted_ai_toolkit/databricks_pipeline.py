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

from trusted_ai_toolkit.cli import _apply_adapter_overrides, _run_prompt_workflow
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.schemas import ToolkitConfig


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

        normalized.append(
            {
                "id": chunk_id,
                "chunk_id": chunk_id,
                "uri": doc_uri,
                "doc_uri": doc_uri,
                "text": chunk_text,
                "chunk_text": chunk_text,
                "title": str(chunk.get("title") or chunk.get("source") or doc_uri or chunk_id),
                "score": chunk.get("score", chunk.get("retrieval_score")),
                "retrieval_score": chunk.get("retrieval_score", chunk.get("score")),
                "rank": chunk.get("rank", index),
            }
        )

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

    payload = {
        "prompt": question,
        "model_output": answer,
        "retrieved_contexts": _normalize_retrieved_chunks(retrieved_chunks),
    }
    if system_context:
        payload["system_context"] = system_context
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

    scorecard_payload = _load_json(scorecard_path)

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
