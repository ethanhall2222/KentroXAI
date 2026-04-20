"""
Reasoning report generation for explainability governance artifacts.

This module orchestrates the full reasoning-report pipeline:

  1. Load prerequisite artifacts from the run directory (eval results,
     prompt bundle, red-team summary, lineage report).
  2. Run all four XAI engines via ``run_xai_analysis`` (context attribution,
     LIME-style LOO attribution, SHAP-style Shapley values, counterfactual
     summary).
  3. Assemble a Jinja2 template context dict that combines governance metadata
     with the XAI outputs.
  4. Render and write ``reasoning_report.md`` and ``reasoning_report.json``
     to the run's artifact directory.

The XAI methods are implemented in ``xai/explainability.py`` and require no
external ML libraries — pure Python stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import ToolkitConfig
from trusted_ai_toolkit.xai.explainability import compute_llm_narrative, run_xai_analysis
from trusted_ai_toolkit.xai.lineage import build_lineage_report

# ─────────────────────────────────────────────────────────────────────────────
# Background references cited in the reasoning report
# ─────────────────────────────────────────────────────────────────────────────

TLDR_REFERENCES = [
    "https://www.ibm.com/products/watsonx-governance",
    "https://www.ibm.com/docs/en/cloud-paks/cp-data/5.0.x?topic=solutions-ai-factsheets",
    "https://www.microsoft.com/en-us/ai/responsible-ai",
    "https://arxiv.org/abs/1810.03993",  # Model Cards for Model Reporting
    "https://arxiv.org/abs/2308.09834",  # AI Risk Management
    "https://arxiv.org/abs/1602.04938",  # LIME — Ribeiro et al. 2016
    "https://arxiv.org/abs/1705.07874",  # SHAP — Lundberg & Lee 2017
]


# ─────────────────────────────────────────────────────────────────────────────
# Artifact loading helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_latest_artifact(output_dir: Path, filename: str) -> Path | None:
    """
    Find the most recently modified artifact file at ``output_dir/*/<filename>``.

    Used as a fallback when the current run's artifact is not yet written (e.g.
    when the reasoning report is generated before the eval sweep completes).

    Args:
        output_dir: Root output directory containing per-run subdirectories.
        filename:   Name of the artifact file to search for.

    Returns:
        The path to the most recently modified matching file, or ``None`` if
        no matching files exist under any subdirectory.
    """
    candidates = list(output_dir.glob(f"*/{filename}"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _try_load_eval_summary(output_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """
    Load the evaluation summary from the active run or the most recent prior run.

    Tries ``output_dir/<run_id>/eval_results.json`` first.  Falls back to the
    latest ``eval_results.json`` found anywhere under ``output_dir`` so that the
    reasoning report can still include historical eval data when the current run
    has not yet produced its own evaluation artifact.

    Args:
        output_dir: Root artifact output directory.
        run_id:     Current run identifier.

    Returns:
        A list of eval result dicts, or an empty list if no file is found or
        the file content is not a list or dict with a ``results`` key.
    """
    path = output_dir / run_id / "eval_results.json"
    if not path.exists():
        latest = _find_latest_artifact(output_dir, "eval_results.json")
        if latest is not None:
            path = latest
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get("results", [])
        return results if isinstance(results, list) else []
    return []


def _try_load_json_object(path: Path) -> dict[str, Any]:
    """
    Load a JSON file and return its contents as a dict.

    Args:
        path: Absolute path to the JSON file.

    Returns:
        The parsed dict, or an empty dict if the file does not exist or its
        top-level value is not a JSON object.
    """
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_reasoning_report(
    config: ToolkitConfig,
    store: ArtifactStore,
) -> tuple[Path, Path]:
    """
    Render and write the reasoning report markdown and JSON artifacts.

    Pipeline:
      1. Load prerequisite artifacts (eval results, prompt bundle, red-team
         summary) from the run directory.
      2. Build the lineage report by parsing the prompt bundle's
         ``retrieved_contexts`` field.
      3. Run all XAI engines (context attribution, LIME attribution, Shapley
         values, counterfactual summary) via ``run_xai_analysis``.
      4. Assemble the Jinja2 template context combining governance metadata
         with XAI outputs.
      5. Render ``reasoning_report.md`` and write ``reasoning_report.json``
         to the run's artifact directory.

    The XAI analysis replaces the former TODO placeholders.  All four methods
    are now live:

    - **Context Attribution** — ranks retrieved source chunks by their lexical
      influence on the model output.
    - **LIME-style Attribution** — LOO sentence attribution with 95% bootstrap
      confidence intervals.
    - **SHAP-style Shapley Values** — exact (N ≤ 8 sentences) or Monte Carlo
      Shapley values quantifying fair credit per prompt segment.
    - **Counterfactual Summary** — narrative "what-if" statements derived from
      eval metrics and lineage data.

    Args:
        config:
            Toolkit configuration object (``ToolkitConfig`` Pydantic model).
            Used to populate governance metadata (project name, risk tier,
            model config, data config, XAI include-sections).
        store:
            Artifact store for the current run.  Provides the run ID, output
            directory, and write helpers.

    Returns:
        A tuple (md_path, json_path) pointing to the written artifacts.

    Raises:
        OSError:  If the artifact directory is not writable.
        ValueError: If the reasoning report template is not found.
    """
    # ── Step 1: load prerequisite artifacts ───────────────────────────────────
    eval_summary = _try_load_eval_summary(store.output_dir, store.run_id)
    prompt_bundle = _try_load_json_object(store.path_for("prompt_run.json"))
    redteam_findings = _try_load_json_object(store.path_for("redteam_summary.json"))

    # ── Step 2: build lineage report from retrieved contexts ─────────────────
    lineage_report = build_lineage_report(store)

    # ── Step 3: run XAI analysis ──────────────────────────────────────────────
    # Extract raw inputs needed by the XAI engines.
    prompt_text = str(prompt_bundle.get("prompt", ""))
    model_output = str(prompt_bundle.get("model_output", ""))
    retrieved_contexts: list[dict[str, Any]] = (
        prompt_bundle.get("retrieved_contexts", [])
        if isinstance(prompt_bundle.get("retrieved_contexts", []), list)
        else []
    )

    # ``run_xai_analysis`` orchestrates all four engines and returns a unified
    # payload.  It is safe to call with empty inputs — all engines degrade
    # gracefully.  Eval summary is passed as plain dicts (not Pydantic models)
    # since the counterfactual engine operates on the serialised form.
    xai_results = run_xai_analysis(
        prompt=prompt_text,
        model_output=model_output,
        contexts=retrieved_contexts,
        eval_results=[r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in eval_summary],
        lineage_nodes=[node.model_dump(mode="json") for node in lineage_report.nodes],
        redteam_summary=redteam_findings,
    )

    # ── Step 3b: optional LLM narrative (Tim2 — Option A) ────────────────────
    # Reads the deterministic verdict and metric values from the scorecard
    # written earlier in the run, then asks the configured LLM to write a
    # plain-language rationale for the existing verdict.  Stub-safe: returns
    # ``available=False`` when no live adapter is configured.
    scorecard_payload = _try_load_json_object(store.path_for("scorecard.json"))
    metric_summary_for_narrative: dict[str, Any] = {}
    truth = scorecard_payload.get("answer_truth_summary") or {} if isinstance(scorecard_payload, dict) else {}
    for key in ("claim_support_rate", "unsupported_claim_rate", "contradiction_rate", "evidence_sufficiency_score"):
        if isinstance(truth, dict) and truth.get(key) is not None:
            metric_summary_for_narrative[key] = truth.get(key)
    bias = scorecard_payload.get("bias_assessment") or {} if isinstance(scorecard_payload, dict) else {}
    if isinstance(bias, dict) and bias.get("signal_count") is not None:
        metric_summary_for_narrative["bias_signal_count"] = bias.get("signal_count")
    if isinstance(scorecard_payload, dict) and scorecard_payload.get("answer_trust_score") is not None:
        metric_summary_for_narrative["answer_trust_score"] = scorecard_payload.get("answer_trust_score")

    llm_narrative = compute_llm_narrative(
        config=config,
        verdict=scorecard_payload.get("answer_verdict") if isinstance(scorecard_payload, dict) else None,
        reasons=(scorecard_payload.get("answer_reasons") or []) if isinstance(scorecard_payload, dict) else [],
        metric_summary=metric_summary_for_narrative,
        model_output=model_output,
        contexts=retrieved_contexts,
    )

    # ── Step 4: assemble Jinja2 template context ──────────────────────────────
    governance_controls = [
        "Intended use and misuse boundaries are defined.",
        "Known limitations and failure modes are documented.",
        "Evaluation and threshold criteria are documented.",
        "Security testing outputs are tracked as review evidence.",
        "Human review remains required for deployment approval.",
    ]

    context: dict[str, Any] = {
        # ── Governance metadata ────────────────────────────────────────────────
        "project_name": config.project_name,
        "run_id": store.run_id,
        "risk_tier": config.risk_tier,
        "data": config.data.model_dump() if config.data else {},
        "model": config.model.model_dump() if config.model else {},
        "include_sections": config.xai.include_sections,
        # ── Prompt and output snapshot ─────────────────────────────────────────
        "prompt": prompt_text,
        "model_output": model_output,
        # ── Evaluation results ─────────────────────────────────────────────────
        "eval_summary": eval_summary,
        # ── Lineage and source provenance ──────────────────────────────────────
        "lineage_nodes": [node.model_dump(mode="json") for node in lineage_report.nodes],
        "citation_coverage": lineage_report.citation_coverage,
        "transparency_risk": lineage_report.transparency_risk,
        # ── Red-team summary ───────────────────────────────────────────────────
        "redteam_summary": redteam_findings,
        # ── Governance controls and escalation cues ────────────────────────────
        "governance_controls": governance_controls,
        "escalation_cues": [
            "Escalate if transparency risk is high.",
            "Escalate if scorecard go/no-go status is no-go.",
            "Escalate if high or critical red-team findings remain open.",
            "Escalate if LIME or Shapley attribution identifies a single segment "
            "that accounts for > 80% of the total output similarity.",
        ],
        "stakeholders": [
            "Model Owner",
            "Responsible AI Reviewer",
            "Security Reviewer",
            "Product and Compliance Stakeholders",
        ],
        "references": TLDR_REFERENCES,
        # ── XAI analysis results (previously TODO placeholders) ────────────────
        # All four XAI methods are now live.  See xai/explainability.py.
        "xai_available": xai_results["xai_available"],
        "xai_method_labels": xai_results["method_labels"],
        "context_attribution": xai_results["context_attribution"],
        "lime_attribution": xai_results["lime_attribution"],
        "shapley_attribution": xai_results["shapley_attribution"],
        "counterfactual_summary": xai_results["counterfactual_summary"],
        # ── LLM narrative explanation (Tim2 — Option A) ────────────────────────
        # Stub-safe; the template renders a fallback note when ``available`` is
        # False so demo runs without a live adapter still produce a valid file.
        "llm_narrative": llm_narrative,
    }

    # ── Step 5: render and write artifacts ────────────────────────────────────
    md_path = store.save_rendered_md(
        config.xai.reasoning_report_template,
        "reasoning_report.md",
        context,
    )
    json_path = store.write_json("reasoning_report.json", context)
    return md_path, json_path
