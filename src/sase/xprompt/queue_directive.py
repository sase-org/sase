"""Thin Python adapter for the shared Rust `%queue` / `%q` contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding
from sase.xprompt._exceptions import DirectiveError


WEIGHTED_QUEUE_CAPACITY_DISABLED_MESSAGE = (
    "The %queue weight arguments require the weighted_queue_capacity beta flag. "
    "Enable it with `sase flag enable weighted_queue_capacity`. Existing "
    "unweighted runner-slot behavior is unchanged while the flag is disabled."
)
_QUEUE_WEIGHT_KEYS = {"w", "weight"}


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


def _weighted_queue_capacity_enabled() -> bool:
    """Return the process-local `weighted_queue_capacity` decision."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags

    return current_flags().enabled(FeatureFlag.weighted_queue_capacity)


def _queue_occurrence_includes_weight(occurrence: Mapping[str, Any]) -> bool:
    """Return whether a raw `%queue` occurrence mentions `w=` or `weight=`."""
    args = occurrence.get("args")
    if not isinstance(args, Sequence) or isinstance(args, (str, bytes)):
        return False
    for arg in args:
        if isinstance(arg, Mapping) and arg.get("name") in _QUEUE_WEIGHT_KEYS:
            return True
    return False


def reject_queue_weight_when_disabled(
    occurrences: Sequence[Mapping[str, Any]],
) -> None:
    """Reject `%queue` weight arguments until the beta flag is enabled."""
    if _weighted_queue_capacity_enabled():
        return
    if any(_queue_occurrence_includes_weight(occurrence) for occurrence in occurrences):
        raise DirectiveError(WEIGHTED_QUEUE_CAPACITY_DISABLED_MESSAGE)


def launch_feature_flag_keys() -> list[str]:
    """Return currently enabled launch/editor flags for Rust entry points."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.xprompt.code_value import typed_launch_units_enabled

    flags: list[str] = []
    if typed_launch_units_enabled():
        flags.append(str(FeatureFlag.typed_launch_units))
    if _weighted_queue_capacity_enabled():
        flags.append(str(FeatureFlag.weighted_queue_capacity))
    return flags
