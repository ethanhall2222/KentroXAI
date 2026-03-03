"""Scorecard reporting utilities for governance artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tat.controls import pillar_scores, risk_tier as controls_risk_tier, run_controls, summarize_redteam, trust_score
from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import MetricResult, RedTeamFinding, Scorecard, ToolkitConfig
from tat.runtime import build_system_context, compute_system_hash


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


def _normalize_eval_metrics(eval_payload: Any) -> list[MetricResult]:
    if not eval_payload:
        return []
    suites = eval_payload
    if isinstance(eval_payload, dict):
        suites = eval_payload.get("results", [])
    if not isinstance(suites, list):
        return []
    results: list[MetricResult] = []
    for suite in suites:
        for item in suite.get("metric_results", []):
            results.append(MetricResult.model_validate(item))
    return results


def _normalize_findings(redteam_payload: Any) -> list[RedTeamFinding]:
    if not redteam_payload:
        return []
    findings = redteam_payload
    if isinstance(redteam_payload, dict):
        findings = redteam_payload.get("findings", [])
    if not isinstance(findings, list):
        return []
    return [RedTeamFinding.model_validate(item) for item in findings]


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

    has_fairness_metric = any(m.metric_id.startswith("fairness_") for m in metric_results)
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


def _pillar_breakdowns(scorecard: Scorecard) -> dict[str, dict[str, Any]] | None:
    """Build display-oriented scoring breakdowns for the interactive HTML scorecard."""

    if not scorecard.pillar_scores:
        return None

    breakdowns: dict[str, dict[str, Any]] = {}
    for pillar in ("security", "reliability", "transparency", "governance"):
        pillar_controls = [item for item in scorecard.control_results if item.get("pillar") == pillar]
        control_total = len(pillar_controls)
        control_passed = sum(1 for item in pillar_controls if item.get("passed") is True)
        control_pass_rate = round(control_passed / control_total, 4) if control_total else None
        pillar_score = scorecard.pillar_scores.get(pillar)
        trust_weight = 0.25

        breakdown: dict[str, Any] = {
            "control_total": control_total,
            "control_passed": control_passed,
            "control_pass_rate": control_pass_rate,
            "pillar_score": pillar_score,
            "trust_weight": trust_weight,
            "trust_contribution": round((pillar_score or 0.0) * trust_weight, 4) if pillar_score is not None else None,
            "formula": "Derived from the pillar control pass rate.",
        }

        if pillar == "security" and "pass_rate" in scorecard.redteam_summary:
            redteam_pass_rate = float(scorecard.redteam_summary["pass_rate"])
            breakdown["redteam_pass_rate"] = redteam_pass_rate
            breakdown["formula"] = (
                "50% control pass rate + 50% red-team pass rate."
            )
        elif pillar != "security":
            breakdown["formula"] = "100% control pass rate."

        breakdowns[pillar] = breakdown

    return breakdowns


def _metric_summary(metric_results: list[MetricResult]) -> dict[str, Any]:
    """Compute display-friendly metric summary values for the scorecard."""

    total = len(metric_results)
    passed = sum(1 for metric in metric_results if metric.passed is True)
    failed = sum(1 for metric in metric_results if metric.passed is False)
    fairness_metrics = [metric.metric_id for metric in metric_results if metric.metric_id.startswith("fairness_")]
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else None,
        "fairness_metrics": fairness_metrics,
    }


def _artifact_signal(scorecard: Scorecard) -> dict[str, str]:
    """Compute compact chip labels for live scorecard signals."""

    blocking_findings = (
        int(scorecard.redteam_summary.get("high", 0)) + int(scorecard.redteam_summary.get("critical", 0))
        if scorecard.redteam_summary
        else 0
    )
    return {
        "evidence_label": f"Evidence Complete {round(scorecard.evidence_completeness, 0):.0f}%",
        "trace_label": "Traceability On" if scorecard.system_context else "Traceability Off",
        "security_label": f"Blocker Findings {blocking_findings}",
    }


def _resolve_brand_logo() -> str | None:
    """Return an absolute path to a preferred Kentro logo asset if present."""

    candidate_names = [
        "kentro-logo-full-color-rgb-900px-w-72ppi.png",
        "Kentro_Teal__1_Logo.jpg",
    ]
    assets_dir = Path.cwd() / "assets"
    for name in candidate_names:
        path = assets_dir / name
        if path.exists():
            return str(path.resolve())
    return None


def _card_score_summary(
    control_score_pct: float | None,
    failing_metrics_count: int,
    severity_counts: dict[str, int],
    evidence_completeness: float,
    overall_status: str,
    stage_gate_status: dict[str, str],
) -> dict[str, Any]:
    """Compute the UI-facing trust score for the current answer."""

    base = float(control_score_pct) if control_score_pct is not None else 70.0
    penalty = 0.0
    penalty += failing_metrics_count * 6.0
    penalty += severity_counts.get("medium", 0) * 2.0
    penalty += severity_counts.get("high", 0) * 8.0
    penalty += severity_counts.get("critical", 0) * 12.0
    penalty += max(0.0, 90.0 - evidence_completeness) * 0.15

    display_score = base - penalty
    display_score = max(0.0, min(100.0, round(display_score, 0)))

    status_note = {
        "pass": "This answer cleared the current governance checks.",
        "needs_review": "This answer is available, but governance review items remain.",
        "fail": "This answer has governance blockers. Review the failed gates and findings.",
    }[overall_status]

    return {
        "display_score_pct": int(display_score),
        "control_score_pct": int(round(control_score_pct, 0)) if control_score_pct is not None else None,
        "label": "Trust Score",
        "status_note": status_note,
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
    redteam_summary = summarize_redteam(findings) or severity_counts
    control_results = run_controls(config.system)
    computed_pillar_scores = pillar_scores(control_results, redteam_summary if redteam_payload else None)
    computed_trust_score = trust_score(computed_pillar_scores)
    computed_risk_tier = controls_risk_tier(control_results)

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
        required_actions.append("No blocking issues in deterministic checks; proceed to human governance review.")

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
        risk_tier=computed_risk_tier or config.risk_tier,
        deployment_risk_tier=config.risk_tier,
        overall_status=overall_status,
        go_no_go=go_no_go,
        stage_gate_status=stage_gate_status,
        evidence_completeness=evidence_completeness,
        metric_results=metric_results,
        redteam_summary=redteam_summary,
        pillar_scores=computed_pillar_scores,
        trust_score=computed_trust_score,
        control_results=[result.as_dict() for result in control_results],
        required_actions=required_actions,
        system_context=build_system_context(
            config.system,
            compute_system_hash(config.system) if config.system is not None else None,
        ),
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
        {"control": item["control_id"], "status": "Yes" if item["passed"] else "No"}
        for item in scorecard.control_results
    ]
    context["artifact_presence"] = {
        "eval_results": eval_path.exists(),
        "redteam_findings": redteam_path.exists(),
        "reasoning_report": reasoning_path.exists(),
    }
    context["metric_summary"] = _metric_summary(metric_results)
    context["pillar_breakdowns"] = _pillar_breakdowns(scorecard)
    context["artifact_signal"] = _artifact_signal(scorecard)
    context["trust_score_pct"] = round(scorecard.trust_score * 100.0, 0) if scorecard.trust_score is not None else None
    context["card_score"] = _card_score_summary(
        context["trust_score_pct"],
        len(failing_metrics),
        severity_counts,
        evidence_completeness,
        overall_status,
        stage_gate_status,
    )
    context["severity_threshold"] = config.redteam.severity_threshold
    context["go_no_go"] = go_no_go
    context["stage_gate_status"] = stage_gate_status
    context["evidence_completeness"] = evidence_completeness
    context["required_outputs"] = required_outputs
    context["raw_trust_score_pct"] = context["trust_score_pct"]
    context["release_readiness_score_pct"] = context["card_score"]["display_score_pct"]
    context["brand_logo_path"] = _resolve_brand_logo()
    context["generated_files"] = {
        "scorecard_md": str(store.path_for("scorecard.md")),
        "scorecard_html": str(store.path_for("scorecard.html")),
    }

    store.save_rendered_md("scorecard.md.j2", "scorecard.md", context)
    store.save_rendered_html("scorecard.html.j2", "scorecard.html", context)
    store.write_json("scorecard.json", scorecard.model_dump(mode="json"))

    return scorecard
