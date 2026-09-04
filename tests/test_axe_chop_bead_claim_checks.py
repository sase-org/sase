"""Claim-candidate prepass, acquisition, and tombstone reconciliation tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_bead_claim_checks as claim_checks
from sase.bead.claims import BEAD_CLAIM_MARKER
from sase.bead.model import Status
from sase.chops.sdk import ChopLogger

from tests._axe_chop_bead_claim_checks_helpers import (
    make_artifact,
    make_runtime,
    make_tick,
    tombstone_path,
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

    (artifact_dir / BEAD_CLAIM_MARKER).write_text(
        "{}\n",
        encoding="utf-8",
    )

    assert claim_checks._scan_claim_artifacts(tmp_path)[0].has_bead_claim_marker


def test_dead_unpromoted_owner_is_released_after_bead_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = make_artifact(tmp_path)
    processed: list[tuple[str, bool, list[tuple[str, str]]]] = []

    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)

    def process(
        project_name: str,
        *,
        need_claimed_snapshot: bool,
        acquisitions: list[tuple[str, str]],
        projects_root: Path,
        log: ChopLogger,
    ) -> claim_checks._ProjectClaimTick:
        del projects_root, log
        processed.append((project_name, need_claimed_snapshot, acquisitions))
        return make_tick(
            snapshot_ok=True,
            scanned=True,
            claimed_count=1,
            released=(("sase-1.1", "sase-1.1"),),
        )

    monkeypatch.setattr(claim_checks, "_process_project_claims", process)

    result = claim_checks._run(make_runtime(tmp_path))

    assert processed == [("sase", True, [])]
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
        lambda _root: [make_artifact(tmp_path, promoted=promoted)],
    )
    monkeypatch.setattr(
        claim_checks,
        "_claim_owner_is_alive",
        lambda _record: alive,
    )
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: pytest.fail(
            "ineligible agent entered reconcile pass"
        ),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"
    assert result.counters["projects_scanned"] == 0


def test_empty_steady_state_never_reads_a_bead_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [])
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: pytest.fail("empty steady state opened a bead store"),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert result.reason == "no_claim_reconciliation_candidates"


def test_live_unpromoted_unmarked_agent_is_claimed_and_marked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = make_artifact(tmp_path, has_marker=False)
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [record],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: True)

    acquired: list[tuple[str, list[tuple[str, str]]]] = []
    marked: list[tuple[Path, str, str, str]] = []

    def process(
        project_name: str,
        *,
        need_claimed_snapshot: bool,
        acquisitions: list[tuple[str, str]],
        projects_root: Path,
        log: ChopLogger,
    ) -> claim_checks._ProjectClaimTick:
        del need_claimed_snapshot, projects_root, log
        acquired.append((project_name, acquisitions))
        return make_tick(held=(("sase-1.1", "sase-1.1"),))

    def mark(
        artifacts_dir: Path,
        *,
        project_name: str,
        bead_id: str,
        agent_name: str,
    ) -> bool:
        marked.append((artifacts_dir, project_name, bead_id, agent_name))
        return True

    monkeypatch.setattr(claim_checks, "_process_project_claims", process)
    monkeypatch.setattr(claim_checks, "write_bead_claim_marker", mark)

    result = claim_checks._run(make_runtime(tmp_path))

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
    record = make_artifact(tmp_path, has_marker=False)
    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [record],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: True)
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: make_tick(),
    )
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: pytest.fail(
            f"{status.value} bead must not receive a marker"
        ),
    )

    result = claim_checks._run(make_runtime(tmp_path))

    assert result.reason == "no_claims_reconciled"
    assert result.counters["claims_acquired"] == 0


def test_dead_agent_is_never_acquired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = make_artifact(tmp_path, has_marker=False)
    processed: list[list[tuple[str, str]]] = []
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)

    def process(
        project_name: str,
        *,
        need_claimed_snapshot: bool,
        acquisitions: list[tuple[str, str]],
        projects_root: Path,
        log: ChopLogger,
    ) -> claim_checks._ProjectClaimTick:
        del project_name, need_claimed_snapshot, projects_root, log
        processed.append(acquisitions)
        return make_tick(snapshot_ok=True, scanned=True)

    monkeypatch.setattr(claim_checks, "_process_project_claims", process)

    result = claim_checks._run(make_runtime(tmp_path))

    assert processed == [[]]
    assert result.reason == "no_claims_reconciled"
    assert result.counters["claims_acquired"] == 0


def test_reconciled_dead_owner_stops_opening_bead_stores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One reconciliation cycle must restore the zero-store-read steady state."""
    ticks: list[str] = []

    monkeypatch.setattr(
        claim_checks,
        "_scan_claim_artifacts",
        lambda _root: [
            make_artifact(tmp_path, tombstoned=tombstone_path(tmp_path).exists())
        ],
    )
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)

    def process(
        project_name: str,
        *,
        need_claimed_snapshot: bool,
        acquisitions: list[tuple[str, str]],
        projects_root: Path,
        log: ChopLogger,
    ) -> claim_checks._ProjectClaimTick:
        del need_claimed_snapshot, acquisitions, projects_root, log
        ticks.append(project_name)
        return make_tick(
            snapshot_ok=True,
            scanned=True,
            claimed_count=1,
            released=(("sase-1.1", "sase-1.1"),),
        )

    monkeypatch.setattr(claim_checks, "_process_project_claims", process)

    first = claim_checks._run(make_runtime(tmp_path))

    assert first.counters["claims_released"] == 1
    assert ticks == ["sase"]
    assert tombstone_path(tmp_path).exists()

    second = claim_checks._run(make_runtime(tmp_path))

    assert second.reason == "no_claim_reconciliation_candidates"
    assert ticks == ["sase"]


