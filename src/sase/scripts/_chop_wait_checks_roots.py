"""Group terminally blocked wait_checks waiters under their root blocker.

A waiter is terminally blocked when one of its dependencies already ended
with an outcome that can never satisfy the wait. A waiter parked behind such
a waiter can never release either, so it counts under the same root. This
module walks those waiter-to-waiter edges from each root, bounded by
:data:`MAX_ROOT_WALK_DEPTH` and guarded against cycles by a visited set.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.scripts._chop_wait_checks_common import TerminalBlocker

#: Longest waiter chain followed below a root blocker.
MAX_ROOT_WALK_DEPTH = 32


@dataclass(frozen=True)
class UnresolvedWaiter:
    """One live waiter whose release check ran this tick and left it parked."""

    artifact_dir: str
    name: str
    project_name: str
    blockers: tuple[TerminalBlocker, ...]
    # Keys of not-yet-finished members that block this waiter. Computed
    # only when some root exists, so a tick without failures pays nothing.
    upstream: Callable[[], frozenset[str]] = field(
        default=frozenset, compare=False, repr=False
    )


@dataclass(frozen=True)
class RootWaiter:
    """One waiter listed on a root-blocker notice."""

    artifact_dir: str
    name: str
    project_name: str
    # The upstream waiter this one is parked behind; ``None`` when the
    # root blocker is this waiter's own dependency.
    via: str | None = None
    via_name: str | None = None


@dataclass
class RootGroup:
    """Every direct and transitive waiter of one root terminal blocker."""

    blocker: TerminalBlocker
    waiters: dict[str, RootWaiter] = field(default_factory=dict)


def group_by_root_blocker(
    waiters: Iterable[UnresolvedWaiter],
) -> dict[str, RootGroup]:
    """Return root groups keyed by the root blocker's artifact-dir key.

    Waiters are visited in artifact-dir order so the blocker label chosen
    for a group, and so the rendered notice, is stable across ticks.
    """
    by_key: dict[str, UnresolvedWaiter] = {}
    for waiter in waiters:
        by_key.setdefault(artifact_dir_key(waiter.artifact_dir), waiter)
    ordered_keys = sorted(by_key)

    groups: dict[str, RootGroup] = {}
    for key in ordered_keys:
        waiter = by_key[key]
        for blocker in waiter.blockers:
            group = groups.setdefault(
                artifact_dir_key(blocker.artifact_dir), RootGroup(blocker=blocker)
            )
            group.waiters.setdefault(
                key,
                RootWaiter(
                    artifact_dir=waiter.artifact_dir,
                    name=waiter.name,
                    project_name=waiter.project_name,
                ),
            )
    if not groups:
        return groups

    downstream: dict[str, list[str]] = {}
    for key in ordered_keys:
        for upstream_key in sorted(by_key[key].upstream()):
            if upstream_key != key and upstream_key in by_key:
                downstream.setdefault(upstream_key, []).append(key)
    if not downstream:
        return groups

    for group in groups.values():
        frontier = sorted(group.waiters)
        depth = 0
        while frontier and depth < MAX_ROOT_WALK_DEPTH:
            next_frontier: list[str] = []
            for upstream_key in frontier:
                upstream = by_key[upstream_key]
                for downstream_key in downstream.get(upstream_key, ()):
                    if downstream_key in group.waiters:
                        continue
                    waiter = by_key[downstream_key]
                    group.waiters[downstream_key] = RootWaiter(
                        artifact_dir=waiter.artifact_dir,
                        name=waiter.name,
                        project_name=waiter.project_name,
                        via=upstream.artifact_dir,
                        via_name=upstream.name,
                    )
                    next_frontier.append(downstream_key)
            frontier = sorted(next_frontier)
            depth += 1
    return groups


__all__ = [
    "MAX_ROOT_WALK_DEPTH",
    "RootGroup",
    "RootWaiter",
    "UnresolvedWaiter",
    "group_by_root_blocker",
]
