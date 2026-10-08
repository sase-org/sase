"""Wait-dependency satisfaction and status-count queries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from sase.ace.tui._agent_completion_wait_models import (
    BEAD_COUNT_FIELDS,
    WAIT_COUNT_FIELDS,
    AgentWaitStatusMaps,
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
    ZERO_WAIT_DEPENDENCY_STATUS_COUNTS,
    parse_tribe_target,
)
from sase.agent.status_buckets import AGENT_STATUS_BUCKETS
from sase.bead_status_presentation import BEAD_STATUS_VALUES

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent
    from sase.ace.tui.models.agent_wait_beads import WaitBeadStatusSnapshot
    from sase.core.wait_dependency_resolution import TribeWaitBinding


def _has_blocking_follow_stage(agent: Agent) -> bool:
    """Return whether any armed follow target is launching or blocked.

    A resolved armed target with no persisted stage (it launched no epic)
    reports as today, so there is no flicker on ordinary agent waits. Only
    the persisted ``launching``/``blocked`` stages hold the row. Memory-only
    over the already-loaded agent: no I/O.
    """
    # Imported lazily to keep the TUI startup closure lean.
    from sase.core.wait_epic_follow_view import (
        FOLLOW_BLOCKING_STATES,
        armed_follow_targets,
        epic_follow_views,
    )

    armed = armed_follow_targets(agent)
    if not armed:
        return False
    armed_set = set(armed)
    return any(
        view.target in armed_set and view.state in FOLLOW_BLOCKING_STATES
        for view in epic_follow_views(agent)
    )


def wait_dependencies_satisfied(
    agent: Agent,
    status_buckets: Mapping[str, str] | None,
    tribe_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None = None,
) -> bool:
    """Return whether every ordinary or tribe wait target is satisfied."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)
    if wait_agent.waiting_for_beads or wait_agent.waiting_for_hoods:
        return False
    if not wait_agent.waiting_for:
        return True
    if _has_blocking_follow_stage(wait_agent):
        return False
    for name in wait_agent.waiting_for:
        tribe = parse_tribe_target(name)
        if tribe is not None:
            binding = (
                tribe_bindings.get((wait_agent.identity, name))
                if tribe_bindings is not None
                else None
            )
            if binding is None or binding.state != "bound":
                return False
        elif status_buckets is None or status_buckets.get(name) != "Done":
            return False
    return True


def has_unresolvable_wait_target(
    agent: Agent,
    tribe_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None,
) -> bool:
    """Return whether any tribe wait target is known to be unresolvable."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    if tribe_bindings is None:
        return False
    wait_agent = wait_display_agent(agent)
    for name in wait_agent.waiting_for:
        if parse_tribe_target(name) is None:
            continue
        binding = tribe_bindings.get((wait_agent.identity, name))
        if binding is not None and binding.state == "reserved":
            return True
    return False


def missing_wait_dependency_names(
    agent: Agent,
    status_buckets: Mapping[str, str] | None,
) -> tuple[str, ...] | None:
    """Return ordered agent wait targets absent from a usable status snapshot.

    ``None`` preserves the distinction between an unavailable snapshot and a
    usable snapshot where every target is known. Synthetic session, clan, and
    root rows inherit the effective wait source used by the rest of the TUI.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    if status_buckets is None:
        return None
    wait_agent = wait_display_agent(agent)
    return tuple(
        name
        for name in wait_agent.waiting_for
        if parse_tribe_target(name) is None and name not in status_buckets
    )


