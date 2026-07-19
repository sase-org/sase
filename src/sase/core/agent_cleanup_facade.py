"""Facade for pure agent-cleanup planning.

The public planner calls ``sase_core_rs.plan_agent_cleanup`` when the binding
is available and falls back to the Python reference planner only when the
extension or binding is temporarily missing. The fallback keeps tests and
older editable installs usable during the staged cleanup-panel migration; it
does not perform side effects.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sase.core.agent_cleanup_python import (
    coerce_cleanup_request,
    coerce_cleanup_target,
    plan_agent_cleanup_python,
)
from sase.core.agent_cleanup_targets import (
    agent_to_cleanup_target,
    agents_to_cleanup_targets,
    is_workflow_child,
)
from sase.core.agent_cleanup_wire import (
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
    AgentCleanupTargetWire,
    agent_cleanup_wire_to_json_dict,
    cleanup_plan_from_dict,
)
from sase.core.rust import require_rust_binding

_plan_agent_cleanup_python = plan_agent_cleanup_python


def plan_agent_cleanup(
    targets: Sequence[AgentCleanupTargetWire | dict[str, Any]],
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupPlanWire:
    """Plan cleanup through Rust, falling back only for missing/stale bindings."""

    wire_targets = [coerce_cleanup_target(target) for target in targets]
    wire_request = coerce_cleanup_request(request)
    try:
        binding = require_rust_binding("plan_agent_cleanup")
    except (ImportError, AttributeError):
        return plan_agent_cleanup_python(wire_targets, wire_request)

    payload: dict[str, Any] = binding(
        agent_cleanup_wire_to_json_dict(wire_targets),
        agent_cleanup_wire_to_json_dict(wire_request),
    )
    plan = cleanup_plan_from_dict(payload)
    dismiss_by_identity = {
        item.identity: item for item in wire_targets if item.raw_suffix is not None
    }
    expected_timestamp_releases = {
        dismiss.identity
        for dismiss in plan.dismiss_items
        if (target := dismiss_by_identity.get(dismiss.identity)) is not None
        and target.agent_type in {"run", "workflow"}
        and not is_workflow_child(target)
    }
    actual_timestamp_releases = {
        intent.identity
        for intent in plan.side_effects.workspace_release_requests
        if intent.lookup_timestamp
    }
    if not expected_timestamp_releases.issubset(actual_timestamp_releases):
        return plan_agent_cleanup_python(wire_targets, wire_request)
    if (plan.kill_items or plan.dismiss_items) and not any(
        getattr(plan.side_effects, attr)
        for attr in (
            "dismissed_index_additions",
            "bundle_save_candidates",
            "artifact_delete_paths",
            "workspace_release_requests",
            "notification_dismiss_candidates",
        )
    ):
        return plan_agent_cleanup_python(wire_targets, wire_request)
    return plan


__all__ = [
    "agent_to_cleanup_target",
    "agents_to_cleanup_targets",
    "plan_agent_cleanup",
]
