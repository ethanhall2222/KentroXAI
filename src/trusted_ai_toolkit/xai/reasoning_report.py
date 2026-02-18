"""Reasoning report generation for explainability artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import ToolkitConfig
from trusted_ai_toolkit.xai.lineage import build_lineage_report

TLDR_REFERENCES = [
    "https://www.ibm.com/products/watsonx-governance",
    "https://www.ibm.com/docs/en/cloud-paks/cp-data/5.0.x?topic=solutions-ai-factsheets",
    "https://www.microsoft.com/en-us/ai/responsible-ai",
    "https://arxiv.org/abs/1810.03993",
    "https://arxiv.org/abs/2308.09834",
]


def _find_latest_artifact(output_dir: Path, filename: str) -> Path | None:
    """Find most recently modified artifact file under output_dir/*/."""

    candidates = list(output_dir.glob(f"*/{filename}"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _try_load_eval_summary(output_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Load eval summary from active run or latest prior run."""

    path = output_dir / run_id / "eval_results.json"
    if not path.exists():
        latest = _find_latest_artifact(output_dir, "eval_results.json")
        if latest is not None:
            path = latest
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _try_load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def generate_reasoning_report(config: ToolkitConfig, store: ArtifactStore) -> tuple[Path, Path]:
    """Render and write reasoning report markdown artifact."""

    eval_summary = _try_load_eval_summary(store.output_dir, store.run_id)
    prompt_bundle = _try_load_json_object(store.path_for("prompt_run.json"))
    redteam_findings = _try_load_json_object(store.path_for("redteam_summary.json"))
    lineage_report = build_lineage_report(store)
    governance_controls = [
        "Intended use and misuse boundaries are defined.",
        "Known limitations and failure modes are documented.",
        "Evaluation and threshold criteria are documented.",
        "Security testing outputs are tracked as review evidence.",
        "Human review remains required for deployment approval.",
    ]

    context = {
        "project_name": config.project_name,
        "run_id": store.run_id,
        "risk_tier": config.risk_tier,
        "data": config.data.model_dump() if config.data else {},
        "model": config.model.model_dump() if config.model else {},
        "prompt": prompt_bundle.get("prompt", "N/A"),
        "model_output": prompt_bundle.get("model_output", "N/A"),
        "include_sections": config.xai.include_sections,
        "eval_summary": eval_summary,
        "lineage_nodes": [node.model_dump(mode="json") for node in lineage_report.nodes],
        "citation_coverage": lineage_report.citation_coverage,
        "transparency_risk": lineage_report.transparency_risk,
        "escalation_cues": [
            "Escalate if transparency risk is high.",
            "Escalate if scorecard go/no-go status is no-go.",
            "Escalate if high or critical red-team findings remain open.",
        ],
        "redteam_summary": redteam_findings,
        "references": TLDR_REFERENCES,
        "governance_controls": governance_controls,
        "stakeholders": [
            "Model Owner",
            "Responsible AI Reviewer",
            "Security Reviewer",
            "Product and Compliance Stakeholders",
        ],
        "explainability_methods": [
            "Feature attribution (planned integration)",
            "Counterfactual reasoning (planned integration)",
            "Global behavior summaries (planned integration)",
        ],
        "todo_markers": [
            "TODO: integrate model-specific explainability library.",
            "TODO: attach reproducible explanation samples for representative cohorts.",
        ],
    }

    md_path = store.save_rendered_md(config.xai.reasoning_report_template, "reasoning_report.md", context)
    json_path = store.write_json("reasoning_report.json", context)
    return md_path, json_path
