# Workstream B Vertical Slice

**Workstream:** Evaluation + Evidence Pipeline  
**Question:** How are decisions documented and graded against thresholds?

## What Exists

This workstream is represented by the evaluation portion of the combined evaluation + explainability slice:
- Backing fixtures: [`tests/evaluation_explainability`](../../evaluation_explainability)
- Runtime code: [`src/trusted_ai_toolkit/eval/runner.py`](../../../src/trusted_ai_toolkit/eval/runner.py)
- Runtime code: [`src/trusted_ai_toolkit/reporting.py`](../../../src/trusted_ai_toolkit/reporting.py)

## Demonstrated Inputs

- Configs:
  - [`tests/evaluation_explainability/configs/config_ev01.yaml`](../../evaluation_explainability/configs/config_ev01.yaml)
  - [`tests/evaluation_explainability/configs/config_ev02.yaml`](../../evaluation_explainability/configs/config_ev02.yaml)
  - [`tests/evaluation_explainability/configs/config_ev03.yaml`](../../evaluation_explainability/configs/config_ev03.yaml)
- Scenario registry: [`tests/evaluation_explainability/evaluation_cases.yaml`](../../evaluation_explainability/evaluation_cases.yaml)
- Expected outcomes: [`tests/evaluation_explainability/expected_outcomes.yaml`](../../evaluation_explainability/expected_outcomes.yaml)

## Demonstrated Outputs

- `eval_results.json`
- `eval_summary.json`
- `telemetry.jsonl`

## What It Proves

- The repo can run deterministic suites at multiple risk tiers.
- Threshold breaches can force evaluation-stage failure.
- The scorecard pipeline can consume those results and produce `pass`, `needs_review`, or `fail`.

## Current Limitation

- Several metrics are still deterministic stubs or synthetic fairness calculations rather than production-grade measurements.
