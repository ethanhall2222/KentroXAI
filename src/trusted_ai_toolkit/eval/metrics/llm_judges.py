"""LLM-as-judge advisory metrics.

These metrics complement the deterministic claim-level grounding family by
asking a configured LLM to grade each extracted claim against its
best-matched evidence.  They are intentionally classified as **advisory** in
``_metric_strength_map`` and never feed the verdict gates in
``_VERDICT_THRESHOLDS``: the deterministic metrics remain the source of
truth for the audit story, and the LLM judges are presented as a
high-signal but non-blocking second opinion.

Design properties
-----------------
* **Stub-safe.**  When ``config.adapters.provider == "stub"`` (or any other
  failure path) the metric returns ``value=None`` with
  ``data_basis="llm_unavailable"`` rather than raising.  Pipelines that
  never configure a live adapter run unchanged.
* **Deterministic mode.**  Each invocation requests temperature=0 and a
  fixed seed via ``invoke_model_safely(deterministic=True)``.  Combined
  with the in-process cache below, repeated runs over the same inputs
  produce identical metric values.
* **In-process cache.**  Per-claim verdicts are cached by
  ``hash((metric_id, model, claim, evidence))`` so re-runs of the same
  judge over the same inputs do not pay duplicate API calls.  The cache
  is per-process; for cross-run reproducibility the determinism flag is
  the load-bearing guarantee.
* **Tiny single-token responses.**  Each claim-level call asks for a
  single ``YES`` or ``NO`` token, parsed by inspecting the first
  alphabetic character of the response.  This keeps cost negligible
  even for long answers.
"""

from __future__ import annotations

import re
from typing import Any

from trusted_ai_toolkit.eval.metrics import _claim_analysis, _context_texts
from trusted_ai_toolkit.model_client import invoke_model_safely
from trusted_ai_toolkit.schemas import MetricResult, ToolkitConfig

# Word-boundary scan for the first standalone yes / no token in the
# response.  The original parser walked characters and returned "unknown"
# the moment it saw any alphabetic character that wasn't y or n — so
# common prose preambles ("The claim does not...", "Based on the evidence,
# no...") all parsed as unknown even though the response was clearly
# answering the question.
_YES_NO_PATTERN = re.compile(r"\b(yes|no)\b", re.IGNORECASE)

# ─────────────────────────────────────────────────────────────────────────────
# Per-process verdict cache
# ─────────────────────────────────────────────────────────────────────────────
# Key: (metric_id, model_name, claim_text, evidence_text)
# Val: "yes" | "no" | "unknown"

_LLM_JUDGE_CACHE: dict[tuple[str, str, str, str], str] = {}


def _parse_yes_no(text: str) -> str:
    """Return 'yes', 'no', or 'unknown' from a model response.

    Looks for the first standalone yes/no token (word boundary match).
    Tolerates prose preambles like "The claim does not contradict..." or
    "Based on the evidence, no contradiction." — both of which would have
    been classified as "unknown" by the previous first-alphabetic-char
    scan.  The prompt still requests a single YES/NO token, but real LLMs
    routinely add explanation; the parser should accept either shape.
    """

    if not text:
        return "unknown"
    match = _YES_NO_PATTERN.search(text)
    if match is None:
        return "unknown"
    return match.group(1).lower()


def _llm_unavailable_result(metric_id: str, reason: str) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        value=None,
        threshold=None,
        passed=None,
        details={
            "method": "llm_judge",
            "data_basis": "llm_unavailable",
            "reason": reason,
            "strength": "advisory",
        },
    )


def _grade_claim(
    metric_id: str,
    config: ToolkitConfig,
    model_label: str,
    claim: str,
    evidence: str,
    instruction: str,
) -> str:
    """Cached single-claim YES/NO grading helper."""

    key = (metric_id, model_label, claim.strip(), evidence.strip())
    if key in _LLM_JUDGE_CACHE:
        return _LLM_JUDGE_CACHE[key]

    prompt = (
        f"{instruction}\n\n"
        f"CLAIM:\n{claim.strip()}\n\n"
        f"EVIDENCE:\n{evidence.strip()}\n\n"
        f"Respond with exactly one word: YES or NO."
    )
    result = invoke_model_safely(prompt, config, deterministic=True)
    if result is None:
        verdict = "unknown"
    else:
        verdict = _parse_yes_no(result.output_text)

    _LLM_JUDGE_CACHE[key] = verdict
    return verdict


