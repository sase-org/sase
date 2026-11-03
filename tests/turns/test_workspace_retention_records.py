"""Dismissal, occupancy, and retention-record tests for workspace retention.

Split from ``tests.turns.test_workspace_retention``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.turns.workspace_retention import (
    RETENTION_RECORD_LOCATOR,
    WorkspaceRetentionSuccessor,
    settle_stranded_workspace,
)
from sase.turns.workspace_retention_surface import (
    dismiss_terminal_workspace_retention,
)
from sase.workspace_provider.occupant import read_occupant_record
from tests._running_field_helpers import create_project_file_with_running
from tests.turns._workspace_retention_helpers import (
    CL_NAME,
    PID,
    WORKFLOW,
    WORKSPACE,
    claim,
    init_repo,
    occupant,
    owner,
    write_empty_baseline,
)

__all__ = [
    "test_claim_transfer_racing_settlement_is_noop",
    "test_explicit_dismissal_preserves_reused_claim_and_unresolved_record",
    "test_explicit_dismissal_releases_exact_retained_claim_and_settles_record",
    "test_historical_settled_boolean_without_timestamp_stays_unresolved",
    "test_incomplete_owner_identity_does_not_mutate",
    "test_metadata_write_failure_still_protects_custody",
    "test_pending_retention_round_trip_and_owner_match",
    "test_same_workspace_successor_settles_prior_retain_record",
    "test_settled_record_survives_fresh_unresolved_hold",
    "test_stale_ownership_probe_leaves_unresolved_retain",
    "test_successful_release_clears_matching_occupant",
]


def test_explicit_dismissal_releases_exact_retained_claim_and_settles_record(
    tmp_path: Path,
) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    occupant(checkout)
    held = settle_stranded_workspace(owner(project_file, checkout, artifacts))
    assert held.disposition == "retain"

    assert dismiss_terminal_workspace_retention(project_file, artifacts) is True

    assert get_claimed_workspaces(project_file) == []
    assert read_occupant_record(str(checkout)) is None
    record = json.loads(
        (artifacts / RETENTION_RECORD_LOCATOR).read_text(encoding="utf-8")
    )
    assert record["settled_reason"] == "dismissed"
    assert record["settled_at"]
    assert dismiss_terminal_workspace_retention(project_file, artifacts) is False


def test_explicit_dismissal_preserves_reused_claim_and_unresolved_record(
    tmp_path: Path,
) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held = settle_stranded_workspace(owner(project_file, checkout, artifacts))
    assert held.disposition == "retain"

    reused = WorkspaceClaim(
        WORKSPACE,
        WORKFLOW,
        CL_NAME,
        pid=999,
        artifacts_timestamp="20260101999999",
    )
    project_path = Path(project_file)
    project_path.write_text(
        "# Test Project\n\nRUNNING:\n"
        + reused.to_line()
        + "\nNAME: Test Feature\nDESCRIPTION:\n  Test description\n"
        "PARENT: None\nPR: None\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    assert dismiss_terminal_workspace_retention(project_file, artifacts) is False

    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == 999
    record = json.loads(
        (artifacts / RETENTION_RECORD_LOCATOR).read_text(encoding="utf-8")
    )
    assert "settled_at" not in record


def test_claim_transfer_racing_settlement_is_noop(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    foreign = WorkspaceClaim(
        WORKSPACE,
        WORKFLOW,
        CL_NAME,
        pid=999,
        artifacts_timestamp="20260101999999",
    )
    project_file = create_project_file_with_running(tmp_path, [foreign])
    occupant(checkout)

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "ownership_moved"
    assert result.stale_attempt is True
    assert result.claim_changed is False
    claims = get_claimed_workspaces(project_file)
    assert claims[0].pid == 999
    assert claims[0].pinned is False
    occupant_record = read_occupant_record(str(checkout))
    assert occupant_record is not None
    assert occupant_record.pid == PID


def test_incomplete_owner_identity_does_not_mutate(tmp_path: Path) -> None:
    """Empty timestamp/workflow identity is a stale attempt, never a wildcard pin."""
    from sase.turns.workspace_retention import write_pending_retention

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = replace(
        owner(project_file, checkout, artifacts), artifacts_timestamp=""
    )

    result = settle_stranded_workspace(held_owner)

    assert result.disposition == "ownership_moved"
    assert result.stale_attempt is True
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is False
    assert write_pending_retention(held_owner, "incomplete") is None


def test_successful_release_clears_matching_occupant(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws")
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    occupant(checkout)

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert read_occupant_record(str(checkout)) is None


def test_settled_record_survives_fresh_unresolved_hold(tmp_path: Path) -> None:
    """Recovery never overwrites a settled record with a fresh hold."""
    from sase.workspace_provider.retention_record import (
        mark_workspace_retention_settled,
    )

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)

    first = settle_stranded_workspace(held_owner)
    assert first.disposition == "retain"
    assert first.record_path is not None
    before = json.loads(Path(first.record_path).read_text(encoding="utf-8"))
    assert before["disposition"] == "retain"

    assert (
        mark_workspace_retention_settled(
            artifacts, reason="resume_transfer", settled_at="2026-11-02T00:00:00+00:00"
        )
        is True
    )

    second = settle_stranded_workspace(held_owner)
    after = json.loads(Path(first.record_path).read_text(encoding="utf-8"))
    assert after.get("settled_at") == "2026-11-02T00:00:00+00:00"
    assert after.get("settled_reason") == "resume_transfer"
    assert second.record_path == first.record_path


def test_pending_retention_round_trip_and_owner_match(tmp_path: Path) -> None:
    """Pending evidence names the exact owner awaiting settlement."""
    from sase.turns.workspace_retention import (
        clear_pending_retention,
        pending_retention_matches_owner,
        read_pending_retention,
        write_pending_retention,
    )

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)

    assert read_pending_retention(artifacts) is None
    assert write_pending_retention(held_owner, "monitor_settlement") is not None
    pending = read_pending_retention(artifacts)
    assert pending is not None
    assert pending_retention_matches_owner(pending, held_owner) is True
    other = replace(held_owner, pid=999999)
    assert pending_retention_matches_owner(pending, other) is False
    clear_pending_retention(artifacts)
    assert read_pending_retention(artifacts) is None


def test_metadata_write_failure_still_protects_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metadata-write failure cannot abort before custody is protected."""
    import sase.axe.run_agent_helpers_artifacts as _meta

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("metadata store unavailable")

    monkeypatch.setattr(_meta, "update_meta_field", _boom)

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.claim_changed is True
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "session owned\n"


