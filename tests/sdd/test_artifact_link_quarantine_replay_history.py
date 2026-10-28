"""Quarantine replay evidence: history honesty and ancestry tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd._artifact_link_event_collision import candidate_from_event
from sase.sdd._artifact_link_event_history import attach_collision_history
from tests.sdd._artifact_link_event_store_test_helpers import (
    edge_event,
    make_store,
    write_event,
)
from tests.sdd._artifact_link_quarantine_replay_helpers import (
    commit_all,
    event_digest,
    init_repo,
    run_git,
)


def test_shallow_history_marks_evidence_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = tmp_path / "full"
    full.mkdir()
    init_repo(full, monkeypatch)
    event_file = full / "link-events" / "v1" / "00" / "aaa.json"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    event_file.write_text('{"first":true}\n', encoding="utf-8")
    commit_all(full, "first add")
    (full / "unrelated.txt").write_text("bump\n", encoding="utf-8")
    commit_all(full, "unrelated second")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{full}", str(shallow)],
        check=True,
    )
    run_git(shallow, "config", "user.name", "SASE Tests")
    run_git(shallow, "config", "user.email", "sase@example.test")

    assert run_git(shallow, "rev-parse", "--is-shallow-repository").strip() == "true"

    event = edge_event("a" * 32)
    digest = event_digest(event)
    candidate = candidate_from_event(
        event,
        tier="durable",
        root=str(shallow),
        relative_path="link-events/v1/00/aaa.json",
        digest=digest,
    )
    (updated,) = attach_collision_history((candidate,), collided_digests={digest})
    assert updated.evidence.history_complete is False
    assert updated.evidence.first_commit_id is None
    assert updated.evidence.first_commit_at is None


def test_timezone_histories_order_by_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    init_repo(plans, monkeypatch)
    # Earlier instant 10:00Z spelled with +02:00 sorts lexically after 10:30Z.
    early = edge_event(
        "b" * 32,
        target="plan:202608/early.md",
        description="earlier instant",
    )
    late = edge_event(
        "b" * 32,
        target="plan:202608/late.md",
        description="later instant",
    )
    early_path = write_event(plans, early)
    commit_all(plans, "early payload", when="2026-10-27T12:00:00+02:00")
    late_path = write_event(plans, late)
    commit_all(plans, "late payload", when="2026-10-27T10:30:00+00:00")

    early_commit = (
        run_git(
            plans,
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            early_path.relative_to(plans).as_posix(),
        )
        .splitlines()[-1]
        .strip()
    )
    late_commit = (
        run_git(
            plans,
            "log",
            "--diff-filter=A",
            "--format=%H",
            "--",
            late_path.relative_to(plans).as_posix(),
        )
        .splitlines()[-1]
        .strip()
    )
    assert early_commit != late_commit

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/early.md"
    assert len(snapshot.quarantine_findings) == 1


def test_cross_root_clone_gathers_ancestry_through_store_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    init_repo(plans, monkeypatch)
    early = edge_event(
        "c" * 32,
        target="plan:202608/original.md",
        description="earlier payload at later clock",
    )
    late = edge_event(
        "c" * 32,
        target="plan:202608/clock-skew.md",
        description="later payload at earlier clock",
    )
    early_path = write_event(plans, early)
    commit_all(plans, "add original A", when="2026-10-27T12:00:00Z")
    early_commit = run_git(plans, "rev-parse", "HEAD").strip()

    if research.exists():
        research.rmdir()
    subprocess.run(
        ["git", "clone", "-q", f"file://{plans}", str(research)],
        check=True,
    )
    run_git(research, "config", "user.name", "SASE Tests")
    run_git(research, "config", "user.email", "sase@example.test")
    run_git(research, "config", "commit.gpgsign", "false")
    cloned_early = research / early_path.relative_to(plans)
    cloned_early.unlink()
    late_path = write_event(research, late)
    commit_all(research, "replace A with B", when="2026-10-27T10:00:00Z")
    late_commit = run_git(research, "rev-parse", "HEAD").strip()
    assert (
        run_git(research, "merge-base", "--is-ancestor", early_commit, late_commit)
        == ""
    )

    early_candidate = candidate_from_event(
        early,
        tier="durable",
        root=str(plans.resolve()),
        relative_path=early_path.relative_to(plans).as_posix(),
        digest=event_digest(early),
    )
    late_candidate = candidate_from_event(
        late,
        tier="durable",
        root=str(research.resolve()),
        relative_path=late_path.relative_to(research).as_posix(),
        digest=event_digest(late),
    )
    updated = attach_collision_history(
        (early_candidate, late_candidate),
        collided_digests={event_digest(early), event_digest(late)},
    )
    by_digest = {item.digest: item for item in updated}
    assert by_digest[event_digest(early)].evidence.history_complete is True
    assert by_digest[event_digest(late)].evidence.history_complete is True
    assert early_commit in by_digest[event_digest(late)].evidence.ancestor_commit_ids
    assert by_digest[event_digest(early)].evidence.ancestor_commit_ids == ()
    assert (
        early_commit not in by_digest[event_digest(early)].evidence.ancestor_commit_ids
    )

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/original.md"
    assert snapshot.quarantine_findings[0].basis == "historical_ancestor_wins"


def test_independent_root_timezone_histories_order_by_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    init_repo(plans, monkeypatch)
    init_repo(research, monkeypatch)
    early = edge_event(
        "d" * 32,
        target="plan:202608/early.md",
        description="earlier instant in independent root",
    )
    late = edge_event(
        "d" * 32,
        target="research:202608/late.md",
        source="research:202608/src.md",
        description="later instant in independent root",
    )
    write_event(plans, early)
    commit_all(plans, "early independent", when="2026-10-27T12:00:00+02:00")
    write_event(research, late)
    commit_all(research, "late independent", when="2026-10-27T10:30:00+00:00")

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    accepted = snapshot.accepted_events[0]
    assert accepted["kind"]["edge"]["target_ref"] == "plan:202608/early.md"
    assert snapshot.quarantine_findings[0].rejected_digest == event_digest(late)


def test_duplicate_independent_roots_do_not_invent_ancestry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path, monkeypatch)
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    init_repo(plans, monkeypatch)
    init_repo(research, monkeypatch)
    payload = edge_event(
        "e" * 32,
        target="plan:202608/copied.md",
        description="identical payload in two roots",
    )
    competitor = edge_event(
        "e" * 32,
        target="plan:202608/competitor.md",
        description="competing payload",
    )
    first_path = write_event(plans, payload)
    commit_all(plans, "plans copy")
    second_path = write_event(research, payload)
    commit_all(research, "research copy")
    write_event(plans, competitor)
    commit_all(plans, "competitor")

    plans_candidate = candidate_from_event(
        payload,
        tier="durable",
        root=str(plans.resolve()),
        relative_path=first_path.relative_to(plans).as_posix(),
        digest=event_digest(payload),
    )
    research_candidate = candidate_from_event(
        payload,
        tier="durable",
        root=str(research.resolve()),
        relative_path=second_path.relative_to(research).as_posix(),
        digest=event_digest(payload),
    )
    updated = attach_collision_history(
        (plans_candidate, research_candidate),
        collided_digests={event_digest(payload), event_digest(competitor)},
    )
    commits = {item.evidence.first_commit_id for item in updated}
    assert len(commits) == 2
    for item in updated:
        assert item.evidence.first_commit_id not in item.evidence.ancestor_commit_ids
        assert item.evidence.history_complete is True

    snapshot = store.artifact_link_event_snapshot(strict=True)
    assert len(snapshot.accepted_events) == 1
    assert snapshot.healthy is True
