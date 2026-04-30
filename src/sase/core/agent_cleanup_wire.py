"""Wire records for pure agent-cleanup planning.

These records define the Python side of the ``sase_core_rs.plan_agent_cleanup``
contract. They intentionally project the mutable TUI ``Agent`` model into a
rectangular, JSON-safe shape so cleanup selection can be planned without doing
process, filesystem, or project-file side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_CLEANUP_WIRE_SCHEMA_VERSION = 1

CLEANUP_SCOPE_FOCUSED_PANEL = "focused_panel"
CLEANUP_SCOPE_ALL_PANELS = "all_panels"
CLEANUP_SCOPE_EXPLICIT_IDENTITIES = "explicit_identities"
CLEANUP_SCOPE_TAG = "tag"
CLEANUP_SCOPE_FOCUSED_GROUP = "focused_group"
CLEANUP_SCOPE_CUSTOM_SELECTION = "custom_selection"

CLEANUP_MODE_DISMISS_COMPLETED = "dismiss_completed"
CLEANUP_MODE_KILL_AND_DISMISS = "kill_and_dismiss"
CLEANUP_MODE_PREVIEW_ONLY = "preview_only"

CONFIRMATION_SEVERITY_NONE = "none"
CONFIRMATION_SEVERITY_DISMISS = "dismiss"
CONFIRMATION_SEVERITY_DESTRUCTIVE = "destructive"

KILL_KIND_RUNNING = "running"
KILL_KIND_HOOK = "hook"
KILL_KIND_MENTOR = "mentor"
KILL_KIND_CRS = "crs"
KILL_KIND_WORKFLOW = "workflow"

SKIPPED_NOT_IN_SCOPE = "not_in_scope"
SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY = "workflow_child_cascade_only"
SKIPPED_NOT_DISMISSABLE = "not_dismissable"
SKIPPED_NOT_KILLABLE = "not_killable"
SKIPPED_UNKNOWN_KILL_KIND = "unknown_kill_kind"
SKIPPED_DUPLICATE = "duplicate"

DISMISSABLE_STATUSES = {
    "DONE",
    "FAILED",
    "PLAN COMMITTED",
    "PLAN DONE",
    "PLAN REJECTED",
    "EPIC CREATED",
}


@dataclass(frozen=True, order=True)
class AgentCleanupIdentityWire:
    """Stable TUI agent identity: ``(agent_type, cl_name, raw_suffix)``."""

    agent_type: str
    cl_name: str
    raw_suffix: str | None = None


@dataclass(frozen=True)
class AgentCleanupTargetWire:
    """One host-provided agent row available for cleanup planning."""

    identity: AgentCleanupIdentityWire
    agent_type: str
    status: str
    pid: int | None = None
    workflow: str | None = None
    parent_workflow: str | None = None
    parent_timestamp: str | None = None
    raw_suffix: str | None = None
    project_file: str | None = None
    artifacts_dir: str | None = None
    from_changespec: bool = False
    workspace: int | None = None
    tag: str | None = None
    agent_name: str | None = None
    display_name: str | None = None
    start_time: str | None = None
    stop_time: str | None = None
    is_workflow_child: bool = False
    appears_as_agent: bool = False
    step_type: str | None = None


@dataclass(frozen=True)
class AgentCleanupRequestWire:
    """Scope and cleanup mode requested by the host."""

    schema_version: int
    scope: str
    mode: str
    focused_panel_tag: str | None = None
    tag: str | None = None
    identities: tuple[AgentCleanupIdentityWire, ...] = ()
    include_pidless_as_dismissable: bool = False
    taken_dismissed_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentCleanupKillItemWire:
    """One process/workflow kill decision."""

    identity: AgentCleanupIdentityWire
    kind: str
    pid: int | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class AgentCleanupDismissItemWire:
    """One dismissal decision."""

    identity: AgentCleanupIdentityWire
    display_name: str | None = None


@dataclass(frozen=True)
class AgentCleanupSkippedItemWire:
    """One target omitted from kill/dismiss outputs."""

    identity: AgentCleanupIdentityWire
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class AgentCleanupCountsWire:
    """Preview counts for the cleanup panel and tests."""

    candidates: int = 0
    selected: int = 0
    kill: int = 0
    dismiss: int = 0
    cascaded_workflow_children: int = 0
    skipped: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


@dataclass(frozen=True)
class AgentCleanupDismissalRenameIntentWire:
    """One dismissal-time name allocation."""

    identity: AgentCleanupIdentityWire
    old_name: str | None
    new_name: str


@dataclass(frozen=True)
class AgentCleanupBundleSaveIntentWire:
    """One agent whose revive bundle should be saved by the host."""

    identity: AgentCleanupIdentityWire


@dataclass(frozen=True)
class AgentCleanupArtifactDeleteIntentWire:
    """One artifact directory whose loader markers should be removed."""

    identity: AgentCleanupIdentityWire
    artifacts_dir: str


@dataclass(frozen=True)
class AgentCleanupWorkspaceReleaseIntentWire:
    """One workspace release request for host-side project-file mutation."""

    identity: AgentCleanupIdentityWire
    project_file: str
    workspace: int | None = None
    workflow: str | None = None
    cl_name: str | None = None
    lookup_workflow: bool = False


@dataclass(frozen=True)
class AgentCleanupNotificationDismissIntentWire:
    """One notification agent key to dismiss after cleanup succeeds."""

    identity: AgentCleanupIdentityWire
    cl_name: str
    raw_suffix: str | None = None


@dataclass(frozen=True)
class AgentCleanupSideEffectsWire:
    """Deterministic side-effect intents for host-side execution."""

    dismissed_index_additions: tuple[AgentCleanupIdentityWire, ...] = ()
    bundle_save_candidates: tuple[AgentCleanupBundleSaveIntentWire, ...] = ()
    artifact_delete_paths: tuple[AgentCleanupArtifactDeleteIntentWire, ...] = ()
    workspace_release_requests: tuple[AgentCleanupWorkspaceReleaseIntentWire, ...] = ()
    notification_dismiss_candidates: tuple[
        AgentCleanupNotificationDismissIntentWire, ...
    ] = ()
    dismissal_rename_allocations: tuple[AgentCleanupDismissalRenameIntentWire, ...] = ()
    wait_reference_rewrite_map: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class AgentCleanupPlanWire:
    """Complete pure cleanup plan."""

    schema_version: int
    selected_identities: tuple[AgentCleanupIdentityWire, ...] = ()
    kill_items: tuple[AgentCleanupKillItemWire, ...] = ()
    dismiss_items: tuple[AgentCleanupDismissItemWire, ...] = ()
    cascaded_workflow_children: tuple[AgentCleanupIdentityWire, ...] = ()
    skipped_items: tuple[AgentCleanupSkippedItemWire, ...] = ()
    counts: AgentCleanupCountsWire = field(default_factory=AgentCleanupCountsWire)
    confirmation_severity: str = CONFIRMATION_SEVERITY_NONE
    summary_lines: tuple[str, ...] = ()
    side_effects: AgentCleanupSideEffectsWire = field(
        default_factory=AgentCleanupSideEffectsWire
    )


def agent_cleanup_wire_to_json_dict(record: Any) -> Any:
    """Project cleanup wire records to a JSON-safe dict/list tree."""

    if isinstance(record, (list, tuple)):
        return [agent_cleanup_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: agent_cleanup_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _identity_from_dict(data: dict[str, Any]) -> AgentCleanupIdentityWire:
    return AgentCleanupIdentityWire(
        agent_type=str(data["agent_type"]),
        cl_name=str(data["cl_name"]),
        raw_suffix=None if data.get("raw_suffix") is None else str(data["raw_suffix"]),
    )


def cleanup_target_from_dict(data: dict[str, Any]) -> AgentCleanupTargetWire:
    """Rehydrate an :class:`AgentCleanupTargetWire` from a dict."""

    return AgentCleanupTargetWire(
        identity=_identity_from_dict(data["identity"]),
        agent_type=str(data["agent_type"]),
        status=str(data["status"]),
        pid=None if data.get("pid") is None else int(data["pid"]),
        workflow=None if data.get("workflow") is None else str(data["workflow"]),
        parent_workflow=(
            None
            if data.get("parent_workflow") is None
            else str(data["parent_workflow"])
        ),
        parent_timestamp=(
            None
            if data.get("parent_timestamp") is None
            else str(data["parent_timestamp"])
        ),
        raw_suffix=None if data.get("raw_suffix") is None else str(data["raw_suffix"]),
        project_file=(
            None if data.get("project_file") is None else str(data["project_file"])
        ),
        artifacts_dir=(
            None if data.get("artifacts_dir") is None else str(data["artifacts_dir"])
        ),
        from_changespec=bool(data.get("from_changespec", False)),
        workspace=None if data.get("workspace") is None else int(data["workspace"]),
        tag=None if data.get("tag") is None else str(data["tag"]),
        agent_name=None if data.get("agent_name") is None else str(data["agent_name"]),
        display_name=(
            None if data.get("display_name") is None else str(data["display_name"])
        ),
        start_time=None if data.get("start_time") is None else str(data["start_time"]),
        stop_time=None if data.get("stop_time") is None else str(data["stop_time"]),
        is_workflow_child=bool(data.get("is_workflow_child", False)),
        appears_as_agent=bool(data.get("appears_as_agent", False)),
        step_type=None if data.get("step_type") is None else str(data["step_type"]),
    )


def cleanup_request_from_dict(data: dict[str, Any]) -> AgentCleanupRequestWire:
    """Rehydrate an :class:`AgentCleanupRequestWire` from a dict."""

    schema = int(data["schema_version"])
    if schema != AGENT_CLEANUP_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"agent cleanup wire schema mismatch: got {schema}, "
            f"expected {AGENT_CLEANUP_WIRE_SCHEMA_VERSION}"
        )
    return AgentCleanupRequestWire(
        schema_version=schema,
        scope=str(data["scope"]),
        mode=str(data["mode"]),
        focused_panel_tag=(
            None
            if data.get("focused_panel_tag") is None
            else str(data["focused_panel_tag"])
        ),
        tag=None if data.get("tag") is None else str(data["tag"]),
        identities=tuple(
            _identity_from_dict(item) for item in data.get("identities") or ()
        ),
        include_pidless_as_dismissable=bool(
            data.get("include_pidless_as_dismissable", False)
        ),
        taken_dismissed_names=tuple(
            str(name) for name in data.get("taken_dismissed_names") or ()
        ),
    )


def cleanup_plan_from_dict(data: dict[str, Any]) -> AgentCleanupPlanWire:
    """Rehydrate an :class:`AgentCleanupPlanWire` from a dict."""

    schema = int(data["schema_version"])
    if schema != AGENT_CLEANUP_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"agent cleanup wire schema mismatch: got {schema}, "
            f"expected {AGENT_CLEANUP_WIRE_SCHEMA_VERSION}"
        )
    side_effect_data = data.get("side_effects") or {}
    return AgentCleanupPlanWire(
        schema_version=schema,
        selected_identities=tuple(
            _identity_from_dict(item) for item in data.get("selected_identities") or ()
        ),
        kill_items=tuple(
            AgentCleanupKillItemWire(
                identity=_identity_from_dict(item["identity"]),
                kind=str(item["kind"]),
                pid=None if item.get("pid") is None else int(item["pid"]),
                display_name=(
                    None
                    if item.get("display_name") is None
                    else str(item["display_name"])
                ),
            )
            for item in data.get("kill_items") or ()
        ),
        dismiss_items=tuple(
            AgentCleanupDismissItemWire(
                identity=_identity_from_dict(item["identity"]),
                display_name=(
                    None
                    if item.get("display_name") is None
                    else str(item["display_name"])
                ),
            )
            for item in data.get("dismiss_items") or ()
        ),
        cascaded_workflow_children=tuple(
            _identity_from_dict(item)
            for item in data.get("cascaded_workflow_children") or ()
        ),
        skipped_items=tuple(
            AgentCleanupSkippedItemWire(
                identity=_identity_from_dict(item["identity"]),
                reason=str(item["reason"]),
                detail=None if item.get("detail") is None else str(item["detail"]),
            )
            for item in data.get("skipped_items") or ()
        ),
        counts=AgentCleanupCountsWire(**(data.get("counts") or {})),
        confirmation_severity=str(
            data.get("confirmation_severity", CONFIRMATION_SEVERITY_NONE)
        ),
        summary_lines=tuple(str(line) for line in data.get("summary_lines") or ()),
        side_effects=AgentCleanupSideEffectsWire(
            dismissed_index_additions=tuple(
                _identity_from_dict(item)
                for item in side_effect_data.get("dismissed_index_additions") or ()
            ),
            bundle_save_candidates=tuple(
                AgentCleanupBundleSaveIntentWire(
                    identity=_identity_from_dict(item["identity"]),
                )
                for item in side_effect_data.get("bundle_save_candidates") or ()
            ),
            artifact_delete_paths=tuple(
                AgentCleanupArtifactDeleteIntentWire(
                    identity=_identity_from_dict(item["identity"]),
                    artifacts_dir=str(item["artifacts_dir"]),
                )
                for item in side_effect_data.get("artifact_delete_paths") or ()
            ),
            workspace_release_requests=tuple(
                AgentCleanupWorkspaceReleaseIntentWire(
                    identity=_identity_from_dict(item["identity"]),
                    project_file=str(item["project_file"]),
                    workspace=(
                        None
                        if item.get("workspace") is None
                        else int(item["workspace"])
                    ),
                    workflow=(
                        None if item.get("workflow") is None else str(item["workflow"])
                    ),
                    cl_name=(
                        None if item.get("cl_name") is None else str(item["cl_name"])
                    ),
                    lookup_workflow=bool(item.get("lookup_workflow", False)),
                )
                for item in side_effect_data.get("workspace_release_requests") or ()
            ),
            notification_dismiss_candidates=tuple(
                AgentCleanupNotificationDismissIntentWire(
                    identity=_identity_from_dict(item["identity"]),
                    cl_name=str(item["cl_name"]),
                    raw_suffix=(
                        None
                        if item.get("raw_suffix") is None
                        else str(item["raw_suffix"])
                    ),
                )
                for item in side_effect_data.get("notification_dismiss_candidates")
                or ()
            ),
            dismissal_rename_allocations=tuple(
                AgentCleanupDismissalRenameIntentWire(
                    identity=_identity_from_dict(item["identity"]),
                    old_name=(
                        None if item.get("old_name") is None else str(item["old_name"])
                    ),
                    new_name=str(item["new_name"]),
                )
                for item in side_effect_data.get("dismissal_rename_allocations") or ()
            ),
            wait_reference_rewrite_map=tuple(
                (str(old), str(new))
                for old, new in side_effect_data.get("wait_reference_rewrite_map") or ()
            ),
        ),
    )


__all__ = [
    "AGENT_CLEANUP_WIRE_SCHEMA_VERSION",
    "CLEANUP_MODE_DISMISS_COMPLETED",
    "CLEANUP_MODE_KILL_AND_DISMISS",
    "CLEANUP_MODE_PREVIEW_ONLY",
    "CLEANUP_SCOPE_ALL_PANELS",
    "CLEANUP_SCOPE_CUSTOM_SELECTION",
    "CLEANUP_SCOPE_EXPLICIT_IDENTITIES",
    "CLEANUP_SCOPE_FOCUSED_GROUP",
    "CLEANUP_SCOPE_FOCUSED_PANEL",
    "CLEANUP_SCOPE_TAG",
    "CONFIRMATION_SEVERITY_DESTRUCTIVE",
    "CONFIRMATION_SEVERITY_DISMISS",
    "CONFIRMATION_SEVERITY_NONE",
    "DISMISSABLE_STATUSES",
    "KILL_KIND_CRS",
    "KILL_KIND_HOOK",
    "KILL_KIND_MENTOR",
    "KILL_KIND_RUNNING",
    "KILL_KIND_WORKFLOW",
    "SKIPPED_DUPLICATE",
    "SKIPPED_NOT_DISMISSABLE",
    "SKIPPED_NOT_IN_SCOPE",
    "SKIPPED_NOT_KILLABLE",
    "SKIPPED_UNKNOWN_KILL_KIND",
    "SKIPPED_WORKFLOW_CHILD_CASCADE_ONLY",
    "AgentCleanupCountsWire",
    "AgentCleanupArtifactDeleteIntentWire",
    "AgentCleanupBundleSaveIntentWire",
    "AgentCleanupDismissItemWire",
    "AgentCleanupDismissalRenameIntentWire",
    "AgentCleanupIdentityWire",
    "AgentCleanupKillItemWire",
    "AgentCleanupNotificationDismissIntentWire",
    "AgentCleanupPlanWire",
    "AgentCleanupRequestWire",
    "AgentCleanupSideEffectsWire",
    "AgentCleanupSkippedItemWire",
    "AgentCleanupTargetWire",
    "AgentCleanupWorkspaceReleaseIntentWire",
    "agent_cleanup_wire_to_json_dict",
    "cleanup_plan_from_dict",
    "cleanup_request_from_dict",
    "cleanup_target_from_dict",
]
