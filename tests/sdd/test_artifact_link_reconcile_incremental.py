"""Skip paths of the hourly reconcile-and-repair pass, pinned by call counts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sase.sdd.artifact_link_backfill as backfill
from sase.sdd._artifact_link_incremental import (
    FULL_PASS_INTERVAL_SECONDS,
    ArtifactLinkReconcileMemo,
)
from sase.sdd._artifact_link_store_aggregate import ArtifactLinkAggregateWriteDeferred
from sase.sdd._artifact_link_store_reconcile import AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row

_NOW = 1_800_000_000.0


class _FakeStore:
    """Records which expensive passes ran; rows stand in for the aggregate."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = [_row()]
        self.reconcile_calls = 0
        self.refresh_calls = 0
        self.reconcile_diagnostics: tuple[str, ...] = ()
        self.refresh_error: Exception | None = None
        self.sidecar_roots: dict[str, Path] = {}
        self.sdd_store = None

    def load_aggregate(self) -> dict[str, Any]:
        return {"generation": 1, "rows": list(self.rows)}

    def reconcile_aggregate(self, *, deadline: float | None = None) -> dict[str, Any]:
        del deadline
        self.reconcile_calls += 1
        document: dict[str, Any] = {"generation": 2, "rows": list(self.rows)}
        if self.reconcile_diagnostics:
            document["skip_diagnostics"] = self.reconcile_diagnostics
        return document

    def refresh_projected_aggregate_rows(
        self, *, deadline: float | None = None
    ) -> bool:
        del deadline
        self.refresh_calls += 1
        if self.refresh_error is not None:
            raise self.refresh_error
        return True


class _World:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inputs: str | None = "inputs-1"
        self.dangling: tuple[str, ...] = ("plan:202611/gone.md",)
        self.heads = "head-1"
        self.renames: tuple[object, ...] = ()
        self.repair_calls = 0
        self.dangling_calls = 0
        monkeypatch.setattr(
            backfill, "reconcile_input_fingerprint", lambda _store: self.inputs
        )
        monkeypatch.setattr(
            backfill,
            "unrepairable_refs_fingerprint",
            lambda _store, refs: f"{sorted(refs)}@{self.heads}",
        )
        monkeypatch.setattr(
            "sase.artifact_cli.link_health.dangling_and_orphaned_artifact_link_refs",
            self._dangling,
        )
        monkeypatch.setattr(
            "sase.sdd._artifact_link_renames.repair_historical_artifact_renames",
            self._repair,
        )

    def _dangling(self, _store: object, **_kwargs: object) -> tuple[str, ...]:
        self.dangling_calls += 1
        return self.dangling

    def _repair(self, _store: object, refs: object, **_kwargs: object) -> object:
        del refs
        self.repair_calls += 1
        return SimpleNamespace(
            renames=self.renames,
            deferred_refs=0,
            changed_paths=(),
            skip_diagnostics=(),
        )


def _run(
    store: _FakeStore, memo: ArtifactLinkReconcileMemo | None, *, now: float = _NOW
) -> Any:
    return backfill.reconcile_and_repair_artifact_links(
        store,  # type: ignore[arg-type]
        memo=memo,
        now=now,
    )


def test_unchanged_inputs_skip_reconcile_and_rename_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()

    first = _run(store, memo)
    assert (store.reconcile_calls, store.refresh_calls, world.repair_calls) == (1, 0, 1)
    assert first.reconcile_skipped is False
    assert memo.input_fingerprint is not None
    assert memo.unrepairable_refs is not None
    assert memo.full_pass_at == _NOW

    second = _run(store, memo, now=_NOW + 3_600.0)
    assert (store.reconcile_calls, store.refresh_calls, world.repair_calls) == (1, 1, 1)
    assert second.reconcile_skipped is True
    assert second.projection_changed is True
    assert second.rename_scan_skipped is True
    assert memo.full_pass_at == _NOW


