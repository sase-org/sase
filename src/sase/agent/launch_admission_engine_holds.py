"""Proc hold checks for launch admission."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sase.agent.launch_admission_engine_helpers import finite_float
from sase.core.agent_launch_wire import LaunchPlanWire, LaunchUnitWire, ProcUnitWire

LOGGER = logging.getLogger(__name__)


def proc_hold_blocks(
    plan: LaunchPlanWire,
    states: Mapping[str, Mapping[str, Any]],
    *,
    now_seconds: float,
) -> list[dict[str, Any]]:
    """Return active hold blocks for pre-dispatch proc units.

    Holds fail open on the admission path: a broken store or predicate must not
    strand a proc that has no separate runner-slot marker to inspect.
    """
    proc_units = [
        unit
        for unit in plan.units
        if isinstance(unit.payload, ProcUnitWire)
        and str((states.get(unit.logical_id) or {}).get("phase") or "")
        in {"waiting", "eligible"}
    ]
    if not proc_units:
        return []
    now_dt = datetime.fromtimestamp(now_seconds, UTC)
    try:
        from sase.core.agent_hold_facade import (
            active_agent_hold_records,
            agent_hold_blocks_candidate,
        )

        active_holds = active_agent_hold_records(now=now_dt)
        if not active_holds:
            return []
        blocks: list[dict[str, Any]] = []
        for unit in proc_units:
            candidate = _proc_hold_candidate(
                plan,
                unit,
                states.get(unit.logical_id) or {},
                now_seconds=now_seconds,
            )
            for hold in active_holds:
                block = agent_hold_blocks_candidate(hold, candidate)
                if block is not None:
                    blocks.append({"logical_id": unit.logical_id, "block": block})
        return blocks
    except Exception as exc:  # noqa: BLE001 - holds fail open by design.
        LOGGER.warning("proc hold admission failed open: %s", exc)
        return []


def _proc_hold_candidate(
    plan: LaunchPlanWire,
    unit: LaunchUnitWire,
    state: Mapping[str, Any],
    *,
    now_seconds: float,
) -> dict[str, Any]:
    payload = unit.payload
    candidate: dict[str, Any] = {
        "project": _proc_hold_project(plan, payload),
        "created_at": finite_float(state.get("first_recorded_at_unix")) or now_seconds,
        "artifact_dirs": [],
    }
    if isinstance(payload, ProcUnitWire) and payload.shell_name:
        candidate["proc_shell"] = payload.shell_name
    return candidate


def _proc_hold_project(plan: LaunchPlanWire, payload: object) -> str:
    if isinstance(payload, ProcUnitWire) and payload.selected_project:
        return payload.selected_project
    if plan.selected_project:
        return plan.selected_project
    try:
        from sase.bead.project_name import infer_project_name_from_cwd

        project = infer_project_name_from_cwd()
        if project:
            return project
    except Exception:  # noqa: BLE001 - host-scoped holds can still match.
        pass
    return "unknown"


__all__ = ["proc_hold_blocks"]
