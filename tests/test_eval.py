from __future__ import annotations

from pathlib import Path

import yaml

from trusted_ai_toolkit.eval.runner import run_eval
from trusted_ai_toolkit.model_client import EmbeddingInvocationResult
from trusted_ai_toolkit.schemas import ToolkitConfig


def test_eval_runner_returns_case_based_results(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": [
                    "accuracy_stub",
                    "reliability",
                    "groundedness_stub",
                    "refusal_correctness",
                    "unanswerable_handling",
                ],
                "cases": [
                    {"case_id": "1", "kind": "safe"},
                    {"case_id": "2", "kind": "unsafe"},
                    {"case_id": "3", "kind": "unanswerable"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = ToolkitConfig(
        project_name="demo",
        risk_tier="medium",
        output_dir=str(tmp_path / "artifacts"),
        eval={
            "suites": ["medium"],
            "thresholds": {
                "context_relevance_tfidf": 0.19,
                "output_support_tfidf": 0.1,
                "context_relevance_embedding": 0.5,
                "output_support_embedding": 0.5,
            },
        },
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    assert len(results) == 1
    assert results[0].suite_name == "medium"
    assert len(results[0].metric_results) == 5
    assert any("Golden cases executed" in note for note in results[0].notes)


def test_eval_runner_computes_contextual_metrics_when_prompt_bundle_exists(tmp_path: Path, monkeypatch) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": [
                    "context_relevance_tfidf",
                    "output_support_tfidf",
                    "context_relevance_embedding",
                    "output_support_embedding",
                ],
                "cases": [{"case_id": "1", "kind": "safe"}],
                "thresholds": {
                    "context_relevance_tfidf": 0.19,
                    "output_support_tfidf": 0.1,
                    "context_relevance_embedding": 0.5,
                    "output_support_embedding": 0.5,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    artifacts_dir = tmp_path / "artifacts" / "run1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "prompt_run.json").write_text(
        """
{"prompt":"summarize controls","model_output":"controls require evidence","retrieved_contexts":[{"title":"Policy","snippet":"controls require evidence and review"}]}
""".strip(),
        encoding="utf-8",
    )

    def _fake_embed_texts(texts, config, model_name=None):
        return EmbeddingInvocationResult(
            provider="ollama",
            model="nomic-embed-text",
            route="embeddings",
            embeddings=[[1.0, 0.0], [0.9, 0.1], [0.95, 0.05]],
            request_payload={"input": texts},
            response_payload={"embeddings": [[1.0, 0.0], [0.9, 0.1], [0.95, 0.05]]},
            request_url="http://localhost:11434/api/embed",
        )

    monkeypatch.setattr("trusted_ai_toolkit.eval.runner.embed_texts", _fake_embed_texts)

    cfg = ToolkitConfig(
        project_name="demo",
        risk_tier="medium",
        output_dir=str(tmp_path / "artifacts"),
        eval={
            "suites": ["medium"],
            "thresholds": {
                "context_relevance_tfidf": 0.19,
                "output_support_tfidf": 0.1,
                "context_relevance_embedding": 0.5,
                "output_support_embedding": 0.5,
            },
        },
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    metrics = {item.metric_id: item for item in results[0].metric_results}

    assert metrics["context_relevance_tfidf"].passed is True
    assert metrics["output_support_tfidf"].passed is True
    assert metrics["context_relevance_embedding"].details["embedding_available"] is True
    assert metrics["output_support_embedding"].passed is True


def test_eval_runner_uses_observed_accuracy_labels_when_present(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": ["accuracy_stub"],
                "cases": [{"case_id": "1", "kind": "safe"}],
                "thresholds": {"accuracy_stub": 0.7},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    artifacts_dir = tmp_path / "artifacts" / "run1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "prompt_run.json").write_text(
        """
{"prompt":"summarize controls","model_output":"controls require evidence","retrieved_contexts":[],"labeled_evaluation":{"dataset_name":"labeled_demo","labels":[1,1,0,1],"predictions":[1,0,0,1]}}
""".strip(),
        encoding="utf-8",
    )

    cfg = ToolkitConfig(project_name="demo", risk_tier="medium", output_dir=str(tmp_path / "artifacts"), eval={"suites": ["medium"]})
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    metric = results[0].metric_results[0]

    assert metric.metric_id == "accuracy_stub"
    assert metric.value == 0.75
    assert metric.details["data_basis"] == "observed_labels"
    assert metric.details["sample_size"] == 4
    assert metric.details["bootstrap_ci_95"] is not None


def test_eval_runner_marks_accuracy_unavailable_without_labels(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": ["accuracy_stub"],
                "cases": [{"case_id": "1", "kind": "safe"}],
                "thresholds": {"accuracy_stub": 0.7},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    artifacts_dir = tmp_path / "artifacts" / "run1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "prompt_run.json").write_text(
        '{"prompt":"summarize controls","model_output":"controls require evidence","retrieved_contexts":[]}',
        encoding="utf-8",
    )

    cfg = ToolkitConfig(project_name="demo", risk_tier="medium", output_dir=str(tmp_path / "artifacts"), eval={"suites": ["medium"]})
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    metric = results[0].metric_results[0]

    assert metric.metric_id == "accuracy_stub"
    assert metric.threshold is None
    assert metric.passed is None
    assert metric.details["data_basis"] == "not_available_from_runtime_metadata"


def test_eval_runner_computes_claim_truth_metrics(tmp_path: Path) -> None:
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": [
                    "claim_support_rate",
                    "unsupported_claim_rate",
                    "contradiction_rate",
                    "evidence_sufficiency_score",
                    "bias_signal_score",
                ],
                "cases": [{"case_id": "1", "kind": "safe"}],
                "thresholds": {
                    "claim_support_rate": 0.5,
                    "unsupported_claim_rate": 0.4,
                    "contradiction_rate": 0.1,
                    "evidence_sufficiency_score": 0.4,
                    "bias_signal_score": 0.8,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    artifacts_dir = tmp_path / "artifacts" / "run1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "prompt_run.json").write_text(
        """
{"prompt":"summarize controls","model_output":"Controls require evidence review. Controls require approval.","retrieved_contexts":[{"title":"Policy","snippet":"Controls require evidence review and approval before release."}]}
""".strip(),
        encoding="utf-8",
    )

    cfg = ToolkitConfig(project_name="demo", risk_tier="medium", output_dir=str(tmp_path / "artifacts"), eval={"suites": ["medium"]})
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    metrics = {item.metric_id: item for item in results[0].metric_results}

    assert metrics["claim_support_rate"].value >= 0.5
    assert metrics["unsupported_claim_rate"].value <= 0.5
    assert metrics["contradiction_rate"].value == 0.0
    assert metrics["evidence_sufficiency_score"].value >= 0.4
    assert metrics["bias_signal_score"].value == 1.0


def test_eval_runner_wires_llm_judges_with_toolkit_config(tmp_path: Path) -> None:
    """Regression: the runner must include `toolkit_config` in the per-metric
    context AND iterate the LLM advisory judges listed in the suite YAML.

    Without either, the judges silently return `data_basis="llm_unavailable"`
    with reason "toolkit_config not present in metric context" (or never run
    at all), even when a provider is configured.  This test exercises both
    invariants against a stub provider — we don't need a live LLM to verify
    that the runner reached the judge with a config in hand.
    """
    suites_dir = tmp_path / "suites"
    suites_dir.mkdir()
    (suites_dir / "medium.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "medium",
                "metrics": [
                    "claim_support_rate",
                    "llm_contradiction_judge",
                    "llm_claim_entailment",
                ],
                "cases": [{"case_id": "1", "kind": "safe"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    artifacts_dir = tmp_path / "artifacts" / "run1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "prompt_run.json").write_text(
        """
{"prompt":"summarize controls","model_output":"Controls require evidence review.","retrieved_contexts":[{"title":"Policy","snippet":"Controls require evidence review and approval before release."}]}
""".strip(),
        encoding="utf-8",
    )

    cfg = ToolkitConfig(
        project_name="demo",
        risk_tier="medium",
        output_dir=str(tmp_path / "artifacts"),
        eval={"suites": ["medium"]},
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    results = run_eval(cfg, run_id="run1", config_path=config_path)
    metrics = {item.metric_id: item for item in results[0].metric_results}

    # Both judges must have been invoked (catches the "judges missing from
    # suite YAML" half of the regression).
    assert "llm_contradiction_judge" in metrics
    assert "llm_claim_entailment" in metrics

    # Stub provider gracefully reports unavailable — but the reason MUST be
    # the provider, not a missing toolkit_config (catches the "runner forgot
    # to inject toolkit_config" half of the regression).
    for judge_id in ("llm_contradiction_judge", "llm_claim_entailment"):
        details = metrics[judge_id].details
        assert details["data_basis"] == "llm_unavailable"
        assert details["strength"] == "advisory"
        reason = details.get("reason", "")
        assert "stub" in reason.lower(), (
            f"{judge_id} reason {reason!r} suggests toolkit_config was not wired "
            "into the runner context — see runner.py and llm_judges.py:_judge_each_claim."
        )
        assert "toolkit_config not present" not in reason
