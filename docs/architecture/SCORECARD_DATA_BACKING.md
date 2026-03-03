# Scorecard Data Backing and Interpretation

## Why This Document Exists

This document explains what the scorecard is showing, where each major number comes from, and whether that number is:

- directly backed by real run artifacts,
- structurally correct but based on synthetic or proxy inputs, or
- presentation-only summary logic.

This is the best way to read the current scorecard without overstating what the toolkit is proving.

## Short Answer

The scorecard logic is real and internally consistent, but not all underlying measurements are production-grade.

- The governance gates, artifact completeness checks, red-team counts, and control checks are real calculations over real run artifacts.
- Several evaluation metrics are still deterministic stubs or synthetic fairness calculations.
- The headline `Trust Score` on the HTML card is a presentation score derived from real stage-gate outcomes plus the underlying control score.

So the scorecard is useful for governance workflow demonstration and comparative review, but it should not be presented as fully model-validated quantitative assurance.

## What the Scorecard Is Doing

The scorecard is generated in [`src/trusted_ai_toolkit/reporting.py`](../../src/trusted_ai_toolkit/reporting.py).

It combines five signal groups:

1. Evaluation metric results from `eval_results.json`
2. Red-team findings from `redteam_findings.json`
3. Governance control results from `config.system`
4. Evidence completeness from required artifact presence
5. Monitoring and incident context from telemetry-derived artifacts

The final release decision is driven by stage gates, not by the headline score alone.

## What Is Strongly Backed

These values are directly tied to real run artifacts or deterministic rule checks and are reliable within the current design:

### Stage Gate Status

Source: [`src/trusted_ai_toolkit/reporting.py`](../../src/trusted_ai_toolkit/reporting.py)

- `evaluation = fail` if any metric result has `passed = false`
- `redteam = fail` or `needs_review` based on finding severity and risk-tier rules
- `documentation = pass` when evidence completeness is at least `90%`
- `monitoring = pass` in the current implementation

This is the main source of truth for:

- `overall_status`
- `go_no_go`

### Red-Team Finding Counts

Source: [`src/tat/controls/scoring.py`](../../src/tat/controls/scoring.py)

These are direct counts of:

- `low`
- `medium`
- `high`
- `critical`
- `critical_fail_count`
- `pass_rate`

These values are structurally sound because they are computed from the actual normalized findings written for the run.

### Evidence Completeness

Sources:

- [`src/trusted_ai_toolkit/reporting.py`](../../src/trusted_ai_toolkit/reporting.py)
- [`src/trusted_ai_toolkit/artifacts.py`](../../src/trusted_ai_toolkit/artifacts.py)

This is calculated from required file presence, not estimation:

`present_required_outputs / total_required_outputs * 100`

It is a real auditability signal, but it measures presence only, not artifact quality.

### Governance Control Results and Underlying Control Score

Sources:

- [`src/tat/controls/library.py`](../../src/tat/controls/library.py)
- [`src/tat/controls/scoring.py`](../../src/tat/controls/scoring.py)

The control checks are deterministic validations against the configured `system` metadata. The underlying control score is the equal-weighted average of pillar scores, with the security pillar blending control pass rate and red-team pass rate.

This is real rule logic, but it reflects policy compliance metadata, not model behavior.

## What Is Proxy-Backed

These values use valid math, but the current inputs are still synthetic or heuristic.

### Evaluation Metrics

Source: [`src/trusted_ai_toolkit/eval/metrics/__init__.py`](../../src/trusted_ai_toolkit/eval/metrics/__init__.py)

- `accuracy_stub`: fixed deterministic value
- `reliability`: fixed deterministic value
- `groundedness_stub`: fixed deterministic value

These are placeholders. The math is trivial and consistent, but the values are not derived from real model outputs.

### Safety Proxy Metrics

Source: [`src/trusted_ai_toolkit/eval/metrics/__init__.py`](../../src/trusted_ai_toolkit/eval/metrics/__init__.py)

- `refusal_correctness`
- `unanswerable_handling`

These are derived from the composition of the eval suite (`unsafe_cases`, `unanswerable_cases`) rather than observed model behavior. They are useful directional signals, but not runtime measurements.

### Fairness Metrics

Sources:

