"""Rust-backed temporary maximum-running-agents override facade."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

RUNNER_LIMIT_OVERRIDE_WIRE_SCHEMA_VERSION = 1


class RunnerLimitOverrideStateError(RuntimeError):
    """Raised when runner-limit override state cannot be safely consumed."""


@dataclass(frozen=True)
class TemporaryRunnerLimitOverride:
    """One active machine-wide runner-capacity override."""

    version: int
    limit: int
    created_at: float
    expires_at: float | None
    source: str

    @classmethod
    def from_wire(cls, payload: object) -> TemporaryRunnerLimitOverride:
        """Strictly rehydrate the stable Rust wire record."""
        if not isinstance(payload, dict):
            raise RunnerLimitOverrideStateError(
                "runner-limit override record is not an object"
            )
        required = {"version", "limit", "created_at", "expires_at", "source"}
        if set(payload) != required:
            missing = sorted(required - set(payload))
            extra = sorted(set(payload) - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"unknown {', '.join(extra)}")
            raise RunnerLimitOverrideStateError(
                "invalid runner-limit override fields: " + "; ".join(details)
            )

        version = payload["version"]
        limit = payload["limit"]
        created_at = payload["created_at"]
        expires_at = payload["expires_at"]
        source = payload["source"]
        if (
            type(version) is not int
            or version != RUNNER_LIMIT_OVERRIDE_WIRE_SCHEMA_VERSION
        ):
            raise RunnerLimitOverrideStateError(
                f"unsupported runner-limit override wire version: {version!r}"
            )
        if type(limit) is not int or limit < 1:
            raise RunnerLimitOverrideStateError(
                f"runner limit must be a positive integer: {limit!r}"
            )
        if not _is_finite_number(created_at) or float(created_at) <= 0.0:
            raise RunnerLimitOverrideStateError(
                "created_at must be a finite positive number"
            )
        if expires_at is not None and not _is_finite_number(expires_at):
            raise RunnerLimitOverrideStateError(
                "expires_at must be a finite number or null"
            )
        if expires_at is not None and float(expires_at) <= float(created_at):
            raise RunnerLimitOverrideStateError(
                "expires_at must be later than created_at"
            )
        if not isinstance(source, str) or not source.strip():
            raise RunnerLimitOverrideStateError("source must be a non-empty string")
        return cls(
            version=version,
            limit=limit,
            created_at=float(created_at),
            expires_at=float(expires_at) if expires_at is not None else None,
            source=source,
        )

    def is_active(self, now: float) -> bool:
        """Return whether this captured record is still active at *now*."""
        return self.expires_at is None or now < self.expires_at


@dataclass(frozen=True)
class EffectiveRunnerLimitSnapshot:
    """Configured and temporary runner-limit state captured together."""

    configured_limit: int
    temporary_override: TemporaryRunnerLimitOverride | None
    captured_at: float

    def active_override(self, now: float) -> TemporaryRunnerLimitOverride | None:
        override = self.temporary_override
        if override is None or not override.is_active(now):
            return None
        return override

    def effective_limit(self, now: float) -> int:
        override = self.active_override(now)
        return override.limit if override is not None else self.configured_limit


def _is_finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _validate_limit(limit: object) -> int:
    if type(limit) is not int or limit < 1:
        raise ValueError("runner limit must be a positive integer")
    return limit


def get_active_runner_limit_override(
    now: float | None = None,
) -> TemporaryRunnerLimitOverride | None:
    """Return the active runner-limit override, self-cleaning stale state."""
    binding = require_rust_binding("runner_limit_override_get")
    payload: Any = binding(str(sase_home()), now)
    if payload is None:
        return None
    return TemporaryRunnerLimitOverride.from_wire(payload)


def set_runner_limit_override(
    limit: int,
    duration_seconds: float | None,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryRunnerLimitOverride:
    """Set or replace a relative/until-cleared runner-limit override."""
    validated = _validate_limit(limit)
    binding = require_rust_binding("runner_limit_override_set_relative")
    payload: Any = binding(str(sase_home()), validated, source, duration_seconds, now)
    return TemporaryRunnerLimitOverride.from_wire(payload)


def set_runner_limit_override_until(
    limit: int,
    expires_at: float,
    *,
    source: str,
    now: float | None = None,
) -> TemporaryRunnerLimitOverride:
    """Set or replace a runner-limit override until an exact timestamp."""
    validated = _validate_limit(limit)
    binding = require_rust_binding("runner_limit_override_set_until")
    payload: Any = binding(str(sase_home()), validated, expires_at, source, now)
    return TemporaryRunnerLimitOverride.from_wire(payload)


def clear_runner_limit_override() -> bool:
    """Idempotently clear the machine-wide runner-limit override."""
    binding = require_rust_binding("runner_limit_override_clear")
    return bool(binding(str(sase_home())))


__all__ = [
    "RUNNER_LIMIT_OVERRIDE_WIRE_SCHEMA_VERSION",
    "EffectiveRunnerLimitSnapshot",
    "RunnerLimitOverrideStateError",
    "TemporaryRunnerLimitOverride",
    "clear_runner_limit_override",
    "get_active_runner_limit_override",
    "set_runner_limit_override",
    "set_runner_limit_override_until",
]
