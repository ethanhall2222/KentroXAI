# Evaluation Vertical Slice
**Owner:** Workstream B (Evaluation & Evidence)  
**Branch:** main  
**Date:** 26FEB2026  

---

## Overview

This vertical slice validates the evaluation harness in deterministic offline mode.

Goals:
- Verify baseline pass behavior under low-risk thresholds.
- Verify moderate-risk gating behavior with fairness sensitivity.
- Verify strict high-risk gating by forcing threshold failures.
- Produce reproducible artifacts for governance evidence and regression checks.

---

## Slice Structure

**Location:** `tests/evaluation/`

Contains:
- `evaluation_cases.yaml` (scenario registry)
- `expected_outcomes.yaml` (asserted pass/fail behavior)
- `schemas/eval_summary.json` (summary contract)
- `outputs/EV-01/`, `outputs/EV-02/`, and `outputs/EV-03/` (captured artifacts)

---

## Scenario Design

### EV-01 (Baseline)
- Config: `tests/evaluation/configs/config_ev01.yaml`
- Suite: `low`
- Expected: all metrics pass and `overall_passed = true`

### EV-02 (Moderate Risk)
- Config: `tests/evaluation/configs/config_ev02.yaml`
- Suite: `medium`
- Expected: targeted fairness failure (`fairness_disparate_impact_ratio`) with remaining metrics passing

### EV-03 (Strict High-Risk)
- Config: `tests/evaluation/configs/config_ev03.yaml`
- Suite: `high`
- Expected: multiple metric failures due to tightened thresholds and `overall_passed = false`

---

## Reproduction Commands

```bash
TAT_OUTPUT_DIR=tests/evaluation/outputs TAT_RUN_ID=EV-01 tat eval run --config tests/evaluation/configs/config_ev01.yaml
TAT_OUTPUT_DIR=tests/evaluation/outputs TAT_RUN_ID=EV-02 tat eval run --config tests/evaluation/configs/config_ev02.yaml
TAT_OUTPUT_DIR=tests/evaluation/outputs TAT_RUN_ID=EV-03 tat eval run --config tests/evaluation/configs/config_ev03.yaml
```

---

## Artifacts Produced Per Slice

- `eval_results.json`
- `eval_summary.json`
- `telemetry.jsonl`

These outputs support regression validation and governance reporting for Measure/Manage workflows.
