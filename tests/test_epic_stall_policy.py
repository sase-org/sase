"""Tests for the shared stalled-epic predicate and fingerprint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.bead.epic_stall_policy import (
    EpicClanMember,
    EpicClanSnapshot,
    EpicStall,
    epic_stall_fingerprint,
    latest_generation_snapshot,
    stalled_epic,
)

_FAILED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
_NOW = _FAILED_AT + timedelta(seconds=180)
_SETTLE_SECONDS = 120


def _member(
    name: str,
    *,
    bead_id: str | None = None,
    artifact_dir: str | None = None,
    timestamp: str = "20260817_120000",
    outcome: str | None = None,
    has_done_marker: bool = False,
    is_live: bool = False,
    finished_at: datetime | None = None,
) -> EpicClanMember:
    return EpicClanMember(
        agent_name=name,
        bead_id=bead_id if bead_id is not None else f"{name}-bead",
        artifact_dir=artifact_dir if artifact_dir is not None else f"/artifacts/{name}",
        timestamp=timestamp,
        outcome=outcome,
        has_done_marker=has_done_marker,
        is_live=is_live,
        finished_at=finished_at,
    )


def _snapshot(
    *members: EpicClanMember,
    project: str = "sase",
    epic_id: str = "sase-p4",
    generation: str = "20260817_120000",
) -> EpicClanSnapshot:
    return EpicClanSnapshot(
        project=project,
        epic_id=epic_id,
        clan_generation=generation,
        members=members,
    )


def _failed_phase(
    name: str = "sase-p4.1",
    *,
    finished_at: datetime | None = _FAILED_AT,
) -> EpicClanMember:
    return _member(
        name,
        outcome="failed",
        has_done_marker=True,
        finished_at=finished_at,
    )


def _waiting_phase(name: str = "sase-p4.2") -> EpicClanMember:
    return _member(name)


def _completed_phase(name: str) -> EpicClanMember:
    return _member(
        name,
        outcome="completed",
        has_done_marker=True,
        finished_at=_FAILED_AT - timedelta(minutes=5),
    )


def _evaluate(
    snapshot: EpicClanSnapshot,
    *,
    epic_open: bool = True,
    now: datetime = _NOW,
    settle_seconds: int = _SETTLE_SECONDS,
) -> EpicStall | None:
    return stalled_epic(
        snapshot,
        epic_open=epic_open,
        now=now,
        settle_seconds=settle_seconds,
    )


def test_plain_stall_returns_failed_and_waiting_members() -> None:
    failed = _failed_phase()
    waiting = _waiting_phase()
    land = _waiting_phase("sase-p4.land")
    stall = _evaluate(_snapshot(failed, waiting, land))

    assert stall is not None
    assert stall.project == "sase"
    assert stall.epic_id == "sase-p4"
    assert stall.clan_generation == "20260817_120000"
    assert stall.failed_members == (failed,)
    assert stall.waiting_members == (waiting, land)
    assert stall.stalled_since == _FAILED_AT


def test_live_member_suppresses_stall() -> None:
    snapshot = _snapshot(
        _failed_phase(),
        _member("sase-p4.2", is_live=True),
        _waiting_phase("sase-p4.land"),
    )

    assert _evaluate(snapshot) is None


def test_closed_epic_suppresses_stall() -> None:
    snapshot = _snapshot(_failed_phase(), _waiting_phase())

    assert _evaluate(snapshot, epic_open=False) is None


def test_settle_window_suppresses_stall_until_newest_failure_is_old_enough() -> None:
    first = _failed_phase("sase-p4.1", finished_at=_FAILED_AT)
    second = _failed_phase(
        "sase-p4.2",
        finished_at=_FAILED_AT + timedelta(seconds=60),
    )
    snapshot = _snapshot(first, second, _waiting_phase("sase-p4.land"))
    just_before = second.finished_at
    assert just_before is not None

    assert (
        _evaluate(
            snapshot,
            now=just_before + timedelta(seconds=_SETTLE_SECONDS - 1),
        )
        is None
    )

    stall = _evaluate(
        snapshot,
        now=just_before + timedelta(seconds=_SETTLE_SECONDS),
    )
    assert stall is not None
    assert stall.stalled_since == just_before
    assert stall.failed_members == (first, second)


def test_killed_and_stopped_members_never_trigger_a_stall() -> None:
    snapshot = _snapshot(
        _member(
            "sase-p4.1",
            outcome="killed",
            has_done_marker=True,
            finished_at=_FAILED_AT,
        ),
        _member(
            "sase-p4.2",
            outcome="stopped",
            has_done_marker=True,
            finished_at=_FAILED_AT,
        ),
        _waiting_phase("sase-p4.land"),
    )

    assert _evaluate(snapshot) is None


def test_all_terminal_clan_with_failed_land_agent_is_a_stall() -> None:
    land = _failed_phase("sase-p4.land")
    snapshot = _snapshot(
        _completed_phase("sase-p4.1"),
        _completed_phase("sase-p4.2"),
        land,
    )

    stall = _evaluate(snapshot)

    assert stall is not None
    assert stall.failed_members == (land,)
    assert stall.waiting_members == ()


def test_fingerprint_is_stable_across_ticks() -> None:
    snapshot = _snapshot(_failed_phase(), _waiting_phase())
    first = _evaluate(snapshot, now=_NOW)
    later = _evaluate(snapshot, now=_NOW + timedelta(hours=1))

    assert first is not None
    assert later is not None
    assert first.stalled_since == later.stalled_since
    assert epic_stall_fingerprint(first) == epic_stall_fingerprint(later)
    shifted = EpicStall(
        project=first.project,
        epic_id=first.epic_id,
        clan_generation=first.clan_generation,
        failed_members=first.failed_members,
        waiting_members=first.waiting_members,
        stalled_since=first.stalled_since + timedelta(minutes=5),
    )
    assert epic_stall_fingerprint(shifted) == epic_stall_fingerprint(first)


def test_fingerprint_changes_when_a_second_member_fails() -> None:
    first_failure = _failed_phase("sase-p4.1")
    one_failure = _evaluate(_snapshot(first_failure, _waiting_phase("sase-p4.2")))
    two_failures = _evaluate(
        _snapshot(
            first_failure, _failed_phase("sase-p4.2"), _waiting_phase("sase-p4.land")
        )
    )

    assert one_failure is not None
    assert two_failures is not None
    assert epic_stall_fingerprint(one_failure) != epic_stall_fingerprint(two_failures)


def test_latest_generation_snapshot_prefers_the_newest_generation() -> None:
    older = _snapshot(_failed_phase(), generation="20260817_120000")
    newer = _snapshot(_failed_phase(), generation="20260817_130000")
    other_epic = _snapshot(
        _failed_phase(),
        project="sase",
        epic_id="sase-p5",
        generation="20260817_140000",
    )

    assert latest_generation_snapshot((older, newer, other_epic)) == newer
    assert latest_generation_snapshot((newer, older)) == newer
    assert latest_generation_snapshot(()) is None
