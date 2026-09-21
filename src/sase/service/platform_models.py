"""Shared models and constants for native platform-unit planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

PlatformKind = Literal["linux", "darwin", "unsupported"]
ServicePlanStatus = Literal["current", "needs_attention", "blocked"]

DECLINED_MARKER = "platform_init.declined"
LEGACY_SYSTEMD_UNITS = (
    "sase-gateway.service",
    "sase-axe-ensure.service",
    "sase-axe-ensure.timer",
)
LEGACY_LAUNCHD_LABELS = ("sh.sase.gateway",)
SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV = "SASE_SERVICE_ALLOW_LIFECYCLE_IN_TESTS"
SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE = (
    "Native service-manager commands are disabled while running under pytest. Set "
    f"{SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV}=1 only for isolated lifecycle tests."
)


@dataclass(frozen=True)
class CommandResult:
    """Small command result protocol for injected platform managers."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str]], CommandResult]


@dataclass(frozen=True)
class NativeServiceDefinition:
    """Desired native-unit identity, paths, and rendered content."""

    platform: PlatformKind
    sase_home: Path
    default_home: Path
    unit_name: str
    label: str
    definition_path: Path
    env_path: Path
    stdout_path: Path
    stderr_path: Path
    executable: Path | None
    content: str
    alternate_home: bool = False

    @property
    def identity(self) -> str:
        return self.unit_name if self.platform == "linux" else self.label


@dataclass(frozen=True)
class NativeInspection:
    """Read-only native-unit state."""

    definition_exists: bool
    definition_current: bool
    environment_exists: bool
    environment_current: bool
    enabled: bool | None = None
    active: bool | None = None
    user_disabled: bool = False
    linger: bool | None = None
    legacy_owners: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServicePlatformPlan:
    """Complete read-only service-platform assessment."""

    definition: NativeServiceDefinition
    status: ServicePlanStatus
    actions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    diff: str = ""
    captured_env_redacted: Mapping[str, str] = field(default_factory=dict)
    inspection: NativeInspection | None = None

    @property
    def current(self) -> bool:
        return self.status == "current"


@dataclass(frozen=True)
class ServicePlatformApplyResult:
    """Result of installing or uninstalling the platform unit."""

    ok: bool
    changed: bool
    message: str
    plan: ServicePlatformPlan | None = None