def test_dead_owner_without_a_claim_is_still_tombstoned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A store read that proves there is nothing to release is terminal too."""
    record = make_artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: make_tick(snapshot_ok=True, scanned=True),
    )

    claim_checks._run(make_runtime(tmp_path))

    assert tombstone_path(tmp_path).exists()


def test_failed_release_and_unreadable_store_leave_no_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = make_artifact(tmp_path)
    monkeypatch.setattr(claim_checks, "_scan_claim_artifacts", lambda _root: [record])
    monkeypatch.setattr(claim_checks, "_claim_owner_is_alive", lambda _record: False)
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: make_tick(
            snapshot_ok=True,
            scanned=True,
            claimed_count=1,
            release_errors=(("sase-1.1", "sase-1.1"),),
        ),
    )

    claim_checks._run(make_runtime(tmp_path))

    assert not tombstone_path(tmp_path).exists()

    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: make_tick(),
    )

    claim_checks._run(make_runtime(tmp_path))

    assert not tombstone_path(tmp_path).exists()


def test_acquire_then_die_is_released_on_following_tick(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    alive_record = make_artifact(tmp_path, has_marker=False)
    dead_record = make_artifact(tmp_path, has_marker=True)
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
            make_tick(held=(("sase-1.1", "sase-1.1"),)),
            make_tick(
                snapshot_ok=True,
                scanned=True,
                claimed_count=1,
                released=(("sase-1.1", "sase-1.1"),),
            ),
        )
    )
    monkeypatch.setattr(
        claim_checks,
        "_process_project_claims",
        lambda *_args, **_kwargs: next(outcomes),
    )
    monkeypatch.setattr(
        claim_checks,
        "write_bead_claim_marker",
        lambda *_args, **_kwargs: True,
    )

    first = claim_checks._run(make_runtime(tmp_path))
    assert first.counters["claims_acquired"] == 1

    current_record = dead_record
    alive = False
    second = claim_checks._run(make_runtime(tmp_path))

    assert second.counters["claims_released"] == 1
