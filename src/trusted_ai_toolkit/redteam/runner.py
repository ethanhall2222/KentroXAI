"""Red-team runner for deterministic security case execution."""

from __future__ import annotations

from trusted_ai_toolkit.monitoring import TelemetryLogger
from trusted_ai_toolkit.redteam.cases import CASE_REGISTRY
from trusted_ai_toolkit.schemas import RedTeamFinding, ToolkitConfig


def run_redteam(
    config: ToolkitConfig,
    telemetry: TelemetryLogger | None = None,
    context_overrides: dict | None = None,
) -> list[RedTeamFinding]:
    """Run configured red-team cases and return findings."""

    findings: list[RedTeamFinding] = []
    context = {
        "risk_tier": config.risk_tier,
        "project_name": config.project_name,
    }
    if context_overrides:
        context.update(context_overrides)

    for case_id in config.redteam.cases:
        case_fn = CASE_REGISTRY.get(case_id)
        if case_fn is None:
            continue
        finding = case_fn(context)
        findings.append(finding)

        if telemetry:
            telemetry.log_event(
                "REDTEAM_CASE_RUN",
                "redteam",
                {
                    "case_id": finding.case_id,
                    "severity": finding.severity,
                    "passed": finding.passed,
                    "tags": finding.tags,
                },
            )

    return findings
