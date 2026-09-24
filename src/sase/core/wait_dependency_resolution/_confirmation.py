"""Confirmation for wait releases derived from live artifact markers."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

from ._index import WaitDependencyIndex
from ._resolution import dependency_resolution_status
from ._types import WaitDependencyStatus


@dataclass(frozen=True)
class WaitReleaseConfirmation:
    """The outcome of validating a resolving view against fresh membership."""

    confirmed: bool
    status: WaitDependencyStatus
    new_member_dirs: tuple[str, ...] = ()


def confirm_dependency_resolution(
    resolved_index: WaitDependencyIndex,
    fresh_index: Callable[[], WaitDependencyIndex],
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    *,
    wait_fork_sources: Iterable[object] = (),
    wait_beads: Iterable[object] = (),
    wait_hoods: Iterable[object] = (),
    closed_bead_ids: Collection[str] | None = None,
    self_artifact_dir: str | Path | None = None,
    max_rounds: int = 2,
) -> WaitReleaseConfirmation:
    """Confirm a resolved wait against membership read after its marker view.

    A shell successor is created before its predecessor writes the terminal marker
    that can make an agent session resolve.  The first index has already read those markers;
    therefore a membership listing built afterwards must contain that successor.  A
    release is safe only if a fresh resolving view introduces no candidate absent from
    the view that resolved.  Repeating once absorbs a member that appeared during the
    first confirmation scan without making every ordinary release pay an unbounded
    polling cost.
    """
    names = tuple(wait_names)
    identity_deps = tuple(wait_identity_deps)
    resolved = tuple(resolved_deps)
    fork_sources = tuple(wait_fork_sources)
    beads = tuple(wait_beads)
    hoods = tuple(wait_hoods)
    status = dependency_resolution_status(
        resolved_index,
        names,
        identity_deps,
        resolved,
        wait_fork_sources=fork_sources,
        wait_beads=beads,
        wait_hoods=hoods,
        closed_bead_ids=closed_bead_ids,
        self_artifact_dir=self_artifact_dir,
    )
    if not _has_agent_shaped_dependencies(names, identity_deps, fork_sources, hoods):
        return WaitReleaseConfirmation(True, status)

    previous = resolved_index
    new_member_dirs: tuple[str, ...] = ()
    for _round in range(max_rounds):
        fresh = fresh_index()
        status = dependency_resolution_status(
            fresh,
            names,
            identity_deps,
            resolved,
            wait_fork_sources=fork_sources,
            wait_beads=beads,
            wait_hoods=hoods,
            closed_bead_ids=closed_bead_ids,
            self_artifact_dir=self_artifact_dir,
        )
        if not status.resolved:
            return WaitReleaseConfirmation(False, status)
        previous_members = previous.dependency_member_dirs(
            names,
            identity_deps,
            resolved,
            wait_fork_sources=fork_sources,
            wait_hoods=hoods,
            self_artifact_dir=self_artifact_dir,
        )
        fresh_members = fresh.dependency_member_dirs(
            names,
            identity_deps,
            resolved,
            wait_fork_sources=fork_sources,
            wait_hoods=hoods,
            self_artifact_dir=self_artifact_dir,
        )
        new_member_dirs = tuple(sorted(fresh_members - previous_members))
        if not new_member_dirs:
            return WaitReleaseConfirmation(True, status)
        previous = fresh
    return WaitReleaseConfirmation(False, status, new_member_dirs)


def _has_agent_shaped_dependencies(
    wait_names: tuple[object, ...],
    wait_identity_deps: tuple[object, ...],
    wait_fork_sources: tuple[object, ...],
    wait_hoods: tuple[object, ...],
) -> bool:
    return bool(wait_names or wait_identity_deps or wait_fork_sources or wait_hoods)
