"""Stale waiting-agent bead claim reconciliation tests."""

from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, Status
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_claim_checks",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _artifact(
    tmp_path: Path,
    *,
    name: str = "sase-1.1",
    bead_id: str = "sase-1.1",
    promoted: bool | None = False,
    has_marker: bool = True,
    timestamp: str = "20260724120000",
    tombstoned: bool = False,
) -> claim_checks._ClaimArtifact:
    return claim_checks._ClaimArtifact(
        project_name="sase",
        agent_name=name,
        artifact_dir=tmp_path / timestamp,
        timestamp=timestamp,
        pid=123,
        stopped_at=None,
        bead_id=bead_id,
        bead_claim_promoted=promoted,
        has_bead_claim_marker=has_marker,
        has_reconcile_tombstone=tombstoned,
    )


def _tombstone_path(tmp_path: Path, timestamp: str = "20260724120000") -> Path:
    return tmp_path / timestamp / claim_checks.BEAD_CLAIM_RECONCILED_MARKER


def _claimed_issue(
    *,
    bead_id: str = "sase-1.1",
    assignee: str = "sase-1.1",
) -> Issue:
    return Issue(
        id=bead_id,
        title="Claimed phase",
        status=Status.CLAIMED,
        parent_id="sase-1",
        assignee=assignee,
    )


def _reconciliation(
    *,
    released: tuple[tuple[str, str], ...] = (),
    release_errors: tuple[tuple[str, str], ...] = (),
    held: tuple[tuple[str, str], ...] = (),
) -> claim_checks._ProjectClaimReconciliation:
    return claim_checks._ProjectClaimReconciliation(
        released=frozenset(released),
        release_errors=frozenset(release_errors),
        held=frozenset(held),
    )


