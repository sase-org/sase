"""Rollback and deterministic-name cleanup helpers for ``sase bead work``."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.bead.cli_common import auto_commit_bead_store

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.project import BeadProject


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
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Persist recoverable state after a failed epic-work agent launch.

    A zero-spawn failure may undo readiness when this launch set it. Once any
    runner has spawned, readiness and runner-owned claims are retained; only
    the partial launch is terminated.
    """
    spawned_any = bool(launched_results or launched_pids)
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    if spawned_any:
        print(
            "Terminated the partially launched agents; preserving "
            "is_ready_to_work and any runner-owned bead claims for recovery.",
            file=sys.stderr,
        )
    elif marked_ready_this_run:
        print(
            "No agents were spawned; restoring the epic's prior "
            "is_ready_to_work state.",
            file=sys.stderr,
        )
        try:
            proj.unmark_ready_to_work(epic_id)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to restore is_ready_to_work on {epic_id}: {exc}",
                file=sys.stderr,
            )
    else:
        print(
            "No agents were spawned; preserving the epic's existing "
            "is_ready_to_work state.",
            file=sys.stderr,
        )

    message = f"chore(beads): recover failed work launch {epic_id}"
    if no_push:
        auto_commit_bead_store(message, push_after_commit=False)
    else:
        auto_commit_bead_store(message)


class ForcedReuseCleanupError(RuntimeError):
    """Raised when forced bead-work name reuse cleanup cannot be completed."""


@dataclass(frozen=True)
class CleanupTarget:
    """One existing owner or reservation affected by forced name reuse."""

    name: str
    action: Literal["KILL", "REMOVE", "RELEASE"]
    current_state: str
    detail: str


@dataclass(frozen=True)
class CleanupPreview:
    """Read-only preview of destructive forced-reuse cleanup."""

    targets: tuple[CleanupTarget, ...]

    @property
    def has_destructive_targets(self) -> bool:
        return bool(self.targets)


def preview_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
) -> CleanupPreview:
    """Describe every owner or stale reservation a live cleanup will affect."""
    from sase.agent.launch_validation import force_reuse_owner_names
    from sase.agent.names import (
        find_agent_clan,
        find_agent_family,
        find_named_agent,
        get_live_agent_name_subset,
        lookup_registered_name,
    )

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


def prepare_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
) -> str:
    """Wipe deterministic bead-work owners and rewrite the prompt for the launcher.

    Bead work is a trusted, confirmed relaunch surface: it deliberately reuses
    the deterministic phase/land names it just computed. This parses the
    ``%id:!<n>`` directives out of *query*, verifies they match the plan's
    *expected_names*, then wipes each owner (plus any *extra_cleanup_names* such
    as a legacy land owner that the new prompt no longer names). Old owners are
    replaced regardless of state — completed, dismissed, or still live (the wipe
    terminates live owners). A family container for an expected name is resolved
    to its concrete members and wiped member-by-member. A clan container for an
    extra cleanup name is left intact because it is the epic's joinable clan
    container. A clan container for an expected phase or land name is an
    unresolvable conflict.

    Unlike a best-effort wipe, this fails *before* the caller performs any bead
    mutation: it raises :class:`ForcedReuseCleanupError` when a wipe raises, when
    an :class:`AgentNameWipeResult` reports errors, or when the registry still
    reports an owner for a force-reused name after the rebuild. On success it
    rewrites ``%id:!<n>`` to ordinary ``%id:<n>`` so
    ``validate_launch_name_requests`` accepts the prompt.
    """
    from sase.agent.launch_validation import (
        force_reuse_owner_names,
        rewrite_force_reuse_name_directives,
    )

    segments = query.split("\n---\n")
    directive_names = force_reuse_owner_names(segments)
    if set(directive_names) != set(expected_names):
        raise ForcedReuseCleanupError(
            "rendered bead-work prompt force-reuse names "
            f"{sorted(directive_names)} do not match the planned agent names "
            f"{sorted(expected_names)}; aborting forced reuse cleanup"
        )

    for name in directive_names:
        _wipe_force_reuse_owner(name, allow_container_skip=False)
    for name in sorted(extra_cleanup_names):
        if name not in directive_names:
            _wipe_force_reuse_owner(name, allow_container_skip=True)
    return rewrite_force_reuse_name_directives(query)


