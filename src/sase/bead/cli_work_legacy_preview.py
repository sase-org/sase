"""Compatibility cleanup preview for legacy bead-work force reuse."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.bead.cli_work_cleanup_types import CleanupPreview


def preview_legacy_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
) -> CleanupPreview:
    """Describe owners affected by the older name-only force-reuse contract."""
    from sase.agent.launch_validation import force_reuse_owner_names
    from sase.agent.names import (
        find_agent_clan,
        find_agent_family,
        find_named_agent,
        get_live_agent_name_subset,
        lookup_registered_name,
    )
    from sase.bead.cli_work_cleanup_types import CleanupPreview, CleanupTarget
    from sase.bead.cli_work_name_cleanup import ForcedReuseCleanupError

    directive_names = force_reuse_owner_names(query.split("\n---\n"))
    if set(directive_names) != set(expected_names):
        raise ForcedReuseCleanupError(
            "rendered bead-work prompt force-reuse names "
            f"{sorted(directive_names)} do not match the planned agent names "
            f"{sorted(expected_names)}; aborting forced reuse preview"
        )

    target_names = [*directive_names]
    target_names.extend(
        name for name in sorted(extra_cleanup_names) if name not in directive_names
    )
    live_names = get_live_agent_name_subset(set(target_names))
    targets: list[CleanupTarget] = []

    for name in target_names:
        owner = lookup_registered_name(name)
        if owner is None:
            continue
        container_kind = owner.get("container_kind")
        if container_kind == "family":
            family = find_agent_family(name)
            members = (
                tuple(
                    member
                    for member in family.members
                    if isinstance(member.name, str)
                    and member.name
                    and member.name != name
                )
                if family is not None
                else ()
            )
            if not members:
                targets.append(
                    CleanupTarget(
                        name=name,
                        action="RELEASE",
                        current_state="stale",
                        detail="orphaned family reservation",
                    )
                )
                continue
            member_names = {member.name for member in members}
            member_live_names = get_live_agent_name_subset(member_names)
            for member in members:
                if not isinstance(member.name, str) or not member.name:
                    continue
                if member.name in member_live_names:
                    targets.append(
                        CleanupTarget(
                            name=member.name,
                            action="KILL",
                            current_state="running",
                            detail=f"at {member_live_names[member.name]}",
                        )
                    )
                    continue
                targets.append(
                    CleanupTarget(
                        name=member.name,
                        action="REMOVE",
                        current_state=member.outcome or "interrupted",
                        detail=f"at {member.artifacts_dir}",
                    )
                )
            continue
        if container_kind == "clan":
            clan = find_agent_clan(name)
            if clan is None or not clan.members:
                targets.append(
                    CleanupTarget(
                        name=name,
                        action="RELEASE",
                        current_state="stale",
                        detail="orphaned clan reservation",
                    )
                )
            # A populated legacy epic clan is intentionally kept and joined.
            # Populated unexpected clans remain a hard cleanup error, but are
            # not themselves destructive targets.
            continue

        agent = find_named_agent(name)
        if name in live_names:
            targets.append(
                CleanupTarget(
                    name=name,
                    action="KILL",
                    current_state="running",
                    detail=f"at {live_names[name]}",
                )
            )
            continue
        if agent is not None:
            targets.append(
                CleanupTarget(
                    name=name,
                    action="REMOVE",
                    current_state=agent.outcome or "completed",
                    detail=f"at {agent.artifacts_dir}",
                )
            )
            continue

        state = owner.get("state")
        current_state = (
            state
            if isinstance(state, str) and state not in {"active", "done"}
            else "completed"
            if state == "done"
            else "interrupted"
        )
        path = owner.get("artifacts_dir") or owner.get("bundle_path")
        detail = f"at {path}" if isinstance(path, str) and path else "stored owner"
        targets.append(
            CleanupTarget(
                name=name,
                action="REMOVE",
                current_state=current_state,
                detail=detail,
            )
        )

    return CleanupPreview(targets=tuple(targets))
