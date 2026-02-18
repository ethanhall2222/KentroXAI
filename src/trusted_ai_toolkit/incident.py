"""Incident generation utilities for governance threshold breaches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from trusted_ai_toolkit.artifacts import ArtifactStore
from trusted_ai_toolkit.schemas import IncidentRecord, MonitoringSummary, Scorecard

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def should_open_incident(
    scorecard: Scorecard,
    monitoring: MonitoringSummary,
    severity_threshold: Literal["low", "medium", "high", "critical"],
) -> tuple[bool, str, str]:
    """Determine whether incident should be created and return trigger metadata."""

    threshold_rank = SEVERITY_ORDER[severity_threshold]
    worst_severity = "low"
    for sev in ("critical", "high", "medium", "low"):
        if scorecard.redteam_summary.get(sev, 0) > 0:
            worst_severity = sev
            break

    redteam_breach = SEVERITY_ORDER[worst_severity] >= threshold_rank and scorecard.redteam_summary.get(worst_severity, 0) > 0
    gate_failed = any(status in {"needs_review", "fail"} for status in scorecard.stage_gate_status.values())
    has_anomalies = len(monitoring.anomaly_flags) > 0

    if redteam_breach:
        return True, "redteam_severity_breach", worst_severity
    if gate_failed:
        return True, "stage_gate_failure", "high"
    if has_anomalies:
        return True, "monitoring_anomaly", "medium"
    return False, "none", "low"


def generate_incident_record(
    store: ArtifactStore,
    scorecard: Scorecard,
    monitoring: MonitoringSummary,
    trigger: str,
    severity: Literal["low", "medium", "high", "critical"],
) -> IncidentRecord:
    """Create deterministic incident record payload."""

    incident_id = f"INC-{store.run_id}"
    summary = "Automated incident generated from Trusted AI Toolkit controls."
    containment = "Block promotion, route to human reviewer, and require remediation evidence."
    related_artifacts = [
        str(store.path_for("scorecard.json")),
        str(store.path_for("redteam_findings.json")),
        str(store.path_for("monitoring_summary.json")),
    ]

    return IncidentRecord(
        incident_id=incident_id,
        run_id=store.run_id,
        severity=severity,
        trigger=trigger,
        summary=summary,
        containment_action=containment,
        owner="responsible-ai-reviewer",
        due_date=datetime.now(timezone.utc).date().isoformat(),
        status="open",
        related_artifacts=related_artifacts,
    )