- [`src/trusted_ai_toolkit/eval/metrics/__init__.py`](../../src/trusted_ai_toolkit/eval/metrics/__init__.py)
- [`src/trusted_ai_toolkit/eval/metrics/aif360_compat.py`](../../src/trusted_ai_toolkit/eval/metrics/aif360_compat.py)

The formulas are real and AIF360-inspired:

- demographic parity difference
- disparate impact ratio
- equal opportunity difference
- average odds difference

However, the current implementation uses hardcoded synthetic cohort labels. That means:

- the formulas are valid,
- the outputs are deterministic,
- but the measured values are not tied to actual run-specific cohort outcomes.

### Explainability Signals

Source: [`src/trusted_ai_toolkit/xai/lineage.py`](../../src/trusted_ai_toolkit/xai/lineage.py)

- `citation_coverage`
- `transparency_risk`

These are based on heuristic string matching between the generated output and retrieved context node IDs or titles. They are useful lightweight traceability indicators, but not semantic attribution proof.

## What Is Presentation-Level

### Headline `Trust Score`

Sources:

- [`src/trusted_ai_toolkit/reporting.py`](../../src/trusted_ai_toolkit/reporting.py)
- [`src/trusted_ai_toolkit/templates/scorecard.html.j2`](../../src/trusted_ai_toolkit/templates/scorecard.html.j2)

The visible `Trust Score` on the HTML card is a presentation score that is now aligned to the release outcome.

It works as:

1. Start from the underlying control score percentage
2. Subtract penalties for:
   - failed evaluation metrics
   - medium/high/critical red-team findings
   - evidence completeness below `90%`
   - failed or weak stage gates
3. Cap the score by final status:
   - `fail` cannot exceed `59`
   - `needs_review` cannot exceed `79`
   - `pass` can reach `100`

This makes the score directionally consistent with `overall_status`, but it is still a summary layer. The hard release decision is still the stage-gate logic.

### Scorecard Labels and Executive Wording

Source: [`src/trusted_ai_toolkit/templates/scorecard.html.j2`](../../src/trusted_ai_toolkit/templates/scorecard.html.j2)

Items such as:

- `Evaluation Summary`
- `Security Findings`
- `Actions Required`
- `Control Summary`

are presentation groupings. They reorganize real underlying values for readability; they are not separate calculations.

## How to Read the Card Correctly

Use this order:

1. `Overall Status`
2. `Go/No-Go`
3. `Stage Gates`
4. `Actions Required`
5. `Trust Score`
6. `Underlying control score`

Why this order:

- `Overall Status` and `Go/No-Go` tell you the actual governance result.
- `Stage Gates` tell you what failed.
- `Actions Required` tells you what must be fixed.
- `Trust Score` is a top-line summary, not the final authority.
- `Underlying control score` is a narrower policy-compliance signal.

## What You Can Safely Claim

Reasonable claims:

- The toolkit produces a real end-to-end governance evidence pack.
- The scorecard’s release decision is based on deterministic stage-gate logic.
- The red-team, completeness, and control checks are genuinely computed from the run state.
- The scorecard is suitable for workflow demonstration and governance process review.

Claims to avoid:

- The evaluation metrics are fully production-validated.
- The fairness outputs reflect real deployment cohort performance.
- The headline score is an externally benchmarked trust metric.
- The current scorecard alone proves production readiness.

## Recommended Explanation for Demos

Use this phrasing:

`The scorecard is a real governance decision layer built on actual artifacts and deterministic controls, but some evaluation inputs are still proxy-backed rather than production-grade measurements.`

## Source of Truth

Primary implementation files:

- [`src/trusted_ai_toolkit/reporting.py`](../../src/trusted_ai_toolkit/reporting.py)
- [`src/tat/controls/scoring.py`](../../src/tat/controls/scoring.py)
- [`src/trusted_ai_toolkit/eval/metrics/__init__.py`](../../src/trusted_ai_toolkit/eval/metrics/__init__.py)
- [`src/trusted_ai_toolkit/eval/metrics/aif360_compat.py`](../../src/trusted_ai_toolkit/eval/metrics/aif360_compat.py)
- [`src/trusted_ai_toolkit/xai/lineage.py`](../../src/trusted_ai_toolkit/xai/lineage.py)
- [`src/trusted_ai_toolkit/templates/scorecard.html.j2`](../../src/trusted_ai_toolkit/templates/scorecard.html.j2)

