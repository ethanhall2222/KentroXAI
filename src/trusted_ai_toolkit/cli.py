"""Typer CLI entrypoint for Trusted AI Toolkit flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.documentation import build_documentation_artifacts
from trusted_ai_toolkit.eval.runner import run_eval
from trusted_ai_toolkit.incident import generate_incident_record, should_open_incident
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
    return config.monitoring.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_store_and_telemetry(config: ToolkitConfig, run_id: str) -> tuple[ArtifactStore, TelemetryLogger]:
    store = ArtifactStore(config.output_dir, run_id)
    telemetry_path = Path(config.output_dir) / run_id / config.monitoring.telemetry_path
    telemetry = TelemetryLogger(telemetry_path=telemetry_path, run_id=run_id, enabled=config.monitoring.enabled)
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


@app.command("init")
def init() -> None:
    """Create sample config.yaml and suite definitions in current directory."""

    config_path = Path("config.yaml")
    suites_dir = Path("suites")
    suites_dir.mkdir(parents=True, exist_ok=True)

    sample_config = ToolkitConfig(
        project_name="sample-trusted-ai-project",
        risk_tier="medium",
        eval={"suites": ["medium"]},
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
    run_id = _resolve_run_id(cfg)
    store, telemetry = _build_store_and_telemetry(cfg, run_id)

    telemetry.log_event("RUN_STARTED", "eval", {"config": config})
    eval_results = run_eval(cfg, run_id, telemetry=telemetry, config_path=Path(config))
    store.write_json("eval_results.json", [item.model_dump(mode="json") for item in eval_results])
    telemetry.log_event("ARTIFACT_WRITTEN", "eval", {"artifact": "eval_results.json"})
    telemetry.log_event("RUN_FINISHED", "eval", {})
    console.print(f"Eval complete. Artifacts: {store.run_dir}")


@xai_app.command("reasoning-report")
def xai_reasoning_report(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Generate explainability artifacts."""

    cfg = load_config(config)
    run_id = _resolve_run_id(cfg)
    store, telemetry = _build_store_and_telemetry(cfg, run_id)

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
    run_id = _resolve_run_id(cfg)
    store, telemetry = _build_store_and_telemetry(cfg, run_id)

    telemetry.log_event("RUN_STARTED", "redteam", {"config": config})
    findings = run_redteam(cfg, telemetry=telemetry)
    finding_payload = [item.model_dump(mode="json") for item in findings]
    store.write_json("redteam_findings.json", finding_payload)
    _write_redteam_summary(store, finding_payload)
    telemetry.log_event("ARTIFACT_WRITTEN", "redteam", {"artifact": "redteam_findings.json"})
    telemetry.log_event("RUN_FINISHED", "redteam", {})
    console.print(f"Red-team complete. Findings written under: {store.run_dir}")


@app.command("report")
def report(config: str = typer.Option(..., "--config", help="Path to toolkit config YAML")) -> None:
    """Generate governance scorecard from available run artifacts."""

    cfg = load_config(config)
    run_id = _resolve_run_id(cfg)
    store, telemetry = _build_store_and_telemetry(cfg, run_id)

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
    store, telemetry = _build_store_and_telemetry(cfg, latest.name)

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
    store, telemetry = _build_store_and_telemetry(cfg, latest.name)

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
    store, telemetry = _build_store_and_telemetry(cfg, latest.name)

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
    run_id = _resolve_run_id(cfg)
    store, telemetry = _build_store_and_telemetry(cfg, run_id)

    retrieved_contexts: list[dict] = []
    if context_file:
        path = Path(context_file)
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                retrieved_contexts = loaded

    resolved_output = model_output or (
        "Stub model response: real provider integration is pending. "
        "TODO: connect Azure OpenAI or another model endpoint."
    )

    telemetry.log_event("RUN_STARTED", "orchestration", {"config": config})
    prompt_bundle = {
        "project_name": cfg.project_name,
        "run_id": run_id,
        "prompt": prompt,
        "model_output": resolved_output,
        "retrieved_contexts": retrieved_contexts,
        "adapter": cfg.adapters.model_dump(mode="json"),
    }
    store.write_json("prompt_run.json", prompt_bundle)
    telemetry.log_event("ARTIFACT_WRITTEN", "orchestration", {"artifact": "prompt_run.json"})

    eval_results = run_eval(cfg, run_id, telemetry=telemetry, config_path=Path(config))
    store.write_json("eval_results.json", [item.model_dump(mode="json") for item in eval_results])
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
    store.write_json("redteam_findings.json", finding_payload)
    _write_redteam_summary(store, finding_payload)
    telemetry.log_event("ARTIFACT_WRITTEN", "redteam", {"artifact": "redteam_findings.json"})

    reasoning_md, reasoning_json = generate_reasoning_report(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(reasoning_md)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(reasoning_json)})
    lineage_md, lineage_json = generate_lineage_artifacts(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(lineage_md)})
    telemetry.log_event("ARTIFACT_WRITTEN", "xai", {"artifact": str(lineage_json)})

    scorecard = generate_scorecard(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.md"})
    telemetry.log_event("ARTIFACT_WRITTEN", "reporting", {"artifact": "scorecard.html"})

    monitoring = _monitoring_for_run(store)
    telemetry.log_event("ARTIFACT_WRITTEN", "monitoring", {"artifact": "monitoring_summary.json"})

    _docs_for_run(cfg, store)
    telemetry.log_event("ARTIFACT_WRITTEN", "docs", {"artifact": "artifact_manifest.json"})

    incident_opened = _incident_for_run(cfg, store, monitoring)
    if incident_opened:
        telemetry.log_event("ARTIFACT_WRITTEN", "incident", {"artifact": "incident_report.md"})

    # Refresh scorecard once docs/monitoring/incident artifacts exist for completeness calculations.
    scorecard = generate_scorecard(cfg, store)
    telemetry.log_event("RUN_FINISHED", "orchestration", {"overall_status": scorecard.overall_status, "go_no_go": scorecard.go_no_go})

    console.print(f"Prompt run complete. Artifacts: {store.run_dir}")


def main() -> None:
    """Console entrypoint for installation script."""

    app()


if __name__ == "__main__":
    main()
