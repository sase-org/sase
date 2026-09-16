"""Small helpers for the launch-admission engine."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchPlanWire, LaunchUnitWire


def unit_by_logical_id(plan: LaunchPlanWire, logical_id: str) -> LaunchUnitWire:
    for unit in plan.units:
        if unit.logical_id == logical_id:
            return unit
    raise LaunchRequestError(
        "invalid_request",
        logical_id,
        f"typed launch plan has no unit {logical_id}",
    )


def unpack_agent_dispatch(
    result: Any,
) -> tuple[bool, str | None, str | None, list[AgentLaunchResult], dict[str, Any]]:
    if not isinstance(result, tuple) or len(result) < 4:
        raise LaunchRequestError(
            "invalid_request",
            "dispatch",
            "agent dispatcher returned an invalid result",
        )
    ok, identity, message, spawned = result[0], result[1], result[2], result[3]
    extra = (
        dict(result[4]) if len(result) > 4 and isinstance(result[4], Mapping) else {}
    )
    return bool(ok), identity, message, list(spawned or []), extra


def finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def all_terminal(plan: LaunchPlanWire, states: Mapping[str, Mapping[str, Any]]) -> bool:
    terminal = {
        "launched",
        "skipped",
        "condition_error",
        "launch_error",
        "cancelled",
    }
    return all(
        str((states.get(unit.logical_id) or {}).get("phase") or "") in terminal
        for unit in plan.units
    )


__all__ = [
    "all_terminal",
    "finite_float",
    "unit_by_logical_id",
    "unpack_agent_dispatch",
]
