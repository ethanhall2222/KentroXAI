"""Run-level context shared across telemetry and artifact generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from tat.schemas.system_spec import SystemSpec


def compute_system_hash(system: SystemSpec) -> str:
    """Return a stable hash of a canonical SystemSpec JSON payload."""

    canonical = json.dumps(
        system.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def build_system_context(system: SystemSpec | None, system_hash: str | None = None) -> dict[str, str] | None:
    """Build the shared system context payload for emitted artifacts."""

    if system is None:
        return None

    resolved_hash = system_hash or compute_system_hash(system)
    return {
        "system_id": system.system_id,
        "system_hash": resolved_hash,
        "system_name": system.system_name,
        "version": system.version,
        "environment": system.environment,
        "risk_level": system.risk_level,
        "telemetry_level": system.telemetry_level,
    }


class RunContext(BaseModel):
    """Run-level metadata carried across runtime components."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system: SystemSpec | None = None
    system_hash: str | None = None
    environment: str | None = None
    risk_level: str | None = None
    telemetry_level: str | None = None

    @classmethod
    def from_system(
        cls,
        system: SystemSpec | None,
        *,
        run_id: str | None = None,
        started_at: datetime | None = None,
    ) -> "RunContext":
        """Construct a run context from an optional validated system spec."""

        resolved_hash = compute_system_hash(system) if system is not None else None
        return cls(
            run_id=run_id or str(uuid4()),
            started_at=started_at or datetime.now(timezone.utc),
            system=system,
            system_hash=resolved_hash,
            environment=system.environment if system is not None else None,
            risk_level=system.risk_level if system is not None else None,
            telemetry_level=system.telemetry_level if system is not None else None,
        )

    def system_context(self) -> dict[str, str] | None:
        """Return the shared system context payload for artifacts."""

        return build_system_context(self.system, self.system_hash)

    def telemetry_fields(self) -> dict[str, Any]:
        """Return flattened telemetry metadata fields for event payloads."""

        if self.system is None:
            return {
                "system_id": None,
                "system_hash": None,
                "system_name": None,
                "system_version": None,
                "environment": None,
                "risk_level": None,
                "telemetry_level": None,
            }

        return {
            "system_id": self.system.system_id,
            "system_hash": self.system_hash,
            "system_name": self.system.system_name,
            "system_version": self.system.version,
            "environment": self.environment,
            "risk_level": self.risk_level,
            "telemetry_level": self.telemetry_level,
        }
