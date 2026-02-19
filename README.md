# Trusted AI Toolkit

A lightweight, offline-first Trusted AI governance toolkit aligned to four workstreams:

- Workstream A: Explainability and Reasoning Report
- Workstream B: Evaluation and Evidence Pipeline
- Workstream C: Security/Red Teaming, Monitoring, and Incident Response
- Workstream D: Documentation Templates and Artifact Repository Structure

## Inspiration and References

- AIF360 (fairness and bias evaluation patterns): https://github.com/Trusted-AI/AIF360

See `DESIGN_NOTES.md` for how this repository maps inspiration patterns into local modules, and `ATTRIBUTION.md` for public reuse guidance.

Current AIF360-inspired implementations:
- Statistical Parity Difference (SPD) fairness metric
- Disparate Impact Ratio (DIR) fairness metric
- Equal Opportunity Difference (EOD) fairness metric
- Average Odds Difference (AOD) fairness metric
- Fairness threshold presentation in scorecards

## Quickstart

```bash
pip install -e .
```

```bash
tat init
tat run prompt --config config.yaml --prompt "Summarize the policy update."
```



## Core Commands

```bash
# (Don't paste this comment in terminal)Primary end-to-end run
tat run prompt --config config.yaml --prompt "Summarize policy controls" --model-output "Stub answer"

# (Don't paste this comment in terminal)Individual workflows
tat eval run --config config.yaml
tat redteam run --config config.yaml
tat xai reasoning-report --config config.yaml
tat report --config config.yaml

# (Don't paste this comment in terminal)Workstream D and Ops workflows
tat docs build --config config.yaml
tat monitor summarize --config config.yaml
tat incident generate --config config.yaml
```
## Open Scorecard:
```
export RUN_ID=$(ls -1t artifacts | head -n 1)
open artifacts/$RUN_ID/scorecard.html
```
## Evidence Pack Outputs

Each run writes to `artifacts/<run_id>/` and includes:

- Workstream A: `reasoning_report.md`, `reasoning_report.json`, `lineage_report.md`, `authoritative_data_index.json`
- Workstream B: `eval_results.json`, `scorecard.md`, `scorecard.html`, `scorecard.json`
- Workstream C: `redteam_findings.json`, `redteam_summary.json`, `monitoring_summary.json`, `incident_report.md` (when triggered)
- Workstream D: `system_card.md`, `data_card.md`, `model_card.md`, `artifact_manifest.json`, `artifact_manifest.md`
- Shared: `prompt_run.json`, `telemetry.jsonl`

## Notes

- No external APIs are required for v0.
- Adapter contracts include future support for Azure OpenAI.
- Golden suites include 50+ deterministic test cases across low, medium, and high tiers.
- Red-team suite includes 20 deterministic security cases.
- This repository is public-facing and designed to allow referenced inspiration patterns with explicit attribution.
