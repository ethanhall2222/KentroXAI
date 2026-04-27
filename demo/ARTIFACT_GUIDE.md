# Artifact Guide

This file explains what each generated artifact is, who it is for, and where it comes from in the code.

## Runtime Evidence

| Artifact | Purpose | Primary Audience | Main Source |
| --- | --- | --- | --- |
| `prompt_run.json` | Captures prompt, model output, retrieved contexts, and run metadata | Engineers, auditors | `src/trusted_ai_toolkit/cli.py` |
| `eval_results.json` | Stores metric-by-metric evaluation results | Engineers, model reviewers | `src/trusted_ai_toolkit/eval/runner.py` |
| `redteam_findings.json` | Raw red-team findings | Security, governance | `src/trusted_ai_toolkit/redteam/runner.py` |
| `redteam_summary.json` | Severity rollup of red-team findings | Security, release owners | `src/trusted_ai_toolkit/cli.py` |
| `monitoring_summary.json` | Event and anomaly summary | Operations, governance | `src/trusted_ai_toolkit/monitoring.py` |
| `telemetry.jsonl` | Append-only execution telemetry | Operations, audit | `src/trusted_ai_toolkit/monitoring.py` |

Directory location:

- generated under `artifacts/<run_id>/`
- sample reference under `sample_evidence_pack/20260218T143752Z/`

## Decision Artifacts

| Artifact | Purpose | Primary Audience | Main Source |
| --- | --- | --- | --- |
| `scorecard.json` | Structured scorecard payload with metrics, verdicts, stage gates, and actions | App backend, engineers, auditors | `src/trusted_ai_toolkit/reporting.py` |
| `scorecard.md` | Human-readable markdown trust card | Reviewers, governance | `src/trusted_ai_toolkit/templates/scorecard.md.j2` |
| `scorecard.html` | Interactive scorecard for the app and demos | Executives, reviewers, users | `src/trusted_ai_toolkit/templates/scorecard.html.j2` |

Directory location:

- render logic: `src/trusted_ai_toolkit/reporting.py`
- templates: `src/trusted_ai_toolkit/templates/`
- generated output: `artifacts/<run_id>/`

## Explainability Artifacts

| Artifact | Purpose | Primary Audience | Main Source |
| --- | --- | --- | --- |
| `reasoning_report.md` | Narrative explainability summary | Governance, reviewers | `src/trusted_ai_toolkit/xai/reasoning_report.py` |
| `reasoning_report.json` | Structured explainability payload | Systems, developers | `src/trusted_ai_toolkit/xai/reasoning_report.py` |
| `lineage_report.md` | Source lineage and provenance summary | Audit, compliance | `src/trusted_ai_toolkit/xai/lineage.py` |
| `authoritative_data_index.json` | Structured reference index of source data used for traceability | Engineers, audit | `src/trusted_ai_toolkit/xai/lineage.py` |

Directory location:

- code: `src/trusted_ai_toolkit/xai/`
- templates: `src/trusted_ai_toolkit/templates/`
- generated output: `artifacts/<run_id>/`

## Documentation and Audit Artifacts

| Artifact | Purpose | Primary Audience | Main Source |
| --- | --- | --- | --- |
| `system_card.md` | System description and intended use | Governance, architecture | `src/trusted_ai_toolkit/documentation.py` |
| `data_card.md` | Data documentation summary | Governance, data owners | `src/trusted_ai_toolkit/documentation.py` |
| `model_card.md` | Model usage and limitation summary | Governance, model risk | `src/trusted_ai_toolkit/documentation.py` |
| `artifact_manifest.json` | Machine-readable inventory of generated artifacts | Audit, automation | `src/trusted_ai_toolkit/documentation.py` |
| `artifact_manifest.md` | Human-readable artifact index | Reviewers, auditors | `src/trusted_ai_toolkit/documentation.py` |
| `incident_report.json` | Structured incident escalation payload when triggered | Ops, governance | `src/trusted_ai_toolkit/incident.py` |
| `incident_report.md` | Human-readable incident escalation summary | Ops, reviewers | `src/trusted_ai_toolkit/incident.py` |

Directory location:

- code: `src/trusted_ai_toolkit/documentation.py`
- incident logic: `src/trusted_ai_toolkit/incident.py`
- templates: `src/trusted_ai_toolkit/templates/`
- generated output: `artifacts/<run_id>/`

## Best Artifacts to Show in a Demo

If time is short, show these:

1. `scorecard.html`
2. `scorecard.json`
3. `eval_results.json`
4. `reasoning_report.md`
5. `artifact_manifest.json`

## Suggested Commentary

- `prompt_run.json` proves what the system saw and answered.
- `eval_results.json` proves how the answer was scored.
- `scorecard.html` is the business-facing decision surface.
- `reasoning_report.md` explains why the answer and system landed where they did.
- `artifact_manifest.json` proves this is an auditable package, not a one-off screen. 

## Repo Directory Map

- App:
  - `apps/kentro-chat/`
- Core package:
  - `src/trusted_ai_toolkit/`
- Controls:
  - `src/tat/`
- Suites:
  - `suites/`
- Templates:
  - `src/trusted_ai_toolkit/templates/`
- Example outputs:
  - `sample_evidence_pack/20260218T143752Z/`
