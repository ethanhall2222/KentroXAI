from __future__ import annotations

from pathlib import Path

import yaml

from trusted_ai_toolkit.eval.runner import run_eval
from trusted_ai_toolkit.schemas import ToolkitConfig


def test_eval_runner_returns_case_based_results(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": [
                    "accuracy_stub",
                    "reliability",
                    "fairness_demographic_parity_diff",
                    "fairness_disparate_impact_ratio",
                    "fairness_equal_opportunity_difference",
                    "fairness_average_odds_difference",
                    "groundedness_stub",
                    "refusal_correctness",
                    "unanswerable_handling",
                ],
                "cases": [
                    {"case_id": "1", "kind": "safe"},
                    {"case_id": "2", "kind": "unsafe"},
                    {"case_id": "3", "kind": "unanswerable"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = ToolkitConfig(project_name="demo", risk_tier="medium", output_dir=str(tmp_path / "artifacts"), eval={"suites": ["medium"]})
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    assert len(results) == 1
    assert results[0].suite_name == "medium"
    assert len(results[0].metric_results) == 9
    assert any("Golden cases executed" in note for note in results[0].notes)
