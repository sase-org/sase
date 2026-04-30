"""Facade for pure agent-cleanup planning.

The public planner calls ``sase_core_rs.plan_agent_cleanup`` when the binding
is available and falls back to the Python reference planner only when the
extension or binding is temporarily missing. The fallback keeps tests and
older editable installs usable during the staged cleanup-panel migration; it
does not perform side effects.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_MODE_PREVIEW_ONLY,
    CLEANUP_SCOPE_ALL_PANELS,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_GROUP,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TAG,
    CONFIRMATION_SEVERITY_DESTRUCTIVE,
    CONFIRMATION_SEVERITY_DISMISS,
    CONFIRMATION_SEVERITY_NONE,
    DISMISSABLE_STATUSES,
    KILL_KIND_CRS,
    KILL_KIND_HOOK,
    KILL_KIND_MENTOR,
    KILL_KIND_RUNNING,
    KILL_KIND_WORKFLOW,
    SKIPPED_DUPLICATE,
    SKIPPED_NOT_DISMISSABLE,
    SKIPPED_NOT_IN_SCOPE,
    SKIPPED_NOT_KILLABLE,
    SKIPPED_UNKNOWN_KILL_KIND,
    SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY,
    AgentCleanupCountsWire,
    AgentCleanupDismissItemWire,
    AgentCleanupIdentityWire,
    AgentCleanupKillItemWire,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
    AgentCleanupSkippedItemWire,
    AgentCleanupTargetWire,
    agent_cleanup_wire_to_json_dict,
    cleanup_plan_from_dict,
    cleanup_request_from_dict,
    cleanup_target_from_dict,
)
from sase.core.rust import require_rust_binding


def _as_target(target: AgentCleanupTargetWire | dict[str, Any]) -> AgentCleanupTargetWire:
    if isinstance(target, AgentCleanupTargetWire):
        return target
    return cleanup_target_from_dict(target)


def _as_request(
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupRequestWire:
    if isinstance(request, AgentCleanupRequestWire):
        return request
    return cleanup_request_from_dict(request)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


# pyvision: tests/test_core_facade/test_agent_cleanup.py
def agent_to_cleanup_target(agent: Any) -> AgentCleanupTargetWire:
    """Convert a TUI ``Agent`` object into cleanup planner wire data."""

    agent_type_value = getattr(agent.agent_type, "value", agent.agent_type)
    raw_suffix = agent.raw_suffix
    artifacts_dir = agent.artifacts_dir
    if artifacts_dir is None:
        get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
        if callable(get_artifacts_dir):
            artifacts_dir = get_artifacts_dir()
    return AgentCleanupTargetWire(
        identity=AgentCleanupIdentityWire(
            agent_type=str(agent_type_value),
            cl_name=str(agent.cl_name),
            raw_suffix=raw_suffix,
        ),
        agent_type=str(agent_type_value),
        status=str(agent.status),
        pid=agent.pid,
        workflow=agent.workflow,
        parent_workflow=agent.parent_workflow,
        parent_timestamp=agent.parent_timestamp,
        raw_suffix=raw_suffix,
        project_file=agent.project_file,
        artifacts_dir=artifacts_dir,
        workspace=agent.effective_workspace_num,
        tag=agent.tag,
        agent_name=agent.agent_name,
        display_name=agent.display_name,
        start_time=_iso_or_none(agent.start_time),
        stop_time=_iso_or_none(agent.stop_time),
        is_workflow_child=agent.is_workflow_child,
        appears_as_agent=agent.appears_as_agent,
        step_type=agent.step_type,
    )


# pyvision: tests/test_core_facade/test_agent_cleanup.py
def agents_to_cleanup_targets(agents: Iterable[Any]) -> tuple[AgentCleanupTargetWire, ...]:
    """Convert an iterable of TUI ``Agent`` objects to cleanup target wires."""

    return tuple(agent_to_cleanup_target(agent) for agent in agents)


def _is_workflow_child(target: AgentCleanupTargetWire) -> bool:
    return (
        target.is_workflow_child
        or target.parent_workflow is not None
        or target.parent_timestamp is not None
    )


def _effective_tag(
    target: AgentCleanupTargetWire,
    parent_tags: dict[str, str | None],
) -> str | None:
    if _is_workflow_child(target) and target.parent_timestamp is not None:
        if target.parent_timestamp in parent_tags:
            return parent_tags[target.parent_timestamp]
    return target.tag


def _selected_by_scope(
    target: AgentCleanupTargetWire,
    request: AgentCleanupRequestWire,
    selected_ids: set[AgentCleanupIdentityWire],
    parent_tags: dict[str, str | None],
) -> bool:
    if request.scope == CLEANUP_SCOPE_ALL_PANELS:
        return True
    if request.scope == CLEANUP_SCOPE_FOCUSED_PANEL:
        return _effective_tag(target, parent_tags) == request.focused_panel_tag
    if request.scope == CLEANUP_SCOPE_TAG:
        return _effective_tag(target, parent_tags) == request.tag
    if request.scope in {
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        CLEANUP_SCOPE_FOCUSED_GROUP,
        CLEANUP_SCOPE_CUSTOM_SELECTION,
    }:
        return target.identity in selected_ids
    return False


def _classify_kill_kind(target: AgentCleanupTargetWire) -> str | None:
    workflow = target.workflow or ""
    if target.agent_type == "workflow":
        return KILL_KIND_WORKFLOW
    if workflow.startswith("axe(fix-hook)") or workflow in {
        "fix-hook",
        "summarize-hook",
    }:
        return KILL_KIND_HOOK
    if (
        workflow.startswith("axe(mentor)")
        or workflow.startswith("mentor(")
        or workflow == "mentor"
    ):
        return KILL_KIND_MENTOR
    if workflow.startswith("axe(crs)") or workflow == "crs":
        return KILL_KIND_CRS
    if target.agent_type == "run":
        return KILL_KIND_RUNNING
    return None


def _add_skip(
    skipped_items: list[AgentCleanupSkippedItemWire],
    target: AgentCleanupTargetWire,
    reason: str,
    detail: str | None = None,
) -> None:
    skipped_items.append(
        AgentCleanupSkippedItemWire(
            identity=target.identity,
            reason=reason,
            detail=detail,
        )
    )


def _push_summary_line(lines: list[str], count: int, noun: str) -> None:
    if count == 0:
        return
    suffix = "" if count == 1 else "s"
    lines.append(f"{count} {noun}{suffix}")


# pyvision: tests/test_core_facade/test_agent_cleanup.py
def plan_agent_cleanup_python(
    targets: Sequence[AgentCleanupTargetWire | dict[str, Any]],
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupPlanWire:
    """Reference Python implementation of the pure cleanup planner."""

    wire_targets = [_as_target(target) for target in targets]
    wire_request = _as_request(request)
    if wire_request.schema_version != AGENT_CLEANUP_WIRE_SCHEMA_VERSION:
        raise ValueError(
            "agent cleanup wire schema mismatch: "
            f"got {wire_request.schema_version}, "
            f"expected {AGENT_CLEANUP_WIRE_SCHEMA_VERSION}"
        )
    if wire_request.mode not in {
        CLEANUP_MODE_DISMISS_COMPLETED,
        CLEANUP_MODE_KILL_AND_DISMISS,
        CLEANUP_MODE_PREVIEW_ONLY,
    }:
        raise ValueError(f"unknown agent cleanup mode: {wire_request.mode}")

    selected_ids = set(wire_request.identities)
    parent_tags = {
        target.raw_suffix: target.tag
        for target in wire_targets
        if not _is_workflow_child(target) and target.raw_suffix is not None
    }
    children_by_parent: dict[
        tuple[str, str | None], list[AgentCleanupTargetWire]
    ] = defaultdict(list)
    for target in wire_targets:
        if _is_workflow_child(target) and target.parent_timestamp is not None:
            children_by_parent[
                (target.parent_timestamp, target.parent_workflow)
            ].append(target)

    seen_live: set[AgentCleanupIdentityWire] = set()
    selected: list[AgentCleanupIdentityWire] = []
    kill_items: list[AgentCleanupKillItemWire] = []
    dismiss_items: list[AgentCleanupDismissItemWire] = []
    cascaded_children: list[AgentCleanupIdentityWire] = []
    skipped_items: list[AgentCleanupSkippedItemWire] = []

    running = completed = failed = 0

    for target in wire_targets:
        dismissable_status = target.status in DISMISSABLE_STATUSES
        if target.status == "FAILED":
            failed += 1
        if dismissable_status:
            completed += 1
        if target.pid is not None and not dismissable_status:
            running += 1

        if not _selected_by_scope(target, wire_request, selected_ids, parent_tags):
            _add_skip(skipped_items, target, SKIPPED_NOT_IN_SCOPE)
            continue

        if _is_workflow_child(target):
            _add_skip(skipped_items, target, SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY)
            continue

        if target.identity in seen_live:
            _add_skip(skipped_items, target, SKIPPED_DUPLICATE)
            continue
        seen_live.add(target.identity)
        selected.append(target.identity)

        if wire_request.mode == CLEANUP_MODE_PREVIEW_ONLY:
            _add_skip(
                skipped_items,
                target,
                SKIPPED_NOT_KILLABLE,
                "preview_only",
            )
            continue

        dismissable = dismissable_status or (
            wire_request.include_pidless_as_dismissable and target.pid is None
        )
        killable = target.pid is not None and not dismissable_status

        if wire_request.mode == CLEANUP_MODE_DISMISS_COMPLETED:
            if dismissable:
                dismiss_items.append(
                    AgentCleanupDismissItemWire(
                        identity=target.identity,
                        display_name=target.display_name,
                    )
                )
            else:
                _add_skip(
                    skipped_items,
                    target,
                    SKIPPED_NOT_DISMISSABLE,
                    target.status,
                )
            continue

        if dismissable:
            dismiss_items.append(
                AgentCleanupDismissItemWire(
                    identity=target.identity,
                    display_name=target.display_name,
                )
            )
            continue

        if not killable:
            _add_skip(skipped_items, target, SKIPPED_NOT_KILLABLE, target.status)
            continue

        kind = _classify_kill_kind(target)
        if kind is None:
            _add_skip(
                skipped_items,
                target,
                SKIPPED_UNKNOWN_KILL_KIND,
                target.agent_type,
            )
            continue

        kill_items.append(
            AgentCleanupKillItemWire(
                identity=target.identity,
                kind=kind,
                pid=target.pid,
                display_name=target.display_name,
            )
        )
        if kind == KILL_KIND_WORKFLOW and target.raw_suffix is not None:
            for child in children_by_parent[(target.raw_suffix, target.workflow)]:
                if child.identity not in seen_live:
                    seen_live.add(child.identity)
                    cascaded_children.append(child.identity)

    counts = AgentCleanupCountsWire(
        candidates=len(wire_targets),
        selected=len(selected),
        kill=len(kill_items),
        dismiss=len(dismiss_items),
        cascaded_workflow_children=len(cascaded_children),
        skipped=len(skipped_items),
        running=running,
        completed=completed,
        failed=failed,
    )
    if kill_items:
        confirmation_severity = CONFIRMATION_SEVERITY_DESTRUCTIVE
    elif dismiss_items:
        confirmation_severity = CONFIRMATION_SEVERITY_DISMISS
    else:
        confirmation_severity = CONFIRMATION_SEVERITY_NONE

    summary_lines: list[str] = []
    _push_summary_line(summary_lines, counts.kill, "agent to kill")
    _push_summary_line(summary_lines, counts.dismiss, "agent to dismiss")
    _push_summary_line(
        summary_lines,
        counts.cascaded_workflow_children,
        "workflow child to hide",
    )
    if not summary_lines:
        summary_lines.append("No agents selected for cleanup")

    return AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        selected_identities=tuple(selected),
        kill_items=tuple(kill_items),
        dismiss_items=tuple(dismiss_items),
        cascaded_workflow_children=tuple(cascaded_children),
        skipped_items=tuple(skipped_items),
        counts=counts,
        confirmation_severity=confirmation_severity,
        summary_lines=tuple(summary_lines),
    )


# pyvision: tests/test_core_facade/test_agent_cleanup.py
def plan_agent_cleanup(
    targets: Sequence[AgentCleanupTargetWire | dict[str, Any]],
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupPlanWire:
    """Plan cleanup through Rust, falling back only for missing/stale bindings."""

    wire_targets = [_as_target(target) for target in targets]
    wire_request = _as_request(request)
    try:
        binding = require_rust_binding("plan_agent_cleanup")
    except (ImportError, AttributeError):
        return plan_agent_cleanup_python(wire_targets, wire_request)

    payload: dict[str, Any] = binding(
        agent_cleanup_wire_to_json_dict(wire_targets),
        agent_cleanup_wire_to_json_dict(wire_request),
    )
    return cleanup_plan_from_dict(payload)


__all__ = [
    "agent_to_cleanup_target",
    "agents_to_cleanup_targets",
    "plan_agent_cleanup",
    "plan_agent_cleanup_python",
]