def test_same_workspace_successor_settles_prior_retain_record(tmp_path: Path) -> None:
    """A proven successor transfer discharges the old retain through the reader."""
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)

    held = settle_stranded_workspace(held_owner)
    assert held.disposition == "retain"
    before = read_workspace_retention_record(artifacts)
    assert before is not None and before.unresolved is True

    result = settle_stranded_workspace(
        held_owner,
        successor=WorkspaceRetentionSuccessor(
            confirmed_active=True,
            same_workspace=True,
            inherited_obligations=True,
        ),
    )

    assert result.disposition == "release"
    assert result.reason == "same_workspace_successor"
    assert get_claimed_workspaces(project_file) == []
    after = read_workspace_retention_record(artifacts)
    assert after is not None
    assert after.unresolved is False
    assert after.payload.get("settled_reason") == "same_workspace_successor"
    assert after.payload.get("settled_at")
    assert after.payload.get("settled") is True


def test_stale_ownership_probe_leaves_unresolved_retain(tmp_path: Path) -> None:
    """A later ownership-moved probe must not hide an unresolved retain."""
    from sase.workspace_provider.retention_record import read_workspace_retention_record

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)
    held = settle_stranded_workspace(held_owner)
    assert held.disposition == "retain"

    foreign = WorkspaceClaim(
        WORKSPACE,
        WORKFLOW,
        CL_NAME,
        pid=999,
        artifacts_timestamp="20260101999999",
    )
    Path(project_file).write_text(
        "# Test Project\n\nRUNNING:\n"
        + foreign.to_line()
        + "\nNAME: Test Feature\nDESCRIPTION:\n  Test description\n"
        "PARENT: None\nPR: None\nSTATUS: Ready\n",
        encoding="utf-8",
    )

    result = settle_stranded_workspace(held_owner)

    assert result.disposition == "ownership_moved"
    after = read_workspace_retention_record(artifacts)
    assert after is not None
    assert after.unresolved is True
    assert after.disposition == "retain"
    assert get_claimed_workspaces(project_file)[0].pid == 999


def test_historical_settled_boolean_without_timestamp_stays_unresolved(
    tmp_path: Path,
) -> None:
    """A legacy settled flag is not transfer evidence for readers."""
    from sase.workspace_provider.retention_record import (
        mark_workspace_retention_settled,
        read_workspace_retention_record,
    )

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held = settle_stranded_workspace(owner(project_file, checkout, artifacts))
    assert held.record_path is not None
    payload = json.loads(Path(held.record_path).read_text(encoding="utf-8"))
    payload["settled"] = True
    Path(held.record_path).write_text(json.dumps(payload), encoding="utf-8")

    record = read_workspace_retention_record(artifacts)
    assert record is not None
    assert record.unresolved is True
    assert (
        mark_workspace_retention_settled(
            artifacts, reason="resume_transfer", settled_at="2026-11-02T00:00:00+00:00"
        )
        is True
    )
    settled = read_workspace_retention_record(artifacts)
    assert settled is not None
    assert settled.unresolved is False
