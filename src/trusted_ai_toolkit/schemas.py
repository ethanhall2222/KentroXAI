"""Pydantic schemas for toolkit configuration and artifact contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DataConfig(BaseModel):
    """Configuration describing the dataset and intended use context."""

    dataset_name: str = "sample_dataset"
    source: str = "local"
    sensitive_features: list[str] = Field(default_factory=list)
    intended_use: str = "Demonstration and governance workflow validation"
    limitations: str = "Synthetic placeholders only; not production data"


class ModelConfig(BaseModel):
    """Configuration describing the model/system under evaluation."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str = "sample_model"
    version: str = "0.1.0"
    owner: str = "ml-team"
    task: str = "classification"
    intended_use: str = "Internal validation and risk documentation"
    limitations: str = "Stub model behavior"
    known_failures: list[str] = Field(default_factory=lambda: ["Out-of-domain inputs may degrade quality"])


class EvalConfig(BaseModel):
    """Evaluation configuration for suite and metric execution."""

    suites: list[str] = Field(default_factory=lambda: ["low"])
    metrics: list[str] = Field(default_factory=lambda: ["accuracy_stub", "reliability"])
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "accuracy_stub": 0.7,
            "reliability": 0.75,
            "fairness_demographic_parity_diff": 0.2,
            "groundedness_stub": 0.6,
            "refusal_correctness": 0.8,
            "unanswerable_handling": 0.78,
        }
    )


class XAIConfig(BaseModel):
    """Explainability artifact generation settings."""

    reasoning_report_template: str = "reasoning_report.md.j2"
    include_sections: list[str] = Field(
        default_factory=lambda: [
            "Overview / Intended Use",
            "Data Summary",
            "Model Summary",
            "Key Risks & Mitigations",
            "Evaluation Summary",
            "Explainability Approach",
            "Limitations / Open Questions",
            "References",
        ]
    )


class RedTeamConfig(BaseModel):
    """Red-team runner configuration."""

    suites: list[str] = Field(default_factory=lambda: ["baseline"])
    cases: list[str] = Field(
        default_factory=lambda: [
            "prompt_injection_basic",
            "prompt_injection_context_override",
            "prompt_injection_multi_step",
            "prompt_injection_unicode",
            "data_exfiltration_attempt",
            "data_exfiltration_prompt_dump",
            "data_exfiltration_embedding_leak",
            "data_exfiltration_indirect",
            "jailbreak_policy_bypass",
            "jailbreak_roleplay",
            "jailbreak_base64",
            "jailbreak_tool_switch",
            "system_prompt_leakage",
            "system_prompt_partial_token_leak",
            "system_prompt_reconstruction",
            "tool_misuse_file_delete",
            "tool_misuse_network_scan",
            "tool_misuse_credential_store",
            "tool_misuse_external_post",
            "system_prompt_leakage_basic",
        ]
    )
    severity_threshold: Literal["low", "medium", "high", "critical"] = "high"


class MonitoringConfig(BaseModel):
    """Monitoring and telemetry settings."""

    enabled: bool = True
    telemetry_path: str = "telemetry.jsonl"
    run_id: str | None = None


class GovernanceConfig(BaseModel):
    """Governance controls and stage-gate rules by risk tier."""

    risk_gate_rules: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {
            "low": {"require_redteam": False, "block_on_high_severity": False},
            "medium": {"require_redteam": True, "block_on_high_severity": True},
            "high": {"require_redteam": True, "block_on_high_severity": True, "require_human_signoff": True},
        }
    )
    required_stage_gates: list[str] = Field(
        default_factory=lambda: [
            "evaluation",
            "redteam",
            "documentation",
            "monitoring",
        ]
    )


class AdapterConfig(BaseModel):
    """Adapter settings for offline stubs and future provider integrations."""

    provider: Literal["stub", "azure_openai"] = "stub"
    endpoint: str | None = None
    deployment: str | None = None
    api_version: str | None = None
    model: str | None = None
    timeout_seconds: int = 30


class ArtifactPolicyConfig(BaseModel):
    """Required outputs for evidence pack completeness checks."""

    required_outputs_by_risk_tier: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "low": [
                "prompt_run.json",
                "eval_results.json",
                "reasoning_report.md",
                "scorecard.md",
                "scorecard.html",
                "scorecard.json",
                "telemetry.jsonl",
            ],
            "medium": [
                "prompt_run.json",
                "eval_results.json",
                "redteam_findings.json",
                "monitoring_summary.json",
                "reasoning_report.md",
                "lineage_report.md",
                "authoritative_data_index.json",
                "system_card.md",
                "data_card.md",
                "model_card.md",
                "scorecard.md",
                "scorecard.html",
                "scorecard.json",
                "artifact_manifest.json",
                "telemetry.jsonl",
            ],
            "high": [
                "prompt_run.json",
                "eval_results.json",
                "redteam_findings.json",
                "monitoring_summary.json",
                "reasoning_report.md",
                "lineage_report.md",
                "authoritative_data_index.json",
                "incident_report.md",
                "system_card.md",
                "data_card.md",
                "model_card.md",
                "scorecard.md",
                "scorecard.html",
                "scorecard.json",
                "artifact_manifest.json",
                "telemetry.jsonl",
            ],
        }
    )


