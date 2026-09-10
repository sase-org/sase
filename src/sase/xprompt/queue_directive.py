"""Thin Python adapter for the shared Rust `%queue` / `%q` contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding


def collect_queue_fields(
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and merge queue occurrences through the Rust contract."""
    payload = require_rust_binding("collect_queue_fields")(list(occurrences))
    if not isinstance(payload, dict):
        return {"fields": None, "errors": []}
    return dict(payload)


def format_queue_directive(
    *,
    runners: int | None = None,
    priority: int | None = None,
    weight: float | None = None,
) -> str | None:
    """Return canonical `%queue(...)`, omitting absent fields."""
    payload: dict[str, int | float | None] = {
        "runners": runners,
        "priority": priority,
    }
    if weight is not None:
        payload["weight"] = weight
    formatted = require_rust_binding("format_queue_directive")(payload)
    return str(formatted) if formatted else None


def launch_feature_flag_keys() -> list[str]:
    """Return currently enabled launch/editor flags for Rust entry points."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.xprompt.code_value import typed_launch_units_enabled

    flags: list[str] = []
    if typed_launch_units_enabled():
        flags.append(str(FeatureFlag.typed_launch_units))
    return flags
