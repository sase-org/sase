"""Typed feature-flag model objects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.feature_flags.registry import FeatureFlag


FlagKind = Literal["beta", "wip", "sunset", "ops"]
FlagScope = Literal["global", "project"]
FlagSource = Literal["default", "user", "overlay", "local", "override", "env", "cli"]

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def is_feature_flag_key(value: str) -> bool:
    """Return whether *value* is a non-empty snake_case flag key."""
    return bool(_SNAKE_CASE_RE.fullmatch(value))


class FeatureFlagError(Exception):
    """Base error for feature-flag resolution failures."""


class FeatureFlagEnvError(FeatureFlagError):
    """Raised when ``SASE_FEATURE_FLAGS`` is malformed."""


@dataclass(frozen=True)
class FeatureFlagDefinition:
    """A single code-owned feature flag definition."""

    key: FeatureFlag
    kind: FlagKind
    description: str
    default: bool
    scope: FlagScope
    bead: str | None = None
    rationale: str = ""

    def validate(self) -> None:
        """Validate registry invariants for this definition."""
        key = str(self.key)
        if not is_feature_flag_key(key):
            raise FeatureFlagError(f"feature flag key must be snake_case: {key!r}")
        if self.kind == "ops":
            if not self.rationale.strip():
                raise FeatureFlagError(
                    f"ops feature flag {key!r} must include a rationale"
                )
        elif self.bead is None:
            raise FeatureFlagError(
                f"{self.kind} feature flag {key!r} must reference its flag bead"
            )
        if type(self.default) is not bool:
            raise FeatureFlagError(f"feature flag {key!r} default must be boolean")


@dataclass(frozen=True)
class FeatureFlagDecision:
    """The resolved value and provenance for one flag."""

    key: str
    enabled: bool
    default: bool
    source: FlagSource
    source_detail: str
    overridden: bool


@dataclass(frozen=True)
class FeatureFlagDiagnostic:
    """A non-fatal or fatal feature-flag diagnostic."""

    severity: Literal["warning", "error"]
    code: str
    message: str
    source: str


@dataclass(frozen=True)
class FeatureFlagSnapshot:
    """Immutable per-process feature-flag decisions."""

    decisions: Mapping[str, FeatureFlagDecision]
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Freeze mapping inputs so callers cannot mutate a snapshot."""
        object.__setattr__(self, "decisions", MappingProxyType(dict(self.decisions)))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def enabled(self, key: object) -> bool:
        """Return whether *key* is enabled, raising for unregistered keys."""
        return self.decision(key).enabled

    def decision(self, key: object) -> FeatureFlagDecision:
        """Return the full decision for *key*, raising for unregistered keys."""
        key_text = str(key)
        try:
            return self.decisions[key_text]
        except KeyError as exc:
            raise FeatureFlagError(f"unknown feature flag: {key_text}") from exc

    def non_default(self) -> tuple[FeatureFlagDecision, ...]:
        """Return decisions supplied by a layer above the registry default."""
        return tuple(
            self.decisions[key]
            for key in sorted(self.decisions)
            if self.decisions[key].overridden
        )


__all__ = [
    "FeatureFlagDecision",
    "FeatureFlagDefinition",
    "FeatureFlagDiagnostic",
    "FeatureFlagEnvError",
    "FeatureFlagError",
    "FeatureFlagSnapshot",
    "FlagKind",
    "FlagScope",
    "FlagSource",
    "is_feature_flag_key",
]
