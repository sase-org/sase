"""Rollback and deterministic-name cleanup helpers for ``sase bead work``."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.bead.cli_work_name_cleanup import (
    ForcedReuseCleanupError,
    release_stale_container,
    wipe_force_reuse_owner,
)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.model import Status
    from sase.bead.project import BeadProject, EpicPreclaimRollback
    from sase.core.agent_identity_facade import AgentIdentitySnapshot
    from sase.core.agent_scan_wire import AgentArtifactRecordWire


def _rollback_launched_agents(
    *,
    launched_results: list[AgentLaunchResult] | None,
    launched_pids: list[int] | None,
) -> None:
    if launched_results:
        from sase.agent.partial_launch import rollback_partial_launch_results

        rollback_partial_launch_results(launched_results)
        return

    if not launched_pids:
        return

    import signal

    for pid in launched_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            print(
                f"Warning: failed to terminate partially-launched pid {pid}: {exc}",
                file=sys.stderr,
            )


def rollback_work_launch(
    proj: BeadProject,
    epic_id: str,
    *,
    marked_ready_this_run: bool,
    rollback_preclaims: Sequence[EpicPreclaimRollback] = (),
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Persist recoverable state after a failed epic-work agent launch.

    A zero-spawn failure restores every batch preclaim plus readiness when this
    launch set it. Once any runner has spawned, the preassigned state is
    retained and only the partial launch is terminated.
    """
    spawned_any = bool(launched_results or launched_pids)
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    if spawned_any:
        print(
            "Terminated the partially launched agents; preserving "
            "is_ready_to_work and all epic work preclaims for recovery.",
            file=sys.stderr,
        )
        return

    if marked_ready_this_run:
        readiness_message = "restoring the epic's prior is_ready_to_work state"
    else:
        readiness_message = "preserving the epic's existing is_ready_to_work state"
    print(
        f"No agents were spawned; restoring {len(rollback_preclaims)} epic work "
        f"preclaim(s) and {readiness_message}.",
        file=sys.stderr,
    )

    from sase.bead.sync import (
        bead_store_write_lock,
        commit_failed_work_launch_recovery,
        push_bead_work_launch,
    )

    committed = False
    try:
        with bead_store_write_lock(proj.beads_dir) as already_locked:
            for prior in rollback_preclaims:
                try:
                    proj.update(
                        prior.bead_id,
                        status=prior.status.value,
                        assignee=prior.assignee,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"Warning: failed to restore preclaim on "
                        f"{prior.bead_id}: {exc}",
                        file=sys.stderr,
                    )
            if marked_ready_this_run:
                try:
                    proj.unmark_ready_to_work(epic_id)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"Warning: failed to restore is_ready_to_work on "
                        f"{epic_id}: {exc}",
                        file=sys.stderr,
                    )
            committed = commit_failed_work_launch_recovery(
                proj.beads_dir,
                epic_id,
                already_locked=already_locked,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to commit restored launch state for {epic_id}: {exc}",
            file=sys.stderr,
        )
        return

    if committed and not no_push:
        outcome = push_bead_work_launch(proj.beads_dir)
        if outcome.error is not None:
            print(
                f"Warning: failed to publish restored launch state for "
                f"{epic_id}: {outcome.error}",
                file=sys.stderr,
            )


