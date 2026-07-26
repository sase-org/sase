"""Stale waiting-agent bead claim reconciliation tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.claims import BeadClaimReleaseOutcome
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
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
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

    released: list[tuple[str, str, str]] = []

    def release(
        *, project_name: str, bead_id: str, agent_name: str
    ) -> BeadClaimReleaseOutcome:
        released.append((project_name, bead_id, agent_name))
        return BeadClaimReleaseOutcome.RELEASED

    monkeypatch.setattr(claim_checks, "release_bead_claim_for_agent", release)

    result = claim_checks._run(_runtime(tmp_path))

    assert events == ["scan", "beads", "scan"]
    assert released == [("sase", "sase-1.1", "sase-1.1")]
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
        "claim_bead_for_waiting_agent",
        lambda **_kwargs: pytest.fail("ineligible agent entered acquire pass"),
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
        "release_bead_claim_for_agent",
        lambda **_kwargs: pytest.fail("unowned claim must not be released"),
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

    acquired: list[tuple[str, str, str]] = []
    marked: list[tuple[Path, str, str, str]] = []

    def claim(*, project_name: str, bead_id: str, agent_name: str) -> bool:
        acquired.append((project_name, bead_id, agent_name))
        return True

    def mark(
        artifacts_dir: Path,
        *,
        project_name: str,
        bead_id: str,
        agent_name: str,
    ) -> bool:
        marked.append((artifacts_dir, project_name, bead_id, agent_name))
        return True

    monkeypatch.setattr(claim_checks, "claim_bead_for_waiting_agent", claim)
    monkeypatch.setattr(claim_checks, "write_bead_claim_marker", mark)

    result = claim_checks._run(_runtime(tmp_path))

    assert acquired == [("sase", "sase-1.1", "sase-1.1")]
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
        "claim_bead_for_waiting_agent",
        lambda **_kwargs: False,
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
        "claim_bead_for_waiting_agent",
        lambda **_kwargs: pytest.fail("dead agent must not acquire a claim"),
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
        "release_bead_claim_for_agent",
        lambda **_kwargs: BeadClaimReleaseOutcome.RELEASED,
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
        "release_bead_claim_for_agent",
        lambda **_kwargs: BeadClaimReleaseOutcome.ERROR,
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
    monkeypatch.setattr(
        claim_checks,
        "claim_bead_for_waiting_agent",
        lambda **_kwargs: True,
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
    released: list[str] = []
    monkeypatch.setattr(
        claim_checks,
        "release_bead_claim_for_agent",
        lambda **kwargs: (
            released.append(kwargs["bead_id"]) or BeadClaimReleaseOutcome.RELEASED
        ),
    )

    second = claim_checks._run(_runtime(tmp_path))

    assert released == ["sase-1.1"]
    assert second.counters["claims_released"] == 1
