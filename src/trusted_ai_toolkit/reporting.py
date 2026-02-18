"""Scorecard reporting utilities for governance artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import MetricResult, RedTeamFinding, Scorecard, ToolkitConfig


def _load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _find_latest_artifact(output_dir: Path, filename: str) -> Path | None:
    candidates = list(output_dir.glob(f"*/{filename}"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _severity_counts(findings: list[RedTeamFinding]) -> dict[str, int]:
    counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def _normalize_eval_metrics(eval_payload: list[dict[str, Any]] | None) -> list[MetricResult]:
    if not eval_payload:
        return []
    results: list[MetricResult] = []
    for suite in eval_payload:
        for item in suite.get("metric_results", []):
            results.append(MetricResult.model_validate(item))
    return results


def _normalize_findings(redteam_payload: list[dict[str, Any]] | None) -> list[RedTeamFinding]:
    if not redteam_payload:
        return []
    return [RedTeamFinding.model_validate(item) for item in redteam_payload]


def _artifact_completeness(store: ArtifactStore, required_outputs: list[str]) -> float:
    present = {path.name for path in store.run_dir.glob("*") if path.is_file()}
    required = set(required_outputs)
    if not required:
        return 100.0
    return round(len(required.intersection(present)) / len(required) * 100.0, 2)


def _rai_dimension_status(
    metric_results: list[MetricResult], severity_counts: dict[str, int], has_reasoning_report: bool
) -> dict[str, str]:
    """Build a lightweight Responsible AI-style dimension status summary."""

    has_fairness_metric = any(m.metric_id == "fairness_demographic_parity_diff" for m in metric_results)
    all_metrics_passed = all(m.passed is not False for m in metric_results) if metric_results else False
    security_blockers = (severity_counts["high"] + severity_counts["critical"]) > 0

    return {
        "fairness": "Provisionally Met" if has_fairness_metric else "Insufficient Evidence",
        "reliability_and_safety": "Provisionally Met" if all_metrics_passed else "Needs Action",
        "privacy_and_security": "Needs Action" if security_blockers else "Provisionally Met",
        "transparency": "Provisionally Met" if has_reasoning_report else "Insufficient Evidence",
        "accountability": "Provisionally Met",
        "inclusiveness": "Insufficient Evidence",
    }


def generate_scorecard(config: ToolkitConfig, store: ArtifactStore) -> Scorecard:
    """Generate and persist scorecard markdown/html artifacts."""

    eval_path = store.path_for("eval_results.json")
    redteam_path = store.path_for("redteam_findings.json")
    reasoning_path = store.path_for("reasoning_report.md")

    if not eval_path.exists():
        latest = _find_latest_artifact(store.output_dir, "eval_results.json")
        if latest is not None:
            eval_path = latest
    if not redteam_path.exists():
        latest = _find_latest_artifact(store.output_dir, "redteam_findings.json")
        if latest is not None:
            redteam_path = latest
    if not reasoning_path.exists():
        latest = _find_latest_artifact(store.output_dir, "reasoning_report.md")
        if latest is not None:
            reasoning_path = latest

    eval_payload = _load_json_if_exists(eval_path)
    redteam_payload = _load_json_if_exists(redteam_path)

    metric_results = _normalize_eval_metrics(eval_payload)
    findings = _normalize_findings(redteam_payload)
    severity_counts = _severity_counts(findings)

    failing_metrics = [m.metric_id for m in metric_results if m.passed is False]
    high_findings = severity_counts["high"] + severity_counts["critical"]
    required_outputs = config.artifact_policy.required_outputs_by_risk_tier.get(config.risk_tier, [])
    evidence_completeness = _artifact_completeness(store, required_outputs)

    required_actions: list[str] = []
    if failing_metrics:
        required_actions.append(f"Address failing metrics: {', '.join(sorted(set(failing_metrics)))}")
    if high_findings:
        required_actions.append("Mitigate high/critical red-team findings before deployment.")
    if not required_actions:
        required_actions.append("No blocking issues in stub checks; proceed to human governance review.")

    stage_gate_status: dict[str, str] = {
        "evaluation": "fail" if failing_metrics else "pass",
        "redteam": "needs_review" if high_findings else "pass",
        "documentation": "pass" if evidence_completeness >= 90 else "needs_review",
        "monitoring": "pass",
    }

    risk_rules = config.governance.risk_gate_rules.get(config.risk_tier, {})
    if risk_rules.get("require_redteam", False) and not findings:
        stage_gate_status["redteam"] = "fail"
    if risk_rules.get("block_on_high_severity", False) and high_findings:
        stage_gate_status["redteam"] = "fail"
    if risk_rules.get("require_human_signoff", False):
        stage_gate_status["human_signoff"] = "needs_review"

    if "fail" in stage_gate_status.values():
        overall_status = "fail"
        go_no_go = "no-go"
    elif "needs_review" in stage_gate_status.values():
        overall_status = "needs_review"
        go_no_go = "no-go"
    else:
        overall_status = "pass"
        go_no_go = "go"

    scorecard = Scorecard(
        project_name=config.project_name,
        run_id=store.run_id,
        risk_tier=config.risk_tier,
        overall_status=overall_status,
        go_no_go=go_no_go,
        stage_gate_status=stage_gate_status,
        evidence_completeness=evidence_completeness,
        metric_results=metric_results,
        redteam_summary=severity_counts,
        required_actions=required_actions,
        artifact_links={
            "eval_results": str(eval_path),
            "redteam_findings": str(redteam_path),
            "reasoning_report": str(reasoning_path),
        },
    )

    context = scorecard.model_dump()
    context["executive_summary"] = (
        "This governance scorecard summarizes model quality, fairness indicators, "
        "security posture, and documentation readiness for release review."
    )
    context["risk_statement"] = (
        "Final deployment approval requires human review of high-risk findings, "
        "business impact, and legal/compliance obligations."
    )
    context["rai_dimensions"] = _rai_dimension_status(metric_results, severity_counts, reasoning_path.exists())
    context["control_checks"] = [
        {"control": "Defined Intended Use", "status": "Yes"},
        {"control": "Documented Limitations", "status": "Yes"},
        {"control": "Evaluation Thresholds Defined", "status": "Yes" if metric_results else "No"},
        {
            "control": "Red-Team Security Testing Completed",
            "status": "Yes" if findings else "No",
        },
        {
            "control": "Explainability Report Available",
            "status": "Yes" if reasoning_path.exists() else "No",
        },
        {"control": "Human Sign-Off Recorded", "status": "Pending"},
    ]
    context["severity_threshold"] = config.redteam.severity_threshold
    context["go_no_go"] = go_no_go
    context["stage_gate_status"] = stage_gate_status
    context["evidence_completeness"] = evidence_completeness
    context["required_outputs"] = required_outputs
    context["generated_files"] = {
        "scorecard_md": str(store.path_for("scorecard.md")),
        "scorecard_html": str(store.path_for("scorecard.html")),
    }

    store.save_rendered_md("scorecard.md.j2", "scorecard.md", context)
    store.save_rendered_html("scorecard.html.j2", "scorecard.html", context)
    store.write_json("scorecard.json", scorecard.model_dump(mode="json"))

    return scorecard
