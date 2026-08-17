"""Preview and launch selection for deterministic bead-work cleanup."""

from __future__ import annotations

from collections.abc import Sequence

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

    selection = select_bead_work_launch(
        slots=tuple(slots),
        bead_assignees=bead_assignees,
    )
    return CleanupPreview(targets=selection.targets, selection=selection)


def select_bead_work_launch(
    *,
    slots: tuple[BeadWorkSlot, ...],
    bead_assignees: dict[str, str],
) -> BeadWorkLaunchSelection:
    """Classify current owners and compute the relaunch subset."""
    from sase.agent.names import lookup_registered_name

    view = load_agent_owner_view()
    targets: list[CleanupTarget] = []
    owner_present_by_slot: dict[str, int] = {}
    preserved_slots: set[str] = set()
    blocked_slots: set[str] = set()

    for slot in slots:
        owner = lookup_registered_name(slot.owner_name)
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
