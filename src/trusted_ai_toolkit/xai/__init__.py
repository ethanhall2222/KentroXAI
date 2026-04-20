"""
Explainability (XAI) package for the Trusted AI Toolkit.

Public API
----------
``generate_reasoning_report``
    Orchestrate the full reasoning report pipeline: load artifacts, run XAI
    engines, render Jinja2 template, write ``reasoning_report.md`` and
    ``reasoning_report.json``.  Primary entry point for the governance pipeline.

``run_xai_analysis``
    Run all four XAI engines (context attribution, LIME-style attribution,
    SHAP-style Shapley values, counterfactual summary) and return a unified
    payload dict.  Useful for testing or embedding XAI in custom pipelines.

``compute_context_attribution``
    Rank retrieved context chunks by TF-IDF influence on the model output.

``compute_lime_attribution``
    LIME-inspired leave-one-out prompt sentence attribution with bootstrap CIs.

``compute_shapley_attribution``
    SHAP-inspired Shapley value attribution (exact for N ≤ 8, Monte Carlo
    otherwise).

``compute_counterfactual_summary``
    Narrative counterfactual statements derived from eval metrics and lineage.

``generate_lineage_artifacts``
    Write lineage report markdown and authoritative source index artifacts.

``build_lineage_report``
    Build the in-memory lineage report from the prompt bundle's
    ``retrieved_contexts`` field.

``build_authoritative_source_index``
    Convert a lineage report into the authoritative data index format.
"""

from trusted_ai_toolkit.xai.explainability import (
    compute_context_attribution,
    compute_counterfactual_summary,
    compute_lime_attribution,
    compute_shapley_attribution,
    run_xai_analysis,
)
from trusted_ai_toolkit.xai.lineage import (
    build_authoritative_source_index,
    build_lineage_report,
    generate_lineage_artifacts,
)
from trusted_ai_toolkit.xai.reasoning_report import generate_reasoning_report

__all__ = [
    "generate_reasoning_report",
    "run_xai_analysis",
    "compute_context_attribution",
    "compute_lime_attribution",
    "compute_shapley_attribution",
    "compute_counterfactual_summary",
    "generate_lineage_artifacts",
    "build_lineage_report",
    "build_authoritative_source_index",
]