def wait_dependency_status_counts(
    agent: Agent,
    status_maps: AgentWaitStatusMaps,
    wait_bead_statuses: WaitBeadStatusSnapshot | None = None,
) -> WaitDependencyStatusCounts:
    """Return compact agent/bead dependency status counts for one row.

    The projection is memory-only: it uses the caller-supplied agent status
    maps and optional cached bead-status snapshot. Cold bead-cache misses are
    omitted because they are not yet evidence for an unknown target. A
    FOLLOWING target leaves the agent counts; its epics feed the separate
    follow segment from the same cached snapshot, and derived
    ``added_bead_ids`` leave the authored bead counts.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    # Imported lazily to keep the TUI startup closure lean.
    from sase.core.wait_epic_follow_view import authored_wait_beads, epic_follow_views

    wait_agent = wait_display_agent(agent)
    if (
        not wait_agent.waiting_for
        and not wait_agent.waiting_for_beads
        and not wait_agent.waiting_for_hoods
    ):
        return ZERO_WAIT_DEPENDENCY_STATUS_COUNTS

    agent_tally = dict.fromkeys((*AGENT_STATUS_BUCKETS, "unknown"), 0)
    bead_tally = dict.fromkeys((*BEAD_STATUS_VALUES, "unknown"), 0)
    follow_tally = dict.fromkeys((*BEAD_STATUS_VALUES, "unknown"), 0)

    waiting_for_set = set(wait_agent.waiting_for)
    following_targets = {
        view.target
        for view in epic_follow_views(wait_agent)
        if view.state == "following" and view.target in waiting_for_set
    }
    for name in wait_agent.waiting_for:
        if name in following_targets:
            continue
        if parse_tribe_target(name) is not None:
            continue
        clan_members = status_maps.clan_member_statuses.get(name)
        if clan_members is not None:
            for _label, bucket in clan_members:
                _increment_agent_wait_count(agent_tally, bucket)
            continue
        _increment_agent_wait_count(agent_tally, status_maps.buckets.get(name))

    if wait_bead_statuses is not None:
        for bead_id in authored_wait_beads(wait_agent):
            entry = wait_bead_statuses.entry_for(bead_id)
            if entry is None or entry.is_cold:
                continue
            _increment_bead_wait_count(bead_tally, entry.status)
        for view in epic_follow_views(wait_agent):
            if view.target not in following_targets:
                continue
            for epic_id in view.epic_ids:
                entry = wait_bead_statuses.entry_for(epic_id)
                if entry is None or entry.is_cold:
                    continue
                _increment_bead_wait_count(follow_tally, entry.status)

    agents = _agent_counts_from_tally(agent_tally)
    beads = _bead_counts_from_tally(bead_tally)
    follows = _bead_counts_from_tally(follow_tally)
    if not agents.has_any and not beads.has_any and not follows.has_any:
        return ZERO_WAIT_DEPENDENCY_STATUS_COUNTS
    return WaitDependencyStatusCounts(agents=agents, beads=beads, follows=follows)


def _is_unknown_agent_bucket(bucket: str | None) -> bool:
    """Return whether an agent wait bucket counts as an unknown dependency."""
    return bucket not in WAIT_COUNT_FIELDS


def _is_unknown_bead_status(status: str | None) -> bool:
    """Return whether a bead wait status counts as an unknown dependency."""
    return status not in BEAD_COUNT_FIELDS


def _increment_agent_wait_count(tally: dict[str, int], bucket: str | None) -> None:
    if _is_unknown_agent_bucket(bucket):
        tally["unknown"] += 1
    else:
        assert bucket is not None
        tally[bucket] += 1


def _increment_bead_wait_count(tally: dict[str, int], status: str | None) -> None:
    if _is_unknown_bead_status(status):
        tally["unknown"] += 1
    else:
        assert status is not None
        tally[status] += 1


def wait_dependency_unknown_targets(
    agent: Agent,
    status_maps: AgentWaitStatusMaps,
    wait_bead_statuses: WaitBeadStatusSnapshot | None = None,
) -> frozenset[tuple[str, str]]:
    """Return stable keys for the unknown dependencies of one row.

    Mirrors :func:`wait_dependency_status_counts`: tribe targets are skipped
    and cold bead-cache misses are omitted. Keys are ``("agent", name)`` for
    ordinary missing agents, ``("agent", "clan:label")`` for unknown clan
    members, and ``("bead", bead_id)`` for unknown bead statuses.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)
    if (
        not wait_agent.waiting_for
        and not wait_agent.waiting_for_beads
        and not wait_agent.waiting_for_hoods
    ):
        return frozenset()
    unknowns: set[tuple[str, str]] = set()
    for name in wait_agent.waiting_for:
        if parse_tribe_target(name) is not None:
            continue
        clan_targets = status_maps.clan_member_statuses.get(name)
        if clan_targets is not None:
            for label, bucket in clan_targets:
                if _is_unknown_agent_bucket(bucket):
                    unknowns.add(("agent", f"{name}:{label}"))
            continue
        if _is_unknown_agent_bucket(status_maps.buckets.get(name)):
            unknowns.add(("agent", name))
    if wait_bead_statuses is not None:
        for bead_id in wait_agent.waiting_for_beads:
            entry = wait_bead_statuses.entry_for(bead_id)
            if entry is None or entry.is_cold:
                continue
            if _is_unknown_bead_status(entry.status):
                unknowns.add(("bead", bead_id))
    return frozenset(unknowns)


def clan_unknown_wait_dependency_count(
    clan: Agent,
    status_maps: AgentWaitStatusMaps,
) -> int:
    """Return the distinct unknown-dependency count across a clan's members.

    Only ``WAITING`` members contribute, mirroring the gate in
    ``append_agent_row_status`` so the clan never shows a ``?`` that no
    visible member explains. Members are deduplicated by identity and only
    direct members are considered.
    """
    if not clan.is_clan_container:
        return 0
    from sase.ace.tui.models._agent_clan import clan_members
    from sase.ace.tui.models.agent_wait_beads import (
        cached_wait_bead_status_snapshot,
    )

    seen: set[object] = set()
    unknowns: set[tuple[str, str]] = set()
    for member in clan_members(clan):
        if member.identity in seen:
            continue
        seen.add(member.identity)
        if member.status != "WAITING":
            continue
        unknowns.update(
            wait_dependency_unknown_targets(
                member,
                status_maps,
                cached_wait_bead_status_snapshot(member),
            )
        )
    return len(unknowns)


def _agent_counts_from_tally(tally: Mapping[str, int]) -> WaitAgentStatusCounts:
    return WaitAgentStatusCounts(
        stopped=tally.get("Stopped", 0),
        failed=tally.get("Failed", 0),
        starting=tally.get("Starting", 0),
        running=tally.get("Running", 0),
        queued=tally.get("Queued", 0),
        waiting=tally.get("Waiting", 0),
        done=tally.get("Done", 0),
        unknown=tally.get("unknown", 0),
    )


def _bead_counts_from_tally(tally: Mapping[str, int]) -> WaitBeadStatusCounts:
    return WaitBeadStatusCounts(
        open=tally.get("open", 0),
        claimed=tally.get("claimed", 0),
        ready=tally.get("ready", 0),
        snoozed=tally.get("snoozed", 0),
        in_progress=tally.get("in_progress", 0),
        closed=tally.get("closed", 0),
        unknown=tally.get("unknown", 0),
    )


__all__ = [
    "clan_unknown_wait_dependency_count",
    "has_unresolvable_wait_target",
    "missing_wait_dependency_names",
    "wait_dependencies_satisfied",
    "wait_dependency_status_counts",
    "wait_dependency_unknown_targets",
]
