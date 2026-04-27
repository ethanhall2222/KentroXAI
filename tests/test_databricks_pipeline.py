from __future__ import annotations

import json
from pathlib import Path

from trusted_ai_toolkit.databricks_pipeline import (
    build_governance_run_row,
    build_prompt_bundle,
    run_databricks_answer_pipeline,
)


def test_build_prompt_bundle_normalizes_databricks_chunk_fields() -> None:
    bundle = build_prompt_bundle(
        "What controls apply?",
        "Documented evaluation and approval are required.",
        [
            {
                "chunk_id": "chunk-001",
                "doc_uri": "dbfs:/Volumes/main/policy.pdf",
                "chunk_text": "Documented evaluation is required before release.",
                "retrieval_score": 0.91,
                "label": 1,
                "prediction": 1,
                "is_privileged": True,
                "owner": "policy-team",
            }
        ],
        system_context={"model_provider": "openai"},
    )

    assert bundle["prompt"] == "What controls apply?"
    assert bundle["model_output"] == "Documented evaluation and approval are required."
    assert bundle["retrieved_contexts"][0]["id"] == "chunk-001"
    assert bundle["retrieved_contexts"][0]["text"] == "Documented evaluation is required before release."
    assert bundle["retrieved_contexts"][0]["uri"] == "dbfs:/Volumes/main/policy.pdf"
    assert bundle["retrieved_contexts"][0]["owner"] == "policy-team"
    assert bundle["system_context"]["model_provider"] == "openai"
    assert bundle["labeled_evaluation"]["labels"] == [1]
    assert bundle["runtime_metadata"]["owners"] == ["policy-team"]


def test_run_databricks_answer_pipeline_reuses_prompt_workflow(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    run_dir = tmp_path / "artifacts" / "run-001"
    run_dir.mkdir(parents=True)
    (run_dir / "scorecard.json").write_text(json.dumps({"answer_verdict": "trusted"}), encoding="utf-8")
    (run_dir / "prompt_run.json").write_text(json.dumps({"prompt": "What controls apply?"}), encoding="utf-8")
    (run_dir / "eval_results.json").write_text(json.dumps({"results": []}), encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run_prompt_workflow(
        cfg,
        config_path_value,
        prompt,
        model_output=None,
        context_file=None,
        invocation_mode="stub",
        model_details=None,
    ):
        captured["config_path"] = config_path_value
        captured["prompt"] = prompt
        captured["model_output"] = model_output
        captured["context_file"] = context_file
        captured["invocation_mode"] = invocation_mode
        captured["model_details"] = model_details
        context_payload = json.loads(Path(context_file).read_text(encoding="utf-8"))
        captured["retrieved_contexts"] = context_payload["retrieved_contexts"]
        return run_dir

    monkeypatch.setattr(
        "trusted_ai_toolkit.databricks_pipeline._run_prompt_workflow",
        _fake_run_prompt_workflow,
    )
    monkeypatch.setattr(
        "trusted_ai_toolkit.databricks_pipeline.generate_scorecard",
        lambda cfg, store: (run_dir / "scorecard.json").write_text(
            json.dumps({"answer_verdict": "trusted", "answer_trust_score": 0.81, "scorecard_template_version": "scorecard-details-v2"}),
            encoding="utf-8",
        ),
    )

    result = run_databricks_answer_pipeline(
        config_path=config_path,
        question="What controls apply?",
        answer="Documented evaluation and approval are required.",
        retrieved_chunks=[
            {
                "chunk_id": "chunk-001",
                "doc_uri": "dbfs:/Volumes/main/policy.pdf",
                "chunk_text": "Documented evaluation is required before release.",
            }
        ],
        system_context={"model_provider": "openai"},
        model_details={"provider": "openai_compatible", "model": "gpt-4.1-mini"},
    )

    assert captured["config_path"] == str(config_path)
    assert captured["prompt"] == "What controls apply?"
    assert captured["model_output"] == "Documented evaluation and approval are required."
    assert captured["invocation_mode"] == "databricks_rag"
    assert captured["retrieved_contexts"][0]["id"] == "chunk-001"
    assert result["scorecard"]["answer_verdict"] == "trusted"
    assert result["scorecard"]["answer_trust_score"] == 0.81
    assert result["scorecard"]["scorecard_template_version"] == "scorecard-details-v2"


def test_build_governance_run_row_preserves_answer_and_chunks() -> None:
    row = build_governance_run_row(
        run_id="run-001",
        question="What controls apply?",
        answer="Documented evaluation and approval are required.",
        retrieved_chunks=[
            {
                "chunk_id": "chunk-001",
                "doc_uri": "dbfs:/Volumes/main/policy.pdf",
                "chunk_text": "Documented evaluation is required before release.",
            }
        ],
        artifact_dir="/tmp/run-001",
        scorecard_json_path="/tmp/run-001/scorecard.json",
        scorecard_payload={
            "overall_status": "pass",
            "go_no_go": "go",
            "answer_verdict": "trusted",
            "answer_trust_score": 0.81,
            "governance_score": 1.0,
            "trust_score": 0.92,
            "evidence_completeness": 100.0,
        },
    )

    assert row["run_id"] == "run-001"
    assert row["answer_text"] == "Documented evaluation and approval are required."
    assert row["top_doc_uris"] == ["dbfs:/Volumes/main/policy.pdf"]
    assert json.loads(row["retrieved_chunks_json"])[0]["chunk_text"] == "Documented evaluation is required before release."
