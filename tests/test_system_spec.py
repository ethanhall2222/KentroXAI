from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from tat.schemas import SystemSpec


ROOT = Path(__file__).resolve().parents[1]


def test_system_spec_example_validates() -> None:
    payload = json.loads((ROOT / "system_spec.example.json").read_text(encoding="utf-8"))

    spec = SystemSpec.model_validate(payload)

    assert spec.system_id == "agent-risk-gateway"
    assert spec.environment == "production"
    assert spec.risk_level == "high"


def test_system_spec_rejects_invalid_environment() -> None:
    payload = json.loads((ROOT / "system_spec.example.json").read_text(encoding="utf-8"))
    payload["environment"] = "qa"

    try:
        SystemSpec.model_validate(payload)
    except ValidationError as exc:
        assert "environment" in str(exc)
    else:
        raise AssertionError("Expected validation to fail for an invalid environment")
