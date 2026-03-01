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
system:
  created_at: "2026-03-01T12:00:00Z"
  system_id: agent-risk-gateway
  system_name: Agent Risk Gateway
  version: 1.0.0
  model_provider: OpenAI
  model_name: gpt-4.1
  model_version: "2026-02-15"
  environment: production
  risk_level: high
  compliance_profile: regulated
  telemetry_level: enhanced
  deployment_region: us-east-1
  owner: ai-governance
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
    assert cfg.system is not None
    assert cfg.system.system_id == "agent-risk-gateway"
    assert cfg.system.environment == "production"
    assert cfg.governance.required_stage_gates == ["evaluation", "redteam", "documentation", "monitoring"]
    assert cfg.adapters.provider == "stub"
