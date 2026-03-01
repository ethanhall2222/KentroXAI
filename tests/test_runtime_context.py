from __future__ import annotations

import json
from pathlib import Path

from tat.runtime import RunContext, compute_system_hash
from tat.schemas import SystemSpec


ROOT = Path(__file__).resolve().parents[1]


def test_run_context_computes_stable_system_hash() -> None:
    payload = json.loads((ROOT / "system_spec.example.json").read_text(encoding="utf-8"))
    system = SystemSpec.model_validate(payload)

    first_hash = compute_system_hash(system)
    second_hash = compute_system_hash(SystemSpec.model_validate(system.model_dump(mode="json")))
    run_context = RunContext.from_system(system, run_id="run-fixed")

    assert first_hash == second_hash
    assert run_context.system_hash == first_hash
    assert run_context.system_context() is not None
    assert run_context.system_context()["system_hash"] == first_hash
