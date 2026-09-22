"""Budget and deferral tests for the ``artifact_link_backfill`` chop."""

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


def test_later_jobs_defer_after_sweep_budget(
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
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])

    def _fake_batch(
        store: object,
        *,
        already_swept: frozenset[str],
        batch_size: int,
        deadline: float | None = None,
        persist_deadline: float | None = None,
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        now[0] = 46.0  # the sweep alone consumes the whole sweep budget
        assert persist_deadline is not None
        return (
            _ArtifactLinkBackfillReport(scanned=1, persisted=1, remaining=1),
            already_swept | {"plan:202608/a.md"},
        )

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(
        backfill_chop,
        "drain_artifact_link_outbox",
        lambda store=None, **_kwargs: pytest.fail("outbox should defer"),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: pytest.fail("reconcile should defer"),
    )

    result = backfill_chop._run(_runtime(tmp_path))

    assert result.counters["projects"] == 1
    assert result.counters["sweep_scanned"] == 1
    assert result.counters["sweep_remaining"] == 1
    assert result.counters["outbox_drained"] == 0
    assert result.counters["deferred_projects"] == 0
    state = (tmp_path / "state" / backfill_chop._STATE_FILENAME).read_text(
        encoding="utf-8"
    )
    assert "plan:202608/a.md" in state


def test_chop_stops_starting_projects_past_the_chop_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects = [_project(tmp_path, name=name) for name in ("p1", "p2", "p3")]
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: projects)
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
            drained=0, dropped=0, deferred=False
        ),
    )
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])

    def _reconcile(store: object, **_kwargs: object) -> _ArtifactLinkReconcileReport:
        # p1's own reconcile job is what blows through the whole-chop budget.
        now[0] = backfill_chop._CHOP_WORK_BUDGET_SECONDS + 1.0
        return _ArtifactLinkReconcileReport()

    monkeypatch.setattr(
        backfill_chop, "reconcile_and_repair_artifact_links", _reconcile
    )

    runtime, stdout, stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert result.counters["projects"] == 1
    assert result.counters["deferred_projects"] == 2
    assert result.reason is None
    warnings = stderr.getvalue()
    assert "p2" in warnings
    assert "p3" in warnings
    assert "job budget exceeded; projects not started: p2, p3" in warnings


def test_per_project_progress_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
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
            drained=0, dropped=0, deferred=False
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    runtime, stdout, _stderr = _runtime_with_logs(tmp_path)
    backfill_chop._run(runtime)

    log_output = stdout.getvalue()
    assert "proj: starting" in log_output
    assert "proj: publication_retry" in log_output
    assert "proj: store_resolution" in log_output
    assert "proj: sweep" in log_output
    assert "proj: drain" in log_output
    assert "proj: reconcile" in log_output
    assert "proj: done" in log_output


def test_chop_passes_budget_through_and_warns_on_deferred_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
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
            drained=0, dropped=0, deferred=False
        ),
    )
    now = [0.0]
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: now[0])
    captured: list[dict[str, object]] = []

    def _reconcile(store: object, **kwargs: object) -> _ArtifactLinkReconcileReport:
        captured.append(kwargs)
        return _ArtifactLinkReconcileReport(deferred_refs=4)

    monkeypatch.setattr(
        backfill_chop, "reconcile_and_repair_artifact_links", _reconcile
    )

    runtime, _stdout, stderr = _runtime_with_logs(tmp_path)
    backfill_chop._run(runtime)

    assert captured == [{"deadline": backfill_chop._CHOP_WORK_BUDGET_SECONDS}]
    warning = stderr.getvalue()
    assert "proj" in warning
    assert "deferred 4" in warning
    assert "past job budget" in warning


def test_chop_forwards_chop_deadline_to_sweep_persist_and_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
    )
    monkeypatch.setattr(
        backfill_chop,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: object(),
    )
    batch_kwargs: list[dict[str, object]] = []
    drain_kwargs: list[dict[str, object]] = []

    def _fake_batch(
        store: object, **kwargs: object
    ) -> tuple[_ArtifactLinkBackfillReport, frozenset[str]]:
        batch_kwargs.append(dict(kwargs))
        return _ArtifactLinkBackfillReport(), frozenset()

    def _fake_drain(**kwargs: object) -> SimpleNamespace:
        drain_kwargs.append(dict(kwargs))
        return SimpleNamespace(drained=0, dropped=0, deferred=False)

    monkeypatch.setattr(backfill_chop, "run_artifact_link_backfill_batch", _fake_batch)
    monkeypatch.setattr(backfill_chop, "drain_artifact_link_outbox", _fake_drain)
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    backfill_chop._run(_runtime(tmp_path))

    assert isinstance(batch_kwargs[0]["deadline"], float)
    assert isinstance(batch_kwargs[0]["persist_deadline"], float)
    assert batch_kwargs[0]["persist_deadline"] > batch_kwargs[0]["deadline"]
    assert drain_kwargs[0]["deadline"] == batch_kwargs[0]["persist_deadline"]


def test_deferred_drain_skips_reconcile_and_counts_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        backfill_chop,
        "_enabled_project_records",
        lambda: [_project(tmp_path, name="proj")],
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
            deferred=True,
            skip_diagnostics=("deferred past job budget",),
        ),
    )
    monkeypatch.setattr(
        backfill_chop,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: pytest.fail("reconcile should defer"),
    )

    runtime, _stdout, stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert result.counters["projects"] == 1
    assert result.counters["deferred_projects"] == 1
    assert "deferred past job budget" in stderr.getvalue()
