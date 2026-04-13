"""Typer CLI entrypoint for Trusted AI Toolkit flows."""

from __future__ import annotations

import json
from pathlib import Path
import random
import tempfile
from typing import Optional
from uuid import uuid4
import webbrowser

import typer
import yaml
from rich.console import Console

from tat.runtime import RunContext
from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.documentation import build_documentation_artifacts
from trusted_ai_toolkit.eval.runner import compute_embedding_features, run_eval
from trusted_ai_toolkit.incident import generate_incident_record, should_open_incident
from trusted_ai_toolkit.model_client import ModelInvocationError, embed_texts, invoke_model, resolve_embedding_model_name
from trusted_ai_toolkit.monitoring import TelemetryLogger, load_telemetry_events, summarize_telemetry
from trusted_ai_toolkit.redteam.runner import run_redteam
from trusted_ai_toolkit.reporting import generate_scorecard
from trusted_ai_toolkit.schemas import MonitoringSummary, ToolkitConfig
from trusted_ai_toolkit.xai.lineage import generate_lineage_artifacts
from trusted_ai_toolkit.xai.reasoning_report import generate_reasoning_report

app = typer.Typer(help="Trusted AI Toolkit CLI")
eval_app = typer.Typer(help="Evaluation commands")
xai_app = typer.Typer(help="Explainability commands")
redteam_app = typer.Typer(help="Red-team commands")
run_app = typer.Typer(help="End-to-end orchestration commands")
docs_app = typer.Typer(help="Documentation and artifact commands")
monitor_app = typer.Typer(help="Monitoring commands")
incident_app = typer.Typer(help="Incident commands")
app.add_typer(eval_app, name="eval")
app.add_typer(xai_app, name="xai")
app.add_typer(redteam_app, name="redteam")
app.add_typer(run_app, name="run")
app.add_typer(docs_app, name="docs")
app.add_typer(monitor_app, name="monitor")
app.add_typer(incident_app, name="incident")

console = Console()


def _resolve_run_id(config: ToolkitConfig) -> str:
    return config.monitoring.run_id or str(uuid4())


def _build_run_context(config: ToolkitConfig, run_id: str) -> RunContext:
    return RunContext.from_system(config.system, run_id=run_id)


def _build_store_and_telemetry(config: ToolkitConfig, run_context: RunContext) -> tuple[ArtifactStore, TelemetryLogger]:
    store = ArtifactStore(config.output_dir, run_context.run_id)
    telemetry_path = Path(config.output_dir) / run_context.run_id / config.monitoring.telemetry_path
    telemetry = TelemetryLogger(
        telemetry_path=telemetry_path,
        run_id=run_context.run_id,
        enabled=config.monitoring.enabled,
        run_context=run_context,
    )
    return store, telemetry


