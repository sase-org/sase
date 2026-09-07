"""Guarded execution of a confirmed bead-work cleanup selection."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import (
    BeadWorkLaunchSelection,
    BeadWorkSlot,
    CleanupTarget,
    format_blocked_cleanup_error,
)
from sase.bead.cli_work_name_cleanup import (
    ForcedReuseCleanupBatchError,
    ForcedReuseCleanupError,
    release_stale_containers,
    wipe_force_reuse_owners,
)

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.core.agent_scan_wire import AgentArtifactRecordWire


def prepare_selected_bead_work_force_reuse(
    query: str,
    *,
    selection: BeadWorkLaunchSelection,
    bead_assignees: dict[str, str],
    timer: LaunchTimingRecorder | None = None,
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

    if selection.blocked_targets:
        raise ForcedReuseCleanupError(
            format_blocked_cleanup_error(selection.blocked_targets)
        )

    # Verify every destructive target before wiping any of them: a stale
    # target discovered mid-loop must not leave earlier targets already
    # wiped with nothing relaunched in their place.
    destructive_targets = selection.destructive_targets
    for index, target in enumerate(destructive_targets, start=1):
        if timer is None:
            _verify_cleanup_target_still_selected(
                target,
                selection=selection,
                bead_assignees=bead_assignees,
            )
        else:
            with timer.stage(
                "target_revalidation",
                completed_owners=index - 1,
                total_owners=len(destructive_targets),
                owner_name=target.name,
            ):
                _verify_cleanup_target_still_selected(
                    target,
                    selection=selection,
                    bead_assignees=bead_assignees,
                    timer=timer,
                )

    try:
        if timer is None:
            _apply_cleanup_targets(destructive_targets)
        else:
            with timer.stage(
                "process_cleanup",
                completed_owners=0,
                total_owners=len(destructive_targets),
                action="batch",
            ):
                _apply_cleanup_targets(destructive_targets, timer=timer)
    except ForcedReuseCleanupBatchError as exc:
        if not exc.completed_names:
            raise
        raise ForcedReuseCleanupError(
            f"{exc}; bead-work cleanup already wiped "
            f"{', '.join(exc.completed_names)} before this failure, so the "
            "epic now has no live agent for those owners until this is rerun"
        ) from exc
    return rewrite_force_reuse_name_directives(query)


def revalidate_bead_work_launch_selection(
    previous: BeadWorkLaunchSelection,
    *,
    bead_assignees: dict[str, str],
    timer: LaunchTimingRecorder | None = None,
) -> BeadWorkLaunchSelection:
    """Rescan owners and ensure cleanup does not broaden after confirmation."""
    current = select_bead_work_launch(
        slots=previous.slots,
        bead_assignees=bead_assignees,
        timer=timer,
    )
    if current.blocked_targets:
        raise ForcedReuseCleanupError(
            format_blocked_cleanup_error(current.blocked_targets)
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
    selection: BeadWorkLaunchSelection,
    bead_assignees: dict[str, str],
    timer: LaunchTimingRecorder | None = None,
) -> None:
    del timer
    slot = next(
        (item for item in selection.slots if item.slot_id == target.slot_id),
        None,
    )
    if slot is None:
        raise ForcedReuseCleanupError(
            f"bead-work cleanup target {target.name} is no longer eligible for "
            "destructive cleanup"
        )
    matching = _fresh_cleanup_target(target, slot=slot, bead_assignees=bead_assignees)
    if matching is None or not matching.destructive:
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


def _fresh_cleanup_target(
    target: CleanupTarget,
    *,
    slot: BeadWorkSlot,
    bead_assignees: dict[str, str],
) -> CleanupTarget | None:
    from sase.bead.cli_work_cleanup_targets import (
        TargetedOwnerLookup,
        classify_artifact_record,
        classify_stale_registry_owner,
        lookup_registry_entry_without_rebuild,
    )
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    view = TargetedOwnerLookup(identity=AgentIdentitySnapshot.current())
    if target.artifacts_dir:
        record = _scan_cleanup_target_artifact(target.artifacts_dir)
        if record is None:
            return None
        membership: Literal["registry", "family"] = (
            "family" if slot.owner_name != target.name else "registry"
        )
        try:
            return classify_artifact_record(
                slot,
                record,
                owner_name=target.name,
                bead_assignees=bead_assignees,
                membership=membership,
                view=view,
            )
        except ForcedReuseCleanupError:
            return None

    owner = lookup_registry_entry_without_rebuild(target.name, identity=view.identity)
    if owner is None:
        return None
    artifacts_dir = owner.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        return None
    if target.action == "RELEASE":
        return target
    return classify_stale_registry_owner(
        slot, owner, bead_assignees=bead_assignees, view=view
    )


def _scan_cleanup_target_artifact(
    artifacts_dir: str,
) -> AgentArtifactRecordWire | None:
    from sase.core.agent_scan_facade import scan_agent_artifact_dirs
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
    from sase.core.paths import sase_projects_dir

    snapshot = scan_agent_artifact_dirs(
        sase_projects_dir(),
        [artifacts_dir],
        AgentArtifactScanOptionsWire(include_prompt_step_markers=False),
    )
    return snapshot.records[0] if snapshot.records else None


def _apply_cleanup_targets(
    targets: Sequence[CleanupTarget],
    *,
    timer: LaunchTimingRecorder | None = None,
) -> None:
    wipe_names = tuple(
        dict.fromkeys(target.name for target in targets if target.action != "RELEASE")
    )
    release_targets = tuple(
        (_release_container_name(target), _release_container_kind(target))
        for target in targets
        if target.action == "RELEASE"
    )
    if timer is None:
        _apply_cleanup_batches(wipe_names, release_targets)
        return

    with timer.stage("closure_planning", total_owners=len(wipe_names)):
        with timer.stage("index_maintenance", total_owners=len(targets)):
            _apply_cleanup_batches(wipe_names, release_targets)


def _apply_cleanup_batches(
    wipe_names: tuple[str, ...],
    release_targets: tuple[tuple[str, Literal["family", "clan"]], ...],
) -> None:
    if wipe_names:
        wipe_force_reuse_owners(wipe_names, allow_container_skip=False)
    if release_targets:
        release_stale_containers(release_targets)


def _release_container_name(target: CleanupTarget) -> str:
    return target.name


def _release_container_kind(target: CleanupTarget) -> Literal["family", "clan"]:
    return "clan" if "clan" in target.detail else "family"
