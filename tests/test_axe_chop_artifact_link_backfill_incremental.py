"""Incremental skips of the artifact_link_backfill chop, pinned by call counts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts._artifact_link_backfill_jobs as backfill_jobs
import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.chops.sdk import ChopResultBuilder
from sase.scripts._artifact_link_backfill_schedule import (
    SCHEDULE_FILENAME,
    BackfillSchedule,
    read_backfill_schedule,
    write_backfill_schedule,
)
from sase.sdd._artifact_link_incremental import (
    FULL_PASS_INTERVAL_SECONDS,
    ArtifactLinkReconcileMemo,
)
from sase.sdd.artifact_link_backfill import (
    _ArtifactLinkBackfillReport,
    _ArtifactLinkReconcileReport,
)

from tests._axe_chop_artifact_link_backfill_helpers import (
    _default_no_publication_retry,  # noqa: F401 (registers the autouse fixture)
    _project,
    _runtime_with_logs,
)

_NOW = 1_800_000_000.0


class _Harness:
    """One project's chop run with fingerprints and sweep results under test control."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.now = _NOW
        self.fingerprint: str | None = "docs-1"
        self.remaining = 0
        self.sweep_calls = 0
        self.memos: list[ArtifactLinkReconcileMemo | None] = []
        self.report = _ArtifactLinkReconcileReport()
        project = _project(tmp_path, name="p1")
        monkeypatch.setattr(
            backfill_chop, "_enabled_project_records", lambda: [project]
        )
        monkeypatch.setattr(
            backfill_jobs,
            "resolve_machine_artifact_link_store",
            lambda project_key, _checkout, **_kwargs: SimpleNamespace(
                project_key=project_key
            ),
        )
        monkeypatch.setattr(
            backfill_jobs, "document_sweep_fingerprint", lambda _store: self.fingerprint
        )
        monkeypatch.setattr(
            backfill_jobs, "run_artifact_link_backfill_batch", self._sweep
        )
        monkeypatch.setattr(
            backfill_jobs,
            "drain_artifact_link_outbox",
            lambda **_kwargs: SimpleNamespace(
                drained=0, dropped=0, deferred=False, stale_checked=True
            ),
        )
        monkeypatch.setattr(
            backfill_jobs, "reconcile_and_repair_artifact_links", self._reconcile
        )
        monkeypatch.setattr(backfill_jobs.time, "time", lambda: self.now)

    def _sweep(
        self, _store: object, **_kwargs: object
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        self.sweep_calls += 1
        return (
            _ArtifactLinkBackfillReport(scanned=1, remaining=self.remaining),
            frozenset({"plan:202611/a.md"}),
        )

    def _reconcile(
        self, _store: object, *, memo: object = None, **_kwargs: object
    ) -> _ArtifactLinkReconcileReport:
        assert memo is None or isinstance(memo, ArtifactLinkReconcileMemo)
        self.memos.append(memo)
        if isinstance(memo, ArtifactLinkReconcileMemo):
            memo.input_fingerprint = "reconciled"
            memo.full_pass_at = self.now
        return self.report

    def run(self) -> ChopResultBuilder:
        runtime, _stdout, _stderr = _runtime_with_logs(self.tmp_path)
        return backfill_chop._run(runtime)

    def schedule(self) -> BackfillSchedule:
        return read_backfill_schedule(self.tmp_path / "state" / SCHEDULE_FILENAME)


def test_unchanged_document_tree_skips_the_sweep_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness(tmp_path, monkeypatch)

    first = harness.run()
    harness.now += 3_600.0
    second = harness.run()

    assert harness.sweep_calls == 1
    assert first.counters["sweep_skipped"] == 0
    assert second.counters["sweep_skipped"] == 1
    schedule = harness.schedule()
    assert schedule.sweep_fingerprints == {"p1": "docs-1"}
    assert schedule.sweep_full_at == {"p1": _NOW}


def test_changed_tree_backlog_unknown_tree_and_daily_backstop_all_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness(tmp_path, monkeypatch)
    harness.run()

    harness.fingerprint = "docs-2"
    harness.run()
    assert harness.sweep_calls == 2

    # A sweep that left documents pending can never vouch for a skip.
    harness.fingerprint = "docs-3"
    harness.remaining = 4
    harness.run()
    harness.run()
    assert harness.sweep_calls == 4
    assert "p1" not in harness.schedule().sweep_fingerprints

    harness.remaining = 0
    harness.fingerprint = None
    harness.run()
    harness.run()
    assert harness.sweep_calls == 6

    harness.fingerprint = "docs-4"
    harness.run()
    harness.run()
    assert harness.sweep_calls == 7
    harness.now += FULL_PASS_INTERVAL_SECONDS
    harness.run()
    assert harness.sweep_calls == 8


def test_reconcile_memo_persists_across_ticks_and_counts_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness(tmp_path, monkeypatch)
    harness.run()
    harness.report = _ArtifactLinkReconcileReport(
        reconcile_skipped=True, projection_changed=True, rename_scan_skipped=True
    )

    result = harness.run()

    first_memo, second_memo = harness.memos
    assert first_memo is not None and second_memo is not None
    assert second_memo.input_fingerprint == "reconciled"
    assert harness.schedule().reconcile_memos["p1"] == ArtifactLinkReconcileMemo(
        input_fingerprint="reconciled", full_pass_at=_NOW
    )
    assert result.counters["reconcile_skipped"] == 1
    assert result.counters["projection_refreshed"] == 1
    assert result.counters["rename_scan_skipped"] == 1


def test_a_skipped_reconcile_never_lowers_the_full_reconcile_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness(tmp_path, monkeypatch)
    write_backfill_schedule(
        tmp_path / "state" / SCHEDULE_FILENAME,
        BackfillSchedule(reconcile_seconds={"p1": 90.0}),
    )
    harness.report = _ArtifactLinkReconcileReport(reconcile_skipped=True)

    harness.run()

    assert harness.schedule().reconcile_seconds == {"p1": 90.0}


def test_a_live_memo_lets_a_later_project_start_its_cheap_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _Harness(tmp_path, monkeypatch)
    projects = [_project(tmp_path, name=name) for name in ("p0", "p1", "p2")]
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: projects)
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: 0.0)
    write_backfill_schedule(
        tmp_path / "state" / SCHEDULE_FILENAME,
        BackfillSchedule(
            reconcile_seconds={"p1": 500.0, "p2": 500.0},
            reconcile_memos={
                "p1": ArtifactLinkReconcileMemo(
                    input_fingerprint="in:agg", full_pass_at=_NOW - 60.0
                ),
                "p2": ArtifactLinkReconcileMemo(
                    input_fingerprint="in:agg",
                    full_pass_at=_NOW - FULL_PASS_INTERVAL_SECONDS,
                ),
            },
        ),
    )

    result = harness.run()

    # p0 is first; p1's memo can still vouch for a skip; p2's backstop is due.
    assert len(harness.memos) == 2
    assert result.counters["deferred_projects"] == 1
