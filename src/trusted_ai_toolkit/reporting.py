"""Scorecard reporting utilities for governance artifacts."""

from __future__ import annotations
import base64

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.benchmarking import (
    benchmark_distributions,
    build_cohort_key,
    metric_z_from_history,
    update_registry_for_config,
)
from tat.controls import pillar_scores, risk_tier as controls_risk_tier, run_controls, summarize_redteam, trust_score
from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import MetricResult, RedTeamFinding, Scorecard, ToolkitConfig
from tat.runtime import build_system_context, compute_system_hash

def _embed_brand_logo() -> str | None:
    """Return a portable data URI for the preferred Kentro logo asset if present."""

    logo_path = _resolve_brand_logo()
    if logo_path is None:
        return None

    path = Path(logo_path)
    mime_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower())
    if mime_type is None:
        return None

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
    trust_weights = {
        "security": 0.30,
        "reliability": 0.30,
        "transparency": 0.25,
        "governance": 0.15,
    }
    control_weights = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}
    for pillar in ("security", "reliability", "transparency", "governance"):
        pillar_controls = [item for item in scorecard.control_results if item.get("pillar") == pillar]
        control_total = len(pillar_controls)
        control_passed = sum(1 for item in pillar_controls if item.get("passed") is True)
        control_weight_total = sum(control_weights.get(str(item.get("severity", "")).lower(), 1.0) for item in pillar_controls)
        control_weight_passed = sum(
            control_weights.get(str(item.get("severity", "")).lower(), 1.0)
            for item in pillar_controls
            if item.get("passed") is True
        )
        control_pass_rate = round(control_weight_passed / control_weight_total, 4) if control_weight_total else None
        pillar_score = scorecard.pillar_scores.get(pillar)
        trust_weight = trust_weights[pillar]

        breakdown: dict[str, Any] = {
            "control_total": control_total,
            "control_passed": control_passed,
            "control_weight_total": round(control_weight_total, 2),
            "control_weight_passed": round(control_weight_passed, 2),
            "control_pass_rate": control_pass_rate,
            "pillar_score": pillar_score,
            "trust_weight": trust_weight,
            "trust_contribution": round((pillar_score or 0.0) * trust_weight, 4) if pillar_score is not None else None,
            "formula": "Weighted control pass rate (high=3, medium=2, low=1).",
        }

        if pillar == "security" and "pass_rate" in scorecard.redteam_summary:
            redteam_pass_rate = float(scorecard.redteam_summary["pass_rate"])
            breakdown["redteam_pass_rate"] = redteam_pass_rate
            breakdown["formula"] = (
                "50% weighted security controls + 50% red-team pass rate."
            )
        elif pillar != "security":
            breakdown["formula"] = "100% weighted control pass rate."

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


def _empirical_metrics(metric_results: list[MetricResult]) -> list[MetricResult]:
    prefixes = (
        "context_",
        "output_support_",
        "lexical_grounding_",
        "claim_coverage_",
        "groundedness_",
        "reliability",
        "refusal_correctness",
        "unanswerable_handling",
    )
    return [metric for metric in metric_results if metric.metric_id.startswith(prefixes)]


def _metric_strength_map(metric_results: list[MetricResult]) -> dict[str, str]:
    """Label metrics by evidentiary strength for downstream UI and scoring.

    The final answer verdict is intended to lean on the "strong" set first,
    keep "moderate" metrics visible as cautionary signals, and demote
    heuristic-only metrics to diagnostics.
    """

    strong = {
        "claim_support_rate",
        "unsupported_claim_rate",
        "contradiction_rate",
        "evidence_sufficiency_score",
        "context_relevance_tfidf",
        "output_support_tfidf",
        "lexical_grounding_precision",
        "claim_coverage_recall",
        "context_relevance_embedding",
        "output_support_embedding",
        "accuracy_stub",
    }
    moderate = {
        "fairness_demographic_parity_diff",
        "fairness_disparate_impact_ratio",
        "fairness_equal_opportunity_difference",
        "fairness_average_odds_difference",
        "bias_signal_score",
    }
    return {
        metric.metric_id: (
            "strong" if metric.metric_id in strong else "moderate" if metric.metric_id in moderate else "proxy"
        )
        for metric in metric_results
    }


def _metric_lookup(metric_results: list[MetricResult]) -> dict[str, MetricResult]:
    return {metric.metric_id: metric for metric in metric_results}


