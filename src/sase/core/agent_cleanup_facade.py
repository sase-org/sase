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
from datetime import datetime
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
    AgentCleanupArtifactDeleteIntentWire,
    AgentCleanupBundleSaveIntentWire,
    AgentCleanupDismissItemWire,
    AgentCleanupDismissalRenameIntentWire,
    AgentCleanupIdentityWire,
    AgentCleanupKillItemWire,
    AgentCleanupNotificationDismissIntentWire,
    AgentCleanupPlanWire,
    AgentCleanupRequestWire,
    AgentCleanupSideEffectsWire,
    AgentCleanupSkippedItemWire,
    AgentCleanupTargetWire,
    AgentCleanupWorkspaceReleaseIntentWire,
    agent_cleanup_wire_to_json_dict,
    cleanup_plan_from_dict,
    cleanup_request_from_dict,
    cleanup_target_from_dict,
)
from sase.core.rust import require_rust_binding


def _as_target(
    target: AgentCleanupTargetWire | dict[str, Any],
) -> AgentCleanupTargetWire:
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
        from_changespec=bool(getattr(agent, "_from_changespec", False)),
        workspace=agent.effective_workspace_num,
        tag=agent.tag,
        agent_name=agent.agent_name,
        display_name=agent.display_name,
        start_time=_iso_or_none(agent.start_time),
        stop_time=_iso_or_none(agent.stop_time),
        is_workflow_child=getattr(agent, "is_rendered_workflow_child", False),
        appears_as_agent=agent.appears_as_agent,
        step_type=agent.step_type,
    )


def agents_to_cleanup_targets(
    agents: Iterable[Any],
) -> tuple[AgentCleanupTargetWire, ...]:
    """Convert an iterable of TUI ``Agent`` objects to cleanup target wires."""

    return tuple(agent_to_cleanup_target(agent) for agent in agents)


def _is_workflow_child(target: AgentCleanupTargetWire) -> bool:
    return target.is_workflow_child or target.parent_workflow is not None


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


def _is_dismissed_prefixed(name: str) -> bool:
    return len(name) > 7 and name[:6].isdigit() and name[6] == "."


def _strip_dismissed_prefix(name: str) -> str:
    if _is_dismissed_prefixed(name):
        return name[7:]
    return name


def _completion_date_prefix(target: AgentCleanupTargetWire) -> str:
    for value in (target.stop_time, target.start_time):
        if not value:
            continue
        try:
            return datetime.fromisoformat(value).strftime("%y%m%d")
        except ValueError:
            pass
    if target.raw_suffix and len(target.raw_suffix) >= 8:
        raw = target.raw_suffix[:8]
        if raw.isdigit():
            return f"{raw[2:4]}{raw[4:6]}{raw[6:8]}"
    return "000101"


def _base_for_dismissal(target: AgentCleanupTargetWire) -> str:
    if target.agent_name:
        return _strip_dismissed_prefix(target.agent_name)
    if target.identity.cl_name and target.identity.cl_name != "unknown":
        return target.identity.cl_name
    if target.raw_suffix:
        return target.raw_suffix
    return "agent"


def _add_dismissed_prefix(name: str, date_prefix: str) -> str:
    if _is_dismissed_prefixed(name):
        return name
    return f"{date_prefix}.{name}"


def _allocate_dismissed_name(
    base: str,
    date_prefix: str,
    taken: set[str],
) -> str:
    base = _strip_dismissed_prefix(base)
    primary = _add_dismissed_prefix(base, date_prefix)
    if primary not in taken:
        taken.add(primary)
        return primary
    n = 2
    while True:
        candidate = f"{primary}.{n}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1


def _related_workflow_targets(
    target: AgentCleanupTargetWire,
    children_by_parent: dict[str, list[AgentCleanupTargetWire]],
) -> list[AgentCleanupTargetWire]:
    related = [target]
    if (
        target.agent_type == "workflow"
        and not _is_workflow_child(target)
        and target.raw_suffix is not None
    ):
        related.extend(
            child
            for child in children_by_parent[target.raw_suffix]
            if child.parent_workflow is None or child.parent_workflow == target.workflow
        )
    return related


def _append_unique_identity(
    items: list[AgentCleanupIdentityWire],
    seen: set[AgentCleanupIdentityWire],
    target: AgentCleanupTargetWire,
) -> None:
    if target.identity not in seen:
        seen.add(target.identity)
        items.append(target.identity)


