"""Typed accessors for the ``goals:`` config block.

Every accessor fails open to its documented default so a broken or missing
config never breaks goal reads or writes; validation reports problems
instead of raising.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

GoalsVisibility = Literal["shared", "local"]

DEFAULT_VISIBILITY: GoalsVisibility = "shared"
DEFAULT_HOST_ROLE = "beads"
DEFAULT_FETCH_TTL_SECONDS = 60.0
DEFAULT_PUSH_TIMEOUT_SECONDS = 20.0


def goals_config() -> Mapping[str, Any]:
    """Return the raw ``goals:`` config mapping, or ``{}`` when unreadable."""
    try:
        from sase.config import load_merged_config

        raw = load_merged_config().get("goals", {})
    except Exception:
        return {}
    return raw if isinstance(raw, Mapping) else {}


def goals_visibility() -> GoalsVisibility:
    """Return the configured ledger visibility (``shared`` or ``local``)."""
    raw = goals_config().get("visibility", DEFAULT_VISIBILITY)
    return raw if raw in ("shared", "local") else DEFAULT_VISIBILITY


def goals_host_role() -> str:
    """Return the sidecar role whose repository hosts ``goals/``."""
    raw = goals_config().get("host_role", DEFAULT_HOST_ROLE)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return DEFAULT_HOST_ROLE


def goals_fetch_ttl_seconds() -> float:
    """Return the background freshness-fetch TTL for ``sase goal list``."""
    try:
        value = float(
            goals_config().get("fetch_ttl_seconds", DEFAULT_FETCH_TTL_SECONDS)
        )
    except (TypeError, ValueError):
        return DEFAULT_FETCH_TTL_SECONDS
    return max(0.0, value)


def goals_push_timeout_seconds() -> float:
    """Return the bound on synchronous publish for goal writes."""
    try:
        value = float(
            goals_config().get("push_timeout_seconds", DEFAULT_PUSH_TIMEOUT_SECONDS)
        )
    except (TypeError, ValueError):
        return DEFAULT_PUSH_TIMEOUT_SECONDS
    return max(0.0, value)


def validate_goals_config(raw: Mapping[str, Any] | None) -> list[str]:
    """Return human-readable problems with a ``goals:`` mapping."""
    problems: list[str] = []
    if raw is None:
        return problems
    if not isinstance(raw, Mapping):
        return ["goals: must be a mapping"]
    visibility = raw.get("visibility", DEFAULT_VISIBILITY)
    if visibility not in ("shared", "local"):
        problems.append(
            f"goals.visibility must be 'shared' or 'local', got {visibility!r}"
        )
    host_role = raw.get("host_role", DEFAULT_HOST_ROLE)
    if not isinstance(host_role, str) or not host_role.strip():
        problems.append("goals.host_role must be a non-empty sidecar role name")
    for key in ("fetch_ttl_seconds", "push_timeout_seconds"):
        try:
            value = float(raw.get(key, 0.0))
        except (TypeError, ValueError):
            problems.append(f"goals.{key} must be a number")
            continue
        if value < 0:
            problems.append(f"goals.{key} must be >= 0")
    return problems
