"""Validation helper for the SystemSpec example payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from tat.schemas import SystemSpec


def main() -> None:
    """Load the example specification and assert it validates."""

    spec_path = PROJECT_ROOT / "system_spec.example.json"
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    system_spec = SystemSpec.model_validate(payload)

    assert system_spec.system_id == payload["system_id"]
    print("SystemSpec validation succeeded.")


if __name__ == "__main__":
    main()