def test_changed_event_inputs_or_aggregate_run_the_full_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()
    _run(store, memo)

    world.inputs = "inputs-2"
    assert _run(store, memo, now=_NOW + 60.0).reconcile_skipped is False
    assert store.reconcile_calls == 2

    # A foreign writer changed a store-backed row after the last reconcile.
    store.rows = [_row(description="written by another workspace")]
    assert _run(store, memo, now=_NOW + 120.0).reconcile_skipped is False
    assert store.reconcile_calls == 3

    # Projected rows alone never count as an aggregate change.
    store.rows = [*store.rows, _row(target="plan:202608/p.md", origin="projected")]
    assert _run(store, memo, now=_NOW + 180.0).reconcile_skipped is True
    assert store.reconcile_calls == 3


def test_unreadable_inputs_never_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(monkeypatch)
    world.inputs = None
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()

    _run(store, memo)
    _run(store, memo, now=_NOW + 60.0)

    assert store.reconcile_calls == 2
    assert memo.input_fingerprint is None


def test_daily_backstop_runs_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()
    _run(store, memo)

    later = _NOW + FULL_PASS_INTERVAL_SECONDS
    report = _run(store, memo, now=later)

    assert report.reconcile_skipped is False
    assert report.rename_scan_skipped is False
    assert (store.reconcile_calls, world.repair_calls) == (2, 2)
    assert memo.full_pass_at == later


def test_rename_scan_reruns_when_dangling_set_or_heads_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()
    _run(store, memo)

    world.dangling = (*world.dangling, "research:202611/old.md")
    assert _run(store, memo, now=_NOW + 60.0).rename_scan_skipped is False
    assert world.repair_calls == 2

    world.heads = "head-2"
    assert _run(store, memo, now=_NOW + 120.0).rename_scan_skipped is False
    assert world.repair_calls == 3

    assert _run(store, memo, now=_NOW + 180.0).rename_scan_skipped is True
    assert world.repair_calls == 3


def test_a_scan_that_repaired_something_is_not_memoized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    world.renames = (object(),)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()

    _run(store, memo)
    _run(store, memo, now=_NOW + 60.0)

    assert memo.unrepairable_refs is None
    assert world.repair_calls == 2


def test_deferred_reconcile_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    store.reconcile_diagnostics = (AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC,)
    memo = ArtifactLinkReconcileMemo()

    report = _run(store, memo)

    assert memo == ArtifactLinkReconcileMemo()
    assert world.dangling_calls == 0
    assert AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC in report.skip_diagnostics


def test_deferred_projection_refresh_stops_before_dangling_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()
    memo = ArtifactLinkReconcileMemo()
    _run(store, memo)
    store.refresh_error = ArtifactLinkAggregateWriteDeferred(
        attempts=1, last_compute_seconds=1.0
    )

    report = _run(store, memo, now=_NOW + 60.0)

    assert report.reconcile_skipped is True
    assert AGGREGATE_WRITE_DEFERRED_DIAGNOSTIC in report.skip_diagnostics
    assert world.dangling_calls == 1


def test_without_a_memo_every_pass_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(monkeypatch)
    store = _FakeStore()

    _run(store, None)
    _run(store, None)

    assert (store.reconcile_calls, store.refresh_calls, world.repair_calls) == (2, 0, 2)


def _real_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "machine" / "plans"
    plans.mkdir(parents=True)
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase", sidecar_roots={"plan": plans}
    )


def test_projection_refresh_keeps_store_backed_rows_and_writes_only_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _real_store(tmp_path, monkeypatch)
    durable = _row()
    stale = _row(target="plan:202608/stale.md", origin="projected")
    fresh = _row(target="plan:202608/fresh.md", origin="projected")
    store._write_aggregate({"rows": [durable, stale]})
    projected = [fresh]
    monkeypatch.setattr(
        ArtifactLinkStore, "projected_rows", lambda self: tuple(projected)
    )

    assert store.refresh_projected_aggregate_rows() is True
    written = store.load_aggregate()
    assert written["rows"] == [durable, fresh]

    assert store.refresh_projected_aggregate_rows() is False
    assert store.load_aggregate()["generation"] == written["generation"]

    # A projected row that duplicates a store-backed identity loses to it.
    projected[:] = [fresh, {**durable, "origin": "projected"}]
    assert store.refresh_projected_aggregate_rows() is False
