# Design Notes: External Inspiration Mapping

This repository is intentionally inspired by established Responsible AI tooling patterns. The primary public reference currently adopted is:

- AIF360: https://github.com/Trusted-AI/AIF360

## Scope of Inspiration (Current)

These inspirations are conceptual and architectural, not a direct code mirror.

- Fairness metric framing and terminology for evaluation suites.
- Bias/fairness as first-class scorecard dimensions.
- Repeatable evaluation contracts, with deterministic local stubs in this repository.

## Current Module Mapping

- `src/trusted_ai_toolkit/eval/metrics/__init__.py`
  - Fairness-inspired metric IDs and pass/fail semantics.
- `src/trusted_ai_toolkit/eval/runner.py`
  - Case-based evaluation workflow and threshold gates.
- `src/trusted_ai_toolkit/reporting.py`
  - Scorecard aggregation with fairness-related governance checks.

## Rules for Future Changes

1. Keep the toolkit offline-first and deterministic by default.
2. When introducing fairness metrics inspired by external toolkits, cite the source in docstrings or docs.
3. If any external code is copied directly, include explicit attribution and preserve required license notices.
4. Prefer adapting concepts into this repository's schema/contracts over introducing heavyweight dependencies.

## Integration Path (Planned)

- Short term: expand deterministic fairness proxy cases in local suites.
- Mid term: optional adapter layer for production-grade fairness libraries.
- Long term: enterprise workflow integration while preserving evidence-pack outputs.
