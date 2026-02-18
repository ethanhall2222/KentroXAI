"""Configuration loading and environment override utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from trusted_ai_toolkit.schemas import ToolkitConfig


class ConfigError(ValueError):
    """Raised when config file parsing or validation fails."""


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config dictionary."""

    output_dir_override = os.getenv("TAT_OUTPUT_DIR")
    run_id_override = os.getenv("TAT_RUN_ID")
    adapter_provider_override = os.getenv("TAT_ADAPTER_PROVIDER")

    if output_dir_override:
        raw["output_dir"] = output_dir_override

    monitoring = raw.setdefault("monitoring", {})
    if run_id_override:
        monitoring["run_id"] = run_id_override
    if adapter_provider_override:
        adapters = raw.setdefault("adapters", {})
        adapters["provider"] = adapter_provider_override

    return raw


def load_config(path: str | Path) -> ToolkitConfig:
    """Load YAML config from path and validate as ToolkitConfig.

    Args:
        path: Path to YAML configuration file.

    Returns:
        Validated ToolkitConfig.

    Raises:
        ConfigError: If file is missing, malformed, or invalid.
    """

    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping/object")

    raw = _apply_env_overrides(raw)

    try:
        return ToolkitConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
