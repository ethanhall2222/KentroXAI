"""Live smoke test for the LLM rationalization layer (Tim2 — Options A and B).

This script makes REAL HTTP calls to a configured LLM provider.  Use it
once you have one of the following set up:

  Ollama (recommended for local testing — no API key needed):
    1. Install Ollama from https://ollama.com/download
    2. `ollama pull qwen2.5:3b`        (or any small instruction-tuned model)
    3. `ollama serve`                  (runs on http://localhost:11434)
    4. PYTHONPATH=src python scripts/smoke_test_llm_rationalization.py

  OpenAI-compatible endpoint:
    1. export OPENAI_API_KEY=sk-...
    2. Edit the LIVE_CONFIG block below to switch provider and endpoint.
    3. PYTHONPATH=src python scripts/smoke_test_llm_rationalization.py

What it tests
-------------
1. Option B — `llm_contradiction_judge` over a fixture answer that
   intentionally contradicts the evidence ("free of charge" vs "USD 50").
   Prints the per-claim verdicts so you can see whether the model caught
   the semantic contradiction the deterministic polarity heuristic would
   miss.

2. Option B — `llm_claim_entailment` over the same fixture.  Should
   grade the un-contradicted claims as entailed.

3. Option A — `compute_llm_narrative` produces a 2-paragraph plain-language
   rationale for a deterministic verdict.  Prints the full narrative and
   confirms the cache short-circuits a second call.

The test is deliberately small (3 claims, 1 evidence chunk) so a 3B-class
model can run it in a few seconds without burning quota.
"""

from __future__ import annotations

import sys
import time

from trusted_ai_toolkit.eval.metrics.llm_judges import (
    metric_llm_claim_entailment,
    metric_llm_contradiction_judge,
)
from trusted_ai_toolkit.schemas import AdapterConfig, ToolkitConfig
from trusted_ai_toolkit.xai.explainability import compute_llm_narrative

# ── Configure your live adapter here ─────────────────────────────────────────

LIVE_CONFIG = ToolkitConfig(
    project_name="smoke_test",
    risk_tier="medium",
    output_dir="/tmp",
    adapters=AdapterConfig(
        provider="ollama",                          # or "openai_compatible" / "azure_openai"
        endpoint="http://localhost:11434",
        model="qwen2.5:3b",                         # any instruction-tuned model
        timeout_seconds=120,
    ),
)

# ── Fixture: an answer that should trip ONE LLM-detected contradiction ───────

FIXTURE_OUTPUT = (
    "The policy is free of charge. "
    "The release date is March 15. "
    "All stakeholders must approve before release."
)

FIXTURE_CONTEXTS = [
    {
        "title": "Policy",
        "snippet": (
            "The policy costs USD 50 per seat. "
            "Release scheduled for March 15. "
            "Stakeholder sign-off required before release."
        ),
    }
]


def _fmt_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def _check_provider() -> bool:
    if LIVE_CONFIG.adapters.provider == "stub":
        print("ERROR: LIVE_CONFIG.adapters.provider is 'stub'. Edit this script "
              "to point at a real provider before running the smoke test.")
        return False
    return True


