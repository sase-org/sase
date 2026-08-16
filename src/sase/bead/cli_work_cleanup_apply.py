"""Guarded execution of a confirmed bead-work cleanup selection."""

from __future__ import annotations

from typing import Literal

from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import (
    BeadWorkLaunchSelection,
    CleanupTarget,
)
from sase.bead.cli_work_name_cleanup import (
    ForcedReuseCleanupError,
    release_stale_container,
    wipe_force_reuse_owner,
)


def prepare_selected_bead_work_force_reuse(
    query: str,
    *,
    selection: BeadWorkLaunchSelection,
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
    previous: BeadWorkLaunchSelection,
    *,
    bead_assignees: dict[str, str],
) -> BeadWorkLaunchSelection:
    """Rescan owners and ensure cleanup does not broaden after confirmation."""
    current = select_bead_work_launch(
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
    selection: BeadWorkLaunchSelection,
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
        current = select_bead_work_launch(
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
