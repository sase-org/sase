"""Claim, preclaim, and ready-to-work tests for the bead mutation facade.

Split from ``tests.test_core_facade.test_bead_mutation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError
from sase.core import bead_mutation_facade as rust_beads
from tests.test_core_facade._bead_mutation_helpers import init_store

__all__ = [
    "test_claim_for_agent_launch_attaches_only_when_close_predates_submission",
    "test_claim_for_agent_launch_converts_issue_and_reassigns",
    "test_claim_for_agent_launch_maps_missing_and_preserves_specific_failures",
    "test_fractional_and_equal_submission_timestamps_attach",
    "test_future_allocated_launch_id_does_not_make_queued_close_attach",
    "test_preclaim_epic_work_allows_empty_subset_without_land_mutation",
    "test_preclaim_epic_work_converts_batch_and_returns_prior_state",
    "test_ready_to_work_errors_map_to_python_exceptions",
    "test_wait_claim_facade_claims_idempotently_and_releases",
]


def test_ready_to_work_errors_map_to_python_exceptions(tmp_path: Path) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    child, _ = rust_beads.create(
        root / "sdd/beads",
        title="Child",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    with pytest.raises(NotAPlanError):
        rust_beads.mark_ready_to_work(root / "sdd/beads", child.id)

    marked, _ = rust_beads.mark_ready_to_work(
        root / "sdd/beads",
        epic.id,
        now="2026-01-01T00:02:00Z",
    )
    assert marked.is_ready_to_work is True

    with pytest.raises(AlreadyReadyError):
        rust_beads.mark_ready_to_work(root / "sdd/beads", epic.id)

    unmarked, _ = rust_beads.unmark_ready_to_work(
        root / "sdd/beads",
        epic.id,
        now="2026-01-01T00:03:00Z",
    )
    assert unmarked.is_ready_to_work is False


def test_claim_for_agent_launch_converts_issue_and_reassigns(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    claimed, outcome = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:02:00Z",
    )

    assert outcome["operation"] == "claim_for_agent_launch"
    assert outcome["changed"] is True
    assert outcome["issue_ids"] == [phase.id]
    assert claimed.id == phase.id
    assert claimed.status == Status.IN_PROGRESS
    assert claimed.assignee == "agent-1"
    assert claimed.updated_at == "2026-01-01T00:02:00Z"

    reassigned, _ = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        phase.id,
        "agent-2",
        now="2026-01-01T00:03:00Z",
    )
    assert reassigned.status == Status.IN_PROGRESS
    assert reassigned.assignee == "agent-2"
    assert reassigned.updated_at == "2026-01-01T00:03:00Z"


def test_preclaim_epic_work_converts_batch_and_returns_prior_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        now="2026-01-01T00:00:00Z",
    )
    first, _ = rust_beads.create(
        root / "sdd/beads",
        title="First",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )
    second, _ = rust_beads.create(
        root / "sdd/beads",
        title="Second",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:02:00Z",
    )
    rust_beads.update(
        root / "sdd/beads",
        second.id,
        status="in_progress",
        assignee="old-worker",
        now="2026-01-01T00:03:00Z",
    )

    assigned, outcome = rust_beads.preclaim_epic_work(
        root / "sdd/beads",
        epic.id,
        [(first.id, "epic.1"), (second.id, "epic.2")],
        land_agent_name="epic.land",
        now="2026-01-01T00:04:00Z",
    )

    assert [(issue.id, issue.status, issue.assignee) for issue in assigned] == [
        (first.id, Status.IN_PROGRESS, "epic.1"),
        (second.id, Status.IN_PROGRESS, "epic.2"),
        (epic.id, Status.IN_PROGRESS, "epic.land"),
    ]
    assert outcome["operation"] == "preclaim_epic_work"
    assert outcome["rollback_preclaims"] == [
        {"bead_id": first.id, "status": "open", "assignee": ""},
        {
            "bead_id": second.id,
            "status": "in_progress",
            "assignee": "old-worker",
        },
        {"bead_id": epic.id, "status": "open", "assignee": ""},
    ]


def test_preclaim_epic_work_allows_empty_subset_without_land_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    assigned, outcome = rust_beads.preclaim_epic_work(
        root / "sdd/beads",
        epic.id,
        [],
        land_agent_name=None,
        now="2026-01-01T00:02:00Z",
    )

    assert assigned == []
    assert outcome["operation"] == "preclaim_epic_work"
    assert outcome["rollback_preclaims"] == []
    with BeadProject(root) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert project.show(epic.id).assignee == ""
        assert project.show(phase.id).status is Status.OPEN
        assert project.show(phase.id).assignee == ""


def test_claim_for_agent_launch_maps_missing_and_preserves_specific_failures(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    rust_beads.close(
        root / "sdd/beads",
        [epic.id],
        now="2026-01-01T00:01:00Z",
    )

    with pytest.raises(KeyError, match="Issue not found: missing"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", "missing", "agent")
    with pytest.raises(ValueError, match="closed: cannot claim closed bead"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", epic.id, "agent")
    with pytest.raises(ValueError, match="validation: agent name"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", epic.id, "  ")


def test_claim_for_agent_launch_attaches_only_when_close_predates_submission(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    bead, _ = rust_beads.create(
        root / "sdd/beads",
        title="Closed before launch",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    closed, _ = rust_beads.close(
        root / "sdd/beads",
        [bead.id],
        now="2026-01-01T00:01:00Z",
    )

    attached, outcome = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        bead.id,
        "agent-1",
        now="2026-01-01T00:03:00Z",
        submitted_at="2026-01-01T00:02:00Z",
        run_id="260101_000200",
    )

    assert attached.status is Status.CLOSED
    assert attached.closed_at == closed[0].closed_at
    assert attached.resolution == closed[0].resolution
    assert len(attached.notes) == 1
    assert attached.notes[0].author == "agent-1"
    assert attached.notes[0].timestamp == "2026-01-01T00:03:00Z"
    assert attached.notes[0].text.startswith("CLOSED-BEAD LAUNCH:")
    assert outcome["changed"] is True
    assert outcome["noted_ids"] == [bead.id]

    with pytest.raises(ValueError, match="closed_while_queued:"):
        rust_beads.claim_for_agent_launch(
            root / "sdd/beads",
            bead.id,
            "agent-2",
            now="2026-01-01T00:04:00Z",
            submitted_at="2026-01-01T00:00:30Z",
            run_id="260101_000030",
        )
    with BeadProject(root) as project:
        unchanged = project.show(bead.id)
    assert unchanged.status is Status.CLOSED
    assert len(unchanged.notes) == 1


def test_future_allocated_launch_id_does_not_make_queued_close_attach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("HOME", str(tmp_path))
    allocated = reserve_launch_timestamp_batch(
        3,
        base_timestamp="260101_120000",
    )
    assert allocated[2] == "260101_120002"

    root = tmp_path / "queued-close"
    init_store(root)
    bead, _ = rust_beads.create(
        root / "sdd/beads",
        title="Closed while queued",
        issue_type=IssueType.PLAN,
        now="2026-01-01T11:59:00Z",
    )
    closed, _ = rust_beads.close(
        root / "sdd/beads",
        [bead.id],
        now="2026-01-01T12:00:01Z",
    )
    before = closed[0]

    with pytest.raises(ValueError, match="closed_while_queued:"):
        rust_beads.claim_for_agent_launch(
            root / "sdd/beads",
            bead.id,
            "worker",
            now="2026-01-01T12:00:03Z",
            submitted_at="2026-01-01T12:00:00Z",
            run_id=allocated[2],
        )

    with BeadProject(root) as project:
        after = project.show(bead.id)
    assert after.status is Status.CLOSED
    assert after.closed_at == before.closed_at
    assert after.resolution == before.resolution
    assert after.close_reason == before.close_reason
    assert after.close_history == before.close_history
    assert after.notes == before.notes


@pytest.mark.parametrize(
    ("closed_at", "submitted_at"),
    [
        ("2026-01-01T12:00:00.100Z", "2026-01-01T12:00:00.900000Z"),
        ("2026-01-01T12:00:00Z", "2026-01-01T12:00:00Z"),
    ],
    ids=["fractional-before-submission", "equal-times-attach"],
)
def test_fractional_and_equal_submission_timestamps_attach(
    tmp_path: Path,
    closed_at: str,
    submitted_at: str,
) -> None:
    root = tmp_path / "timestamp-boundary"
    init_store(root)
    bead, _ = rust_beads.create(
        root / "sdd/beads",
        title="Timestamp boundary",
        issue_type=IssueType.PLAN,
        now="2026-01-01T11:59:00Z",
    )
    closed, _ = rust_beads.close(
        root / "sdd/beads",
        [bead.id],
        now=closed_at,
    )

    attached, _ = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        bead.id,
        "worker",
        now="2026-01-01T12:00:02Z",
        submitted_at=submitted_at,
        run_id="260101_120002",
    )

    assert attached.status is Status.CLOSED
    assert attached.closed_at == closed[0].closed_at == closed_at
    assert len(attached.notes) == 1
    assert attached.notes[0].author == "worker"


def test_wait_claim_facade_claims_idempotently_and_releases(tmp_path: Path) -> None:
    root = tmp_path / "rust"
    init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:00:01Z",
    )

    claimed, claim_outcome = rust_beads.claim_for_agent_wait(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:01:00Z",
    )
    retained, retained_outcome = rust_beads.claim_for_agent_wait(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:02:00Z",
    )
    released, release_outcome = rust_beads.release_agent_claim(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:03:00Z",
    )

    assert (claimed.status, claimed.assignee) == (Status.CLAIMED, "agent-1")
    assert claim_outcome["changed"] is True
    assert (retained.status, retained.assignee) == (Status.CLAIMED, "agent-1")
    assert retained_outcome["changed"] is False
    assert (released.status, released.assignee) == (Status.OPEN, "")
    assert release_outcome["changed"] is True
