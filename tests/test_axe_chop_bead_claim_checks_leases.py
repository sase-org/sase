"""Bead-store lease, commit, and publish tests for claim reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.bead.model import Issue, Status

from tests._axe_chop_bead_claim_checks_helpers import (
    install_leased_apply,
    make_artifact,
    make_claimed_issue,
    make_runtime,
    tombstone_path,
)


def test_project_reconciliation_batches_mutations_into_one_commit_and_push(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    project = MagicMock()
    project.release_agent_claim.side_effect = [
        (make_claimed_issue(bead_id="sase-1.1", assignee="worker.1"), True),
        (make_claimed_issue(bead_id="sase-1.2", assignee="worker.2"), True),
    ]
    project.claim_for_agent_wait.side_effect = [
        (make_claimed_issue(bead_id="sase-1.3", assignee="worker.3"), True),
        (
            Issue(
                id="sase-1.4",
                title="Pre-marked phase",
                status=Status.IN_PROGRESS,
                assignee="worker.4",
            ),
            False,
        ),
    ]
    project_context = MagicMock()
    project_context.__enter__.return_value = project
    lock_entries: list[Path] = []

    @contextmanager
    def lock(path: Path):
        lock_entries.append(path)
        yield True

    commit = MagicMock(return_value=True)
    publish = MagicMock()
    hint = MagicMock()
    operation_context = SimpleNamespace()
    monkeypatch.setattr(
        claim_checks,
        "open_bead_project_for_beads_dir",
        lambda _path: project_context,
    )
    monkeypatch.setattr(claim_checks, "bead_store_write_lock", lock)
    monkeypatch.setattr(claim_checks, "commit_bead_claim_reconciliation", commit)
    monkeypatch.setattr(claim_checks, "publish_bead_claim", publish)
    monkeypatch.setattr(
        "sase.bead.background_store.schedule_beads_sidecar_convergence",
        hint,
    )

    result = claim_checks._reconcile_project_claims(
        "sase",
        beads_dir=beads_dir,
        operation_context=operation_context,
        releases=[("sase-1.1", "worker.1"), ("sase-1.2", "worker.2")],
        acquisitions=[("sase-1.3", "worker.3"), ("sase-1.4", "worker.4")],
        log=make_runtime(tmp_path).log,
    )

    assert lock_entries == [beads_dir]
    assert project.release_agent_claim.call_args_list == [
        call("sase-1.1", "worker.1"),
        call("sase-1.2", "worker.2"),
    ]
    assert project.claim_for_agent_wait.call_args_list == [
        call("sase-1.3", "worker.3"),
        call("sase-1.4", "worker.4"),
    ]
    commit.assert_called_once()
    assert commit.call_args.args == (beads_dir,)
    assert commit.call_args.kwargs["already_locked"] is True
    assert commit.call_args.kwargs["mutation_origin"] == "machine"
    assert commit.call_args.kwargs["operation_context"] is operation_context
    publish.assert_called_once_with(beads_dir, "reconciliation", "sase")
    hint.assert_called_once_with("sase")
    assert result.released == frozenset(
        {("sase-1.1", "worker.1"), ("sase-1.2", "worker.2")}
    )
    assert result.held == frozenset(
        {("sase-1.3", "worker.3"), ("sase-1.4", "worker.4")}
    )


def test_unresolvable_assignee_is_not_released(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    holders, lock_entries, commit, publish = install_leased_apply(monkeypatch, tmp_path)
    dead = make_artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [dead])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _beads_dir: [make_claimed_issue(assignee="missing-agent")],
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert holders == ["bead_claim_checks:sase"]
    assert lock_entries == []
    commit.assert_not_called()
    publish.assert_not_called()
    assert result.counters["claims_examined"] == 1
    assert result.counters["claims_released"] == 0


def test_snapshot_and_reconcile_share_one_lease_and_one_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = MagicMock()
    project.release_agent_claim.return_value = (make_claimed_issue(), True)
    holders, lock_entries, commit, publish = install_leased_apply(
        monkeypatch, tmp_path, project=project
    )
    events: list[str] = []
    record = make_artifact(tmp_path)
    refresh_calls: list[Path] = []

    def scan(_root: Path) -> list[claim_checks._ClaimArtifact]:
        events.append("scan")
        return [record]

    def read(_beads_dir: Path) -> list[Issue]:
        events.append("beads")
        return [make_claimed_issue()]

    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", scan)
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(claim_checks, "_read_claimed_issues", read)
    monkeypatch.setattr(
        claim_checks,
        "refresh_bead_store",
        lambda path: refresh_calls.append(path),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert events == ["scan", "beads", "scan"]
    assert holders == ["bead_claim_checks:sase"]
    assert len(refresh_calls) == 1
    assert lock_entries == [tmp_path / "beads"]
    commit.assert_called_once()
    publish.assert_called_once_with(tmp_path / "beads", "reconciliation", "sase")
    project.release_agent_claim.assert_called_once_with("sase-1.1", "sase-1.1")
    assert result.counters == {
        "projects_scanned": 1,
        "claims_examined": 1,
        "claims_released": 1,
        "claims_acquired": 0,
    }
    assert tombstone_path(tmp_path).exists()


def test_acquire_only_tick_uses_one_lease_without_reading_claimed_issues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = MagicMock()
    project.claim_for_agent_wait.return_value = (make_claimed_issue(), True)
    holders, lock_entries, commit, publish = install_leased_apply(
        monkeypatch, tmp_path, project=project
    )
    record = make_artifact(tmp_path, has_marker=False)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: True)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _beads_dir: pytest.fail("acquire-only tick used the release read path"),
    )
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: True,
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert holders == ["bead_claim_checks:sase"]
    assert lock_entries == [tmp_path / "beads"]
    commit.assert_called_once()
    publish.assert_called_once()
    project.release_agent_claim.assert_not_called()
    project.claim_for_agent_wait.assert_called_once_with("sase-1.1", "sase-1.1")
    assert result.counters["claims_acquired"] == 1


def test_empty_authoritative_snapshot_skips_write_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    holders, lock_entries, commit, publish = install_leased_apply(monkeypatch, tmp_path)
    record = make_artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(claim_checks, "_read_claimed_issues", lambda _beads_dir: [])

    result = claim_checks._run(make_runtime(tmp_path))

    assert holders == ["bead_claim_checks:sase"]
    assert lock_entries == []
    commit.assert_not_called()
    publish.assert_not_called()
    assert result.reason == "no_claims_reconciled"
    assert tombstone_path(tmp_path).exists()


def test_failed_snapshot_still_applies_acquisitions_under_the_same_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = MagicMock()
    project.claim_for_agent_wait.return_value = (
        make_claimed_issue(bead_id="sase-1.2", assignee="live.1"),
        True,
    )
    holders, lock_entries, commit, publish = install_leased_apply(
        monkeypatch, tmp_path, project=project
    )
    dead = make_artifact(tmp_path, name="dead.1", bead_id="sase-1.1")
    live = make_artifact(
        tmp_path,
        name="live.1",
        bead_id="sase-1.2",
        has_marker=False,
        timestamp="20260724120001",
    )
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [dead, live],
    )
    monkeypatch.setattr(
        claim_checks,
        "_claim_owner_is_alive",
        lambda record: record.agent_name == "live.1",
    )

    def unreadable(_beads_dir: Path) -> list[Issue]:
        raise RuntimeError("store is broken")

    monkeypatch.setattr(claim_checks, "_read_claimed_issues", unreadable)
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: True,
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert holders == ["bead_claim_checks:sase"]
    assert lock_entries == [tmp_path / "beads"]
    commit.assert_called_once()
    publish.assert_called_once()
    project.release_agent_claim.assert_not_called()
    project.claim_for_agent_wait.assert_called_once_with("sase-1.2", "live.1")
    assert result.counters["claims_acquired"] == 1
    assert result.counters["claims_released"] == 0
    assert not tombstone_path(tmp_path).exists()


def test_two_projects_each_take_one_lease_and_isolate_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = MagicMock()
    project.release_agent_claim.return_value = (
        make_claimed_issue(bead_id="beta-1.1", assignee="beta-1.1"),
        True,
    )
    holders, lock_entries, commit, publish = install_leased_apply(
        monkeypatch,
        tmp_path,
        project=project,
        fail_projects=frozenset({"alpha"}),
    )
    alpha = make_artifact(
        tmp_path,
        name="alpha-1.1",
        bead_id="alpha-1.1",
        project_name="alpha",
        timestamp="20260724120000",
    )
    beta = make_artifact(
        tmp_path,
        name="beta-1.1",
        bead_id="beta-1.1",
        project_name="beta",
        timestamp="20260724120001",
    )
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [alpha, beta],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _beads_dir: [
            make_claimed_issue(bead_id="beta-1.1", assignee="beta-1.1")
        ],
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert holders == ["bead_claim_checks:alpha", "bead_claim_checks:beta"]
    assert lock_entries == [tmp_path / "beads"]
    commit.assert_called_once()
    publish.assert_called_once_with(tmp_path / "beads", "reconciliation", "beta")
    assert result.counters["claims_released"] == 1
    assert not tombstone_path(tmp_path, "20260724120000").exists()
    assert tombstone_path(tmp_path, "20260724120001").exists()
