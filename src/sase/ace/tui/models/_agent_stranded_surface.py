"""Stranded-work counts and identity tokens for rendered Agents-tab rows."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock
from typing import TYPE_CHECKING

from ._agent_stranded_cache import (
    stranded_project_key_for_agent,
    stranded_project_keys,
    stranded_report_cache,
)
from ._agent_stranded_view import agent_stranded_view, verdict_index_for_project

if TYPE_CHECKING:
    from sase.core.stranded_work_facade import StrandedWorkVerdict

    from .agent import Agent

_SURFACED_COUNT_LOCK = RLock()
_surfaced_count_key: tuple[object, ...] | None = None
_surfaced_count_value = 0


def _surfaced_count_memo_value(key: tuple[object, ...]) -> int | None:
    with _SURFACED_COUNT_LOCK:
        if _surfaced_count_key == key:
            return _surfaced_count_value
    return None


def _set_surfaced_count_memo(key: tuple[object, ...], value: int) -> None:
    global _surfaced_count_key, _surfaced_count_value
    with _SURFACED_COUNT_LOCK:
        _surfaced_count_key = key
        _surfaced_count_value = value


def stranded_count_for_agents(agents: Iterable[Agent]) -> int:
    """Count unique stranded beads in reports for the represented projects."""
    project_keys = tuple(sorted(set(stranded_project_keys(agents))))
    return stranded_report_cache().stranded_count(project_keys)


def cached_stranded_verdict_state(project: str, bead_id: str) -> str | None:
    """Return the cached verdict state for one bead without filesystem access.

    This is the O(1) verdict-index lookup shared by Beads filtering. It never
    scans every verdict the way a linear search would.
    """
    index = stranded_report_cache().verdict_index(project)
    if not index:
        return None
    verdict = index.get(bead_id)
    return None if verdict is None else verdict.state


def stranded_verdict_for_bead(project: str, bead_id: str) -> StrandedWorkVerdict | None:
    """Return the cached verdict for one bead without filesystem access."""
    index = stranded_report_cache().verdict_index(project)
    if not index:
        return None
    return index.get(bead_id)


def stranded_snapshot_token(project_keys: Iterable[str]) -> tuple[object, ...]:
    """Return an identity token for the cached reports of *project_keys*.

    The token changes whenever any represented report snapshot is replaced,
    so filter indexes can rebuild without scanning verdicts on the key path.
    """
    token: list[object] = []
    for key in sorted(set(project_keys)):
        entry = stranded_report_cache().entry(key)
        token.append((key, None if entry is None else id(entry.snapshot)))
    return tuple(token)


def _surfaced_reports_token() -> tuple[object, ...]:
    """Return an identity token over every cached stranded report."""
    return stranded_report_cache().report_token()


def surfaced_stranded_leaves(agent: Agent) -> tuple[tuple[str, str], ...]:
    """Return the ``(project_key, bead_id)`` stranded leaves one row flags.

    Only stranded leaves count: the row's own stranded verdict, stranded
    ``waiting_on`` / ``waiting_on_agents`` targets, and stranded ids in a
    clan container's subtree. Blocked (breadcrumb) states never count.
    """
    view = agent_stranded_view(agent)
    leaves: set[tuple[str, str]] = set()
    verdict = view.verdict
    if verdict is not None and verdict.state == "stranded":
        project = stranded_project_key_for_agent(agent)
        if project is not None:
            leaves.add((project, verdict.bead_id))
    wait_project = view.wait_project or stranded_project_key_for_agent(agent)
    if wait_project is not None:
        for bead_id, state in (*view.waiting_on, *view.waiting_on_agents):
            if state == "stranded":
                leaves.add((wait_project, bead_id))
    clan_project = view.clan_project or stranded_project_key_for_agent(agent)
    if clan_project is not None and view.clan_stranded_ids:
        index = verdict_index_for_project(clan_project)
        for bead_id in view.clan_stranded_ids:
            leaf = index.get(bead_id)
            if leaf is not None and leaf.state == "stranded":
                leaves.add((clan_project, bead_id))
            elif leaf is None:
                # The clan view only collects ids from cached verdicts, so a
                # missing index entry means the report turned over mid-read.
                # Keep the flagged id so a racing refresh cannot hide a leaf.
                leaves.add((clan_project, bead_id))
    return tuple(sorted(leaves))


def surfaced_stranded_count(
    agents: Iterable[Agent],
    app: object | None = None,
) -> int:
    """Count distinct stranded leaves flagged on loaded rows.

    The union is over :func:`surfaced_stranded_leaves`, so every counted leaf
    has a reachable Agents-tab row. The result is memoized keyed by roster
    generation, roster identity/length, and cached report identities, staying
    O(1) on a cache hit because the info strip refreshes often.
    """
    roster = tuple(agents)
    generation: object = None
    tribe_generation: object = None
    if app is not None:
        try:
            from sase.ace.tui.actions.agents._roster_generation import (
                get_roster_generation,
                get_tribe_assignment_generation,
            )

            generation = get_roster_generation(app)
            tribe_generation = get_tribe_assignment_generation(app)
        except Exception:  # noqa: BLE001 - memo key stays fail-open.
            generation = None
            tribe_generation = None
    key = (
        generation,
        tribe_generation,
        id(agents),
        len(roster),
        _surfaced_reports_token(),
    )
    memoized = _surfaced_count_memo_value(key)
    if memoized is not None:
        return memoized
    seen: set[tuple[str, str]] = set()
    for agent in roster:
        seen.update(surfaced_stranded_leaves(agent))
    value = len(seen)
    _set_surfaced_count_memo(key, value)
    return value
