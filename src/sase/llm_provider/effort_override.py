"""Rust-backed temporary default reasoning-effort override facade."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.xprompt.effort import is_valid_effort

EFFORT_OVERRIDE_WIRE_SCHEMA_VERSION = 1


class EffortOverrideStateError(RuntimeError):
    """Raised when the Rust binding returns an invalid effort-state record."""


@dataclass(frozen=True)
class TemporaryEffortOverride:
    """One active machine-wide default-effort override."""

    version: int
    effort: str
    created_at: float
    expires_at: float | None
    source: str

    @classmethod
    def from_wire(cls, payload: object) -> TemporaryEffortOverride:
        """Strictly rehydrate the stable Rust wire record."""
        if not isinstance(payload, dict):
            raise EffortOverrideStateError("effort override record is not an object")
        required = {"version", "effort", "created_at", "expires_at", "source"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            detail: list[str] = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if extra:
                detail.append(f"unknown {', '.join(extra)}")
            raise EffortOverrideStateError(
                "invalid effort override fields: " + "; ".join(detail)
            )

        version = payload["version"]
        effort = payload["effort"]
        created_at = payload["created_at"]
        expires_at = payload["expires_at"]
        source = payload["source"]
        if type(version) is not int or version != EFFORT_OVERRIDE_WIRE_SCHEMA_VERSION:
            raise EffortOverrideStateError(
                f"unsupported effort override wire version: {version!r}"
            )
        if not isinstance(effort, str) or not is_valid_effort(effort):
            raise EffortOverrideStateError(f"invalid effort override level: {effort!r}")
        if not _is_finite_number(created_at):
            raise EffortOverrideStateError("created_at must be a finite number")
        if expires_at is not None and not _is_finite_number(expires_at):
            raise EffortOverrideStateError("expires_at must be a finite number or null")
        if not isinstance(source, str) or not source.strip():
            raise EffortOverrideStateError("source must be a non-empty string")
        return cls(
            version=version,
            effort=effort,
            created_at=float(created_at),
            expires_at=float(expires_at) if expires_at is not None else None,
            source=source,
        )

    def is_active(self, now: float) -> bool:
        """Return whether this captured record is still active at *now*."""
        return self.expires_at is None or now < self.expires_at


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def get_active_effort_override(
    now: float | None = None,
) -> TemporaryEffortOverride | None:
    """Return the active default-effort override, self-cleaning stale state."""
    binding = require_rust_binding("effort_override_get")
    payload: Any = binding(str(sase_home()), now)
    if payload is None:
        return None
    return TemporaryEffortOverride.from_wire(payload)


def set_effort_override(
    effort: str,
    duration_seconds: float | None,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryEffortOverride:
    """Set or replace a relative/until-cleared effort override."""
    binding = require_rust_binding("effort_override_set_relative")
    payload: Any = binding(
        str(sase_home()),
        effort,
        source,
        duration_seconds,
        now,
    )
    return TemporaryEffortOverride.from_wire(payload)


def set_effort_override_until(
    effort: str,
    expires_at: float,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryEffortOverride:
    """Set or replace an effort override until an exact timestamp."""
    binding = require_rust_binding("effort_override_set_until")
    payload: Any = binding(
        str(sase_home()),
        effort,
        expires_at,
        source,
        now,
    )
    return TemporaryEffortOverride.from_wire(payload)


def clear_effort_override() -> bool:
    """Idempotently clear the machine-wide default-effort override."""
    binding = require_rust_binding("effort_override_clear")
    return bool(binding(str(sase_home())))


__all__ = [
    "EFFORT_OVERRIDE_WIRE_SCHEMA_VERSION",
    "EffortOverrideStateError",
    "TemporaryEffortOverride",
    "clear_effort_override",
    "get_active_effort_override",
    "set_effort_override",
    "set_effort_override_until",
]
