"""Project-local authorization for SASE-managed repository resources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config import ConfigEditError, set_key

SASE_MANAGED_CONFIG_KEY = "is_sase_managed"


@dataclass(frozen=True)
class _LocalConfigResult:
    """A project-local YAML mapping or the error that made it unusable."""

    config: Mapping[str, Any]
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ProjectManagementStatus:
    """Whether one repository explicitly authorizes SASE management."""

    config_path: Path
    is_sase_managed: bool
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class _ProjectManagementUpdate:
    """Result of setting the project-local SASE management marker."""

    changed: bool
    error: str | None = None


def load_local_config(config_path: Path) -> _LocalConfigResult:
    """Load only *config_path* as a YAML mapping, without merged defaults."""

    if not config_path.exists():
        return _LocalConfigResult({})
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return _LocalConfigResult({}, f"{config_path}: failed to parse YAML: {exc}")
    except OSError as exc:
        return _LocalConfigResult({}, f"{config_path}: failed to read file: {exc}")
    if data is None:
        return _LocalConfigResult({})
    if not isinstance(data, Mapping):
        return _LocalConfigResult(
            {}, f"{config_path}: expected a YAML mapping at the top level"
        )
    return _LocalConfigResult(data)


def project_management_status(config_path: Path) -> ProjectManagementStatus:
    """Read the sole local authorization marker for a repository."""

    loaded = load_local_config(config_path)
    if not loaded.valid:
        return ProjectManagementStatus(config_path, False, loaded.error)

    value = loaded.config.get(SASE_MANAGED_CONFIG_KEY, False)
    if not isinstance(value, bool):
        return ProjectManagementStatus(
            config_path,
            False,
            f"{config_path}: {SASE_MANAGED_CONFIG_KEY} must be a boolean",
        )
    return ProjectManagementStatus(config_path, value)


def enable_sase_management(config_path: Path) -> _ProjectManagementUpdate:
    """Set the local authorization marker while preserving YAML comments."""

    loaded = load_local_config(config_path)
    if not loaded.valid:
        return _ProjectManagementUpdate(False, loaded.error)

    try:
        current_text = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )
        updated_text = set_key(current_text, (SASE_MANAGED_CONFIG_KEY,), True)
    except (ConfigEditError, OSError) as exc:
        return _ProjectManagementUpdate(
            False,
            f"{config_path}: failed to update {SASE_MANAGED_CONFIG_KEY}: {exc}",
        )

    if updated_text == current_text:
        return _ProjectManagementUpdate(False)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(updated_text, encoding="utf-8")
    except OSError as exc:
        return _ProjectManagementUpdate(
            False, f"{config_path}: failed to write file: {exc}"
        )
    return _ProjectManagementUpdate(True)


__all__ = [
    "ProjectManagementStatus",
    "SASE_MANAGED_CONFIG_KEY",
    "enable_sase_management",
    "load_local_config",
    "project_management_status",
]
