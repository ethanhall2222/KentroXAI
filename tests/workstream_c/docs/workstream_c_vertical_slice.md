# Workstream C Vertical Slice

**Workstream:** Security / Red Teaming + Monitoring & Incident Response  
**Question:** How is the model protected and monitored against degradation, misuse, and hallucination risk?

## What Exists

This workstream is represented by the red-team vertical slice:
- Backing fixtures: [`tests/redteam`](../../redteam)
- Runtime code: [`src/trusted_ai_toolkit/redteam/runner.py`](../../../src/trusted_ai_toolkit/redteam/runner.py)
- Runtime code: [`src/trusted_ai_toolkit/monitoring.py`](../../../src/trusted_ai_toolkit/monitoring.py)
- Runtime code: [`src/trusted_ai_toolkit/incident.py`](../../../src/trusted_ai_toolkit/incident.py)

## Demonstrated Inputs

- Configs:
  - [`tests/redteam/configs/config_rt01.yaml`](../../redteam/configs/config_rt01.yaml)
  - [`tests/redteam/configs/config_rt03.yaml`](../../redteam/configs/config_rt03.yaml)
- Case registry: [`tests/redteam/redteam_cases.yaml`](../../redteam/redteam_cases.yaml)
- Expected outcomes: [`tests/redteam/expected_outcomes.yaml`](../../redteam/expected_outcomes.yaml)

## Demonstrated Outputs

- `redteam_findings.json`
- `redteam_summary.json`
- `telemetry.jsonl`
- `monitoring_summary.json`
- `incident_report.md` / `incident_report.json` when triggered

## What It Proves

- The repo can run deterministic adversarial cases.
- Severity and pass/fail are captured as reviewable evidence.
- Telemetry can be aggregated into monitoring summaries.
- Threshold or anomaly conditions can automatically open an incident artifact.

## Current Limitation

- Monitoring is event aggregation and rule-based anomaly detection, not full live production degradation monitoring.
