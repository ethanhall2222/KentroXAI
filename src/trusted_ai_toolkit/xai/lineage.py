"""Lineage and authoritative source index generation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import AuthoritativeSource, LineageNode, LineageReport


def _load_prompt_bundle(store: ArtifactStore) -> dict[str, Any]:
    path = store.path_for("prompt_run.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def build_lineage_report(store: ArtifactStore) -> LineageReport:
    """Build lineage report from prompt bundle contexts."""

    bundle = _load_prompt_bundle(store)
    contexts = bundle.get("retrieved_contexts", []) if isinstance(bundle.get("retrieved_contexts", []), list) else []

    nodes: list[LineageNode] = []
    for idx, item in enumerate(contexts, start=1):
        if not isinstance(item, dict):
            continue
        nodes.append(
            LineageNode(
                node_id=str(item.get("id", f"ctx-{idx}")),
                source_type="document",
                title=str(item.get("title", f"Context Source {idx}")),
                uri=item.get("uri"),
                used_for=str(item.get("used_for", "retrieval grounding")),
            )
        )

    if not nodes:
        nodes.append(
            LineageNode(
                node_id="ctx-none",
                source_type="document",
                title="No retrieved sources provided",
                uri=None,
                used_for="fallback",
            )
        )

    output_text = str(bundle.get("model_output", ""))
    cited_nodes = sum(1 for node in nodes if node.node_id.lower() in output_text.lower() or node.title.lower() in output_text.lower())
    coverage = cited_nodes / len(nodes) if nodes else 0.0
    if coverage >= 0.7:
        risk = "low"
    elif coverage >= 0.4:
        risk = "medium"
    else:
        risk = "high"

    return LineageReport(
        run_id=store.run_id,
        prompt=str(bundle.get("prompt", "")),
        model_output=output_text,
        nodes=nodes,
        citation_coverage=round(coverage, 3),
        transparency_risk=risk,
    )


def build_authoritative_source_index(lineage: LineageReport) -> list[AuthoritativeSource]:
    """Build authoritative source index from lineage nodes."""

    return [
        AuthoritativeSource(
            source_id=node.node_id,
            name=node.title,
            owner="data-governance",
            classification="internal",
            uri=node.uri,
            approved=True,
        )
        for node in lineage.nodes
    ]


def generate_lineage_artifacts(store: ArtifactStore) -> tuple[Path, Path]:
    """Write lineage markdown and authoritative source index artifacts."""

    lineage = build_lineage_report(store)
    sources = build_authoritative_source_index(lineage)

    lineage_path = store.save_rendered_md(
        "lineage_report.md.j2",
        "lineage_report.md",
        {
            "run_id": lineage.run_id,
            "prompt": lineage.prompt,
            "model_output": lineage.model_output,
            "citation_coverage": lineage.citation_coverage,
            "transparency_risk": lineage.transparency_risk,
            "nodes": [node.model_dump(mode="json") for node in lineage.nodes],
        },
    )
    source_path = store.write_json(
        "authoritative_data_index.json",
        {"sources": [item.model_dump(mode="json") for item in sources]},
    )
    return lineage_path, source_path
