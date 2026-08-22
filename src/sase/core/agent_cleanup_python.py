"""Python reference implementation of agent cleanup planning."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sase.core.agent_cleanup_side_effects import build_cleanup_side_effects
from sase.core.agent_cleanup_targets import is_workflow_child, is_workflow_step_child
from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    CLEANUP_MODE_DISMISS_COMPLETED,
    CLEANUP_MODE_KILL_AND_DISMISS,
    CLEANUP_MODE_PREVIEW_ONLY,
    CLEANUP_SCOPE_ALL_PANELS,
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
    CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    CLEANUP_SCOPE_FOCUSED_GROUP,
    CLEANUP_SCOPE_FOCUSED_PANEL,
    CLEANUP_SCOPE_TRIBE,
    CONFIRMATION_SEVERITY_DESTRUCTIVE,
    CONFIRMATION_SEVERITY_DISMISS,
    CONFIRMATION_SEVERITY_NONE,
    DISMISSABLE_STATUSES,
    KILL_KIND_CRS,
    KILL_KIND_HOOK,
    KILL_KIND_MENTOR,
    KILL_KIND_MONITOR,
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
    cleanup_request_from_dict,
    cleanup_target_from_dict,
)


def coerce_cleanup_target(
    target: AgentCleanupTargetWire | dict[str, Any],
) -> AgentCleanupTargetWire:
    if isinstance(target, AgentCleanupTargetWire):
        return target
    return cleanup_target_from_dict(target)


def coerce_cleanup_request(
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupRequestWire:
    if isinstance(request, AgentCleanupRequestWire):
        return request
    return cleanup_request_from_dict(request)


def _effective_tribe(
    target: AgentCleanupTargetWire,
    parent_tribes: dict[str, str | None],
) -> str | None:
    if is_workflow_child(target) and target.parent_timestamp is not None:
        if target.parent_timestamp in parent_tribes:
            return parent_tribes[target.parent_timestamp]
    return target.tribe


def _selected_by_scope(
    target: AgentCleanupTargetWire,
    request: AgentCleanupRequestWire,
    selected_ids: set[AgentCleanupIdentityWire],
    parent_tribes: dict[str, str | None],
) -> bool:
    if request.scope == CLEANUP_SCOPE_ALL_PANELS:
        return True
    if request.scope == CLEANUP_SCOPE_FOCUSED_PANEL:
        return _effective_tribe(target, parent_tribes) == request.focused_panel_tribe
    if request.scope == CLEANUP_SCOPE_TRIBE:
        return _effective_tribe(target, parent_tribes) == request.tribe
    if request.scope == CLEANUP_SCOPE_CLAN:
        return request.clan_name is not None and (
            target.agent_clan == request.clan_name
            and (
                request.clan_generation is None
                or target.agent_clan_generation == request.clan_generation
            )
        )
    if request.scope in {
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        CLEANUP_SCOPE_FOCUSED_GROUP,
        CLEANUP_SCOPE_CUSTOM_SELECTION,
    }:
        return target.identity in selected_ids
    return False


def _scope_allows_direct_child_targets(scope: str) -> bool:
    return scope in {
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        CLEANUP_SCOPE_CUSTOM_SELECTION,
    }


def _parent_matches_child(
    parent: AgentCleanupTargetWire,
    child: AgentCleanupTargetWire,
) -> bool:
    if is_workflow_child(parent):
        return False
    if parent.raw_suffix != child.parent_timestamp:
        return False
    if child.parent_workflow is not None:
        return parent.workflow == child.parent_workflow
    return True


def _parent_selected_for_child(
    child: AgentCleanupTargetWire,
    targets: Sequence[AgentCleanupTargetWire],
    request: AgentCleanupRequestWire,
    selected_ids: set[AgentCleanupIdentityWire],
    parent_tribes: dict[str, str | None],
) -> bool:
    if child.parent_timestamp is None:
        return False
    return any(
        _parent_matches_child(candidate, child)
        and _selected_by_scope(candidate, request, selected_ids, parent_tribes)
        for candidate in targets
    )


def _is_direct_child_target(
    target: AgentCleanupTargetWire,
    targets: Sequence[AgentCleanupTargetWire],
    request: AgentCleanupRequestWire,
    selected_ids: set[AgentCleanupIdentityWire],
    parent_tribes: dict[str, str | None],
) -> bool:
    return (
        is_workflow_step_child(target)
        and _scope_allows_direct_child_targets(request.scope)
        and target.identity in selected_ids
        and not _parent_selected_for_child(
            target,
            targets,
            request,
            selected_ids,
            parent_tribes,
        )
    )


def _classify_kill_kind(target: AgentCleanupTargetWire) -> str | None:
    if target.is_live_monitor:
        return KILL_KIND_MONITOR
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


def _parallel_members_by_parent(
    targets: Sequence[AgentCleanupTargetWire],
) -> dict[str, list[AgentCleanupTargetWire]]:
    members: dict[str, list[AgentCleanupTargetWire]] = defaultdict(list)
    for target in targets:
        if (
            target.agent_family_parallel
            and target.parent_workflow is None
            and target.parent_timestamp is not None
        ):
            members[target.parent_timestamp].append(target)
    return members


def _parallel_family_members(
    root: AgentCleanupTargetWire,
    members_by_parent: dict[str, list[AgentCleanupTargetWire]],
) -> list[AgentCleanupTargetWire]:
    if (
        not root.agent_family_parallel
        or is_workflow_child(root)
        or root.raw_suffix is None
    ):
        return []
    return members_by_parent[root.raw_suffix]


def _target_is_dismissable(
    target: AgentCleanupTargetWire,
    request: AgentCleanupRequestWire,
) -> bool:
    return target.status in DISMISSABLE_STATUSES or (
        request.include_pidless_as_dismissable and target.pid is None
    )


def _children_by_parent_timestamp(
    targets: Sequence[AgentCleanupTargetWire],
) -> dict[str, list[AgentCleanupTargetWire]]:
    children: dict[str, list[AgentCleanupTargetWire]] = defaultdict(list)
    for target in targets:
        if target.parent_timestamp is not None:
            children[target.parent_timestamp].append(target)
    return children


def _collect_live_monitor_descendants(
    owner: AgentCleanupTargetWire,
    children_by_parent_ts: dict[str, list[AgentCleanupTargetWire]],
    owned: set[AgentCleanupIdentityWire],
) -> None:
    if owner.raw_suffix is None:
        return
    stack = [owner.raw_suffix]
    seen: set[str] = set()
    while stack:
        timestamp = stack.pop()
        if timestamp in seen:
            continue
        seen.add(timestamp)
        for child in children_by_parent_ts.get(timestamp, ()):
            if child.is_live_monitor:
                owned.add(child.identity)
            if child.raw_suffix is not None:
                stack.append(child.raw_suffix)


def _owned_live_monitor_identities(
    targets: Sequence[AgentCleanupTargetWire],
    request: AgentCleanupRequestWire,
    selected_ids: set[AgentCleanupIdentityWire],
    parent_tribes: dict[str, str | None],
    children_by_parent_ts: dict[str, list[AgentCleanupTargetWire]],
) -> set[AgentCleanupIdentityWire]:
    owned: set[AgentCleanupIdentityWire] = set()
    if request.mode != CLEANUP_MODE_KILL_AND_DISMISS:
        return owned
    for target in targets:
        if not _selected_by_scope(target, request, selected_ids, parent_tribes):
            continue
        if is_workflow_step_child(target) and not _is_direct_child_target(
            target,
            targets,
            request,
            selected_ids,
            parent_tribes,
        ):
            continue
        _collect_live_monitor_descendants(target, children_by_parent_ts, owned)
    return owned


def _monitor_id_for_kill(target: AgentCleanupTargetWire) -> str | None:
    monitor_id = target.monitor_id
    if monitor_id is None:
        return None
    stripped = monitor_id.strip()
    return stripped or None


def _push_monitor_kill_item(
    kill_items: list[AgentCleanupKillItemWire],
    target: AgentCleanupTargetWire,
) -> bool:
    monitor_id = _monitor_id_for_kill(target)
    if monitor_id is None:
        return False
    kill_items.append(
        AgentCleanupKillItemWire(
            identity=target.identity,
            kind=KILL_KIND_MONITOR,
            pid=None,
            display_name=target.display_name,
            monitor_id=monitor_id,
        )
    )
    return True


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


def plan_agent_cleanup_python(
    targets: Sequence[AgentCleanupTargetWire | dict[str, Any]],
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupPlanWire:
    """Reference Python implementation of the pure cleanup planner."""

    wire_targets = [coerce_cleanup_target(target) for target in targets]
    wire_request = coerce_cleanup_request(request)
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
    parent_tribes = {
        target.raw_suffix: target.tribe
        for target in wire_targets
        if not is_workflow_child(target) and target.raw_suffix is not None
    }
    children_by_parent: dict[tuple[str, str | None], list[AgentCleanupTargetWire]] = (
        defaultdict(list)
    )
    for target in wire_targets:
        if is_workflow_child(target) and target.parent_timestamp is not None:
            children_by_parent[
                (target.parent_timestamp, target.parent_workflow)
            ].append(target)
    parallel_members_by_parent = _parallel_members_by_parent(wire_targets)
    children_by_parent_ts = _children_by_parent_timestamp(wire_targets)
    owned_live_monitors = _owned_live_monitor_identities(
        wire_targets,
        wire_request,
        selected_ids,
        parent_tribes,
        children_by_parent_ts,
    )

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

        in_scope = _selected_by_scope(target, wire_request, selected_ids, parent_tribes)
        cascaded_monitor = not in_scope and target.identity in owned_live_monitors
        if not in_scope and not cascaded_monitor:
            _add_skip(skipped_items, target, SKIPPED_NOT_IN_SCOPE)
            continue

        direct_child_target = _is_direct_child_target(
            target,
            wire_targets,
            wire_request,
            selected_ids,
            parent_tribes,
        )
        if is_workflow_step_child(target) and not direct_child_target:
            _add_skip(skipped_items, target, SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY)
            continue

        if target.identity in seen_live:
            _add_skip(skipped_items, target, SKIPPED_DUPLICATE)
            continue
        seen_live.add(target.identity)
        if not cascaded_monitor:
            selected.append(target.identity)

        if wire_request.mode == CLEANUP_MODE_PREVIEW_ONLY:
            _add_skip(
                skipped_items,
                target,
                SKIPPED_NOT_KILLABLE,
                "preview_only",
            )
            continue

        dismissable = not target.is_live_monitor and _target_is_dismissable(
            target, wire_request
        )
        killable = target.is_live_monitor or (
            target.pid is not None and not dismissable_status
        )

        if wire_request.mode == CLEANUP_MODE_DISMISS_COMPLETED:
            if dismissable:
                live_family_members = [
                    member
                    for member in _parallel_family_members(
                        target,
                        parallel_members_by_parent,
                    )
                    if not _target_is_dismissable(member, wire_request)
                ]
                if live_family_members:
                    _add_skip(
                        skipped_items,
                        target,
                        SKIPPED_NOT_DISMISSABLE,
                        "parallel family still active",
                    )
                    continue
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

        if target.is_live_monitor:
            if not _push_monitor_kill_item(kill_items, target):
                _add_skip(
                    skipped_items,
                    target,
                    SKIPPED_UNKNOWN_KILL_KIND,
                    "live monitor missing monitor_id",
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

    action_identities = {item.identity for item in kill_items} | {
        item.identity for item in dismiss_items
    }
    for root in wire_targets:
        if root.identity not in action_identities:
            continue
        for member in _parallel_family_members(root, parallel_members_by_parent):
            if member.identity in action_identities:
                continue
            if _target_is_dismissable(member, wire_request):
                dismiss_items.append(
                    AgentCleanupDismissItemWire(
                        identity=member.identity,
                        display_name=member.display_name,
                    )
                )
                action_identities.add(member.identity)
                continue
            if wire_request.mode != CLEANUP_MODE_KILL_AND_DISMISS:
                continue
            if member.is_live_monitor:
                if _push_monitor_kill_item(kill_items, member):
                    action_identities.add(member.identity)
                continue
            if member.pid is None:
                continue
            kind = _classify_kill_kind(member)
            if kind is None:
                continue
            kill_items.append(
                AgentCleanupKillItemWire(
                    identity=member.identity,
                    kind=kind,
                    pid=member.pid,
                    display_name=member.display_name,
                )
            )
            action_identities.add(member.identity)

    kill_items.sort(key=lambda item: item.kind != KILL_KIND_MONITOR)

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

    side_effects = build_cleanup_side_effects(
        wire_targets,
        wire_request,
        kill_items,
        dismiss_items,
        children_by_parent,
    )

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
        side_effects=side_effects,
    )