def _latest_run_dir(output_dir: str | Path) -> Path | None:
    root = Path(output_dir)
    candidates = [p for p in root.glob("*") if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _load_summary(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _artifact_system_context(run_context: RunContext) -> dict[str, str] | None:
    return run_context.system_context()


def _compose_model_prompt(prompt: str, retrieved_contexts: list[dict]) -> str:
    if not retrieved_contexts:
        return prompt

    sections = ["Use the retrieved context below when answering the user prompt.", ""]
    for idx, item in enumerate(retrieved_contexts, start=1):
        title = str(item.get("title") or item.get("source") or f"Context {idx}")
        body = (
            str(item.get("snippet") or item.get("text") or item.get("content") or "")
            .strip()
        )
        sections.append(f"[Source {idx}] {title}")
        if body:
            sections.append(body)
        sections.append("")
    sections.append(f"User prompt: {prompt}")
    return "\n".join(sections).strip()


def _model_artifact_payload(
    invocation_mode: str,
    provider: str,
    model_name: str,
    route: str,
    request_url: str,
    request_payload: dict | None = None,
    response_payload: dict | None = None,
) -> dict:
    payload = {
        "invocation_mode": invocation_mode,
        "provider": provider,
        "model": model_name,
        "route": route,
        "request_url": request_url,
    }
    if request_payload is not None:
        payload["request"] = request_payload
    if response_payload is not None:
        payload["response"] = response_payload
    return payload


def _write_redteam_summary(store: ArtifactStore, findings: list[dict]) -> Path:
    severity_summary = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    by_tag: dict[str, int] = {}
    for finding in findings:
        sev = finding.get("severity", "low")
        if sev in severity_summary:
            severity_summary[sev] += 1
        for tag in finding.get("tags", []):
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return store.write_json("redteam_summary.json", {"severity": severity_summary, "tags": by_tag})


def _write_embedding_trace(store: ArtifactStore, embedding_features: dict[str, object]) -> None:
    if not embedding_features.get("embedding_available"):
        store.write_json(
            "embedding_trace.json",
            {
                "enabled": False,
                "reason": embedding_features.get("reason") or embedding_features.get("error") or "embedding unavailable",
            },
        )
        return

    context_vectors = embedding_features.get("context_vectors", [])
    vector_count = 2 + len(context_vectors) if isinstance(context_vectors, list) else 0
    prompt_vector = embedding_features.get("prompt_vector")
    vector_dimensions = len(prompt_vector) if isinstance(prompt_vector, list) else 0

    store.write_json(
        "embedding_trace.json",
        {
            "enabled": True,
            "provider": embedding_features.get("provider"),
            "model": embedding_features.get("embedding_model"),
            "route": "embeddings",
            "request_url": embedding_features.get("request_url"),
            "vector_count": vector_count,
            "vector_dimensions": vector_dimensions,
            "request": embedding_features.get("request_payload"),
            "response_preview": {
                "keys": sorted(embedding_features.get("response_payload", {}).keys())
                if isinstance(embedding_features.get("response_payload"), dict)
                else [],
            },
        },
    )


def _apply_adapter_overrides(
    cfg: ToolkitConfig,
    provider: Optional[str] = None,
    endpoint: Optional[str] = None,
    model: Optional[str] = None,
    api_key_env: Optional[str] = None,
    request_format: Optional[str] = None,
) -> ToolkitConfig:
    updates: dict[str, str] = {}
    if provider:
        updates["provider"] = provider
    if endpoint:
        updates["endpoint"] = endpoint
    if model:
        updates["model"] = model
    if api_key_env:
        updates["api_key_env"] = api_key_env
    if request_format:
        updates["request_format"] = request_format
    if not updates:
        return cfg
    return cfg.model_copy(update={"adapters": cfg.adapters.model_copy(update=updates)})


def _load_context_payload(context_file: str | None) -> dict:
    """Load optional context payload from JSON file.

    Accepts either:
    - a JSON array of context objects, or
    - an object with `retrieved_contexts` array.
    """

    if not context_file:
        return {"retrieved_contexts": []}

    path = Path(context_file)
    if not path.exists():
        raise typer.BadParameter(f"context file not found: {path}")

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"context file is not valid JSON: {path}") from exc

    if isinstance(loaded, list):
        if not all(isinstance(item, dict) for item in loaded):
            raise typer.BadParameter("context file list items must be JSON objects")
        return {"retrieved_contexts": loaded}

    if isinstance(loaded, dict):
        contexts = loaded.get("retrieved_contexts", [])
        if not isinstance(contexts, list):
            raise typer.BadParameter("'retrieved_contexts' must be a JSON array when context file is an object")
        if not all(isinstance(item, dict) for item in contexts):
            raise typer.BadParameter("'retrieved_contexts' items must be JSON objects")
        return loaded

    raise typer.BadParameter("context file must be a JSON array or object with 'retrieved_contexts'")


def _load_retrieved_contexts(context_file: str | None) -> list[dict]:
    payload = _load_context_payload(context_file)
    contexts = payload.get("retrieved_contexts", [])
    return contexts if isinstance(contexts, list) else []


def _prompt_from_context_payload(context_payload: dict, default_prompt: str) -> str:
    prompt = context_payload.get("prompt")
    return str(prompt) if isinstance(prompt, str) and prompt.strip() else default_prompt


def _benchmark_tier_sequence(scenario_count: int) -> list[str]:
    tiers = ("low", "medium", "high")
    return [tiers[idx % len(tiers)] for idx in range(scenario_count)]


def _benchmark_scenario_family(tier_index: int) -> str:
    families = (
        "evidence_quality",
        "release_gate",
        "failure_modes",
        "monitoring_traceability",
        "human_approval",
    )
    return families[(tier_index - 1) % len(families)]


def _benchmark_prompt_variant(base_prompt: str, tier: str, scenario_index: int, tier_index: int) -> tuple[str, str]:
    family = _benchmark_scenario_family(tier_index)
    suffixes = {
        "evidence_quality": "Focus on evidence quality, grounding, and deployment risk.",
        "release_gate": "State the release gate decision and the minimum controls that must pass.",
        "failure_modes": "Highlight residual failure modes and the most material governance gap.",
        "monitoring_traceability": "Focus on telemetry, lineage, and audit traceability.",
        "human_approval": "Explain where human approval or escalation is required.",
    }
    suffix = suffixes[family]
    prompt = (
        f"{base_prompt} Scenario {scenario_index:03d} for the {tier} risk cohort. {suffix} "
        "Respond with at most 3 bullets and no more than 60 words total."
    )
    return prompt, family


def _bootstrap_sequence(values: list[int], rng: random.Random) -> list[int]:
    if not values:
        return []
    return [int(values[rng.randrange(len(values))]) for _ in range(len(values))]


def _bootstrap_paired_sequences(left: list[int], right: list[int], rng: random.Random) -> tuple[list[int], list[int]]:
    if not left or not right or len(left) != len(right):
        return left, right
    sample_indices = [rng.randrange(len(left)) for _ in range(len(left))]
    return ([int(left[idx]) for idx in sample_indices], [int(right[idx]) for idx in sample_indices])


def _benchmark_context_variant(context_payload: dict, tier: str, scenario_index: int, tier_index: int) -> tuple[dict, str]:
    rng = random.Random(f"{tier}-{scenario_index}-{tier_index}")
    variant_payload = json.loads(json.dumps(context_payload))

    retrieved_contexts = variant_payload.get("retrieved_contexts", [])
    if isinstance(retrieved_contexts, list):
        rng.shuffle(retrieved_contexts)
        if retrieved_contexts and (tier_index % 4 == 0):
            distractor = {
                "id": f"ctx-{tier}-distractor-{scenario_index:03d}",
                "title": f"{tier.title()} Risk Administrative Note",
                "snippet": "Administrative notes describe review logistics, but they are not primary policy evidence.",
                "content": (
                    "Administrative notes describe meeting cadence and reviewers but do not define deployment policy, "
                    "approval thresholds, or decision rights."
                ),
                "uri": f"file://benchmarks/{tier}_administrative_note_{scenario_index:03d}.md",
                "used_for": "retrieval distractor robustness",
            }
            retrieved_contexts.append(distractor)

    fairness_dataset = variant_payload.get("fairness_dataset")
    if isinstance(fairness_dataset, dict):
        for key in ("privileged_labels", "unprivileged_labels", "privileged_true", "privileged_pred", "unprivileged_true", "unprivileged_pred"):
            value = fairness_dataset.get(key)
            if isinstance(value, list):
                fairness_dataset[key] = _bootstrap_sequence([int(item) for item in value], rng)

    labeled_evaluation = variant_payload.get("labeled_evaluation")
    if isinstance(labeled_evaluation, dict):
        labels = labeled_evaluation.get("labels")
        predictions = labeled_evaluation.get("predictions")
        if isinstance(labels, list) and isinstance(predictions, list):
            sample_labels, sample_predictions = _bootstrap_paired_sequences(
                [int(item) for item in labels],
                [int(item) for item in predictions],
                rng,
            )
            labeled_evaluation["labels"] = sample_labels
            labeled_evaluation["predictions"] = sample_predictions

    family = _benchmark_scenario_family(tier_index)
    variant_payload["benchmark_scenario"] = {
        "family": family,
        "scenario_index": scenario_index,
        "tier_scenario_index": tier_index,
    }
    return variant_payload, family


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _write_temporary_context_payload(context_payload: dict) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(context_payload, handle)
        return handle.name


def _write_benchmark_summary(
    summary_path: Path,
    scenario_count: int,
    tier_counts: dict[str, int],
    aggregate_runs: dict[str, dict[str, object]],
    summary: list[dict[str, str | float | None]],
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "scenario_count": scenario_count,
                "completed_scenarios": len(summary),
                "tier_counts": tier_counts,
                "aggregates": aggregate_runs,
                "runs": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _monitoring_for_run(store: ArtifactStore) -> MonitoringSummary:
    telemetry_path = store.path_for("telemetry.jsonl")
    events = load_telemetry_events(telemetry_path)
    summary = summarize_telemetry(store.run_id, events)
    store.write_json("monitoring_summary.json", summary.model_dump(mode="json"))
    return summary


def _docs_for_run(config: ToolkitConfig, store: ArtifactStore) -> None:
    build_documentation_artifacts(config, store)


def _incident_for_run(config: ToolkitConfig, store: ArtifactStore, monitoring: MonitoringSummary) -> bool:
    scorecard_payload = _load_summary(store.path_for("scorecard.json"))
    if not scorecard_payload:
        return False
    from trusted_ai_toolkit.schemas import Scorecard

    scorecard = Scorecard.model_validate(scorecard_payload)
    should_open, trigger, severity = should_open_incident(scorecard, monitoring, config.redteam.severity_threshold)
    if not should_open:
        return False
    incident = generate_incident_record(store, scorecard, monitoring, trigger, severity)
    store.write_json("incident_report.json", incident.model_dump(mode="json"))
    store.save_rendered_md("incident_template.md.j2", "incident_report.md", incident.model_dump(mode="json"))
    return True


def _run_prompt_workflow(
    cfg: ToolkitConfig,
    config_path: str,
    prompt: str,
    model_output: Optional[str] = None,
    context_file: Optional[str] = None,
    invocation_mode: str = "stub",
    model_details: Optional[dict] = None,
) -> Path:
    """Run the end-to-end prompt workflow and return the artifact directory."""

    run_context = _build_run_context(cfg, _resolve_run_id(cfg))
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    context_payload = _load_context_payload(context_file)
    retrieved_contexts = context_payload.get("retrieved_contexts", [])

    resolved_output = model_output or (
        "Stub model response: real provider integration is pending. "
        "TODO: connect Azure OpenAI or another model endpoint."
    )

    telemetry.log_event("RUN_STARTED", "orchestration", {"config": config_path})
    prompt_bundle = {
        "project_name": cfg.project_name,
        "run_id": run_context.run_id,
        "prompt": prompt,
        "model_output": resolved_output,
        "retrieved_contexts": retrieved_contexts,
        "adapter": cfg.adapters.model_dump(mode="json"),
        "simulation": {
            "enabled": invocation_mode != "stub",
            "mode": invocation_mode,
        },
    }
    for key, value in context_payload.items():
        if key != "retrieved_contexts":
            prompt_bundle[key] = value
    if model_details:
        prompt_bundle["model_invocation"] = model_details
    store.write_json("prompt_run.json", prompt_bundle)
    telemetry.log_event("ARTIFACT_WRITTEN", "orchestration", {"artifact": "prompt_run.json"})
    if model_details:
        store.write_json("model_response.json", model_details)
        telemetry.log_event("ARTIFACT_WRITTEN", "orchestration", {"artifact": "model_response.json"})
    embedding_features = compute_embedding_features(cfg, prompt_bundle)
    _write_embedding_trace(store, embedding_features)
    telemetry.log_event("ARTIFACT_WRITTEN", "orchestration", {"artifact": "embedding_trace.json"})

    eval_results = run_eval(
        cfg,
        run_context.run_id,
        telemetry=telemetry,
        config_path=Path(config_path),
        prompt_bundle=prompt_bundle,
        embedding_features=embedding_features,
    )
    store.write_json(
        "eval_results.json",
        {
            "run_id": run_context.run_id,
            "system_context": _artifact_system_context(run_context),
            "results": [item.model_dump(mode="json") for item in eval_results],
        },
    )
    telemetry.log_event("ARTIFACT_WRITTEN", "eval", {"artifact": "eval_results.json"})

    findings = run_redteam(
        cfg,
        telemetry=telemetry,
        context_overrides={
            "prompt": prompt,
            "model_output": resolved_output,
            "retrieved_contexts": retrieved_contexts,
        },
    )
    finding_payload = [item.model_dump(mode="json") for item in findings]
    store.write_json(
        "redteam_findings.json",
        {
            "run_id": run_context.run_id,
            "system_context": _artifact_system_context(run_context),
            "findings": finding_payload,
        },
    )
    _write_redteam_summary(store, finding_payload)
    telemetry.log_event("ARTIFACT_WRITTEN", "redteam", {"artifact": "redteam_findings.json"})

    reasoning_md, reasoning_json = generate_reasoning_report(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(reasoning_md)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(reasoning_json)})
    lineage_md, lineage_json = generate_lineage_artifacts(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(lineage_md)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(lineage_json)})

    monitoring = _monitoring_for_run(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "monitoring", {"artifact": "monitoring_summary.json"})

    _docs_for_run(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "docs", {"artifact": "artifact_manifest.json"})

    scorecard = generate_scorecard(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.md"})
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.html"})

    incident_opened = _incident_for_run(cfg, store, monitoring)
    if incident_opened:
        telemetry.log_event("ARTIFACT_WRITTEN", "incident", {"artifact": "incident_report.md"})
        # Refresh docs and scorecard only when incident artifacts changed completeness.
        _docs_for_run(cfg, store)
        scorecard = generate_scorecard(cfg, store)
    telemetry.log_event(
        "RUN_FINISHED",
        "orchestration",
        {"overall_status": scorecard.overall_status, "go_no_go": scorecard.go_no_go},
    )
    return store.run_dir


@app.command("init")
def init() -> None:
    """Create sample config.yaml and suite definitions in current directory."""

    config_path = Path("config.yaml")
    suites_dir = Path("suites")
    suites_dir.mkdir(parents=True, exist_ok=True)

    sample_config = ToolkitConfig(
        project_name="sample-trusted-ai-project",
        risk_tier="medium",
        eval={"suites": ["medium"], "benchmark_registry_path": "benchmarks/metric_registry.json"},
        system={
            "system_id": "sample-trusted-ai-system",
            "system_name": "Sample Trusted AI System",
            "version": "1.0.0",
            "model_provider": "OpenAI",
            "model_name": "sample-classifier",
            "model_version": "2026-03-01",
            "environment": "staging",
            "risk_level": "medium",
            "compliance_profile": "internal",
            "telemetry_level": "standard",
            "deployment_region": "us-east-1",
            "owner": "responsible-ai-team",
            "metadata": {
                "intended_use": "Evaluate governance shell and workflows",
                "limitations": "Synthetic records for demonstration",
                "change_ticket": "DEMO-100",
                "data_classification": "internal",
            },
        },
        data={
            "dataset_name": "sample_customer_data",
            "source": "local_csv",
            "sensitive_features": ["gender", "age_bucket"],
            "intended_use": "Evaluate governance shell and workflows",
            "limitations": "Synthetic records for demonstration",
        },
        model={
            "model_name": "sample_classifier",
            "version": "0.1.0",
            "owner": "responsible-ai-team",
            "task": "classification",
            "intended_use": "Internal policy and quality checks",
            "limitations": "Not production-grade",
            "known_failures": ["Edge cases may be unstable"],
        },
        adapters={
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "qwen2.5-coder:3b",
            "request_format": "ollama_generate",
            "timeout_seconds": 60,
        },
    )
    config_path.write_text(yaml.safe_dump(sample_config.model_dump(mode="python"), sort_keys=False), encoding="utf-8")

    packaged_suites = Path(__file__).resolve().parent / "eval" / "suites"
    for name in ("low", "medium", "high"):
        (suites_dir / f"{name}.yaml").write_text((packaged_suites / f"{name}.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    console.print("Initialized config.yaml and deck-aligned suites/*.yaml")


@eval_app.command("run")
def eval_run(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Run evaluation suites and persist eval outputs."""

    cfg = load_config(config)
    run_context = _build_run_context(cfg, _resolve_run_id(cfg))
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "eval", {"config": config})
    eval_results = run_eval(cfg, run_context.run_id, telemetry=telemetry, config_path=Path(config))
    store.write_json(
        "eval_results.json",
        {
            "run_id": run_context.run_id,
            "system_context": _artifact_system_context(run_context),
            "results": [item.model_dump(mode="json") for item in eval_results],
        },
    )
    telemetry.log_event("ARTIFACT_WRITTEN", "eval", {"artifact": "eval_results.json"})
    telemetry.log_event("RUN_FINISHED", "eval", {})
    console.print(f"Eval complete. Artifacts: {store.run_dir}")


@xai_app.command("reasoning-report")
def xai_reasoning_report(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Generate explainability artifacts."""

    cfg = load_config(config)
    run_context = _build_run_context(cfg, _resolve_run_id(cfg))
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "xai", {"config": config})
    md_path, json_path = generate_reasoning_report(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(md_path)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(json_path)})
    lineage_path, index_path = generate_lineage_artifacts(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(lineage_path)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(index_path)})
    telemetry.log_event("RUN_FINISHED", "xai", {})

    console.print(f"Reasoning artifacts written under: {store.run_dir}")


@redteam_app.command("run")
def redteam_run(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Run red-team cases and write findings artifacts."""

    cfg = load_config(config)
    run_context = _build_run_context(cfg, _resolve_run_id(cfg))
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "redteam", {"config": config})
    findings = run_redteam(cfg, telemetry=telemetry)
    finding_payload = [item.model_dump(mode="json") for item in findings]
    store.write_json(
        "redteam_findings.json",
        {
            "run_id": run_context.run_id,
            "system_context": _artifact_system_context(run_context),
            "findings": finding_payload,
        },
    )
    _write_redteam_summary(store, finding_payload)
    telemetry.log_event("ARTIFACT_WRITTEN", "redteam", {"artifact": "redteam_findings.json"})
    telemetry.log_event("RUN_FINISHED", "redteam", {})
    console.print(f"Red-team complete. Findings written under: {store.run_dir}")


@app.command("report")
def report(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Generate governance scorecard from available run artifacts."""

    cfg = load_config(config)
    run_context = _build_run_context(cfg, _resolve_run_id(cfg))
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "reporting", {"config": config})
    scorecard = generate_scorecard(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.md"})
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.html"})
    telemetry.log_event("RUN_FINISHED", "reporting", {"overall_status": scorecard.overall_status})

    console.print(f"Scorecard written under: {store.run_dir}")


@docs_app.command("build")
def docs_build(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Regenerate Workstream D documentation artifacts for latest run."""

    cfg = load_config(config)
    latest = _latest_run_dir(cfg.output_dir)
    if latest is None:
        raise typer.BadParameter("No run directory found under output_dir")
    run_context = _build_run_context(cfg, latest.name)
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "docs", {"config": config, "run_id": latest.name})
    _docs_for_run(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "docs", {"artifact": "system_card.md"})
    telemetry.log_event("ARTIFACT_WRITTEN", "docs", {"artifact": "artifact_manifest.json"})
    telemetry.log_event("RUN_FINISHED", "docs", {})
    console.print(f"Documentation artifacts built for run: {latest.name}")


@monitor_app.command("summarize")
def monitor_summarize(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Create monitoring summary from telemetry JSONL for latest run."""

    cfg = load_config(config)
    latest = _latest_run_dir(cfg.output_dir)
    if latest is None:
        raise typer.BadParameter("No run directory found under output_dir")
    run_context = _build_run_context(cfg, latest.name)
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "monitoring", {"config": config, "run_id": latest.name})
    summary = _monitoring_for_run(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "monitoring", {"artifact": "monitoring_summary.json"})
    telemetry.log_event("RUN_FINISHED", "monitoring", {"total_events": summary.total_events})
    console.print(f"Monitoring summary generated for run: {latest.name}")


@incident_app.command("generate")
def incident_generate(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Force incident artifact generation for latest run."""

    cfg = load_config(config)
    latest = _latest_run_dir(cfg.output_dir)
    if latest is None:
        raise typer.BadParameter("No run directory found under output_dir")
    run_context = _build_run_context(cfg, latest.name)
    store, telemetry = _build_store_and_telemetry(cfg, run_context)

    telemetry.log_event("RUN_STARTED", "incident", {"config": config, "run_id": latest.name})
    summary_payload = _load_summary(store.path_for("monitoring_summary.json"))
    monitoring = MonitoringSummary.model_validate(summary_payload) if summary_payload else _monitoring_for_run(store)

    scorecard = _load_summary(store.path_for("scorecard.json"))
    if not scorecard:
        generate_scorecard(cfg, store)

    opened = _incident_for_run(cfg, store, monitoring)
    telemetry.log_event("ARTIFACT_WRITTEN", "incident", {"artifact": "incident_report.md", "opened": opened})
    telemetry.log_event("RUN_FINISHED", "incident", {"opened": opened})
    console.print(f"Incident generation complete for run: {latest.name} | opened={opened}")


@run_app.command("prompt")
def run_prompt(
    config: str = typer.Option(..., "--config", help="Path to toolkit config YAML"),
    prompt: str = typer.Option(..., "--prompt", help="End-user prompt text"),
    model_output: Optional[str] = typer.Option(
        None,
        "--model-output",
        help="Optional model output text. If omitted, a deterministic placeholder is used.",
    ),
    context_file: Optional[str] = typer.Option(
        None,
        "--context-file",
        help="Optional JSON file of retrieved RAG contexts or metadata.",
    ),
) -> None:
    """Run full trusted-AI evidence workflow for one prompt."""

    cfg = load_config(config)
    run_dir = _run_prompt_workflow(cfg, config, prompt, model_output=model_output, context_file=context_file)
    console.print(f"Prompt run complete. Artifacts: {run_dir}")


@run_app.command("simulate")
def run_simulate(
    config: str = typer.Option(..., "--config", help="Path to toolkit config YAML"),
    prompt: str = typer.Option(..., "--prompt", help="End-user prompt text"),
    context_file: Optional[str] = typer.Option(
        None,
        "--context-file",
        help="Optional JSON file of retrieved RAG contexts or metadata.",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Optional live provider override. Supported: ollama, openai_compatible, azure_openai.",
    ),
    endpoint: Optional[str] = typer.Option(
        None,
        "--endpoint",
        help="Optional provider endpoint override. Defaults to adapters.endpoint.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Optional model override. Defaults to adapters.model or system.model_name.",
    ),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="Optional API key environment variable override. Defaults to adapters.api_key_env.",
    ),
    request_format: Optional[str] = typer.Option(
        None,
        "--request-format",
        help="Optional routing override. Supported: auto, responses, chat_completions, ollama_generate.",
    ),
) -> None:
    """Run the full toolkit using a live model while simulating downstream operation."""

    cfg = _apply_adapter_overrides(
        load_config(config),
        provider=provider,
        endpoint=endpoint,
        model=model,
        api_key_env=api_key_env,
        request_format=request_format,
    )
    retrieved_contexts = _load_retrieved_contexts(context_file)

    model_prompt = _compose_model_prompt(prompt, retrieved_contexts)
    try:
        invocation = invoke_model(model_prompt, cfg)
    except ModelInvocationError as exc:
        raise typer.BadParameter(str(exc)) from exc

    model_details = _model_artifact_payload(
        invocation_mode="live_simulation",
        provider=invocation.provider,
        model_name=invocation.model,
        route=invocation.route,
        request_url=invocation.request_url,
        request_payload=invocation.request_payload,
        response_payload=invocation.response_payload,
    )
    run_dir = _run_prompt_workflow(
        cfg,
        config,
        prompt,
        model_output=invocation.output_text,
        context_file=context_file,
        invocation_mode="live_simulation",
        model_details=model_details,
    )
    console.print(f"Simulation run complete. Artifacts: {run_dir}")


@run_app.command("benchmark-matrix")
def run_benchmark_matrix(
    fixture_dir: str = typer.Option(
        "configs/benchmarks",
        "--fixture-dir",
        help="Directory containing low.yaml, medium.yaml, high.yaml and matching *_context.json fixtures.",
    ),
    scenario_count: int = typer.Option(
        3,
        "--scenario-count",
        min=3,
        help="Total benchmark scenarios to run across low/medium/high cohorts.",
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="Optional live provider override. Supported: ollama, openai_compatible, azure_openai.",
    ),
    endpoint: Optional[str] = typer.Option(
        None,
        "--endpoint",
        help="Optional provider endpoint override.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Optional model override.",
    ),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="Optional API key environment variable override.",
    ),
    request_format: Optional[str] = typer.Option(
        None,
        "--request-format",
        help="Optional routing override.",
    ),
) -> None:
    """Run low/medium/high benchmark fixtures and populate the benchmark registry."""

    root = Path(fixture_dir)
    if not root.exists():
        raise typer.BadParameter(f"fixture directory not found: {root}")

    fixture_configs: dict[str, ToolkitConfig] = {}
    fixture_contexts: dict[str, dict] = {}
    for tier in ("low", "medium", "high"):
        config_path = root / f"{tier}.yaml"
        context_path = root / f"{tier}_context.json"
        if not config_path.exists():
            raise typer.BadParameter(f"missing benchmark config: {config_path}")
        if not context_path.exists():
            raise typer.BadParameter(f"missing benchmark context: {context_path}")
        fixture_configs[tier] = _apply_adapter_overrides(
            load_config(config_path),
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key_env=api_key_env,
            request_format=request_format,
        )
        fixture_contexts[tier] = _load_context_payload(str(context_path))

    summary_path = Path("artifacts") / "benchmark_matrix_summary.json"
    summary: list[dict[str, str | float | None]] = []
    tier_counts = {tier: 0 for tier in ("low", "medium", "high")}
    for scenario_index, tier in enumerate(_benchmark_tier_sequence(scenario_count), start=1):
        config_path = root / f"{tier}.yaml"
        cfg = fixture_configs[tier]
        tier_counts[tier] += 1
        context_payload, scenario_family = _benchmark_context_variant(
            fixture_contexts[tier],
            tier,
            scenario_index,
            tier_counts[tier],
        )
        prompt = _prompt_from_context_payload(context_payload, f"Summarize the {tier} risk governance posture")
        prompt, scenario_family = _benchmark_prompt_variant(prompt, tier, scenario_index, tier_counts[tier])
        model_prompt = _compose_model_prompt(prompt, context_payload.get("retrieved_contexts", []))
        try:
            invocation = invoke_model(model_prompt, cfg)
        except ModelInvocationError as exc:
            raise typer.BadParameter(f"{tier} benchmark failed at scenario {scenario_index}: {exc}") from exc

        model_details = _model_artifact_payload(
            invocation_mode="live_simulation",
            provider=invocation.provider,
            model_name=invocation.model,
            route=invocation.route,
            request_url=invocation.request_url,
            request_payload=invocation.request_payload,
            response_payload=invocation.response_payload,
        )
        context_path = _write_temporary_context_payload(context_payload)
        run_dir = _run_prompt_workflow(
            cfg,
            str(config_path),
            prompt,
            model_output=invocation.output_text,
            context_file=str(context_path),
            invocation_mode="live_simulation",
            model_details=model_details,
        )
        scorecard_payload = _load_summary(run_dir / "scorecard.json")
        summary.append(
            {
                "tier": tier,
                "scenario_index": float(scenario_index),
                "tier_scenario_index": float(tier_counts[tier]),
                "scenario_family": scenario_family,
                "run_id": scorecard_payload.get("run_id"),
                "trust_score": scorecard_payload.get("trust_score"),
                "empirical_score": scorecard_payload.get("empirical_score"),
                "governance_score": scorecard_payload.get("governance_score"),
                "overall_status": scorecard_payload.get("overall_status"),
            }
        )
        aggregate_runs: dict[str, dict[str, object]] = {}
        for aggregate_tier in ("low", "medium", "high"):
            tier_runs = [item for item in summary if item["tier"] == aggregate_tier]
            trust_scores = [
                float(item["trust_score"]) for item in tier_runs if isinstance(item.get("trust_score"), (int, float))
            ]
            empirical_scores = [
                float(item["empirical_score"])
                for item in tier_runs
                if isinstance(item.get("empirical_score"), (int, float))
            ]
            governance_scores = [
                float(item["governance_score"])
                for item in tier_runs
                if isinstance(item.get("governance_score"), (int, float))
            ]
            aggregate_runs[aggregate_tier] = {
                "scenario_count": len(tier_runs),
                "pass_count": sum(1 for item in tier_runs if item.get("overall_status") == "pass"),
                "needs_review_count": sum(1 for item in tier_runs if item.get("overall_status") == "needs_review"),
                "fail_count": sum(1 for item in tier_runs if item.get("overall_status") == "fail"),
                "mean_trust_score": _safe_mean(trust_scores),
                "mean_empirical_score": _safe_mean(empirical_scores),
                "mean_governance_score": _safe_mean(governance_scores),
            }
        _write_benchmark_summary(summary_path, scenario_count, tier_counts, aggregate_runs, summary)
        if scenario_index % 10 == 0 or scenario_index == scenario_count:
            console.print(f"Benchmark progress: {scenario_index}/{scenario_count} scenarios completed")

    console.print(f"Benchmark matrix complete. Summary: {summary_path}")


@app.command("demo")
def demo(
    config: str = typer.Option("config.yaml", "--config", help="Path to toolkit config YAML"),
    prompt: str = typer.Option("Summarize policy controls", "--prompt", help="Demo prompt text"),
    model_output: Optional[str] = typer.Option(
        "Stub answer",
        "--model-output",
        help="Optional model output text to keep the demo deterministic.",
    ),
    open_scorecard: bool = typer.Option(
        False,
        "--open-scorecard/--no-open-scorecard",
        help="Open the generated scorecard HTML in the default browser.",
    ),
) -> None:
    """Initialize (if needed), run a deterministic demo, and surface the scorecard path."""

    config_path = Path(config)
    if not config_path.exists():
        init()

    cfg = load_config(config)
    run_dir = _run_prompt_workflow(cfg, config, prompt, model_output=model_output)
    scorecard_html = run_dir / "scorecard.html"

    if open_scorecard:
        webbrowser.open(scorecard_html.resolve().as_uri())

    console.print(f"Demo complete. Scorecard: {scorecard_html}")


def main() -> None:
    """Console entrypoint for installation script."""

    app()


if __name__ == "__main__":
    main()
