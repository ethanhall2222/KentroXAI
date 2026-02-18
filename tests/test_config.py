from __future__ import annotations

from pathlib import Path

from trusted_ai_toolkit.config import load_config


def test_load_config_validates_new_sections(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
risk_tier: medium
output_dir: artifacts
eval:
  suites: [medium]
xai:
  reasoning_report_template: reasoning_report.md.j2
  include_sections: [Overview]
redteam:
  suites: [baseline]
  cases: [prompt_injection_basic]
  severity_threshold: high
monitoring:
  enabled: true
  telemetry_path: telemetry.jsonl
governance:
  required_stage_gates: [evaluation, redteam, documentation, monitoring]
adapters:
  provider: stub
artifact_policy:
  required_outputs_by_risk_tier:
    medium: [scorecard.md, scorecard.json]
""",
        encoding="utf-8",
    )

    cfg = load_config(config_path)
    assert cfg.project_name == "demo"
    assert cfg.governance.required_stage_gates == ["evaluation", "redteam", "documentation", "monitoring"]
    assert cfg.adapters.provider == "stub"
