"""Side-effect intent planning for agent cleanup plans."""

from __future__ import annotations

from collections.abc import Sequence

from sase.core.agent_cleanup_targets import is_workflow_child
from sase.core.agent_cleanup_wire import (
    CLEANUP_MODE_PREVIEW_ONLY,
    KILL_KIND_RUNNING,
    KILL_KIND_WORKFLOW,
    AgentCleanupArtifactDeleteIntentWire,
    AgentCleanupBundleSaveIntentWire,
    AgentCleanupDismissItemWire,
    AgentCleanupIdentityWire,
    AgentCleanupKillItemWire,
    AgentCleanupNotificationDismissIntentWire,
    AgentCleanupRequestWire,
    AgentCleanupSideEffectsWire,
    AgentCleanupTargetWire,
    AgentCleanupWorkspaceReleaseIntentWire,
)


def _related_workflow_targets(
    target: AgentCleanupTargetWire,
    children_by_parent: dict[tuple[str, str | None], list[AgentCleanupTargetWire]],
) -> list[AgentCleanupTargetWire]:
    related = [target]
    if (
        target.agent_type == "workflow"
        and not is_workflow_child(target)
        and target.raw_suffix is not None
    ):
        related.extend(children_by_parent[(target.raw_suffix, target.workflow)])
    return related


def _append_unique_identity(
    items: list[AgentCleanupIdentityWire],
    seen: set[AgentCleanupIdentityWire],
    target: AgentCleanupTargetWire,
) -> None:
    if target.identity not in seen:
        seen.add(target.identity)
        items.append(target.identity)


def build_cleanup_side_effects(
    targets: Sequence[AgentCleanupTargetWire],
    request: AgentCleanupRequestWire,
    kill_items: Sequence[AgentCleanupKillItemWire],
    dismiss_items: Sequence[AgentCleanupDismissItemWire],
    children_by_parent: dict[tuple[str, str | None], list[AgentCleanupTargetWire]],
) -> AgentCleanupSideEffectsWire:
    """Build the deferred side-effect intents for a cleanup plan."""

    if request.mode == CLEANUP_MODE_PREVIEW_ONLY:
        return AgentCleanupSideEffectsWire()

    by_id = {target.identity: target for target in targets}
    dismissed_index: list[AgentCleanupIdentityWire] = []
    bundle_candidates: list[AgentCleanupBundleSaveIntentWire] = []
    artifact_deletes: list[AgentCleanupArtifactDeleteIntentWire] = []
    workspace_releases: list[AgentCleanupWorkspaceReleaseIntentWire] = []
    notification_candidates: list[AgentCleanupNotificationDismissIntentWire] = []

    seen_index: set[AgentCleanupIdentityWire] = set()
    seen_bundle: set[AgentCleanupIdentityWire] = set()
    seen_artifact: set[tuple[AgentCleanupIdentityWire, str]] = set()
    seen_workspace: set[AgentCleanupIdentityWire] = set()
    seen_held_workspace: set[AgentCleanupIdentityWire] = set()
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
                    lookup_timestamp=False,
                    artifacts_timestamp=None,
                )
            )
        elif kind == KILL_KIND_WORKFLOW:
            if is_workflow_child(target):
                return
            workflow_name = target.workflow
            if workflow_name is None:
                return
            lookup_cl_name = (
                target.identity.cl_name
                if target.identity.cl_name != "unknown"
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
                    lookup_timestamp=False,
                    artifacts_timestamp=None,
                )
            )

    def add_held_workspace(target: AgentCleanupTargetWire) -> None:
        if (
            is_workflow_child(target)
            or target.identity in seen_held_workspace
            or target.raw_suffix is None
        ):
            return
        seen_held_workspace.add(target.identity)
        workspace_releases.append(
            AgentCleanupWorkspaceReleaseIntentWire(
                identity=target.identity,
                project_file=target.project_file or "",
                workflow=target.workflow,
                cl_name=target.identity.cl_name,
                lookup_timestamp=True,
                artifacts_timestamp=target.raw_suffix,
            )
        )

    for dismiss in dismiss_items:
        target = by_id.get(dismiss.identity)
        if target is None:
            continue
        related = _related_workflow_targets(target, children_by_parent)
        for item in related:
            _append_unique_identity(dismissed_index, seen_index, item)
            add_bundle(item)
            add_artifact(item)
            add_notification(item)
            if item.agent_type in {"run", "workflow"}:
                add_held_workspace(item)
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
    )
