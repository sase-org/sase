"""Typed feature-flag model objects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sase.feature_flags.registry import FeatureFlag


FlagKind = Literal["beta", "sunset"]
FlagSource = Literal[
    "default", "user", "overlay", "local", "state", "override", "env", "cli"
]

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def is_feature_flag_key(value: str) -> bool:
    """Return whether *value* is a non-empty snake_case flag key."""
    return bool(_SNAKE_CASE_RE.fullmatch(value))


class FeatureFlagError(Exception):
    """Base error for feature-flag resolution failures."""


class FeatureFlagEnvError(FeatureFlagError):
    """Raised when ``SASE_FEATURE_FLAGS`` is malformed."""


class FeatureFlagStateError(FeatureFlagError):
    """Raised when the machine-local feature-flag store cannot be used."""

    def __init__(self, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True)
class FeatureFlagDefinition:
    """A single code-owned feature flag definition."""

    key: FeatureFlag
    kind: FlagKind
    description: str
    bead: str | None = None

    @property
    def default(self) -> bool:
        """Return the kind-derived default: a sunset flag defaults on."""
        return self.kind == "sunset"

    def validate(self) -> None:
        """Validate registry invariants for this definition."""
        key = str(self.key)
        if not is_feature_flag_key(key):
            raise FeatureFlagError(f"feature flag key must be snake_case: {key!r}")
        if self.bead is None:
            raise FeatureFlagError(
                f"{self.kind} feature flag {key!r} must reference its flag bead"
            )


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
    saved: Mapping[str, bool] = field(default_factory=dict)
    state_path: str = ""

    def __post_init__(self) -> None:
        """Freeze mapping inputs so callers cannot mutate a snapshot."""
        object.__setattr__(self, "decisions", MappingProxyType(dict(self.decisions)))
        object.__setattr__(self, "saved", MappingProxyType(dict(self.saved)))
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


@dataclass(frozen=True)
class FeatureFlagMutationOutcome:
    """Structured result of one saved-preference mutation."""

    key: str
    enabled: bool
    previous_saved: bool | None
    changed: bool
    before: FeatureFlagDecision
    after: FeatureFlagDecision
    shadowed: bool
    shadowing_source: FlagSource | None
    state_path: str
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        """Freeze diagnostic inputs so callers cannot mutate an outcome."""
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


__all__ = [
    "FeatureFlagDecision",
    "FeatureFlagDefinition",
    "FeatureFlagDiagnostic",
    "FeatureFlagEnvError",
    "FeatureFlagError",
    "FeatureFlagMutationOutcome",
    "FeatureFlagSnapshot",
    "FeatureFlagStateError",
    "FlagKind",
    "FlagSource",
    "is_feature_flag_key",
]
