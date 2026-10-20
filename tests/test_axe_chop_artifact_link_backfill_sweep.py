"""Sweep aggregation tests for the ``artifact_link_backfill`` chop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.sdd.artifact_link_backfill import (
    _ArtifactLinkBackfillReport,
    _ArtifactLinkReconcileReport,
)

from tests._axe_chop_artifact_link_backfill_helpers import (
    _default_no_publication_retry,  # noqa: F401 (registers the autouse fixture)
    _project,
    _runtime,
    _runtime_with_logs,
)


def test_runs_every_job_and_aggregates_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: object(),
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (
            _ArtifactLinkBackfillReport(scanned=3, persisted=2, remaining=1),
            frozenset({"plan:202608/a.md"}),
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=4, dropped=1, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(repaired_renames=2),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["sweep_scanned"] == 3
    assert result.counters["sweep_persisted"] == 2
    assert result.counters["sweep_remaining"] == 1
    assert result.counters["outbox_drained"] == 4
    assert result.counters["outbox_dropped"] == 1
    assert result.counters["reconciled"] == 1
    assert result.counters["repaired_renames"] == 2

    state = (tmp_path / "state" / backfill_chop._STATE_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "plan:202608/a.md" in state


def test_publication_retry_runs_before_store_resolution_and_reports_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, name="widget")
    order: list[str] = []
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: [project])

    def _roots(
        project_key: str, primary_checkout: Path, **kwargs: object
    ) -> tuple[tuple[object, ...], tuple[str, ...]]:
        order.append(f"roots:{project_key}")
        assert kwargs["deadline"] is not None
        return (object(),), ("plans: diagnostic",)

    monkeypatch.setattr(backfill_chop, "machine_document_sidecar_roots", _roots)

    def _sweep(roots: object, **kwargs: object) -> SimpleNamespace:
        order.append("retry")
        assert kwargs["deadline"] is not None
        return SimpleNamespace(
            attempted=2,
            published=1,
            deferred=1,
            failed=0,
            aged=1,
            discovered=1,
            cleared=1,
            diagnostics=("widget/plans: aged",),
            details=(),
        )

    def _resolve(project_key: str, primary_checkout: Path, **kwargs: object) -> object:
        order.append("resolve")
        assert kwargs["deadline"] is not None
        return object()

    monkeypatch.setattr(
        backfill_chop, "sweep_artifact_link_publication_retries", _sweep
    )
    monkeypatch.setattr(backfill_chop, "resolve_machine_artifact_link_store", _resolve)
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    runtime, _stdout, stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert order == ["roots:widget", "retry", "resolve"]
    assert result.counters["publication_attempted"] == 2
    assert result.counters["publication_published"] == 1
    assert result.counters["publication_deferred"] == 1
    assert result.counters["publication_aged"] == 1
    assert result.counters["publication_discovered"] == 1
    assert result.counters["publication_cleared"] == 1
    warnings = stderr.getvalue()
    assert "plans: diagnostic" in warnings
    assert "widget/plans: aged" in warnings


def test_checkpoint_survives_across_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: object(),
    )
    seen_already_swept: list[frozenset[str]] = []

    def _fake_batch(
        store: object,
        *,
        already_swept: frozenset[str],
        batch_size: int,
        deadline: float | None = None,
        persist_deadline: float | None = None,
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        assert deadline is not None
        assert persist_deadline is not None
        seen_already_swept.append(already_swept)
        return _ArtifactLinkBackfillReport(), already_swept | {"plan:202608/a.md"}

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    backfill_chop._run(_runtime(tmp_path))
    backfill_chop._run(_runtime(tmp_path))

    assert seen_already_swept == [frozenset(), frozenset({"plan:202608/a.md"})]


def test_bead_projection_failed_marks_check_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: object(),
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0,
            dropped=0,
            deferred=False,
            bead_projection_failed=1,
            parked_new=0,
            parked_total=0,
            transient=0,
            parked_details=(),
            skip_diagnostics=("chunk exploded",),
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.status == "check_error"
    assert result.reason == "bead_projection_failed"
    assert result.counters["bead_projection_failed"] == 1


def test_parked_operations_alone_are_not_check_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop, "_enabled_project_records", lambda: [_project(tmp_path)]
    )
    monkeypatch.setattr(
        backfill_chop,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: object(),
    )
    monkeypatch.setattr(
        backfill_chop,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: SimpleNamespace(
            drained=0,
            dropped=0,
            deferred=False,
            bead_projection_failed=0,
            parked_new=2,
            parked_total=2,
            transient=0,
            parked_details=(
                SimpleNamespace(operation_id="c" * 32, reasons=("outcome foreign",)),
            ),
            skip_diagnostics=(),
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    runtime, stdout, _stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert result.status == "ok"
    assert result.reason is None
    assert result.counters["parked_new"] == 2
    assert result.counters["parked_total"] == 2
    assert "parked " + "c" * 32 in stdout.getvalue()
