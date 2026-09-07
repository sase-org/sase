"""Preview and launch selection for deterministic bead-work cleanup."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.cli_work_cleanup_targets import (
    classify_slot_owner,
    load_agent_owner_view,
)
from sase.bead.cli_work_cleanup_types import (
    BeadWorkLaunchSelection,
    BeadWorkSlot,
    CleanupPreview,
    CleanupTarget,
)
from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder


def preview_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
    expected_bead_ids: dict[str, str] | None = None,
    bead_assignees: dict[str, str] | None = None,
    timer: LaunchTimingRecorder | None = None,
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
            timer=timer,
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
    timer: LaunchTimingRecorder | None = None,
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

    selection = select_bead_work_launch(
        slots=tuple(slots),
        bead_assignees=bead_assignees,
        timer=timer,
    )
    return CleanupPreview(targets=selection.targets, selection=selection)


def select_bead_work_launch(
    *,
    slots: tuple[BeadWorkSlot, ...],
    bead_assignees: dict[str, str],
    timer: LaunchTimingRecorder | None = None,
) -> BeadWorkLaunchSelection:
    """Classify current owners and compute the relaunch subset."""
    from sase.agent.names import registered_name_reservation_snapshot

    targeted = _select_preserved_slots_from_registry(
        slots, bead_assignees=bead_assignees, timer=timer
    )
    if targeted is not None:
        return targeted

    if timer is None:
        view = load_agent_owner_view()
        registry_snapshot = registered_name_reservation_snapshot()
    else:
        with timer.stage("owner_discovery", full_scans=1):
            view = load_agent_owner_view()
        with timer.stage("registry_read", relevant_row_reads=len(slots)):
            registry_snapshot = registered_name_reservation_snapshot()
    targets: list[CleanupTarget] = []
    owner_present_by_slot: dict[str, int] = {}
    preserved_slots: set[str] = set()
    blocked_slots: set[str] = set()

    for slot in slots:
        owner = registry_snapshot.lookup(slot.owner_name)
        if owner is None:
            continue
        try:
            classified = classify_slot_owner(
                slot,
                owner,
                bead_assignees=bead_assignees,
                view=view,
            )
        except ForcedReuseCleanupError as exc:
            classified = (
                CleanupTarget(
                    name=slot.owner_name,
                    action="BLOCKED",
                    current_state="blocked",
                    detail=str(exc),
                    expected_bead_id=slot.expected_bead_id,
                    slot_id=slot.slot_id,
                ),
            )
        if classified is None:
            continue
        owner_present_by_slot[slot.slot_id] = (
            owner_present_by_slot.get(slot.slot_id, 0) + 1
        )
        if any(target.blocked for target in classified):
            blocked_slots.add(slot.slot_id)
            targets.extend(target for target in classified if not target.destructive)
            continue
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
        if slot.slot_id in preserved_slots or slot.slot_id in blocked_slots:
            continue
        if slot.launch_name is not None:
            launch_names.add(slot.launch_name)

    return BeadWorkLaunchSelection(
        slots=slots,
        targets=tuple(targets),
        launch_names=frozenset(launch_names),
    )


def _select_preserved_slots_from_registry(
    slots: tuple[BeadWorkSlot, ...],
    *,
    bead_assignees: dict[str, str],
    timer: LaunchTimingRecorder | None,
) -> BeadWorkLaunchSelection | None:
    """Return an all-preserved selection without scanning unrelated history.

    This is the already-running fast path: every logical slot must already be a
    concrete registry owner whose targeted artifact check is PRESERVE. Family
    and clan containers, missing owners, and destructive or blocked states fall
    through to the full archive view.
    """
    from sase.agent.names._registry_store import read_registry, registry_path
    from sase.bead.cli_work_cleanup_targets import classify_artifact_record
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        current_owner_agent_name_lookup_candidates,
    )
    from sase.core.agent_scan_facade import scan_agent_artifact_dirs
    from sase.core.agent_scan_wire import (
        AgentArtifactRecordWire,
        AgentArtifactScanOptionsWire,
    )
    from sase.core.paths import sase_projects_dir

    if not slots:
        return None
    data = read_registry(registry_path())
    if data is None:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None

    identity = AgentIdentitySnapshot.current()
    targets: list[CleanupTarget] = []
    artifact_dirs: list[str] = []
    owners: list[tuple[BeadWorkSlot, dict[str, object]]] = []
    for slot in slots:
        owner = None
        for candidate in current_owner_agent_name_lookup_candidates(
            slot.owner_name, identity
        ):
            entry = entries.get(candidate)
            if isinstance(entry, dict):
                owner = dict(entry)
                break
        if owner is None:
            if slot.allow_populated_clan_skip:
                continue
            return None
        if owner.get("container_kind"):
            return None
        artifacts_dir = owner.get("artifacts_dir")
        if not isinstance(artifacts_dir, str) or not artifacts_dir:
            return None
        artifact_dirs.append(artifacts_dir)
        owners.append((slot, owner))

    if timer is None:
        snapshot = scan_agent_artifact_dirs(
            sase_projects_dir(),
            artifact_dirs,
            AgentArtifactScanOptionsWire(include_prompt_step_markers=False),
        )
    else:
        with timer.stage(
            "owner_discovery",
            full_scans=0,
            targeted_artifact_reads=len(artifact_dirs),
        ):
            snapshot = scan_agent_artifact_dirs(
                sase_projects_dir(),
                artifact_dirs,
                AgentArtifactScanOptionsWire(include_prompt_step_markers=False),
            )
    records_by_dir: dict[str, AgentArtifactRecordWire] = {}
    records_by_name: dict[str, AgentArtifactRecordWire] = {}
    for record in snapshot.records:
        records_by_dir[
            str(Path(str(record.artifact_dir)).expanduser().resolve(strict=False))
        ] = record
        meta = getattr(record, "agent_meta", None)
        name = getattr(meta, "name", None)
        if isinstance(name, str) and name:
            records_by_name[name] = record
    for index, (slot, _owner) in enumerate(owners):
        artifact_key = str(
            Path(artifact_dirs[index]).expanduser().resolve(strict=False)
        )
        matched = records_by_dir.get(artifact_key) or records_by_name.get(
            slot.owner_name
        )
        if matched is None:
            return None
        try:
            classified = classify_artifact_record(
                slot,
                matched,
                owner_name=slot.owner_name,
                bead_assignees=bead_assignees,
                membership="registry",
                identity=identity,
            )
        except ForcedReuseCleanupError:
            return None
        if not classified.preserved:
            return None
        targets.append(classified)
    return BeadWorkLaunchSelection(
        slots=slots,
        targets=tuple(targets),
        launch_names=frozenset(),
    )