def rollback_task_work_launch(
    proj: BeadProject,
    task_id: str,
    *,
    prior_status: Status,
    prior_assignee: str,
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Persist recoverable state after a failed task-worker launch."""
    spawned_any = bool(launched_results or launched_pids)
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    if spawned_any:
        print(
            "Terminated the partially launched task agent; preserving the "
            "in-progress task assignment for recovery.",
            file=sys.stderr,
        )
        return

    print(
        f"No agents were spawned; restoring task {task_id} to "
        f"status={prior_status.value} and its prior assignee.",
        file=sys.stderr,
    )
    from sase.bead.sync import (
        bead_store_write_lock,
        commit_failed_work_launch_recovery,
        push_bead_work_launch,
    )

    committed = False
    try:
        with bead_store_write_lock(proj.beads_dir) as already_locked:
            proj.update(
                task_id,
                status=prior_status.value,
                assignee=prior_assignee,
            )
            committed = commit_failed_work_launch_recovery(
                proj.beads_dir,
                task_id,
                already_locked=already_locked,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to commit restored launch state for {task_id}: {exc}",
            file=sys.stderr,
        )
        return

    if committed and not no_push:
        outcome = push_bead_work_launch(proj.beads_dir)
        if outcome.error is not None:
            print(
                f"Warning: failed to publish restored launch state for "
                f"{task_id}: {outcome.error}",
                file=sys.stderr,
            )


type CleanupAction = Literal["PRESERVE", "KILL", "REMOVE", "RELEASE"]


@dataclass(frozen=True)
class BeadWorkSlot:
    """One logical bead-work owner name that may block a relaunch segment."""

    slot_id: str
    owner_name: str
    expected_bead_id: str
    launch_name: str | None
    allow_populated_clan_skip: bool = False


@dataclass(frozen=True)
class CleanupTarget:
    """One existing owner or reservation affected by forced name reuse."""

    name: str
    action: CleanupAction
    current_state: str
    detail: str
    expected_bead_id: str = ""
    slot_id: str = ""
    artifacts_dir: str = ""
    generation: str = ""

    @property
    def destructive(self) -> bool:
        return self.action in {"KILL", "REMOVE", "RELEASE"}

    @property
    def preserved(self) -> bool:
        return self.action == "PRESERVE"


@dataclass(frozen=True)
class _BeadWorkLaunchSelection:
    """Immutable cleanup and replacement decision for one bead-work retry."""

    slots: tuple[BeadWorkSlot, ...]
    targets: tuple[CleanupTarget, ...]
    launch_names: frozenset[str]

    @property
    def destructive_targets(self) -> tuple[CleanupTarget, ...]:
        return tuple(target for target in self.targets if target.destructive)

    @property
    def preserved_names(self) -> tuple[str, ...]:
        return tuple(target.name for target in self.targets if target.preserved)

    @property
    def has_launches(self) -> bool:
        return bool(self.launch_names)


@dataclass(frozen=True)
class CleanupPreview:
    """Read-only preview of destructive forced-reuse cleanup."""

    targets: tuple[CleanupTarget, ...]
    selection: _BeadWorkLaunchSelection | None = None

    @property
    def has_destructive_targets(self) -> bool:
        return any(target.destructive for target in self.targets)


def preview_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
    expected_bead_ids: dict[str, str] | None = None,
    bead_assignees: dict[str, str] | None = None,
) -> CleanupPreview:
    """Describe every owner or stale reservation a live cleanup will affect."""
    if expected_bead_ids is not None:
        slots = tuple(
            BeadWorkSlot(
                slot_id=name,
                owner_name=name,
                expected_bead_id=expected_bead_ids[name],
                launch_name=name,
            )
            for name in sorted(expected_names)
        ) + tuple(
            BeadWorkSlot(
                slot_id=name,
                owner_name=name,
                expected_bead_id=expected_bead_ids.get(name, name),
                launch_name=None,
                allow_populated_clan_skip=True,
            )
            for name in sorted(extra_cleanup_names)
        )
        return preview_bead_work_launch_selection(
            query,
            slots=slots,
            directive_names=expected_names,
            bead_assignees=bead_assignees or {},
        )

    from sase.bead.cli_work_legacy_preview import (
        preview_legacy_bead_work_force_reuse,
    )

    return preview_legacy_bead_work_force_reuse(
        query,
        expected_names=expected_names,
        extra_cleanup_names=extra_cleanup_names,
    )


def preview_bead_work_launch_selection(
    query: str,
    *,
    slots: Sequence[BeadWorkSlot],
    directive_names: set[str],
    bead_assignees: dict[str, str],
) -> CleanupPreview:
    """Return the assignment-aware relaunch selection for rendered bead work."""
    from sase.agent.launch_validation import force_reuse_owner_names

    parsed_directive_names = set(force_reuse_owner_names(query.split("\n---\n")))
    if parsed_directive_names != set(directive_names):
        raise ForcedReuseCleanupError(
            "rendered bead-work prompt force-reuse names "
            f"{sorted(parsed_directive_names)} do not match the planned agent "
            f"names {sorted(directive_names)}; aborting forced reuse preview"
        )

    selection = _select_bead_work_launch(
        slots=tuple(slots),
        bead_assignees=bead_assignees,
    )
    return CleanupPreview(targets=selection.targets, selection=selection)


def _select_bead_work_launch(
    *,
    slots: tuple[BeadWorkSlot, ...],
    bead_assignees: dict[str, str],
) -> _BeadWorkLaunchSelection:
    """Classify current owners and compute the relaunch subset."""
    from sase.agent.names import lookup_registered_name

    view = _load_agent_owner_view()
    targets: list[CleanupTarget] = []
    owner_present_by_slot: dict[str, int] = {}
    preserved_slots: set[str] = set()

    for slot in slots:
        owner = lookup_registered_name(slot.owner_name)
        if owner is None:
            continue
        classified = _classify_slot_owner(
            slot,
            owner,
            bead_assignees=bead_assignees,
            view=view,
        )
        if classified is None:
            continue
        owner_present_by_slot[slot.slot_id] = (
            owner_present_by_slot.get(slot.slot_id, 0) + 1
        )
        targets.extend(classified)
        if any(target.preserved for target in classified):
            preserved_slots.add(slot.slot_id)

    collisions = sorted(
        slot_id for slot_id, count in owner_present_by_slot.items() if count > 1
    )
    if collisions:
        raise ForcedReuseCleanupError(
            "multiple existing owners match one bead-work logical slot: "
            + ", ".join(collisions)
        )

    launch_names: set[str] = set()
    seen_slot_ids: set[str] = set()
    for slot in slots:
        if slot.slot_id in seen_slot_ids:
            continue
        seen_slot_ids.add(slot.slot_id)
        if slot.slot_id in preserved_slots:
            continue
        if slot.launch_name is not None:
            launch_names.add(slot.launch_name)

    return _BeadWorkLaunchSelection(
        slots=slots,
        targets=tuple(targets),
        launch_names=frozenset(launch_names),
    )


@dataclass(frozen=True)
class _AgentOwnerView:
    records_by_artifact_dir: dict[str, AgentArtifactRecordWire]
    family_members_by_key: dict[str, tuple[AgentArtifactRecordWire, ...]]
    clan_members_by_key: dict[str, tuple[AgentArtifactRecordWire, ...]]
    identity: AgentIdentitySnapshot


def _load_agent_owner_view() -> _AgentOwnerView:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )
    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
    from sase.core.paths import sase_projects_dir

    identity = AgentIdentitySnapshot.current()
    snapshot = scan_agent_artifacts(
        sase_projects_dir(),
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=False,
            only_workflow_dirs=("ace-run",),
        ),
    )
    records_by_artifact_dir: dict[str, AgentArtifactRecordWire] = {}
    family_members: dict[str, list[AgentArtifactRecordWire]] = {}
    clan_members: dict[str, list[AgentArtifactRecordWire]] = {}
    for record in snapshot.records:
        records_by_artifact_dir[_normalized_path_key(record.artifact_dir)] = record
        meta = record.agent_meta
        if meta is None:
            continue
        family_name = meta.agent_family or (
            meta.workflow_name if meta.agent_family_role else None
        )
        if family_name:
            key = current_owner_agent_name_key(family_name, identity)
            family_members.setdefault(key, []).append(record)
        if meta.agent_clan:
            key = current_owner_agent_name_key(meta.agent_clan, identity)
            clan_members.setdefault(key, []).append(record)

    return _AgentOwnerView(
        records_by_artifact_dir=records_by_artifact_dir,
        family_members_by_key={
            key: tuple(value) for key, value in family_members.items()
        },
        clan_members_by_key={key: tuple(value) for key, value in clan_members.items()},
        identity=identity,
    )


def _normalized_path_key(value: object) -> str:
    return str(Path(str(value)).expanduser().resolve(strict=False))


def _classify_slot_owner(
    slot: BeadWorkSlot,
    owner: dict[str, object],
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...] | None:
    container_kind = owner.get("container_kind")
    if container_kind == "family":
        return _classify_family_owner(
            slot,
            bead_assignees=bead_assignees,
            view=view,
        )
    if container_kind == "clan":
        return _classify_clan_owner(
            slot,
            bead_assignees=bead_assignees,
            view=view,
        )

    record = _record_for_owner(owner, view)
    if record is None:
        return (
            _classify_stale_registry_owner(
                slot,
                owner,
                bead_assignees=bead_assignees,
            ),
        )
    return (
        _classify_artifact_record(
            slot,
            record,
            owner_name=slot.owner_name,
            bead_assignees=bead_assignees,
        ),
    )


def _record_for_owner(
    owner: dict[str, object],
    view: _AgentOwnerView,
) -> AgentArtifactRecordWire | None:
    artifacts_dir = owner.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return view.records_by_artifact_dir.get(_normalized_path_key(artifacts_dir))


def _classify_family_owner(
    slot: BeadWorkSlot,
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...]:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    key = current_owner_agent_name_key(slot.owner_name, view.identity)
    members = view.family_members_by_key.get(key, ())
    if not members:
        return (
            CleanupTarget(
                name=slot.owner_name,
                action="RELEASE",
                current_state="stale",
                detail=f"orphaned family reservation for bead {slot.expected_bead_id}",
                expected_bead_id=slot.expected_bead_id,
                slot_id=slot.slot_id,
            ),
        )

    member_targets = tuple(
        _classify_artifact_record(
            slot,
            member,
            owner_name=_record_agent_name(member) or slot.owner_name,
            bead_assignees=bead_assignees,
        )
        for member in members
    )
    if any(target.preserved for target in member_targets):
        preserved = next(target for target in member_targets if target.preserved)
        return (
            CleanupTarget(
                name=slot.owner_name,
                action="PRESERVE",
                current_state=preserved.current_state,
                detail=f"family member {preserved.name} {preserved.detail}",
                expected_bead_id=slot.expected_bead_id,
                slot_id=slot.slot_id,
                artifacts_dir=preserved.artifacts_dir,
                generation=preserved.generation,
            ),
        )
    return member_targets


def _classify_clan_owner(
    slot: BeadWorkSlot,
    *,
    bead_assignees: dict[str, str],
    view: _AgentOwnerView,
) -> tuple[CleanupTarget, ...] | None:
    from sase.core.agent_identity_facade import current_owner_agent_name_key

    key = current_owner_agent_name_key(slot.owner_name, view.identity)
    members = view.clan_members_by_key.get(key, ())
    if members and slot.allow_populated_clan_skip:
        return None
    if members:
        raise ForcedReuseCleanupError(
            f"agent name '{slot.owner_name}' is reserved by a populated clan "
            "container and cannot be force-reused; retry after the concrete "
            "member finishes or dismiss the conflicting clan"
        )
    return (
        CleanupTarget(
            name=slot.owner_name,
            action="RELEASE",
            current_state="stale",
            detail=f"orphaned clan reservation for bead {slot.expected_bead_id}",
            expected_bead_id=slot.expected_bead_id,
            slot_id=slot.slot_id,
        ),
    )


def _classify_artifact_record(
    slot: BeadWorkSlot,
    record: AgentArtifactRecordWire,
    *,
    owner_name: str,
    bead_assignees: dict[str, str],
) -> CleanupTarget:
    _require_record_bead(slot, record, owner_name=owner_name)
    _require_compatible_assignee(
        slot,
        owner_name=owner_name,
        bead_assignees=bead_assignees,
    )

    current_state = _record_current_state(record)
    detail = f"for bead {slot.expected_bead_id} at {record.artifact_dir}"
    generation = str(getattr(record, "timestamp", ""))
    artifacts_dir = str(getattr(record, "artifact_dir", ""))
    if current_state == "WAITING":
        action: CleanupAction = "KILL"
    elif current_state.startswith("FAILED"):
        action = "REMOVE"
    elif _record_is_live(record):
        action = "PRESERVE"
    else:
        action = "REMOVE"
    return CleanupTarget(
        name=owner_name,
        action=action,
        current_state=current_state,
        detail=detail,
        expected_bead_id=slot.expected_bead_id,
        slot_id=slot.slot_id,
        artifacts_dir=artifacts_dir,
        generation=generation,
    )


def _classify_stale_registry_owner(
    slot: BeadWorkSlot,
    owner: dict[str, object],
    *,
    bead_assignees: dict[str, str],
) -> CleanupTarget:
    _require_compatible_assignee(
        slot,
        owner_name=slot.owner_name,
        bead_assignees=bead_assignees,
    )
    state = owner.get("state")
    current_state = (
        state
        if isinstance(state, str) and state not in {"active", "done"}
        else "completed"
        if state == "done"
        else "interrupted"
    )
    path = owner.get("bundle_path") or owner.get("artifacts_dir")
    detail = (
        f"for bead {slot.expected_bead_id} at {path}"
        if isinstance(path, str) and path
        else f"stored owner for bead {slot.expected_bead_id}"
    )
    return CleanupTarget(
        name=slot.owner_name,
        action="REMOVE",
        current_state=current_state,
        detail=detail,
        expected_bead_id=slot.expected_bead_id,
        slot_id=slot.slot_id,
    )


def _record_agent_name(record: AgentArtifactRecordWire) -> str | None:
    meta = getattr(record, "agent_meta", None)
    value = getattr(meta, "name", None)
    return value if isinstance(value, str) and value else None


def _record_bead_ids(record: AgentArtifactRecordWire) -> set[str]:
    meta = getattr(record, "agent_meta", None)
    if meta is None:
        return set()
    return {
        value
        for value in (
            getattr(meta, "bead_id", None),
            getattr(meta, "phase_bead_id", None),
            getattr(meta, "epic_bead_id", None),
        )
        if isinstance(value, str) and value
    }


def _require_record_bead(
    slot: BeadWorkSlot,
    record: AgentArtifactRecordWire,
    *,
    owner_name: str,
) -> None:
    bead_ids = _record_bead_ids(record)
    if slot.expected_bead_id in bead_ids:
        return
    observed = ", ".join(sorted(bead_ids)) or "none"
    raise ForcedReuseCleanupError(
        f"agent owner '{owner_name}' is not associated with expected bead "
        f"{slot.expected_bead_id}; observed bead association(s): {observed}"
    )


def _require_compatible_assignee(
    slot: BeadWorkSlot,
    *,
    owner_name: str,
    bead_assignees: dict[str, str],
) -> None:
    assignee = bead_assignees.get(slot.expected_bead_id, "")
    if not assignee:
        return
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_key,
    )

    identity = AgentIdentitySnapshot.current()
    allowed = {owner_name}
    if slot.launch_name:
        allowed.add(slot.launch_name)
    assignee_key = current_owner_agent_name_key(assignee, identity)
    if assignee_key in {
        current_owner_agent_name_key(name, identity) for name in allowed
    }:
        return
    raise ForcedReuseCleanupError(
        f"bead {slot.expected_bead_id} is assigned to {assignee}, which does "
        f"not match the relaunch owner {owner_name}"
    )


def _record_current_state(record: AgentArtifactRecordWire) -> str:
    done = getattr(record, "done", None)
    if getattr(record, "has_done_marker", False):
        outcome = getattr(done, "outcome", None)
        if outcome == "failed":
            return "FAILED"
        if isinstance(outcome, str) and outcome:
            return outcome.upper()
        return "DONE"
    if _record_is_live(record):
        from sase.agent.running_listing import active_status_for_record

        status = active_status_for_record(record)
        if status:
            return status
        raise ForcedReuseCleanupError(
            f"agent owner at {record.artifact_dir} has unknown live state"
        )
    return "interrupted"


def _record_is_live(record: AgentArtifactRecordWire) -> bool:
    if getattr(record, "has_done_marker", False):
        return False
    meta = getattr(record, "agent_meta", None)
    if meta is None:
        return False
    meta_dict: dict[str, object] = {}
    pid = getattr(meta, "pid", None)
    if pid is not None:
        meta_dict["pid"] = pid
    stopped_at = getattr(meta, "stopped_at", None)
    if stopped_at is not None:
        meta_dict["stopped_at"] = stopped_at
    from sase.agent.names import is_process_alive

    return is_process_alive(meta_dict, Path(str(record.artifact_dir)))


def prepare_selected_bead_work_force_reuse(
    query: str,
    *,
    selection: _BeadWorkLaunchSelection,
    bead_assignees: dict[str, str],
) -> str:
    """Guardedly clean only the replacement owners selected for bead work."""
    from sase.agent.launch_validation import (
        force_reuse_owner_names,
        rewrite_force_reuse_name_directives,
    )

    segments = query.split("\n---\n") if query else []
    directive_names = set(force_reuse_owner_names(segments))
    if directive_names != set(selection.launch_names):
        raise ForcedReuseCleanupError(
            "rendered bead-work prompt force-reuse names "
            f"{sorted(directive_names)} do not match the selected launch names "
            f"{sorted(selection.launch_names)}; aborting forced reuse cleanup"
        )

    for target in selection.destructive_targets:
        _verify_cleanup_target_still_selected(
            target,
            selection=selection,
            bead_assignees=bead_assignees,
        )
        if target.action == "RELEASE":
            _release_selected_stale_container(target)
            continue
        wipe_force_reuse_owner(target.name, allow_container_skip=False)
    return rewrite_force_reuse_name_directives(query)


def revalidate_bead_work_launch_selection(
    previous: _BeadWorkLaunchSelection,
    *,
    bead_assignees: dict[str, str],
) -> _BeadWorkLaunchSelection:
    """Rescan owners and ensure cleanup does not broaden after confirmation."""
    current = _select_bead_work_launch(
        slots=previous.slots,
        bead_assignees=bead_assignees,
    )

    previous_targets = {
        _target_stability_key(target): target for target in previous.targets
    }
    for target in current.targets:
        prior = previous_targets.get(_target_stability_key(target))
        if prior is None:
            raise ForcedReuseCleanupError(
                "bead-work owner changed after cleanup preview; rerun to review "
                f"the new owner for {target.name}"
            )
        if target.destructive and not prior.destructive:
            raise ForcedReuseCleanupError(
                "bead-work cleanup would become destructive after preview; "
                f"rerun to review {target.name}"
            )
        if target.destructive and (
            target.artifacts_dir != prior.artifacts_dir
            or target.generation != prior.generation
            or target.expected_bead_id != prior.expected_bead_id
        ):
            raise ForcedReuseCleanupError(
                "bead-work cleanup target changed after preview; rerun to "
                f"review {target.name}"
            )
        if prior.destructive and target.preserved:
            # A waiting owner started running after preview. This is a safe
            # shrink: the owner is retained and its replacement segment drops.
            continue
        if target.destructive and target.action != prior.action:
            raise ForcedReuseCleanupError(
                "bead-work cleanup action changed after preview; rerun to "
                f"review {target.name}"
            )
    return current


def _target_stability_key(target: CleanupTarget) -> tuple[str, str, str]:
    return (target.slot_id, target.name, target.expected_bead_id)


def _verify_cleanup_target_still_selected(
    target: CleanupTarget,
    *,
    selection: _BeadWorkLaunchSelection,
    bead_assignees: dict[str, str],
) -> None:
    slot = next(
        (
            item
            for item in selection.slots
            if item.slot_id == target.slot_id and item.owner_name == target.name
        ),
        None,
    )
    if slot is None:
        # Family cleanup targets are concrete members rather than the logical
        # family slot. In that case, revalidating the full selection below is
        # the authoritative check.
        current = revalidate_bead_work_launch_selection(
            selection,
            bead_assignees=bead_assignees,
        )
    else:
        current = _select_bead_work_launch(
            slots=(slot,),
            bead_assignees=bead_assignees,
        )
    matching = {
        _target_stability_key(item): item for item in current.destructive_targets
    }.get(_target_stability_key(target))
    if matching is None:
        raise ForcedReuseCleanupError(
            f"bead-work cleanup target {target.name} is no longer eligible for "
            "destructive cleanup"
        )
    if (
        matching.action != target.action
        or matching.current_state != target.current_state
        or matching.artifacts_dir != target.artifacts_dir
        or matching.generation != target.generation
    ):
        raise ForcedReuseCleanupError(
            f"bead-work cleanup target {target.name} changed before wipe; rerun"
        )


def _release_selected_stale_container(target: CleanupTarget) -> None:
    container_kind: Literal["family", "clan"] = (
        "clan" if "clan" in target.detail else "family"
    )
    release_stale_container(target.name, container_kind=container_kind)