def main() -> int:
    if not _check_provider():
        return 1

    print("=" * 72)
    print(f"LLM rationalization smoke test")
    print(f"  provider: {LIVE_CONFIG.adapters.provider}")
    print(f"  endpoint: {LIVE_CONFIG.adapters.endpoint}")
    print(f"  model:    {LIVE_CONFIG.adapters.model}")
    print("=" * 72)

    ctx = {
        "toolkit_config": LIVE_CONFIG,
        "model_output": FIXTURE_OUTPUT,
        "retrieved_contexts": FIXTURE_CONTEXTS,
    }

    # ── Test 1: contradiction judge ──────────────────────────────────────────
    print("\n[1/3] llm_contradiction_judge — grading 3 claims for contradictions")
    t0 = time.monotonic()
    result = metric_llm_contradiction_judge(ctx)
    elapsed = time.monotonic() - t0

    if result.value is None:
        print(f"  FAILED to invoke LLM after {_fmt_seconds(elapsed)}")
        print(f"  reason: {result.details.get('reason', 'unknown')}")
        print(f"  Make sure the provider is reachable.")
        return 1

    print(f"  value          = {result.value}  ({result.details['yes_count']}/"
          f"{result.details['claim_count']} contradictions)")
    print(f"  data_basis     = {result.details['data_basis']}")
    print(f"  strength       = {result.details['strength']}")
    print(f"  elapsed        = {_fmt_seconds(elapsed)}")
    print(f"  per-claim verdicts:")
    for j in result.details["judgments"]:
        verdict = j["verdict"]
        marker = "X" if verdict == "yes" else ("." if verdict == "no" else "?")
        print(f"    [{marker}] {verdict:>7}  {j['claim'][:62]}")

    if result.details["yes_count"] == 0:
        print("  WARN: the model found no contradictions; the deterministic "
              "polarity heuristic also misses the 'free vs $50' case so this "
              "tells you the LLM judge is not giving extra value here. Try a "
              "larger model.")

    # ── Test 2: entailment judge ─────────────────────────────────────────────
    print("\n[2/3] llm_claim_entailment — grading 3 claims for entailment")
    t0 = time.monotonic()
    result = metric_llm_claim_entailment(ctx)
    elapsed = time.monotonic() - t0
    if result.value is None:
        print(f"  FAILED: {result.details.get('reason', 'unknown')}")
        return 1
    print(f"  value          = {result.value}  ({result.details['yes_count']}/"
          f"{result.details['claim_count']} entailed)")
    print(f"  elapsed        = {_fmt_seconds(elapsed)}")

    # ── Test 3: narrative ────────────────────────────────────────────────────
    print("\n[3/3] compute_llm_narrative — 2-paragraph rationale")
    t0 = time.monotonic()
    narrative = compute_llm_narrative(
        config=LIVE_CONFIG,
        verdict="trusted",
        reasons=[
            "The answer is well supported by the retrieved evidence "
            "and no contradictions were detected."
        ],
        metric_summary={
            "claim_support_rate": 0.91,
            "contradiction_rate": 0.0,
            "evidence_sufficiency_score": 0.78,
            "bias_signal_count": 0,
            "answer_trust_score": 0.83,
        },
        model_output=FIXTURE_OUTPUT,
        contexts=FIXTURE_CONTEXTS,
    )
    elapsed = time.monotonic() - t0

    if not narrative["available"]:
        print(f"  FAILED to generate narrative after {_fmt_seconds(elapsed)}")
        return 1

    print(f"  available      = {narrative['available']}")
    print(f"  model          = {narrative['model']}")
    print(f"  cache_hit      = {narrative['cache_hit']}")
    print(f"  elapsed        = {_fmt_seconds(elapsed)}")
    print(f"  narrative:")
    print("  " + "─" * 68)
    for line in narrative["narrative"].split("\n"):
        print(f"  {line}")
    print("  " + "─" * 68)

    # ── Test 4: cache verification ───────────────────────────────────────────
    print("\n[bonus] Cache short-circuit check — same call again, expecting cache hit")
    t0 = time.monotonic()
    narrative2 = compute_llm_narrative(
        config=LIVE_CONFIG,
        verdict="trusted",
        reasons=[
            "The answer is well supported by the retrieved evidence "
            "and no contradictions were detected."
        ],
        metric_summary={
            "claim_support_rate": 0.91,
            "contradiction_rate": 0.0,
            "evidence_sufficiency_score": 0.78,
            "bias_signal_count": 0,
            "answer_trust_score": 0.83,
        },
        model_output=FIXTURE_OUTPUT,
        contexts=FIXTURE_CONTEXTS,
    )
    elapsed = time.monotonic() - t0
    print(f"  cache_hit      = {narrative2['cache_hit']}")
    print(f"  elapsed        = {_fmt_seconds(elapsed)}  (should be near-zero)")
    print(f"  identical      = {narrative2['narrative'] == narrative['narrative']}")

    print("\n" + "=" * 72)
    print("smoke test complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