def test_project_reconciliation_batches_mutations_into_one_commit_and_push(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    project = MagicMock()
    project.release_agent_claim.side_effect = [
        (_claimed_issue(bead_id="sase-1.1", assignee="worker.1"), True),
        (_claimed_issue(bead_id="sase-1.2", assignee="worker.2"), True),
    ]
    project.claim_for_agent_wait.side_effect = [
        (_claimed_issue(bead_id="sase-1.3", assignee="worker.3"), True),
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
    monkeypatch.setattr(
        claim_checks,
        "canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr(
        claim_checks,
        "open_bead_project_for_beads_dir",
        lambda _path: project_context,
    )
    monkeypatch.setattr(claim_checks, "bead_store_write_lock", lock)
    monkeypatch.setattr(claim_checks, "commit_bead_claim_reconciliation", commit)
    monkeypatch.setattr(claim_checks, "publish_bead_claim", publish)

    result = claim_checks._reconcile_project_claims(
        "sase",
        releases=[("sase-1.1", "worker.1"), ("sase-1.2", "worker.2")],
        acquisitions=[("sase-1.3", "worker.3"), ("sase-1.4", "worker.4")],
        log=_runtime(tmp_path).log,
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
    commit.assert_called_once_with(beads_dir, already_locked=True)
    publish.assert_called_once_with(beads_dir, "reconciliation", "sase")
    assert result.released == frozenset(
        {("sase-1.1", "worker.1"), ("sase-1.2", "worker.2")}
    )
    assert result.held == frozenset(
        {("sase-1.3", "worker.3"), ("sase-1.4", "worker.4")}
    )


def test_artifact_scan_records_claim_marker_presence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "20260724120000"
    artifact_dir.mkdir()
    (artifact_dir / "agent_meta.json").write_text(
        '{"bead_claim_promoted": false}\n',
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(
        records=[
            SimpleNamespace(
                project_name="sase",
                workflow_dir_name="ace-run",
                artifact_dir=str(artifact_dir),
                timestamp=artifact_dir.name,
                agent_meta=SimpleNamespace(
                    name="sase-1.1",
                    bead_id="sase-1.1",
                    pid=123,
                    stopped_at=None,
                ),
            )
        ]
    )
    monkeypatch.setattr(
        claim_checks,
        "scan_agent_artifacts",
        lambda _root, _options: snapshot,
    )

    assert not claim_checks._scan_claim_artifacts(tmp_path)[0].has_bead_claim_marker

    (artifact_dir / claim_checks.BEAD_CLAIM_MARKER).write_text(
        "{}\n",
        encoding="utf-8",
    )

    assert claim_checks._scan_claim_artifacts(tmp_path)[0].has_bead_claim_marker


def test_dead_unpromoted_owner_is_released_after_bead_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _artifact(tmp_path)
    events: list[str] = []
    scans = iter(([record], [record]))

    def scan(_root: Path) -> list[claim_checks._ClaimArtifact]:
        events.append("scan")
        return next(scans)

    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", scan)
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: events.append("beads") or [_claimed_issue()],
    )

    reconciled: list[tuple[str, list[tuple[str, str]], list[tuple[str, str]]]] = []

    def reconcile(project_name: str, *, releases, acquisitions, log):
        del log
        reconciled.append((project_name, releases, acquisitions))
        return _reconciliation(released=(("sase-1.1", "sase-1.1"),))

    monkeypatch.setattr(claim_checks, "_reconcile_project_claims", reconcile)

    result = claim_checks._run(_runtime(tmp_path))

    assert events == ["scan", "beads", "scan"]
    assert reconciled == [("sase", [("sase-1.1", "sase-1.1")], [])]
    assert result.counters == {
        "projects_scanned": 1,
        "claims_examined": 1,
        "claims_released": 1,
        "claims_acquired": 0,
    }


@pytest.mark.parametrize(
    ("promoted", "alive"),
    [(False, True), (True, False), (True, True), (None, False)],
)
def test_live_promoted_or_unreadable_owner_is_untouched_in_prepass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    promoted: bool | None,
    alive: bool,
) -> None:
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [_artifact(tmp_path, promoted=promoted)],
    )
    monkeypatch.setattr(
        claim_checks,
        "_claim_owner_is_alive",
        lambda _record: alive,
    )

    def unexpected_read(_project: str) -> list[Issue]:
        raise AssertionError("steady-state prepass opened a bead store")

    monkeypatch.setattr(claim_checks, "_read_claimed_issues", unexpected_read)
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: pytest.fail(
            "ineligible agent entered reconcile pass"
        ),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"
    assert result.counters["projects_scanned"] == 0


def test_unresolvable_assignee_is_not_released(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dead = _artifact(tmp_path)
    scans = iter(([dead], [dead]))
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: next(scans),
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: [_claimed_issue(assignee="missing-agent")],
    )
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: pytest.fail("unowned claim must not be released"),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.counters["claims_examined"] == 1
    assert result.counters["claims_released"] == 0


def test_empty_steady_state_never_reads_a_bead_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [])
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: pytest.fail("empty steady state opened a bead store"),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"


def test_live_unpromoted_unmarked_agent_is_claimed_and_marked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _artifact(tmp_path, has_marker=False)
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [record],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: True)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: pytest.fail("acquire-only tick used the release read path"),
    )

    acquired: list[tuple[str, list[tuple[str, str]]]] = []
    marked: list[tuple[Path, str, str, str]] = []

    def reconcile(project_name: str, *, releases, acquisitions, log):
        del log, releases
        acquired.append((project_name, acquisitions))
        return _reconciliation(held=(("sase-1.1", "sase-1.1"),))

    def mark(
        artifacts_dir: Path,
        *,
        project_name: str,
        bead_id: str,
        agent_name: str,
    ) -> bool:
        marked.append((artifacts_dir, project_name, bead_id, agent_name))
        return True

    monkeypatch.setattr(claim_checks, "_reconcile_project_claims", reconcile)
    monkeypatch.setattr(claim_checks, "write_bead_claim_marker", mark)

    result = claim_checks._run(_runtime(tmp_path))

    assert acquired == [("sase", [("sase-1.1", "sase-1.1")])]
    assert marked == [(record.artifact_dir, "sase", "sase-1.1", "sase-1.1")]
    assert result.reason is None
    assert result.counters == {
        "projects_scanned": 1,
        "claims_examined": 1,
        "claims_released": 0,
        "claims_acquired": 1,
    }


