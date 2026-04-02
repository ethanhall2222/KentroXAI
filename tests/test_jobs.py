from __future__ import annotations

from pathlib import Path

from trusted_ai_toolkit.jobs import run_prompt_job


def test_run_prompt_job_uses_keyword_arguments(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

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
        return tmp_path / "artifacts" / "run-001"

    monkeypatch.setattr("trusted_ai_toolkit.jobs._run_prompt_workflow", _fake_run_prompt_workflow)

    result = run_prompt_job(
        config=str(config_path),
        prompt="Summarize controls",
        model_output="Stub answer",
        context_file=str(tmp_path / "context.json"),
        mode="prompt",
    )

    assert captured["config_path"] == str(config_path)
    assert captured["prompt"] == "Summarize controls"
    assert captured["model_output"] == "Stub answer"
    assert captured["context_file"] == str(tmp_path / "context.json")
    assert captured["invocation_mode"] == "stub"
    assert result["mode"] == "prompt"
    assert result["scorecard_json"].endswith("scorecard.json")


def test_run_prompt_job_uses_environment_fallbacks(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: demo\n", encoding="utf-8")

    monkeypatch.setenv("TAT_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("TAT_PROMPT", "Summarize from env")
    monkeypatch.setenv("TAT_CONTEXT_FILE", str(tmp_path / "env-context.json"))

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
        captured["context_file"] = context_file
        return tmp_path / "artifacts" / "run-002"

    monkeypatch.setattr("trusted_ai_toolkit.jobs._run_prompt_workflow", _fake_run_prompt_workflow)

    result = run_prompt_job()

    assert captured["config_path"] == str(config_path)
    assert captured["prompt"] == "Summarize from env"
    assert captured["context_file"] == str(tmp_path / "env-context.json")
    assert result["run_dir"].endswith("run-002")


def test_run_prompt_job_simulate_mode_invokes_model(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: openai_compatible
  endpoint: https://api.openai.com/v1
  model: gpt-4.1-mini
""",
        encoding="utf-8",
    )

    class _Invocation:
        provider = "openai_compatible"
        model = "gpt-4.1-mini"
        route = "responses"
        output_text = "Synthetic reply"
        request_url = "https://api.openai.com/v1/responses"
        request_payload = {"model": "gpt-4.1-mini", "input": "Summarize controls"}
        response_payload = {"output_text": "Synthetic reply"}

    captured: dict[str, object] = {}

    monkeypatch.setattr("trusted_ai_toolkit.jobs.invoke_model", lambda prompt, cfg: _Invocation())

    def _fake_run_prompt_workflow(
        cfg,
        config_path_value,
        prompt,
        model_output=None,
        context_file=None,
        invocation_mode="stub",
        model_details=None,
    ):
        captured["prompt"] = prompt
        captured["model_output"] = model_output
        captured["invocation_mode"] = invocation_mode
        captured["model_details"] = model_details
        return tmp_path / "artifacts" / "run-003"

    monkeypatch.setattr("trusted_ai_toolkit.jobs._run_prompt_workflow", _fake_run_prompt_workflow)

    result = run_prompt_job(
        config=str(config_path),
        prompt="Summarize controls",
        mode="simulate",
    )

    assert captured["prompt"] == "Summarize controls"
    assert captured["model_output"] == "Synthetic reply"
    assert captured["invocation_mode"] == "live_simulation"
    assert captured["model_details"]["route"] == "responses"
    assert result["mode"] == "simulate"
