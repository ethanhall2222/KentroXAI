"""Pydantic schema definitions for system governance specifications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


class ConfigBase(BaseModel):
    """Shared schema base for immutable governance timestamps."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Governance: records when the specification was authored for audit trails.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp for spec creation and audit lineage.",
    )


class SystemSpec(ConfigBase):
    """Source-of-truth configuration for AI system governance workflows."""

    # Governance: stable identifier used across telemetry and red-team artifacts.
    system_id: str = Field(..., description="Unique identifier for the governed AI system.")
    # Governance: human-readable label for reports and cross-team review.
    system_name: str = Field(..., description="Display name for the AI system.")
    # Governance: schema revision enables non-breaking expansion over time.
    version: str = Field(
        ...,
        pattern=SEMVER_PATTERN,
        description="Semantic version for the specification contract.",
    )
    # Governance: identifies the vendor or internal provider accountable for the model.
    model_provider: str = Field(..., description="Provider or owning organization for the model.")
    # Governance: captures the deployed model family for reproducibility.
    model_name: str = Field(..., description="Model family or deployment name in use.")
    # Governance: pins the exact model release referenced by evaluations.
    model_version: str = Field(..., description="Specific model build or release identifier.")
    # Governance: defines the runtime stage where controls and approvals apply.
    environment: Literal["development", "staging", "production"] = Field(
        ...,
        description="Operational environment for the system deployment.",
    )
    # Governance: expresses the required oversight intensity for the system.
    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        ...,
        description="Risk classification used for governance and approvals.",
    )
    # Governance: maps the system to a compliance handling posture.
    compliance_profile: Literal["internal", "regulated", "restricted"] = Field(
        ...,
        description="Compliance posture that drives control requirements.",
    )
    # Governance: sets the expected telemetry depth for monitoring and forensics.
    telemetry_level: Literal["minimal", "standard", "enhanced"] = Field(
        ...,
        description="Telemetry capture intensity required for this system.",
    )
    # Governance: records the primary runtime location for regional controls.
    deployment_region: str = Field(
        ...,
        description="Primary region or jurisdiction where the system operates.",
    )
    # Governance: identifies the accountable owner for policy exceptions and review.
    owner: str = Field(..., description="Team or individual accountable for the system.")
    # Governance: allows additive metadata without changing the core contract.
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata for future governance attributes.",
    )
