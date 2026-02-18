from __future__ import annotations

from pathlib import Path

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.reporting import generate_scorecard
from trusted_ai_toolkit.schemas import ToolkitConfig


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
    assert store.path_for("scorecard.md").exists()
    assert store.path_for("scorecard.html").exists()