def _answer_truth_summary(metric_results: list[MetricResult]) -> dict[str, Any]:
    """Collect the answer-truth metrics into one display-oriented bundle."""

    lookup = _metric_lookup(metric_results)
    support = lookup.get("claim_support_rate")
    unsupported = lookup.get("unsupported_claim_rate")
    contradiction = lookup.get("contradiction_rate")
    sufficiency = lookup.get("evidence_sufficiency_score")
    bias = lookup.get("bias_signal_score")
    return {
        "claim_support_rate": support.value if support else None,
        "unsupported_claim_rate": unsupported.value if unsupported else None,
        "contradiction_rate": contradiction.value if contradiction else None,
        "evidence_sufficiency_score": sufficiency.value if sufficiency else None,
        "bias_signal_score": bias.value if bias else None,
        "support_details": support.details if support else {},
        "unsupported_details": unsupported.details if unsupported else {},
        "contradiction_details": contradiction.details if contradiction else {},
        "evidence_details": sufficiency.details if sufficiency else {},
    }


def _bias_assessment(metric_results: list[MetricResult]) -> dict[str, Any]:
    bias_metric = _metric_lookup(metric_results).get("bias_signal_score")
    if bias_metric is None:
        return {"risk": "unknown", "signal_terms": [], "signal_count": 0}
    count = int(bias_metric.details.get("signal_count", 0))
    if count == 0:
        risk = "low"
    elif count == 1:
        risk = "moderate"
    else:
        risk = "high"
    return {
        "risk": risk,
        "score": bias_metric.value,
        "signal_terms": bias_metric.details.get("signal_terms", []),
        "signal_count": count,
    }


def _answer_trust_score(metric_results: list[MetricResult]) -> float | None:
    """Compute the user-facing answer trust score from strong answer metrics.

    This deliberately inverts failure-style metrics like unsupported-claim rate
    and contradiction rate so the aggregate stays on a "higher is better"
    scale for UI and thresholding.
    """

    lookup = _metric_lookup(metric_results)
    strong_ids = [
        "claim_support_rate",
        "unsupported_claim_rate",
        "contradiction_rate",
        "evidence_sufficiency_score",
        "output_support_tfidf",
        "output_support_embedding",
    ]
    normalized: list[float] = []
    for metric_id in strong_ids:
        metric = lookup.get(metric_id)
        if metric is None:
            continue
        if metric_id in {"unsupported_claim_rate", "contradiction_rate"}:
            normalized.append(max(0.0, 1.0 - float(metric.value)))
        else:
            normalized.append(float(metric.value))
    if not normalized:
        return None
    return round(sum(normalized) / len(normalized), 4)


def _answer_verdict(metric_results: list[MetricResult]) -> tuple[str | None, list[str]]:
    """Convert answer-level metric results into a user-facing verdict.

    The verdict is intentionally conservative:
    - contradictions or many unsupported claims -> not_trusted
    - partial support / thin evidence / bias signals -> use_caution
    - otherwise -> trusted
    """

    lookup = _metric_lookup(metric_results)
    reasons: list[str] = []
    contradiction = lookup.get("contradiction_rate")
    unsupported = lookup.get("unsupported_claim_rate")
    support = lookup.get("claim_support_rate")
    sufficiency = lookup.get("evidence_sufficiency_score")
    bias = lookup.get("bias_signal_score")

    if contradiction and contradiction.value > 0.05:
        reasons.append("Detected answer claims that conflict with matched source evidence.")
        return "not_trusted", reasons
    if unsupported and unsupported.value > 0.35:
        reasons.append("Too many answer claims could not be grounded in the provided evidence.")
        return "not_trusted", reasons

    caution = False
    if support and support.value < 0.7:
        caution = True
        reasons.append("Only part of the answer is directly supported by the provided evidence.")
    if sufficiency and sufficiency.value < 0.6:
        caution = True
        reasons.append("The retrieved evidence may be too thin to fully justify the answer.")
    if bias and int(bias.details.get("signal_count", 0)) > 0:
        caution = True
        reasons.append("Potential bias-linked language was detected and should be reviewed.")

    if caution:
        return "use_caution", reasons
    reasons.append("The answer is well supported by the retrieved evidence and no contradictions were detected.")
    return "trusted", reasons


def _empirical_score(metric_results: list[MetricResult]) -> float | None:
    empirical = [metric.value for metric in _empirical_metrics(metric_results) if metric.passed is not None]
    if not empirical:
        return None
    return round(sum(empirical) / len(empirical), 4)


def _metric_z_value(metric: MetricResult, historical_distributions: dict[str, dict[str, float]] | None = None) -> float | None:
    if historical_distributions:
        historical_z = metric_z_from_history(metric, historical_distributions)
        if historical_z is not None:
            return historical_z
    if metric.threshold is None or metric.passed is None:
        return None

    threshold = float(metric.threshold)
    if metric.metric_id in {
        "fairness_demographic_parity_diff",
        "fairness_equal_opportunity_difference",
        "fairness_average_odds_difference",
    }:
        margin = threshold - abs(metric.value)
        scale = max(threshold * 0.5, 0.05)
    else:
        margin = float(metric.value) - threshold
        scale = max(abs(threshold) * 0.25, 0.05)
    return round(margin / scale, 4)


