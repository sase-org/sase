"""Runtime types and errors for axe configuration."""

from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .chop_env import ChopEnvValue

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS = 5 * 60
DEFAULT_LUMBERJACK_RESTART_BACKOFF_MAX_SECONDS = 60

# Diagnostic codes the Rust axe-chop config validator raises when a
# guard/trigger provider token isn't one it recognizes, mapped to the noun
# used in the stale-core-binding hint below.
_STALE_CORE_HINT_CODES = {
    "unknown_guard_provider": "guard",
    "unknown_trigger_provider": "trigger",
}
_PROVIDER_TOKEN_RE = re.compile(r"provider `([^`]+)`")


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


def _rejected_provider_token(item: AxeConfigDiagnostic) -> str | None:
    """Extract the rejected provider name from an unknown-provider diagnostic.

    The Rust validator always backtick-quotes the token in ``message`` (both
    the tagged-array and keyed guard/trigger forms), so that is the reliable
    source; the diagnostic ``path`` only ends in the token for the keyed form.
    """
    match = _PROVIDER_TOKEN_RE.search(item.message)
    if match:
        return match.group(1)
    if item.path:
        tail = item.path.rsplit(".", 1)[-1].split("[", 1)[0]
        return tail or None
    return None


def _collect_schema_providers(
    node: Any, *, keys: frozenset[str], active: bool
) -> set[str]:
    """Recursively collect ``provider`` enum values nested under any of *keys*."""
    providers: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            nested = active or key in keys
            if active and key == "provider" and isinstance(value, dict):
                enum_values = value.get("enum")
                if isinstance(enum_values, list):
                    providers.update(v for v in enum_values if isinstance(v, str))
            providers |= _collect_schema_providers(value, keys=keys, active=nested)
    elif isinstance(node, list):
        for item in node:
            providers |= _collect_schema_providers(item, keys=keys, active=active)
    return providers


@lru_cache(maxsize=1)
def _advertised_chop_providers() -> frozenset[str]:
    """Return every guard/trigger provider name the bundled schema advertises.

    Returns an empty set, and never raises, when the schema cannot be read or
    parsed -- a malformed/missing schema degrades to "no hint" instead of
    turning a config error into a crash.
    """
    try:
        from sase.config.inventory import load_config_schema

        schema = load_config_schema()
    except Exception:
        return frozenset()
    return frozenset(
        _collect_schema_providers(
            schema, keys=frozenset({"inhibit_if", "trigger"}), active=False
        )
    )


def _installed_core_version() -> str | None:
    try:
        return importlib.metadata.version("sase-core-rs")
    except Exception:
        return None


def _stale_core_binding_hint(
    diagnostics: tuple[AxeConfigDiagnostic, ...],
) -> str | None:
    """Return a hint line when the core rejected a provider this build advertises.

    Deliberately does not compare the installed core version against the
    declared floor: between core releases the Cargo version does not move and
    the floor legitimately lags master, so a version comparison both misses
    real skew and fires falsely. Whether the bundled schema advertises a
    provider the installed core just rejected is the exact signal.
    """
    try:
        for item in diagnostics:
            kind = _STALE_CORE_HINT_CODES.get(item.code)
            if kind is None:
                continue
            token = _rejected_provider_token(item)
            if not token or token not in _advertised_chop_providers():
                continue
            version = _installed_core_version()
            version_part = f" ({version})" if version else ""
            return (
                f"hint: this sase build advertises {kind} provider {token!r}, "
                f"but the installed sase_core_rs{version_part} rejects it — "
                "the Rust core binding is older than this sase build; run "
                "'sase update' (dev installs) or reinstall sase to rebuild "
                "sase_core_rs."
            )
    except Exception:
        return None
    return None


class AxeConfigError(ValueError):
    """Raised when the effective ``axe:`` configuration is invalid."""

    def __init__(self, diagnostics: list[AxeConfigDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        details = "\n".join(f"- {item.format()}" for item in diagnostics)
        message = f"Invalid axe configuration:\n{details}"
        hint = _stale_core_binding_hint(self.diagnostics)
        if hint:
            message += f"\n{hint}"
        super().__init__(message)


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
    description_summary: str = ""
    description_body: str = ""

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
    description: str
    interval: int
    chop_timeout: int | None = None
    wait_runners: int | None = None
    env: dict[str, ChopEnvValue] = field(default_factory=dict)
    chops: list[ChopConfig] = field(default_factory=list)
    description_summary: str = ""
    description_body: str = ""

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
    lumberjack_log_temp_max_age_seconds: int = (
        DEFAULT_LUMBERJACK_LOG_TEMP_MAX_AGE_SECONDS
    )
    lumberjack_restart_backoff_max_seconds: int = (
        DEFAULT_LUMBERJACK_RESTART_BACKOFF_MAX_SECONDS
    )
    verbose_lumberjack_diagnostics: bool = False
    query: str = ""
    chop_script_dirs: list[str] = field(default_factory=list)
    lumberjacks: dict[str, LumberjackConfig] = field(default_factory=dict)
