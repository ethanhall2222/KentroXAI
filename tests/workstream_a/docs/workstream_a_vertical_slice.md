# Workstream A Vertical Slice

**Workstream:** Explainability and Decision Basis  
**Question:** Why is the model making decisions, and what is the knowledge basis for those decisions?

## What Exists

This workstream is represented by the explainability portion of the combined evaluation + explainability slice:
- Backing fixtures: [`tests/evaluation_explainability`](../../evaluation_explainability)
- Runtime code: [`src/trusted_ai_toolkit/xai/reasoning_report.py`](../../../src/trusted_ai_toolkit/xai/reasoning_report.py)
- Runtime code: [`src/trusted_ai_toolkit/xai/lineage.py`](../../../src/trusted_ai_toolkit/xai/lineage.py)

## Demonstrated Artifacts

- `reasoning_report.md`
- `reasoning_report.json`
- `lineage_report.md`
- `authoritative_data_index.json`

## What It Proves

- The repo can generate a reasoning artifact for review.
- The repo can trace provided `retrieved_contexts` into lineage/source artifacts.
- The repo can expose a lightweight transparency signal (`citation_coverage`, `transparency_risk`).

## Current Limitation

- This is governance-oriented explainability and provenance tracing, not full model-native explanation.
- The lineage signal depends on supplied `retrieved_contexts`; no standalone retrieval engine is in the repo yet.
