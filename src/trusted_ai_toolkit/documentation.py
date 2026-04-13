"""Documentation artifact generation utilities (Workstream D)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import ToolkitConfig


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _build_dynamic_model_context(config: ToolkitConfig, prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    base = config.model.model_dump() if config.model else {}
    system_context = prompt_bundle.get("system_context", {})
    invocation = prompt_bundle.get("model_invocation", {})

    if isinstance(system_context, dict):
        base.setdefault("model_name", system_context.get("model_name"))
        base.setdefault("owner", system_context.get("owner"))
        base.setdefault("version", system_context.get("model_version") or system_context.get("version"))
        base.setdefault("task", system_context.get("task"))
        base.setdefault("intended_use", system_context.get("intended_use") or system_context.get("endpoint_name"))
        base.setdefault("limitations", system_context.get("limitations"))
    if isinstance(invocation, dict):
        base["model_name"] = invocation.get("model", base.get("model_name"))
    return base


def _build_dynamic_data_context(config: ToolkitConfig, prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    base = config.data.model_dump() if config.data else {}
    runtime_metadata = prompt_bundle.get("runtime_metadata", {})
    if not isinstance(runtime_metadata, dict):
        return base

    dataset_names = runtime_metadata.get("dataset_names", [])
    owners = runtime_metadata.get("owners", [])
    classifications = runtime_metadata.get("classifications", [])
    source_types = runtime_metadata.get("source_types", [])

    if dataset_names and not base.get("dataset_name"):
        base["dataset_name"] = ", ".join(str(item) for item in dataset_names)
    if source_types and not base.get("source"):
        base["source"] = ", ".join(str(item) for item in source_types)
    if owners:
        base["intended_use"] = f"Retrieved from runtime-governed sources owned by {', '.join(str(item) for item in owners)}."
    if classifications:
        base["limitations"] = f"Runtime classifications observed: {', '.join(str(item) for item in classifications)}."
    return base


def build_documentation_artifacts(config: ToolkitConfig, store: ArtifactStore) -> list[Path]:
    """Generate governance card artifacts and artifact manifest outputs."""

    prompt_bundle = _load_json_if_exists(store.path_for("prompt_run.json"))

    paths: list[Path] = []
    paths.append(
        store.save_rendered_md(
            "system_card.md.j2",
            "system_card.md",
            {
                "project_name": config.project_name,
                "risk_tier": config.risk_tier,
                "model": _build_dynamic_model_context(config, prompt_bundle),
                "prompt": prompt_bundle.get("prompt", "N/A"),
            },
        )
    )
    paths.append(
        store.save_rendered_md(
            "data_card.md.j2",
            "data_card.md",
            {
                "data": _build_dynamic_data_context(config, prompt_bundle),
                "project_name": config.project_name,
            },
        )
    )
    paths.append(
        store.save_rendered_md(
            "model_card.md.j2",
            "model_card.md",
            {
                "model": _build_dynamic_model_context(config, prompt_bundle),
                "project_name": config.project_name,
                "adapter": config.adapters.model_dump(mode="json"),
            },
        )
    )

    required = config.artifact_policy.required_outputs_by_risk_tier.get(config.risk_tier, [])
    manifest_path = store.write_manifest(required)
    paths.append(manifest_path)

    manifest_payload = _load_json_if_exists(manifest_path)
    paths.append(
        store.save_rendered_md(
            "artifact_manifest.md.j2",
            "artifact_manifest.md",
            {
                "run_id": store.run_id,
                "completeness": manifest_payload.get("completeness", 0),
                "required_outputs": manifest_payload.get("required_outputs", []),
                "items": manifest_payload.get("items", []),
            },
        )
    )
    return paths
