"""The shared stalled-epic predicate for EpicResume detection.

When an epic clan has a failed member and nobody is still live, later
phases sit in ``WAITING`` forever and the epic makes no further progress.
Every surface that decides whether that clan is stalled — or whether two
observations are the same stall — derives it through :func:`stalled_epic`
and :func:`epic_stall_fingerprint` rather than recompute the comparison
itself.

These helpers are pure functions of their arguments: callers own the
clock, the configured settle window, and every filesystem read, so no
test needs to freeze time globally and no consumer can disagree with
another about what "stalled" means. Nothing here imports the chop, the
gate, or the scanner.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sase.notification_gates.durability import canonical_json_bytes, sha256_bytes

_FAILED_OUTCOME = "failed"


@dataclass(frozen=True, slots=True)
class EpicClanMember:
    """One clan member as the stall predicate sees it.

    ``is_live`` is the caller's projection of ``RUNNING`` / ``STARTING`` /
    ``QUEUED``. ``finished_at`` is absent when the member has no completion
    marker the caller could parse.
    """

    agent_name: str
    bead_id: str
    artifact_dir: str
    timestamp: str
    outcome: str | None
    has_done_marker: bool
    is_live: bool
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class EpicClanSnapshot:
    """One ``(project, epic_id, clan_generation)`` roster."""

    project: str
    epic_id: str
    clan_generation: str
    members: tuple[EpicClanMember, ...]


@dataclass(frozen=True, slots=True)
class EpicStall:
    """A settled stall in one open epic clan generation."""

    project: str
    epic_id: str
    clan_generation: str
    failed_members: tuple[EpicClanMember, ...]
    waiting_members: tuple[EpicClanMember, ...]
    stalled_since: datetime


def stalled_epic(
    snapshot: EpicClanSnapshot,
    *,
    epic_open: bool,
    now: datetime,
    settle_seconds: int,
) -> EpicStall | None:
    """Return a stall when *snapshot* cannot advance and has settled.

    A stall requires an open epic bead, at least one member whose outcome
    is ``failed``, no live member, and the newest failure to be at least
    *settle_seconds* old. ``killed`` and ``stopped`` are deliberate user
    actions and never satisfy the failed-member check.

    Waiting members are the non-live, non-failed members that have not
    reached a done marker. The predicate does not inspect *why* they wait:
    with no live sibling, an epic clan cannot advance.
    """
    if not epic_open:
        return None
    if any(member.is_live for member in snapshot.members):
        return None
    failed_members = tuple(
        member for member in snapshot.members if member.outcome == _FAILED_OUTCOME
    )
    if not failed_members:
        return None
    stalled_since = _newest_failure_finished_at(failed_members)
    if stalled_since is None:
        return None
    if stalled_since > now - timedelta(seconds=settle_seconds):
        return None
    waiting_members = tuple(
        member
        for member in snapshot.members
        if not member.is_live
        and member.outcome != _FAILED_OUTCOME
        and not member.has_done_marker
    )
    return EpicStall(
        project=snapshot.project,
        epic_id=snapshot.epic_id,
        clan_generation=snapshot.clan_generation,
        failed_members=failed_members,
        waiting_members=waiting_members,
        stalled_since=stalled_since,
    )


def epic_stall_fingerprint(stall: EpicStall) -> str:
    """Return the durable identity of *stall* for lane-state dedupe.

    The digest covers ``project``, ``epic_id``, ``clan_generation``, and the
    sorted ``(agent_name, artifact_dir)`` pairs of the failed members.
    ``stalled_since`` and any other wall-clock value are excluded so a later
    tick of the same stall cannot look like a new failure.
    """
    failed_pairs = sorted(
        (member.agent_name, member.artifact_dir) for member in stall.failed_members
    )
    return sha256_bytes(
        canonical_json_bytes(
            {
                "clan_generation": stall.clan_generation,
                "epic_id": stall.epic_id,
                "failed_members": [
                    {"agent_name": agent_name, "artifact_dir": artifact_dir}
                    for agent_name, artifact_dir in failed_pairs
                ],
                "project": stall.project,
            }
        )
    )


def latest_generation_snapshot(
    snapshots: Iterable[EpicClanSnapshot],
) -> EpicClanSnapshot | None:
    """Return the newest ``clan_generation`` snapshot for one epic.

    Callers pass the snapshots for a single ``(project, epic_id)`` so a
    superseded generation cannot be evaluated by accident. When more than
    one pair is present, the first snapshot's pair is the one selected.
    """
    items = tuple(snapshots)
    if not items:
        return None
    project = items[0].project
    epic_id = items[0].epic_id
    newest: EpicClanSnapshot | None = None
    for snapshot in items:
        if snapshot.project != project or snapshot.epic_id != epic_id:
            continue
        if newest is None or snapshot.clan_generation > newest.clan_generation:
            newest = snapshot
    return newest


def _newest_failure_finished_at(
    failed_members: tuple[EpicClanMember, ...],
) -> datetime | None:
    finished_at_times = [
        member.finished_at
        for member in failed_members
        if member.finished_at is not None
    ]
    if not finished_at_times:
        return None
    return max(finished_at_times)


__all__ = [
    "EpicClanMember",
    "EpicClanSnapshot",
    "EpicStall",
    "epic_stall_fingerprint",
    "latest_generation_snapshot",
    "stalled_epic",
]
