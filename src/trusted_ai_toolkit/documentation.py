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
                "model": config.model.model_dump() if config.model else {},
                "prompt": prompt_bundle.get("prompt", "N/A"),
            },
        )
    )
    paths.append(
        store.save_rendered_md(
            "data_card.md.j2",
            "data_card.md",
            {
                "data": config.data.model_dump() if config.data else {},
                "project_name": config.project_name,
            },
        )
    )
    paths.append(
        store.save_rendered_md(
            "model_card.md.j2",
            "model_card.md",
            {
                "model": config.model.model_dump() if config.model else {},
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
