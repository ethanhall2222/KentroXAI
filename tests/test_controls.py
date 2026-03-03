from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tat.controls import pillar_scores, risk_tier, run_controls, trust_score
from tat.controls.models import ControlResult
from tat.schemas import SystemSpec


def _system_fixture(**overrides: object) -> SystemSpec:
    payload = {
        "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "system_id": "system-1",
        "system_name": "System 1",
        "version": "1.2.3",
        "model_provider": "OpenAI",
        "model_name": "gpt-4.1",
        "model_version": "2026-02-15",
        "environment": "production",
        "risk_level": "high",
        "compliance_profile": "regulated",
        "telemetry_level": "enhanced",
        "deployment_region": "us-east-1",
        "owner": "ai-governance",
        "metadata": {
            "intended_use": "Summarize governance posture",
            "change_ticket": "GRC-2048",
            "data_classification": "confidential",
        },
    }
    payload.update(overrides)
    return SystemSpec.model_validate(payload)


def test_controls_compute_deterministic_pillar_scores() -> None:
    system = _system_fixture()
    results = run_controls(system)
    scores = pillar_scores(results)

    assert scores == {
        "security": 1.0,
        "reliability": 1.0,
        "transparency": 0.75,
        "governance": 1.0,
    }
    assert trust_score(scores) == pytest.approx(0.9375, abs=1e-4)


def test_risk_tier_gates_on_failed_control_severity() -> None:
    assert risk_tier(
        [
            ControlResult("SEC-01", "security", "high", False, "high fail"),
            ControlResult("REL-01", "reliability", "low", True, "pass"),
        ]
    ) == "Tier 3"
    assert risk_tier(
        [
            ControlResult("TRN-01", "transparency", "medium", False, "medium fail"),
            ControlResult("REL-01", "reliability", "low", True, "pass"),
        ]
    ) == "Tier 2"
    assert risk_tier(
        [
            ControlResult("GOV-01", "governance", "high", True, "pass"),
            ControlResult("REL-01", "reliability", "low", True, "pass"),
        ]
    ) == "Tier 1"