class ToolkitConfig(BaseModel):
    """Top-level toolkit configuration contract."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = "trusted-ai-project"
    risk_tier: Literal["low", "medium", "high"] = "medium"
    output_dir: str = "artifacts"
    data: DataConfig | None = None
    model: ModelConfig | None = None
    eval: EvalConfig = Field(default_factory=EvalConfig)
    xai: XAIConfig = Field(default_factory=XAIConfig)
    redteam: RedTeamConfig = Field(default_factory=RedTeamConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    adapters: AdapterConfig = Field(default_factory=AdapterConfig)
    artifact_policy: ArtifactPolicyConfig = Field(default_factory=ArtifactPolicyConfig)


class MetricResult(BaseModel):
    """Individual metric output with threshold evaluation status."""

    metric_id: str
    value: float
    threshold: float | None = None
    passed: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EvalResult(BaseModel):
    """Aggregate evaluation result payload."""

    suite_name: str
    run_id: str
    started_at: datetime
    completed_at: datetime
    metric_results: list[MetricResult]
    overall_passed: bool
    notes: list[str] = Field(default_factory=list)


class RedTeamFinding(BaseModel):
    """Security finding from an executed red-team case."""

    case_id: str
    severity: Literal["low", "medium", "high", "critical"]
    passed: bool
    evidence: str
    recommendation: str
    tags: list[str] = Field(default_factory=list)


class Scorecard(BaseModel):
    """Governance scorecard summary contract."""

    project_name: str
    run_id: str
    risk_tier: Literal["low", "medium", "high"]
    overall_status: Literal["pass", "fail", "needs_review"]
    go_no_go: Literal["go", "no-go"]
    stage_gate_status: dict[str, Literal["pass", "needs_review", "fail"]] = Field(default_factory=dict)
    evidence_completeness: float = 0.0
    metric_results: list[MetricResult] = Field(default_factory=list)
    redteam_summary: dict[str, int] = Field(default_factory=dict)
    required_actions: list[str] = Field(default_factory=list)
    artifact_links: dict[str, str] = Field(default_factory=dict)


class TelemetryEvent(BaseModel):
    """Event emitted by monitoring logger as JSONL."""

    timestamp: datetime
    run_id: str
    event_type: Literal[
        "RUN_STARTED",
        "METRIC_COMPUTED",
        "REDTEAM_CASE_RUN",
        "ARTIFACT_WRITTEN",
        "RUN_FINISHED",
    ]
    component: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemSpec(BaseModel):
    """System metadata used for evaluation and governance."""

    system_name: str
    owner: str
    risk_tier: Literal["low", "medium", "high"]
    intended_use: str
    constraints: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    """Evaluation or red-team test case contract."""

    case_id: str
    prompt: str
    expected_behavior: str
    category: str
    risk_tier: Literal["low", "medium", "high"] = "medium"
    tags: list[str] = Field(default_factory=list)


class LineageNode(BaseModel):
    """One lineage/source node used by generated outputs."""

    node_id: str
    source_type: Literal["document", "dataset", "policy", "prompt", "system"]
    title: str
    uri: str | None = None
    used_for: str = "context"


class LineageReport(BaseModel):
    """Lineage report payload for explainability artifacts."""

    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    prompt: str
    model_output: str
    nodes: list[LineageNode] = Field(default_factory=list)
    citation_coverage: float = 0.0
    transparency_risk: Literal["low", "medium", "high"] = "medium"


class AuthoritativeSource(BaseModel):
    """Approved source entry for authoritative data index."""

    source_id: str
    name: str
    owner: str = "unknown"
    classification: Literal["public", "internal", "cui", "pii"] = "internal"
    uri: str | None = None
    approved: bool = True


class ArtifactManifestItem(BaseModel):
    """One manifest record for an artifact in a run directory."""

    path: str
    sha256: str
    size_bytes: int
    modified_at: datetime


class ArtifactManifest(BaseModel):
    """Manifest of generated run artifacts."""

    run_id: str
    generated_at: datetime
    items: list[ArtifactManifestItem] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    completeness: float = 0.0


class IncidentRecord(BaseModel):
    """Incident record contract for threshold breaches."""

    incident_id: str
    run_id: str
    severity: Literal["low", "medium", "high", "critical"]
    trigger: str
    summary: str
    containment_action: str
    owner: str = "incident-commander"
    due_date: str = "TBD"
    status: Literal["open", "triaged", "mitigated", "closed"] = "open"
    related_artifacts: list[str] = Field(default_factory=list)


class MonitoringSummary(BaseModel):
    """Aggregated telemetry metrics for one run."""

    run_id: str
    total_events: int
    events_by_type: dict[str, int] = Field(default_factory=dict)
    events_by_component: dict[str, int] = Field(default_factory=dict)
    metric_failure_rate: float = 0.0
    anomaly_flags: list[str] = Field(default_factory=list)


class StageGateDecision(BaseModel):
    """Stage-gate evaluation contract used in scorecards."""

    gate: str
    status: Literal["pass", "needs_review", "fail"]
    rationale: str
