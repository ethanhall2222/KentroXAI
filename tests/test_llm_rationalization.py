"""Tests for the LLM rationalization features (Tim2 — Options A and B).

Covers:
  - Stub-safe degradation: every code path that touches a live LLM must
    return a useful no-op when ``adapters.provider == "stub"``.
  - Deterministic-mode injection: invoke_model_safely must request
    temperature=0 and seed=42 via the extra_payload merge.
  - LLM judge metrics (Option B): correct value computation, advisory
    strength label, no impact on _answer_verdict gates.
  - LLM narrative (Option A): returns the model text on success, returns
    the unavailable shape on stub/failure, caches by prompt hash.
"""

from __future__ import annotations

from typing import Any

import pytest

from trusted_ai_toolkit.eval.metrics.llm_judges import (
    _LLM_JUDGE_CACHE,
    _parse_yes_no,
    metric_llm_claim_entailment,
    metric_llm_contradiction_judge,
)
from trusted_ai_toolkit.model_client import (
    ModelInvocationResult,
    _build_request_payload,
    _deterministic_extra_payload,
    invoke_model_safely,
)
from trusted_ai_toolkit.reporting import _answer_verdict, _metric_strength_map
from trusted_ai_toolkit.schemas import (
    AdapterConfig,
    MetricResult,
    ToolkitConfig,
)
from trusted_ai_toolkit.xai.explainability import (
    _LLM_NARRATIVE_CACHE,
    compute_llm_narrative,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _stub_config() -> ToolkitConfig:
    return ToolkitConfig(project_name="t", risk_tier="medium", output_dir="/tmp")


def _live_config(model_name: str = "test-model") -> ToolkitConfig:
    return ToolkitConfig(
        project_name="t",
        risk_tier="medium",
        output_dir="/tmp",
        adapters=AdapterConfig(
            provider="ollama",
            endpoint="http://localhost:11434",
            model=model_name,
        ),
    )


def _make_result(text: str, model: str = "test-model") -> ModelInvocationResult:
    return ModelInvocationResult(
        provider="ollama",
        model=model,
        route="ollama_generate",
        output_text=text,
        request_payload={},
        response_payload={},
        request_url="http://localhost:11434/api/generate",
    )


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    _LLM_JUDGE_CACHE.clear()
    _LLM_NARRATIVE_CACHE.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Deterministic-mode injection
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterministicMode:

    def test_deterministic_payload_for_openai(self) -> None:
        extra = _deterministic_extra_payload("openai_compatible")
        assert extra == {"temperature": 0, "seed": 42, "max_tokens": 256}

    def test_deterministic_payload_for_ollama(self) -> None:
        extra = _deterministic_extra_payload("ollama")
        assert extra == {"options": {"temperature": 0, "seed": 42, "num_predict": 256}}

    def test_extra_payload_merged_into_chat_completions(self) -> None:
        payload = _build_request_payload(
            prompt="hi",
            model_name="m",
            route="chat_completions",
            extra_payload={"temperature": 0, "seed": 42},
        )
        assert payload["model"] == "m"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["temperature"] == 0
        assert payload["seed"] == 42

    def test_extra_payload_cannot_clobber_structural_keys(self) -> None:
        payload = _build_request_payload(
            prompt="hi",
            model_name="m",
            route="chat_completions",
            extra_payload={"model": "evil", "messages": "evil", "temperature": 0},
        )
        assert payload["model"] == "m"  # not clobbered
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["temperature"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — invoke_model_safely
# ─────────────────────────────────────────────────────────────────────────────

class TestInvokeModelSafely:

    def test_stub_provider_returns_none(self) -> None:
        assert invoke_model_safely("anything", _stub_config()) is None

    def test_invocation_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit import model_client

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise model_client.ModelInvocationError("simulated")

        monkeypatch.setattr(model_client, "invoke_model", _boom)
        assert invoke_model_safely("anything", _live_config()) is None

    def test_unexpected_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit import model_client

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("network died")

        monkeypatch.setattr(model_client, "invoke_model", _boom)
        assert invoke_model_safely("anything", _live_config()) is None

    def test_success_passes_extra_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit import model_client

        captured: dict[str, Any] = {}

        def _spy(prompt: str, config: ToolkitConfig, extra_payload: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
            captured["extra"] = extra_payload
            return _make_result("ok")

        monkeypatch.setattr(model_client, "invoke_model", _spy)
        result = invoke_model_safely("hello", _live_config())
        assert result is not None
        # ollama deterministic payload uses nested options
        assert captured["extra"] == {"options": {"temperature": 0, "seed": 42, "num_predict": 256}}


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — LLM judge metrics (Option B)
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMJudgeMetrics:
    """The judges read claims from _claim_analysis and grade each one."""

    def _context_with_claims(self, config: ToolkitConfig) -> dict:
        return {
            "toolkit_config": config,
            "model_output": (
                "The policy requires approval. The release date is March. "
                "All stakeholders must sign off."
            ),
            "retrieved_contexts": [
                {
                    "title": "Policy",
                    "snippet": "The policy requires approval before release. "
                               "All stakeholders must sign off in March.",
                }
            ],
        }

    def test_yes_no_parser(self) -> None:
        assert _parse_yes_no("YES") == "yes"
        assert _parse_yes_no("y") == "yes"
        assert _parse_yes_no("Yes, definitely.") == "yes"
        assert _parse_yes_no("NO") == "no"
        assert _parse_yes_no("nope") == "no"
        assert _parse_yes_no("") == "unknown"
        assert _parse_yes_no("???") == "unknown"
        assert _parse_yes_no("maybe") == "unknown"

    def test_judge_unavailable_when_provider_is_stub(self) -> None:
        ctx = self._context_with_claims(_stub_config())
        m = metric_llm_contradiction_judge(ctx)
        assert m.value is None
        assert m.details["data_basis"] == "llm_unavailable"
        assert m.details["strength"] == "advisory"

    def test_judge_unavailable_without_toolkit_config(self) -> None:
        ctx = {"model_output": "hi", "retrieved_contexts": []}
        m = metric_llm_contradiction_judge(ctx)
        assert m.value is None
        assert m.details["data_basis"] == "llm_unavailable"

    def test_contradiction_judge_grades_each_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from trusted_ai_toolkit.eval.metrics import llm_judges

        # Return YES for the first claim (contradiction), NO for the rest.
        call_count = {"n": 0}

        def _fake(prompt: str, config: ToolkitConfig, deterministic: bool = True):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            return _make_result("YES" if call_count["n"] == 1 else "NO")

        monkeypatch.setattr(llm_judges, "invoke_model_safely", _fake)
        ctx = self._context_with_claims(_live_config())
        m = metric_llm_contradiction_judge(ctx)
        assert m.value == round(1 / 3, 3)  # exactly one YES out of three claims
        assert m.details["yes_count"] == 1
        assert m.details["claim_count"] == 3
        assert m.details["strength"] == "advisory"
        assert m.details["data_basis"] == "llm_judged"
        assert call_count["n"] == 3

    def test_entailment_judge_grades_each_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from trusted_ai_toolkit.eval.metrics import llm_judges
        monkeypatch.setattr(
            llm_judges, "invoke_model_safely",
            lambda *a, **k: _make_result("YES"),
        )
        ctx = self._context_with_claims(_live_config())
        m = metric_llm_claim_entailment(ctx)
        assert m.value == 1.0  # all three graded YES
        assert m.details["yes_count"] == 3

    def test_judge_caches_repeat_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit.eval.metrics import llm_judges
        call_count = {"n": 0}

        def _fake(*args: Any, **kwargs: Any):
            call_count["n"] += 1
            return _make_result("NO")

        monkeypatch.setattr(llm_judges, "invoke_model_safely", _fake)
        ctx = self._context_with_claims(_live_config())
        metric_llm_contradiction_judge(ctx)
        first = call_count["n"]
        metric_llm_contradiction_judge(ctx)  # identical inputs
        assert call_count["n"] == first  # second call hit the cache for every claim

    def test_judge_unavailable_when_all_claims_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from trusted_ai_toolkit.eval.metrics import llm_judges
        monkeypatch.setattr(
            llm_judges, "invoke_model_safely",
            lambda *a, **k: None,  # every call fails
        )
        ctx = self._context_with_claims(_live_config())
        m = metric_llm_contradiction_judge(ctx)
        assert m.value is None
        assert m.details["data_basis"] == "llm_unavailable"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Strength map and verdict isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestAdvisoryIsolation:
    """LLM judges must be tagged 'advisory' and never feed verdict gates."""

    def _m(self, metric_id: str, value: float) -> MetricResult:
        return MetricResult(metric_id=metric_id, value=value, threshold=None, passed=None, details={})

    def test_llm_judges_are_labeled_advisory(self) -> None:
        results = [
            self._m("llm_contradiction_judge", 0.5),
            self._m("llm_claim_entailment", 0.5),
            self._m("claim_support_rate", 0.9),
        ]
        labels = _metric_strength_map(results)
        assert labels["llm_contradiction_judge"] == "advisory"
        assert labels["llm_claim_entailment"] == "advisory"
        assert labels["claim_support_rate"] == "strong"

    def test_high_llm_contradiction_does_not_trigger_verdict_gate(self) -> None:
        # 0.50 from the LLM judge is 25× the high-tier deterministic gate (0.02)
        # but only the deterministic contradiction_rate metric drives the gate.
        results = [
            self._m("llm_contradiction_judge", 0.50),
            self._m("claim_support_rate", 0.95),
        ]
        verdict, _ = _answer_verdict(results, risk_tier="high")
        assert verdict == "trusted"  # deterministic signals are clean


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — LLM narrative (Option A)
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMNarrative:

    def test_unavailable_when_config_is_none(self) -> None:
        result = compute_llm_narrative(
            config=None,
            verdict="trusted",
            reasons=[],
            metric_summary={},
            model_output="hi",
        )
        assert result["available"] is False
        assert result["narrative"] is None

    def test_unavailable_when_provider_is_stub(self) -> None:
        result = compute_llm_narrative(
            config=_stub_config(),
            verdict="trusted",
            reasons=[],
            metric_summary={},
            model_output="hi",
        )
        assert result["available"] is False

    def test_returns_narrative_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from trusted_ai_toolkit.xai import explainability
        monkeypatch.setattr(
            explainability, "invoke_model_safely",
            lambda *a, **k: _make_result(
                "The answer is well grounded. The metrics agree.", model="test-model"
            ),
        )
        result = compute_llm_narrative(
            config=_live_config(),
            verdict="trusted",
            reasons=["The answer is well supported by the retrieved evidence."],
            metric_summary={
                "claim_support_rate": 0.92,
                "contradiction_rate": 0.0,
                "evidence_sufficiency_score": 0.85,
            },
            model_output="The policy requires approval.",
            contexts=[{"title": "P", "snippet": "Approval is required."}],
        )
        assert result["available"] is True
        assert "well grounded" in result["narrative"]
        assert result["model"] == "test-model"
        assert result["cache_hit"] is False

    def test_cache_hit_on_repeat_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit.xai import explainability
        call_count = {"n": 0}

        def _spy(*args: Any, **kwargs: Any):
            call_count["n"] += 1
            return _make_result("cached narrative")

        monkeypatch.setattr(explainability, "invoke_model_safely", _spy)
        config = _live_config()
        kwargs = dict(
            config=config,
            verdict="trusted",
            reasons=[],
            metric_summary={"claim_support_rate": 0.9},
            model_output="hi",
        )
        first = compute_llm_narrative(**kwargs)
        second = compute_llm_narrative(**kwargs)
        assert first["narrative"] == second["narrative"] == "cached narrative"
        assert call_count["n"] == 1
        assert second["cache_hit"] is True

    def test_failure_returns_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trusted_ai_toolkit.xai import explainability
        monkeypatch.setattr(
            explainability, "invoke_model_safely",
            lambda *a, **k: None,
        )
        result = compute_llm_narrative(
            config=_live_config(),
            verdict="trusted",
            reasons=[],
            metric_summary={},
            model_output="hi",
        )
        assert result["available"] is False
        assert result["narrative"] is None