@pytest.mark.parametrize("status", [Status.IN_PROGRESS, Status.CLOSED])
def test_live_candidate_declined_by_terminal_bead_state_is_not_marked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: Status,
) -> None:
    record = _artifact(tmp_path, has_marker=False)
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [record],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: True)
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: _reconciliation(),
    )
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: pytest.fail(
            f"{status.value} bead must not receive a marker"
        ),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_claims_reconciled"
    assert result.counters["claims_acquired"] == 0


def test_dead_agent_is_never_acquired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _artifact(tmp_path, has_marker=False)
    scans = iter(([record], [record]))
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: next(scans),
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(claim_checks, "_read_claimed_issues", lambda _project: [])
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: pytest.fail("dead agent must not acquire a claim"),
    )

    result = claim_checks._run(_runtime(tmp_path))

    assert result.reason == "no_claims_reconciled"
    assert result.counters["claims_acquired"] == 0


def test_reconciled_dead_owner_stops_opening_bead_stores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One reconciliation cycle must restore the zero-store-read steady state."""
    reads: list[str] = []

    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [
            _artifact(tmp_path, tombstoned=_tombstone_path(tmp_path).exists())
        ],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda project: reads.append(project) or [_claimed_issue()],
    )
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: _reconciliation(released=(("sase-1.1", "sase-1.1"),)),
    )

    first = claim_checks._run(_runtime(tmp_path))

    assert first.counters["claims_released"] == 1
    assert reads == ["sase"]
    assert _tombstone_path(tmp_path).exists()

    second = claim_checks._run(_runtime(tmp_path))

    assert second.reason == "no_claim_reconciliation_candidates"
    assert reads == ["sase"]


def test_dead_owner_without_a_claim_is_still_tombstoned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A store read that proves there is nothing to release is terminal too."""
    record = _artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(claim_checks, "_read_claimed_issues", lambda _project: [])

    claim_checks._run(_runtime(tmp_path))

    assert _tombstone_path(tmp_path).exists()


def test_failed_release_and_unreadable_store_leave_no_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: [_claimed_issue()],
    )
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: _reconciliation(
            release_errors=(("sase-1.1", "sase-1.1"),)
        ),
    )

    claim_checks._run(_runtime(tmp_path))

    assert not _tombstone_path(tmp_path).exists()

    def unreadable(_project: str) -> list[Issue]:
        raise RuntimeError("store is broken")

    monkeypatch.setattr(claim_checks, "_read_claimed_issues", unreadable)

    claim_checks._run(_runtime(tmp_path))

    assert not _tombstone_path(tmp_path).exists()


def test_acquire_then_die_is_released_on_following_tick(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alive_record = _artifact(tmp_path, has_marker=False)
    dead_record = _artifact(tmp_path, has_marker=True)
    current_record = alive_record
    alive = True

    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [current_record],
    )
    monkeypatch.setattr(
        claim_checks,
        "_claim_owner_is_alive",
        lambda _record: alive,
    )
    outcomes = iter(
        (
            _reconciliation(held=(("sase-1.1", "sase-1.1"),)),
            _reconciliation(released=(("sase-1.1", "sase-1.1"),)),
        )
    )
    monkeypatch.setattr(
        claim_checks,
        "_reconcile_project_claims",
        lambda *_args, **_kwargs: next(outcomes),
    )
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: True,
    )

    first = claim_checks._run(_runtime(tmp_path))
    assert first.counters["claims_acquired"] == 1

    current_record = dead_record
    alive = False
    monkeypatch.setattr(
        claim_checks,
        "_read_claimed_issues",
        lambda _project: [_claimed_issue()],
    )
    second = claim_checks._run(_runtime(tmp_path))

    assert second.counters["claims_released"] == 1