def _wipe_force_reuse_owner(name: str, *, allow_container_skip: bool) -> None:
    """Wipe a single deterministic owner, raising on any cleanup failure."""
    from sase.agent.names import wipe_agent_name_for_reuse

    try:
        result = wipe_agent_name_for_reuse(name)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' failed: {exc}"
        ) from exc
    if result.errors:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' reported errors: "
            + "; ".join(result.errors)
        )
    if result.skipped_container_kind:
        if result.skipped_container_kind == "family":
            _wipe_force_reuse_family(name)
            return
        if result.skipped_container_kind == "clan":
            from sase.agent.names import find_agent_clan

            try:
                clan = find_agent_clan(name)
            except Exception as exc:  # noqa: BLE001
                raise ForcedReuseCleanupError(
                    f"forced reuse cleanup could not resolve agent clan '{name}': {exc}"
                ) from exc
            if clan is None or not clan.members:
                _release_stale_container(name, container_kind="clan")
                return
            if allow_container_skip:
                return
        raise ForcedReuseCleanupError(
            f"agent name '{name}' is reserved by a "
            f"{result.skipped_container_kind} container and cannot be "
            "force-reused; dismiss or clean up the container's members, then retry"
        )
    if result.found and name not in result.registry_names_removed:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left agent name '{name}' reserved after "
            "rebuild; resolve the conflicting owner and retry"
        )


def _wipe_force_reuse_family(name: str) -> None:
    """Resolve and wipe every concrete member of a deterministic family."""
    from sase.agent.names import (
        find_agent_family,
        rebuild_name_registry,
        wipe_agent_name_for_reuse,
    )

    try:
        family = find_agent_family(name)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not resolve agent family '{name}': {exc}"
        ) from exc

    member_names = sorted(
        {
            member.name
            for member in family.members
            if isinstance(member.name, str) and member.name and member.name != name
        }
        if family is not None
        else set()
    )
    if not member_names:
        _release_stale_container(name, container_kind="family")
        return

    for member_name in member_names:
        try:
            result = wipe_agent_name_for_reuse(member_name)
        except Exception as exc:  # noqa: BLE001
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' failed: {exc}"
            ) from exc
        if result.errors:
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' reported errors: " + "; ".join(result.errors)
            )
        if result.skipped_container_kind:
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup for agent family '{name}' member "
                f"'{member_name}' resolved to a "
                f"{result.skipped_container_kind} container"
            )
        if result.found and member_name not in result.registry_names_removed:
            raise ForcedReuseCleanupError(
                f"forced reuse cleanup left agent family '{name}' member "
                f"'{member_name}' reserved after rebuild"
            )

    try:
        registry = rebuild_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent family '{name}' could not rebuild "
            f"the name registry: {exc}"
        ) from exc
    entries = registry.get("entries")
    if not isinstance(entries, dict):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for agent family '{name}' received an "
            "invalid name registry after rebuild"
        )
    residual_names = sorted({name, *member_names} & set(entries))
    if residual_names:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left agent family '{name}' reservations "
            f"after rebuild: {', '.join(residual_names)}"
        )


def _release_stale_container(
    name: str,
    *,
    container_kind: Literal["family", "clan"],
) -> None:
    """Remove an orphaned container's residual owner and verify its release."""
    from sase.agent.names import (
        is_name_reserved,
        rebuild_name_registry,
        wipe_agent_name_for_reuse,
    )

    try:
        result = wipe_agent_name_for_reuse(name, allow_stale_container=True)
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' failed: {exc}"
        ) from exc
    if result.errors:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' reported errors: " + "; ".join(result.errors)
        )
    if result.skipped_container_kind:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup could not release stale {container_kind} "
            f"reservation '{name}'"
        )

    try:
        registry = rebuild_name_registry()
    except Exception as exc:  # noqa: BLE001
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' could not rebuild the name registry: {exc}"
        ) from exc
    if not isinstance(registry.get("entries"), dict):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup for stale {container_kind} reservation "
            f"'{name}' received an invalid name registry after rebuild"
        )
    if is_name_reserved(name):
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left stale {container_kind} reservation "
            f"'{name}' reserved after rebuild"
        )