def _build_cleanup_side_effects(
    targets: Sequence[AgentCleanupTargetWire],
    request: AgentCleanupRequestWire,
    kill_items: Sequence[AgentCleanupKillItemWire],
    dismiss_items: Sequence[AgentCleanupDismissItemWire],
    children_by_parent: dict[str, list[AgentCleanupTargetWire]],
) -> AgentCleanupSideEffectsWire:
    if request.mode == CLEANUP_MODE_PREVIEW_ONLY:
        return AgentCleanupSideEffectsWire()

    by_id = {target.identity: target for target in targets}
    taken = set(request.taken_dismissed_names)

    dismissed_index: list[AgentCleanupIdentityWire] = []
    bundle_candidates: list[AgentCleanupBundleSaveIntentWire] = []
    artifact_deletes: list[AgentCleanupArtifactDeleteIntentWire] = []
    workspace_releases: list[AgentCleanupWorkspaceReleaseIntentWire] = []
    notification_candidates: list[AgentCleanupNotificationDismissIntentWire] = []
    rename_allocations: list[AgentCleanupDismissalRenameIntentWire] = []
    rewrite_map: list[tuple[str, str]] = []

    seen_index: set[AgentCleanupIdentityWire] = set()
    seen_bundle: set[AgentCleanupIdentityWire] = set()
    seen_artifact: set[tuple[AgentCleanupIdentityWire, str]] = set()
    seen_workspace: set[AgentCleanupIdentityWire] = set()
    seen_notifications: set[AgentCleanupIdentityWire] = set()

    def add_bundle(target: AgentCleanupTargetWire) -> None:
        if target.from_changespec or target.identity in seen_bundle:
            return
        seen_bundle.add(target.identity)
        bundle_candidates.append(AgentCleanupBundleSaveIntentWire(target.identity))

    def add_artifact(target: AgentCleanupTargetWire) -> None:
        if not target.artifacts_dir:
            return
        key = (target.identity, target.artifacts_dir)
        if key in seen_artifact:
            return
        seen_artifact.add(key)
        artifact_deletes.append(
            AgentCleanupArtifactDeleteIntentWire(target.identity, target.artifacts_dir)
        )

    def add_notification(target: AgentCleanupTargetWire) -> None:
        if target.identity in seen_notifications:
            return
        seen_notifications.add(target.identity)
        notification_candidates.append(
            AgentCleanupNotificationDismissIntentWire(
                target.identity,
                target.identity.cl_name,
                target.raw_suffix,
            )
        )

    def add_workspace(target: AgentCleanupTargetWire, kind: str) -> None:
        if target.identity in seen_workspace:
            return
        seen_workspace.add(target.identity)
        if kind == KILL_KIND_RUNNING:
            if target.workspace is None:
                return
            workspace_releases.append(
                AgentCleanupWorkspaceReleaseIntentWire(
                    identity=target.identity,
                    project_file=target.project_file or "",
                    workspace=target.workspace,
                    workflow=target.workflow,
                    cl_name=target.identity.cl_name,
                    lookup_workflow=False,
                )
            )
        elif kind == KILL_KIND_WORKFLOW:
            workflow_name = (
                target.parent_workflow or target.workflow
                if target.is_workflow_child
                else target.workflow
            )
            if workflow_name is None:
                return
            lookup_cl_name = (
                target.identity.cl_name
                if not target.is_workflow_child and target.identity.cl_name != "unknown"
                else None
            )
            workspace_releases.append(
                AgentCleanupWorkspaceReleaseIntentWire(
                    identity=target.identity,
                    project_file=target.project_file or "",
                    workspace=target.workspace,
                    workflow=workflow_name,
                    cl_name=lookup_cl_name,
                    lookup_workflow=target.workspace is None,
                )
            )

    def add_renames(related: list[AgentCleanupTargetWire]) -> None:
        if not related:
            return
        parent = related[0]
        date_prefix = _completion_date_prefix(parent)
        old_name = parent.agent_name
        new_name = _allocate_dismissed_name(
            _base_for_dismissal(parent),
            date_prefix,
            taken,
        )
        rename_allocations.append(
            AgentCleanupDismissalRenameIntentWire(parent.identity, old_name, new_name)
        )
        if old_name and old_name != new_name:
            rewrite_map.append((old_name, new_name))
        if parent.agent_type != "workflow" or _is_workflow_child(parent):
            return
        for child in related[1:]:
            if not child.agent_name:
                continue
            child_new = _add_dismissed_prefix(child.agent_name, date_prefix)
            if child_new == child.agent_name:
                continue
            rename_allocations.append(
                AgentCleanupDismissalRenameIntentWire(
                    child.identity,
                    child.agent_name,
                    child_new,
                )
            )
            rewrite_map.append((child.agent_name, child_new))

    for dismiss in dismiss_items:
        target = by_id.get(dismiss.identity)
        if target is None:
            continue
        related = _related_workflow_targets(target, children_by_parent)
        add_renames(related)
        for item in related:
            _append_unique_identity(dismissed_index, seen_index, item)
            add_bundle(item)
            add_artifact(item)
            add_notification(item)
            if item.agent_type == "workflow":
                add_workspace(item, KILL_KIND_WORKFLOW)

    for kill in kill_items:
        target = by_id.get(kill.identity)
        if target is None:
            continue
        related = _related_workflow_targets(target, children_by_parent)
        for item in related:
            _append_unique_identity(dismissed_index, seen_index, item)
            add_notification(item)
            if kill.kind == KILL_KIND_WORKFLOW:
                add_bundle(item)
                add_artifact(item)
        add_workspace(target, kill.kind)

    return AgentCleanupSideEffectsWire(
        dismissed_index_additions=tuple(dismissed_index),
        bundle_save_candidates=tuple(bundle_candidates),
        artifact_delete_paths=tuple(artifact_deletes),
        workspace_release_requests=tuple(workspace_releases),
        notification_dismiss_candidates=tuple(notification_candidates),
        dismissal_rename_allocations=tuple(rename_allocations),
        wait_reference_rewrite_map=tuple(rewrite_map),
    )


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
    children_by_parent: dict[str, list[AgentCleanupTargetWire]] = defaultdict(list)
    for target in wire_targets:
        if target.parent_timestamp is not None:
            children_by_parent[target.parent_timestamp].append(target)

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
            for child in children_by_parent[target.raw_suffix]:
                if (
                    child.parent_workflow is not None
                    and child.parent_workflow != target.workflow
                ):
                    continue
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

    side_effects = _build_cleanup_side_effects(
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


def plan_agent_cleanup(
    targets: Sequence[AgentCleanupTargetWire | dict[str, Any]],
    request: AgentCleanupRequestWire | dict[str, Any],
) -> AgentCleanupPlanWire:
    """Plan cleanup through Rust, falling back only for missing/stale bindings."""

    wire_targets = [_as_target(target) for target in targets]
    wire_request = _as_request(request)
    if _has_independent_parent_timestamp_target(wire_targets):
        return plan_agent_cleanup_python(wire_targets, wire_request)
    try:
        binding = require_rust_binding("plan_agent_cleanup")
    except (ImportError, AttributeError):
        return plan_agent_cleanup_python(wire_targets, wire_request)

    payload: dict[str, Any] = binding(
        agent_cleanup_wire_to_json_dict(wire_targets),
        agent_cleanup_wire_to_json_dict(wire_request),
    )
    plan = cleanup_plan_from_dict(payload)
    if (plan.kill_items or plan.dismiss_items) and not any(
        getattr(plan.side_effects, attr)
        for attr in (
            "dismissed_index_additions",
            "bundle_save_candidates",
            "artifact_delete_paths",
            "workspace_release_requests",
            "notification_dismiss_candidates",
            "dismissal_rename_allocations",
            "wait_reference_rewrite_map",
        )
    ):
        return plan_agent_cleanup_python(wire_targets, wire_request)
    return plan


def _has_independent_parent_timestamp_target(
    targets: Sequence[AgentCleanupTargetWire],
) -> bool:
    """Return True when stale Rust cleanup semantics would treat a row as child."""
    return any(
        target.parent_timestamp is not None and not _is_workflow_child(target)
        for target in targets
    )


__all__ = [
    "agent_to_cleanup_target",
    "agents_to_cleanup_targets",
    "plan_agent_cleanup",
    "plan_agent_cleanup_python",
]
