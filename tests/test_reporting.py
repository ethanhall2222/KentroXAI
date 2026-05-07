from __future__ import annotations

import json
from pathlib import Path

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.benchmarking import update_registry_for_config
from trusted_ai_toolkit.reporting import generate_scorecard
from trusted_ai_toolkit.schemas import MetricResult, ToolkitConfig
from tat.schemas import SystemSpec


def test_reporting_generates_scorecard_with_stage_gates(tmp_path: Path) -> None:
    cfg = ToolkitConfig(project_name="demo", risk_tier="high", output_dir=str(tmp_path / "artifacts"))
    store = ArtifactStore(output_dir=cfg.output_dir, run_id="run9")

    store.write_json(
        "eval_results.json",
        [
            {
                "suite_name": "high",
                "run_id": "run9",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:01Z",
                "overall_passed": True,
                "notes": [],
                "metric_results": [
                    {"metric_id": "accuracy_stub", "value": 0.8, "threshold": 0.7, "passed": True, "details": {}},
                ],
            }
        ],
    )
    store.write_json(
        "redteam_findings.json",
        [
            {
                "case_id": "prompt_injection_basic",
                "severity": "critical",
                "passed": False,
                "evidence": "stub",
                "recommendation": "stub",
                "tags": ["injection"],
            }
        ],
    )

    scorecard = generate_scorecard(cfg, store)
    assert scorecard.overall_status in {"fail", "needs_review"}
    assert scorecard.go_no_go == "no-go"
    assert "redteam" in scorecard.stage_gate_status
    assert scorecard.trust_score is not None
    assert scorecard.governance_score is None
    assert scorecard.control_results == []
    assert store.path_for("scorecard.md").exists()
    assert store.path_for("scorecard.html").exists()


def test_reporting_writes_computed_scores_and_system_context(tmp_path: Path) -> None:
    cfg = ToolkitConfig(
        project_name="demo",
        risk_tier="medium",
        output_dir=str(tmp_path / "artifacts"),
        system=SystemSpec.model_validate(
            {
                "created_at": "2026-03-01T12:00:00Z",
                "system_id": "agent-risk-gateway",
                "system_name": "Agent Risk Gateway",
                "version": "1.0.0",
                "model_provider": "OpenAI",
                "model_name": "gpt-4.1",
                "model_version": "2026-02-15",
                "environment": "production",
                "risk_level": "high",
                "compliance_profile": "regulated",
                "telemetry_level": "enhanced",
                "deployment_region": "us-east-1",
                "owner": "ai-governance",
                "metadata": {
                    "intended_use": "Summarize governance controls",
                    "limitations": "May require human escalation",
                    "change_ticket": "GRC-2048",
                    "data_classification": "confidential",
                },
            }
        ),
    )
    store = ArtifactStore(output_dir=cfg.output_dir, run_id="run10")

    store.write_json(
        "redteam_findings.json",
        [
            {
                "case_id": "low-pass",
                "severity": "low",
                "passed": True,
                "evidence": "ok",
                "recommendation": "none",
                "tags": [],
            },
            {
                "case_id": "critical-fail",
                "severity": "critical",
                "passed": False,
                "evidence": "bad",
                "recommendation": "fix",
                "tags": [],
            },
        ],
    )

    scorecard = generate_scorecard(cfg, store)
    payload = json.loads(store.path_for("scorecard.json").read_text(encoding="utf-8"))

    assert scorecard.pillar_scores == {
        "security": 0.75,
        "reliability": 1.0,
        "transparency": 1.0,
        "governance": 1.0,
    }
    assert scorecard.trust_score is None
    assert scorecard.governance_score == 0.925
    assert scorecard.risk_tier == "Tier 1"
    assert scorecard.deployment_risk_tier == "medium"
    assert scorecard.system_context is not None
    assert payload["system_context"] == scorecard.system_context
    assert payload["pillar_scores"] == scorecard.pillar_scores
    assert payload["trust_score"] is None
    assert payload["governance_score"] == 0.925
    assert payload["weighting_rationale"] == {
        "security": 0.3,
        "reliability": 0.3,
        "transparency": 0.25,
        "governance": 0.15,
    }
    assert payload["risk_tier"] == "Tier 1"
    assert len(payload["control_results"]) == 12
    assert payload["redteam_summary"]["pass_rate"] == 0.5
    assert payload["redteam_summary"]["critical_fail_count"] == 1
    assert payload["answer_verdict"] is not None
    scorecard_md = store.path_for("scorecard.md").read_text(encoding="utf-8")
    assert "**Deployment Risk:** Medium" in scorecard_md
    assert "**Control-Derived Tier:** Tier 1" in scorecard_md
    assert "## Weighting Rationale" in scorecard_md
    assert "## Trust Math" in scorecard_md
    assert "## Answer Truth Summary" in scorecard_md
    assert "- Security: 75%" in scorecard_md
    scorecard_html = store.path_for("scorecard.html").read_text(encoding="utf-8")
    assert "Answer Trust" in scorecard_html
    assert "Baseline Trust Inputs" in scorecard_html
    assert "Weighting policy: Security 30%, Reliability 30%, Transparency 25%, Governance 15%." in scorecard_html
    assert "Contribution to the final trust score: 22 points out of 100." in scorecard_html
    assert "50% weighted security controls + 50% red-team pass rate." in scorecard_html
    assert "Evidence Complete" in scorecard_html
    assert "Traceability On" in scorecard_html
    assert "Blocker Findings 1" in scorecard_html
    assert "This answer has governance blockers. Review the failed gates and findings." in scorecard_html


def test_reporting_uses_historical_metric_distribution_for_trust_score(tmp_path: Path) -> None:
    registry_path = tmp_path / "benchmarks" / "registry.json"
    cfg = ToolkitConfig(
        project_name="demo",
        risk_tier="medium",
        output_dir=str(tmp_path / "artifacts"),
        eval={"benchmark_registry_path": str(registry_path)},
    )
    current = ArtifactStore(output_dir=cfg.output_dir, run_id="run3")

    update_registry_for_config(
        registry_path,
        cfg,
        "run1",
        [
            MetricResult(metric_id="accuracy_stub", value=0.7, threshold=0.7, passed=True, details={}),
        ],
    )
    update_registry_for_config(
        registry_path,
        cfg,
        "run2",
        [
            MetricResult(metric_id="accuracy_stub", value=0.8, threshold=0.7, passed=True, details={}),
        ],
    )

    current.write_json(
        "eval_results.json",
        [
            {
                "suite_name": "medium",
                "run_id": "run3",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:01Z",
                "overall_passed": True,
                "notes": [],
                "metric_results": [
                    {"metric_id": "accuracy_stub", "value": 0.9, "threshold": 0.7, "passed": True, "details": {}},
                ],
            }
        ],
    )

    scorecard = generate_scorecard(cfg, current)
    payload = json.loads(current.path_for("benchmark_summary.json").read_text(encoding="utf-8"))

    assert scorecard.trust_score is not None
    assert scorecard.trust_score > 1.0
    assert payload["registry_path"].endswith("registry.json")
    assert "accuracy_stub" in payload["metric_distributions"]
