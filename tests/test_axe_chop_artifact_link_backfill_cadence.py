"""Stale-drop cadence, reconcile headroom, and phase-log tests for the chop."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.scripts._artifact_link_backfill_jobs as backfill_jobs
import sase.scripts._artifact_link_backfill_state as backfill_state
import sase.scripts.sase_chop_artifact_link_backfill as backfill_chop
from sase.scripts._artifact_link_backfill_schedule import (
    DEFAULT_RECONCILE_ESTIMATE_SECONDS,
    SCHEDULE_FILENAME,
    STALE_DROP_INTERVAL_SECONDS,
    BackfillSchedule,
    read_backfill_schedule,
    write_backfill_schedule,
)
from sase.sdd._artifact_link_outbox_drain_support import AgentTerminalTimes
from sase.sdd.artifact_link_backfill import (
    _ArtifactLinkBackfillReport,
    _ArtifactLinkReconcileReport,
)

from tests._axe_chop_artifact_link_backfill_helpers import (
    _default_no_publication_retry,  # noqa: F401 (registers the autouse fixture)
    _project,
    _runtime_with_logs,
)


def _patch_projects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, names: tuple[str, ...]
) -> None:
    projects = [_project(tmp_path, name=name) for name in names]
    monkeypatch.setattr(backfill_chop, "_enabled_project_records", lambda: projects)
    monkeypatch.setattr(
        backfill_jobs,
        "resolve_machine_artifact_link_store",
        lambda project_key, primary_checkout, **_kwargs: SimpleNamespace(
            project_key=project_key
        ),
    )
    monkeypatch.setattr(
        backfill_jobs,
        "run_artifact_link_backfill_batch",
        lambda store, **kwargs: (_ArtifactLinkBackfillReport(), frozenset()),
    )


def _schedule_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / SCHEDULE_FILENAME


def test_stale_drop_due_and_reconcile_estimate_rules() -> None:
    schedule = BackfillSchedule()

    assert schedule.stale_drop_due("p", now=1_000.0) is True
    schedule.record_stale_checked("p", now=1_000.0)
    assert schedule.stale_drop_due("p", now=1_000.0 + 3_600.0) is False
    assert (
        schedule.stale_drop_due("p", now=1_000.0 + STALE_DROP_INTERVAL_SECONDS) is True
    )

    assert schedule.reconcile_estimate("p") == DEFAULT_RECONCILE_ESTIMATE_SECONDS
    schedule.record_reconcile("p", 40.0)
    assert schedule.reconcile_seconds["p"] == 40.0
    schedule.record_reconcile("p", 100.0)  # a slower run raises it at once
    assert schedule.reconcile_seconds["p"] == 100.0
    schedule.record_reconcile("p", 10.0)  # a faster run decays it slowly
    assert schedule.reconcile_seconds["p"] == pytest.approx(0.7 * 100.0 + 0.3 * 10.0)


def test_schedule_round_trips_prunes_and_reads_invalid_files_as_empty(
    tmp_path: Path,
) -> None:
    path = _schedule_path(tmp_path)
    schedule = BackfillSchedule(
        stale_checked_at={"keep": 1.0, "gone": 2.0},
        reconcile_seconds={"keep": 30.0, "gone": 40.0},
    )
    schedule.prune({"keep"})
    write_backfill_schedule(path, schedule)

    assert read_backfill_schedule(path) == BackfillSchedule(
        stale_checked_at={"keep": 1.0}, reconcile_seconds={"keep": 30.0}
    )
    for payload in ("{not-json", "[]", json.dumps({"schema_version": 99})):
        path.write_text(payload, encoding="utf-8")
        assert read_backfill_schedule(path) == BackfillSchedule()


def test_chop_drops_stale_daily_shares_one_catalog_and_logs_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_projects(monkeypatch, tmp_path, ("p1", "p2", "p3"))
    write_backfill_schedule(
        _schedule_path(tmp_path),
        BackfillSchedule(
            # p2 completed its stale drop an hour ago; "gone" is disabled now.
            stale_checked_at={
                "p2": backfill_chop.time.time() - 3_600.0,
                "gone": 1.0,
            },
            reconcile_seconds={"gone": 5.0},
        ),
    )
    drain_kwargs: list[dict[str, object]] = []

    def _fake_drain(**kwargs: object) -> SimpleNamespace:
        drain_kwargs.append(dict(kwargs))
        terminal_times = kwargs["terminal_times"]
        assert isinstance(terminal_times, AgentTerminalTimes)
        phases: tuple[tuple[str, float], ...] = (
            ("read", 0.1),
            ("evidence", 0.2),
            ("eligibility", 0.3),
        )
        if kwargs["drop_stale_terminal"]:
            phases = (*phases, ("catalog", 1.25))
            terminal_times.built = True
            terminal_times.ok = True
        return SimpleNamespace(
            drained=0,
            dropped=0,
            deferred=False,
            stale_checked=bool(kwargs["drop_stale_terminal"]),
            phase_seconds=phases,
        )

    monkeypatch.setattr(backfill_jobs, "drain_artifact_link_outbox", _fake_drain)
    monkeypatch.setattr(
        backfill_jobs,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(),
    )

    runtime, stdout, _stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    assert [kwargs["drop_stale_terminal"] for kwargs in drain_kwargs] == [
        True,
        False,
        True,
    ]
    providers = {id(kwargs["terminal_times"]) for kwargs in drain_kwargs}
    assert len(providers) == 1
    assert result.counters["stale_checked_projects"] == 2
    schedule = read_backfill_schedule(_schedule_path(tmp_path))
    assert set(schedule.stale_checked_at) == {"p1", "p2", "p3"}
    assert set(schedule.reconcile_seconds) == {"p1", "p2", "p3"}
    log_output = stdout.getvalue()
    assert (
        "p1: drain phases: read=0.10s evidence=0.20s eligibility=0.30s "
        "catalog=1.25s publish=skipped rewrite=skipped"
    ) in log_output
    assert "p2: drain phases:" in log_output
    assert "catalog=skipped" in log_output.split("p2: drain phases:")[1].splitlines()[0]
    assert "catalog=shared" in log_output.split("p3: drain phases:")[1].splitlines()[0]


def test_reconcile_waits_for_headroom_unless_first_and_cursor_goes_to_deferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_projects(monkeypatch, tmp_path, ("p1", "p2", "p3"))
    write_backfill_schedule(
        _schedule_path(tmp_path),
        BackfillSchedule(reconcile_seconds={"p1": 500.0, "p2": 500.0}),
    )
    monkeypatch.setattr(
        backfill_jobs,
        "drain_artifact_link_outbox",
        lambda **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False, stale_checked=True
        ),
    )
    monkeypatch.setattr(backfill_chop.time, "monotonic", lambda: 0.0)
    reconciled: list[str] = []

    def _reconcile(store: SimpleNamespace, **_kwargs: object) -> object:
        reconciled.append(store.project_key)
        return _ArtifactLinkReconcileReport()

    monkeypatch.setattr(
        backfill_jobs, "reconcile_and_repair_artifact_links", _reconcile
    )

    runtime, _stdout, stderr = _runtime_with_logs(tmp_path)
    result = backfill_chop._run(runtime)

    # p1 is first this tick, so it reconciles despite a 500s estimate; p2's
    # estimate exceeds the 240s left; p3 fits the default estimate.
    assert reconciled == ["p1", "p3"]
    assert result.counters["deferred_projects"] == 1
    assert "p2: deferred reconcile/repair: needs ~500s, 240s left" in stderr.getvalue()
    cursor = json.loads(
        (tmp_path / "state" / backfill_state.CURSOR_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert cursor["next_project"] == "p2"
    schedule = read_backfill_schedule(_schedule_path(tmp_path))
    assert schedule.reconcile_seconds["p1"] == pytest.approx(0.7 * 500.0)
    assert schedule.reconcile_seconds["p2"] == 500.0
    assert schedule.reconcile_seconds["p3"] == 0.0


def test_cut_short_reconcile_keeps_its_estimate_and_defers_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_projects(monkeypatch, tmp_path, ("p1", "p2"))
    write_backfill_schedule(
        _schedule_path(tmp_path),
        BackfillSchedule(reconcile_seconds={"p1": 50.0}),
    )
    monkeypatch.setattr(
        backfill_jobs,
        "drain_artifact_link_outbox",
        lambda **_kwargs: SimpleNamespace(
            drained=0, dropped=0, deferred=False, stale_checked=True
        ),
    )
    monkeypatch.setattr(
        backfill_jobs,
        "reconcile_and_repair_artifact_links",
        lambda store, **_kwargs: _ArtifactLinkReconcileReport(
            skip_diagnostics=(
                "reconcile deadline expired; deferred dangling-ref repair",
            )
            if store.project_key == "p1"
            else ()
        ),
    )

    runtime, _stdout, _stderr = _runtime_with_logs(tmp_path)
    backfill_chop._run(runtime)

    schedule = read_backfill_schedule(_schedule_path(tmp_path))
    assert schedule.reconcile_seconds["p1"] == 50.0
    assert "p2" in schedule.reconcile_seconds
    cursor = json.loads(
        (tmp_path / "state" / backfill_state.CURSOR_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert cursor["next_project"] == "p1"