def _trust_z_score(
    metric_results: list[MetricResult],
    historical_distributions: dict[str, dict[str, float]] | None = None,
) -> float | None:
    z_values = [z for metric in metric_results if (z := _metric_z_value(metric, historical_distributions)) is not None]
    if not z_values:
        return None
    return round(sum(z_values) / len(z_values), 4)


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
    # Historical distributions are cohort-scoped so OpenAI runs do not get
    # standardized against unrelated local-model history.
    historical_distributions = benchmark_distributions(
        config.eval.benchmark_registry_path,
        config,
        store.run_id,
    )
    severity_counts = _severity_counts(findings)
    redteam_summary = summarize_redteam(findings) or severity_counts
    control_results = run_controls(config.system)
    computed_pillar_scores = pillar_scores(control_results, redteam_summary if redteam_payload else None)
    computed_governance_score = trust_score(computed_pillar_scores)
    computed_empirical_score = _empirical_score(metric_results)
    computed_trust_score = _trust_z_score(metric_results, historical_distributions)
    computed_answer_trust_score = _answer_trust_score(metric_results)
    answer_verdict, answer_reasons = _answer_verdict(metric_results)
    truth_summary = _answer_truth_summary(metric_results)
    bias_assessment = _bias_assessment(metric_results)
    metric_strength = _metric_strength_map(metric_results)
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

    # Governance status remains separate from the answer-level verdict on
    # purpose. A specific answer can be well-grounded while the surrounding
    # system still fails release policy gates such as fairness or red-team.
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
        answer_verdict=answer_verdict,
        answer_trust_score=computed_answer_trust_score,
        answer_truth_summary=truth_summary,
        bias_assessment=bias_assessment,
        metric_strength=metric_strength,
        redteam_summary=redteam_summary,
        pillar_scores=computed_pillar_scores,
        trust_score=computed_trust_score,
        empirical_score=computed_empirical_score,
        governance_score=computed_governance_score,
        weighting_rationale={
            "security": 0.30,
            "reliability": 0.30,
            "transparency": 0.25,
            "governance": 0.15,
        },
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
        "This answer trust card summarizes whether the model answer is supported by the available evidence, "
        "whether contradictions were detected, and whether the answer should be trusted, used cautiously, or rejected."
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
    context["empirical_metric_summary"] = _metric_summary(_empirical_metrics(metric_results))
    context["benchmark_distributions"] = historical_distributions
    context["answer_verdict"] = scorecard.answer_verdict
    context["answer_trust_score_pct"] = (
        round(scorecard.answer_trust_score * 100.0, 0) if scorecard.answer_trust_score is not None else None
    )
    context["answer_truth_summary"] = scorecard.answer_truth_summary
    context["bias_assessment"] = scorecard.bias_assessment
    context["metric_strength"] = scorecard.metric_strength
    context["answer_reasons"] = answer_reasons
    context["pillar_breakdowns"] = _pillar_breakdowns(scorecard)
    context["artifact_signal"] = _artifact_signal(scorecard)
    context["trust_score_z"] = scorecard.trust_score
    context["governance_score_pct"] = (
        round(scorecard.governance_score * 100.0, 0) if scorecard.governance_score is not None else None
    )
    context["empirical_score_pct"] = (
        round(scorecard.empirical_score * 100.0, 0) if scorecard.empirical_score is not None else None
    )
    context["card_score"] = _card_score_summary(
        context["governance_score_pct"],
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
    context["redteam_gate_rules"] = {
        "require_redteam": bool(risk_rules.get("require_redteam", False)),
        "block_on_high_severity": bool(risk_rules.get("block_on_high_severity", False)),
    }
    context["raw_trust_score_pct"] = context["governance_score_pct"]
    context["weighting_rationale"] = scorecard.weighting_rationale
    context["release_readiness_score_pct"] = context["card_score"]["display_score_pct"]
    context["brand_logo_src"] = _embed_brand_logo()
    context["generated_files"] = {
        "scorecard_md": str(store.path_for("scorecard.md")),
        "scorecard_html": str(store.path_for("scorecard.html")),
    }

    store.save_rendered_md("scorecard.md.j2", "scorecard.md", context)
    store.save_rendered_html("scorecard.html.j2", "scorecard.html", context)
    store.write_json("scorecard.json", scorecard.model_dump(mode="json"))
    registry_path = update_registry_for_config(config.eval.benchmark_registry_path, config, store.run_id, metric_results)
    store.write_json(
        "benchmark_summary.json",
        {
            "run_id": store.run_id,
            "registry_path": str(Path(registry_path).resolve()),
            "cohort_key": build_cohort_key(config),
            "metric_distributions": historical_distributions,
            "trust_score_method": "historical_zscore_with_threshold_fallback",
        },
    )

    return scorecard
