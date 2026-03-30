"""Databricks-friendly job entrypoints for toolkit workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.cli import (
    _apply_adapter_overrides,
    _compose_model_prompt,
    _load_retrieved_contexts,
    _model_artifact_payload,
    _run_prompt_workflow,
)
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.model_client import ModelInvocationError, invoke_model


def _pick(value: str | None, env_name: str, default: str | None = None) -> str | None:
    """Return an explicit value, then an environment variable, then a default."""

    if value is not None:
        stripped = value.strip()
        if stripped:
            return stripped
        return default
    env_value = os.getenv(env_name)
    if env_value is not None:
        stripped = env_value.strip()
        if stripped:
            return stripped
    return default


def _require(value: str | None, env_name: str) -> str:
    """Resolve a required argument from a direct value or environment."""

    resolved = _pick(value, env_name)
    if resolved is None:
        raise ValueError(f"missing required value: pass it directly or set {env_name}")
    return resolved


def _normalize_mode(mode: str | None) -> str:
    """Normalize the Databricks job mode to one of the supported workflows."""

    resolved = (mode or "prompt").strip().lower()
    if resolved not in {"prompt", "simulate"}:
        raise ValueError(f"unsupported Databricks job mode: {resolved}")
    return resolved


def _job_result(run_dir: Path, mode: str, config_path: str) -> dict[str, Any]:
    """Build a compact result payload for Databricks task logs and downstream parsing."""

    return {
        "mode": mode,
        "config_path": config_path,
        "run_dir": str(run_dir),
        "scorecard_json": str(run_dir / "scorecard.json"),
        "scorecard_html": str(run_dir / "scorecard.html"),
        "artifact_manifest_json": str(run_dir / "artifact_manifest.json"),
    }


def run_prompt_job(
    config: str | None = None,
    prompt: str | None = None,
    model_output: str | None = None,
    context_file: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    request_format: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Run the toolkit in a Databricks Python wheel task.

    Arguments can be passed as Python wheel keyword arguments or through
    environment variables such as ``TAT_CONFIG_PATH`` and ``TAT_PROMPT``.
    """

    resolved_mode = _normalize_mode(_pick(mode, "TAT_JOB_MODE", "prompt"))
    config_path = _require(config, "TAT_CONFIG_PATH")
    resolved_prompt = _require(prompt, "TAT_PROMPT")
    resolved_context_file = _pick(context_file, "TAT_CONTEXT_FILE")
    resolved_model_output = _pick(model_output, "TAT_MODEL_OUTPUT")

    cfg = _apply_adapter_overrides(
        load_config(config_path),
        provider=_pick(provider, "TAT_ADAPTER_PROVIDER"),
        endpoint=_pick(endpoint, "TAT_ADAPTER_ENDPOINT"),
        model=_pick(model, "TAT_ADAPTER_MODEL"),
        api_key_env=_pick(api_key_env, "TAT_ADAPTER_API_KEY_ENV"),
        request_format=_pick(request_format, "TAT_ADAPTER_REQUEST_FORMAT"),
    )

    if resolved_mode == "simulate":
        retrieved_contexts = _load_retrieved_contexts(resolved_context_file)
        model_prompt = _compose_model_prompt(resolved_prompt, retrieved_contexts)
        try:
            invocation = invoke_model(model_prompt, cfg)
        except ModelInvocationError as exc:
            raise ValueError(str(exc)) from exc

        model_details = _model_artifact_payload(
            invocation_mode="live_simulation",
            provider=invocation.provider,
            model_name=invocation.model,
            route=invocation.route,
            request_url=invocation.request_url,
            request_payload=invocation.request_payload,
            response_payload=invocation.response_payload,
        )
        run_dir = _run_prompt_workflow(
            cfg,
            config_path,
            resolved_prompt,
            model_output=invocation.output_text,
            context_file=resolved_context_file,
            invocation_mode="live_simulation",
            model_details=model_details,
        )
        return _job_result(run_dir, resolved_mode, config_path)

    run_dir = _run_prompt_workflow(
        cfg,
        config_path,
        resolved_prompt,
        model_output=resolved_model_output,
        context_file=resolved_context_file,
    )
    return _job_result(run_dir, resolved_mode, config_path)


def main() -> None:
    """Console wrapper for Databricks script tasks and ad-hoc validation."""

    result = run_prompt_job()
    print(json.dumps(result, indent=2))
