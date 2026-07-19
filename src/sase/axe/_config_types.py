"""Runtime types and errors for axe configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .chop_env import ChopEnvValue

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class AxeConfigDiagnostic:
    """One fail-closed axe configuration diagnostic from the Rust core."""

    code: str
    message: str
    path: str | None = None
    layer: str | None = None
    severity: str = "error"

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeConfigDiagnostic:
        return cls(
            code=str(payload["code"]),
            message=str(payload["message"]),
            path=str(payload["path"]) if payload.get("path") else None,
            layer=str(payload["layer"]) if payload.get("layer") else None,
            severity=str(payload.get("severity", "error")),
        )

    def format(self) -> str:
        """Render a compact config-path + provenance diagnostic."""
        location = self.path or "axe"
        source = f" (source: {self.layer})" if self.layer else ""
        return f"[{self.code}] {location}{source}: {self.message}"


class AxeConfigError(ValueError):
    """Raised when the effective ``axe:`` configuration is invalid."""

    def __init__(self, diagnostics: list[AxeConfigDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        details = "\n".join(f"- {item.format()}" for item in diagnostics)
        super().__init__(f"Invalid axe configuration:\n{details}")


@dataclass
class ChopConfig:
    """Configuration for a single script chop."""

    name: str
    description: str
    script: str | None = None
    enabled: bool = True
    run_every: int | None = None
    timeout: int | None = None
    env: dict[str, ChopEnvValue] = field(default_factory=dict)
    inhibit_if: list[dict[str, Any]] = field(default_factory=list)
    trigger: dict[str, Any] = field(default_factory=lambda: {"provider": "always"})
    once_per: dict[str, Any] | None = None
    base_name: str | None = None
    target_key: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    vars: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def script_name(self) -> str:
        """Return the exact executable name configured for this chop."""
        return self.script or self.name

    @property
    def parent_name(self) -> str | None:
        """Return the unexpanded parent identity for a target instance."""
        if not self.target_key:
            return None
        return self.base_name or self.name


@dataclass
class LumberjackConfig:
    """Configuration for a single lumberjack."""

    name: str
    interval: int
    chop_timeout: int | None = None
    env: dict[str, ChopEnvValue] = field(default_factory=dict)
    chops: list[ChopConfig] = field(default_factory=list)

    @property
    def chop_names(self) -> list[str]:
        """Return just the chop names as strings."""
        return [c.name for c in self.chops if c.enabled]


@dataclass
class AxeConfig:
    """Top-level axe configuration with lumberjack definitions."""

    max_hook_runners: int = 3
    max_agent_runners: int = 3
    zombie_timeout_seconds: int = 7200
    lumberjack_log_max_bytes: int = DEFAULT_LUMBERJACK_LOG_MAX_BYTES
    verbose_lumberjack_diagnostics: bool = False
    query: str = ""
    chop_script_dirs: list[str] = field(default_factory=list)
    lumberjacks: dict[str, LumberjackConfig] = field(default_factory=dict)