def _resolve_model_label(config: ToolkitConfig) -> str:
    """A stable label for the configured chat model, used as a cache key."""

    if config.adapters.model:
        return config.adapters.model
    if config.system and config.system.model_name:
        return config.system.model_name
    return f"{config.adapters.provider}:default"


def _judge_each_claim(
    metric_id: str,
    context: dict,
    instruction: str,
    target_label: str,
) -> MetricResult:
    """Shared body for both LLM judge metrics.

    Iterates the deterministically extracted claims, asks the LLM whether
    each one satisfies the instruction against its best-matched evidence,
    and returns ``count(target_label) / total_claims`` as the metric value.
    """

    config = context.get("toolkit_config")
    if not isinstance(config, ToolkitConfig):
        return _llm_unavailable_result(
            metric_id, "toolkit_config not present in metric context"
        )
    if config.adapters.provider == "stub":
        return _llm_unavailable_result(
            metric_id, "adapters.provider is 'stub'; no live LLM is configured"
        )

    output_text = str(context.get("model_output", ""))
    contexts = _context_texts(context)
    analysis = _claim_analysis(output_text, contexts)
    claim_rows = analysis.get("claims", [])
    if not isinstance(claim_rows, list) or not claim_rows:
        return _llm_unavailable_result(metric_id, "no extractable claims in model output")

    model_label = _resolve_model_label(config)

    judgments: list[dict[str, Any]] = []
    target_count = 0
    unknown_count = 0
    for row in claim_rows:
        if not isinstance(row, dict):
            continue
        claim = str(row.get("claim", ""))
        evidence = str(row.get("matched_context", ""))
        if not claim or not evidence:
            unknown_count += 1
            judgments.append({"claim": claim, "verdict": "unknown", "reason": "missing claim or evidence"})
            continue
        verdict = _grade_claim(metric_id, config, model_label, claim, evidence, instruction)
        if verdict == target_label:
            target_count += 1
        elif verdict == "unknown":
            unknown_count += 1
        judgments.append({"claim": claim[:200], "verdict": verdict})

    total_claims = len(claim_rows)
    # Deterministic baseline: if the LLM could not grade any claim, surface
    # the metric as unavailable rather than reporting a misleading 0.
    if unknown_count == total_claims:
        return _llm_unavailable_result(metric_id, "LLM did not grade any claim")

    value = round(target_count / total_claims, 3)
    return MetricResult(
        metric_id=metric_id,
        value=value,
        threshold=None,
        passed=None,
        details={
            "method": "llm_judge",
            "model": model_label,
            "claim_count": total_claims,
            f"{target_label}_count": target_count,
            "unknown_count": unknown_count,
            "judgments": judgments,
            "strength": "advisory",
            "data_basis": "llm_judged",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public metric functions
# ─────────────────────────────────────────────────────────────────────────────

def metric_llm_contradiction_judge(context: dict) -> MetricResult:
    """LLM-graded contradiction rate.

    For each claim extracted from the model output, ask the configured LLM
    whether the claim contradicts the matched evidence chunk.  Returns the
    fraction graded as contradictory.  Compare against the deterministic
    ``contradiction_rate`` to spot cases the polarity heuristic missed
    (e.g., "free" vs "$50") or false positives (e.g., the heuristic sees
    "not" but the surrounding meaning is consistent).
    """

    return _judge_each_claim(
        metric_id="llm_contradiction_judge",
        context=context,
        instruction=(
            "You are a careful fact-checker. Decide whether the CLAIM contradicts "
            "the EVIDENCE. A contradiction exists when the claim asserts something "
            "that the evidence directly denies or that cannot be reconciled with the "
            "evidence. Lexical similarity is not sufficient — focus on meaning."
        ),
        target_label="yes",
    )


def metric_llm_claim_entailment(context: dict) -> MetricResult:
    """LLM-graded claim entailment rate.

    For each extracted claim, ask whether the matched evidence entails the
    claim.  Returns the fraction graded as entailed.  This is the LLM
    equivalent of ``claim_support_rate``: the deterministic version uses
    TF-IDF overlap thresholds, this version uses model judgment, and the
    two should be reported side-by-side for governance review.
    """

    return _judge_each_claim(
        metric_id="llm_claim_entailment",
        context=context,
        instruction=(
            "You are a careful fact-checker. Decide whether the EVIDENCE entails "
            "the CLAIM — that is, whether a reasonable reader would conclude that "
            "the claim is supported by the evidence. Partial or paraphrased support "
            "counts as entailed; unsupported speculation does not."
        ),
        target_label="yes",
    )
