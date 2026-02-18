"""JSONL telemetry logging for toolkit execution flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trusted_ai_toolkit.schemas import MonitoringSummary, TelemetryEvent


class TelemetryLogger:
    """Append-only JSONL telemetry event logger."""

    def __init__(self, telemetry_path: str | Path, run_id: str, enabled: bool = True) -> None:
        self.path = Path(telemetry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.enabled = enabled

    def log_event(self, event_type: str, component: str, metadata: dict[str, Any] | None = None) -> None:
        """Emit one telemetry event as a JSONL line."""

        if not self.enabled:
            return

        payload = TelemetryEvent(
            timestamp=datetime.now(timezone.utc),
            run_id=self.run_id,
            event_type=event_type,
            component=component,
            metadata=metadata or {},
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload.model_dump(mode="json")) + "\n")


def load_telemetry_events(path: str | Path) -> list[dict[str, Any]]:
    """Load telemetry JSONL rows from disk."""

    telemetry_path = Path(path)
    if not telemetry_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in telemetry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def summarize_telemetry(run_id: str, events: list[dict[str, Any]]) -> MonitoringSummary:
    """Aggregate telemetry events into monitoring summary metrics."""

    events_by_type: dict[str, int] = {}
    events_by_component: dict[str, int] = {}
    metric_event_count = 0
    metric_failed_count = 0

    for event in events:
        event_type = str(event.get("event_type", "UNKNOWN"))
        component = str(event.get("component", "unknown"))
        events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
        events_by_component[component] = events_by_component.get(component, 0) + 1

        if event_type == "METRIC_COMPUTED":
            metric_event_count += 1
            passed = event.get("metadata", {}).get("passed")
            if passed is False:
                metric_failed_count += 1

    failure_rate = (metric_failed_count / metric_event_count) if metric_event_count else 0.0
    anomaly_flags: list[str] = []
    if failure_rate > 0.2:
        anomaly_flags.append("metric_failure_rate_above_20_percent")
    if events_by_type.get("REDTEAM_CASE_RUN", 0) == 0:
        anomaly_flags.append("redteam_events_missing")

    return MonitoringSummary(
        run_id=run_id,
        total_events=len(events),
        events_by_type=events_by_type,
        events_by_component=events_by_component,
        metric_failure_rate=round(failure_rate, 3),
        anomaly_flags=anomaly_flags,
    )
