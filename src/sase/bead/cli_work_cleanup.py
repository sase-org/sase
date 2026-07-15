"""Rollback and deterministic-name cleanup helpers for ``sase bead work``."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from sase.bead.cli_common import auto_commit_bead_store

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.model import Status
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
    claimed: list[tuple[str, Status, str]],
    *,
    unmark_ready: bool,
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Best-effort: terminate already-spawned agents and revert pre-claims."""
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    target = "pre-claims and is_ready_to_work flag" if unmark_ready else "pre-claims"
    print(
        f"Rolling back {target}. If rollback also fails, fix the affected "
        "bead status/assignee fields manually.",
        file=sys.stderr,
    )
    for bead_id, prior_status, prior_assignee in reversed(claimed):
        try:
            proj.update(
                bead_id,
                status=prior_status.value,
                assignee=prior_assignee,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to roll back pre-claim on {bead_id}: {exc}",
                file=sys.stderr,
            )
    if unmark_ready:
        try:
            proj.unmark_ready_to_work(epic_id)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to roll back is_ready_to_work on {epic_id}: {exc}",
                file=sys.stderr,
            )
    message = f"chore(beads): rollback work launch {epic_id}"
    if no_push:
        auto_commit_bead_store(message, push_after_commit=False)
    else:
        auto_commit_bead_store(message)


class ForcedReuseCleanupError(RuntimeError):
    """Raised when forced bead-work name reuse cleanup cannot be completed."""


def warn_force_reuse_collisions(collisions: dict[str, str]) -> None:
    """Warn (for ``--dry-run``) which live agents a real launch would replace."""
    if not collisions:
        return
    print(
        "\nWarning: these live agents would be force-reused (terminated) "
        "on a live launch:",
        file=sys.stderr,
    )
    for name, path in sorted(collisions.items()):
        print(f"  {name} (already running at {path})", file=sys.stderr)


def prepare_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
) -> str:
    """Wipe deterministic bead-work owners and rewrite the prompt for the launcher.

    Bead work is a trusted, confirmed relaunch surface: it deliberately reuses
    the deterministic phase/land names it just computed. This parses the
    ``%name:!<n>`` directives out of *query*, verifies they match the plan's
    *expected_names*, then wipes each owner (plus any *extra_cleanup_names* such
    as a legacy land owner that the new prompt no longer names). Old owners are
    replaced regardless of state — completed, dismissed, or still live (the wipe
    terminates live owners).

    Unlike a best-effort wipe, this fails *before* the caller performs any bead
    mutation: it raises :class:`ForcedReuseCleanupError` when a wipe raises, when
    an :class:`AgentNameWipeResult` reports errors, or when the registry still
    reports an owner for a force-reused name after the rebuild. On success it
    rewrites ``%name:!<n>`` to ordinary ``%name:<n>`` so
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

    cleanup_order = list(directive_names)
    cleanup_order.extend(
        name for name in sorted(extra_cleanup_names) if name not in directive_names
    )
    for name in cleanup_order:
        _wipe_force_reuse_owner(name)
    return rewrite_force_reuse_name_directives(query)


def _wipe_force_reuse_owner(name: str) -> None:
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
    if result.found and name not in result.registry_names_removed:
        raise ForcedReuseCleanupError(
            f"forced reuse cleanup left agent name '{name}' reserved after "
            "rebuild; resolve the conflicting owner and retry"
        )
