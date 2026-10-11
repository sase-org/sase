"""Rust-backed Git index-lock recovery policy facade.

The Rust core classifies failures, lock-path eligibility, owner association,
and stop/retry/remove decisions. Python owns subprocesses, filesystem
snapshots, process probes, waiting, and unlinking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.git_lock_wire import (
    GIT_LOCK_WIRE_SCHEMA_VERSION,
    require_git_lock_schema,
)
from sase.core.rust import require_rust_binding


def git_lock_wire_schema_version() -> int:
    """Return the installed core's git-lock wire schema version."""
    binding = require_rust_binding("git_lock_wire_schema_version")
    return int(binding())


def _require_wire_schema() -> None:
    version = git_lock_wire_schema_version()
    if version != GIT_LOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs git-lock wire is stale: expected "
            f"{GIT_LOCK_WIRE_SCHEMA_VERSION}, got {version}"
        )


def default_git_lock_retry_delays() -> tuple[float, ...]:
    """Return the built-in six-delay backoff schedule."""
    _require_wire_schema()
    binding = require_rust_binding("default_git_lock_retry_delays")
    return tuple(float(delay) for delay in binding())


def parse_git_lock_retry_delays(raw: str | None) -> tuple[float, ...]:
    """Parse an environment override, falling back to the built-in schedule."""
    _require_wire_schema()
    binding = require_rust_binding("parse_git_lock_retry_delays")
    return tuple(float(delay) for delay in binding(raw))


def validate_git_lock_retry_delays(delays: Sequence[float]) -> tuple[float, ...]:
    """Validate an explicit caller-supplied schedule."""
    _require_wire_schema()
    binding = require_rust_binding("validate_git_lock_retry_delays")
    return tuple(float(delay) for delay in binding(list(delays)))


def classify_git_lock_failure(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one observed Git failure through ``sase_core_rs``."""
    _require_wire_schema()
    binding = require_rust_binding("classify_git_lock_failure")
    raw = binding(dict(observation))
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned an invalid git-lock classification")
    require_git_lock_schema(raw, what="classification")
    return raw


def match_git_lock_path(request: Mapping[str, Any]) -> dict[str, Any]:
    """Match an error path against the independently resolved index lock."""
    _require_wire_schema()
    payload = dict(request)
    payload["schema_version"] = GIT_LOCK_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("match_git_lock_path")
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned an invalid git-lock path match")
    require_git_lock_schema(raw, what="path match")
    return raw


def classify_git_lock_owner(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Classify collected process facts as active, absent, or unknown."""
    _require_wire_schema()
    payload = dict(facts)
    payload["schema_version"] = GIT_LOCK_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("classify_git_lock_owner")
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError(
            "sase_core_rs returned an invalid git-lock owner observation"
        )
    require_git_lock_schema(raw, what="owner observation")
    return raw


def decide_git_lock_recovery(request: Mapping[str, Any]) -> dict[str, Any]:
    """Decide the next recovery action from classified observations."""
    _require_wire_schema()
    payload = dict(request)
    payload["schema_version"] = GIT_LOCK_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("decide_git_lock_recovery")
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError(
            "sase_core_rs returned an invalid git-lock recovery decision"
        )
    require_git_lock_schema(raw, what="recovery decision")
    return raw


def decide_eager_git_lock_cleanup(request: Mapping[str, Any]) -> dict[str, Any]:
    """Decide whether an eager pre-command cleanup may remove a lock."""
    _require_wire_schema()
    payload = dict(request)
    payload["schema_version"] = GIT_LOCK_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("decide_eager_git_lock_cleanup")
    raw = binding(payload)
    if not isinstance(raw, dict):
        raise RuntimeError("sase_core_rs returned an invalid git-lock cleanup decision")
    require_git_lock_schema(raw, what="cleanup decision")
    return raw


__all__ = [
    "classify_git_lock_failure",
    "classify_git_lock_owner",
    "decide_eager_git_lock_cleanup",
    "decide_git_lock_recovery",
    "default_git_lock_retry_delays",
    "git_lock_wire_schema_version",
    "match_git_lock_path",
    "parse_git_lock_retry_delays",
    "validate_git_lock_retry_delays",
]
