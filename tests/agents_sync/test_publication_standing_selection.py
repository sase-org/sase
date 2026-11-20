"""Standing alerts for machine-wide and skipped-project selection failures."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import (
    _publication_job_run as job_run,
    _publication_job_shared as job_shared,
    publication_job,
    publication_standing,
)
from sase.agents_sync.models import SyncOutcome
from sase.notifications.store import load_notifications
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import publication_target


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, start: float = 1_000_000.0):
    clock = [start]
    monkeypatch.setattr(job_run.time, "time", lambda: clock[0])
    return clock


def _project_record(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        project_name=name, workspace_dir=f"/tmp/{name}", is_project=True
    )


def _quiet_queues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(job_shared, "list_referenced_by_requests", lambda *_a, **_k: ())


def _record_bells(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    bells: list[str] = []
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    return bells


def test_failing_project_listing_reports_one_transition_then_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    _quiet_queues(monkeypatch)
    listing = {"fail": True}

    def list_records(*_args, **_kwargs):
        if listing["fail"]:
            raise RuntimeError("projects directory is unreadable")
        return []

    monkeypatch.setattr(job_run, "list_project_records", list_records)

    reported: list[str] = []
    total_errors = 0
    for tick in range(20):
        clock[0] += 15.0
        summary = publication_job.run_publication_job(work_budget_seconds=10)
        total_errors += summary.errors
        reported.extend(summary.standing_report)
        assert summary.standing == 1
        if tick == 0:
            assert summary.diagnostics == [
                "*publisher*: could not list enabled projects: "
                "projects directory is unreadable"
            ]
        else:
            assert summary.errors == 0, f"tick {tick} must stay silent"
            assert summary.diagnostics == []

    assert total_errors == 1
    assert reported == ["*publisher*:opened:selection_error:attempt1"]
    [stored] = publication_standing.load_standing_alerts().values()
    assert stored.project == "*publisher*"
    assert stored.failure_kind == "selection_error"
    assert stored.attempts == 20

    listing["fail"] = False
    clock[0] += 15.0
    recovered = publication_job.run_publication_job(work_budget_seconds=10)
    assert recovered.errors == 0
    assert recovered.standing == 0
    assert recovered.standing_report == []
    assert publication_standing.load_standing_alerts() == {}
    rows = [
        row
        for row in load_notifications()
        if (row.dedup_key or "").startswith("agent-publication-standing:*publisher*")
    ]
    assert len(rows) == 1
    assert rows[0].plus_one_count == 1


def test_failing_target_resolution_is_one_publisher_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    _quiet_queues(monkeypatch)
    monkeypatch.setattr(
        job_run, "list_project_records", lambda *_a, **_k: [_project_record("proj")]
    )

    def resolve(_keys):
        raise RuntimeError("inventory exploded")

    monkeypatch.setattr(job_run, "resolve_sync_targets", resolve)

    errors = []
    for _ in range(5):
        clock[0] += 15.0
        errors.append(publication_job.run_publication_job().errors)

    assert errors == [1, 0, 0, 0, 0]
    [stored] = publication_standing.load_standing_alerts().values()
    assert stored.project == "*publisher*"
    assert stored.detail.startswith("could not resolve publication targets")


def test_budget_deferred_selection_error_is_not_counted_every_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    _quiet_queues(monkeypatch)
    _record_bells(monkeypatch)
    monkeypatch.setattr(
        job_run, "list_project_records", lambda *_a, **_k: [_project_record("proj")]
    )
    target = publication_target(tmp_path)
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(
            targets=(target,),
            outcomes=(
                SyncOutcome("proj", "Project", error="inventory row is malformed"),
            ),
        ),
    )

    # Budget-deferred ticks never charge the error, but the log still says
    # why the project's selection error went unrecorded.
    for _ in range(5):
        clock[0] += 15.0
        deferred = publication_job.run_publication_job(work_budget_seconds=0)
        assert deferred.errors == 0
        assert deferred.standing_report == []
        assert deferred.project_stats["proj"]["last_outcome"] == "deferred_budget"
        assert deferred.diagnostics == [
            "proj: selection error left for the next processed pass: "
            "inventory row is malformed"
        ]
    assert publication_standing.load_standing_alerts() == {}

    # The next processed pass records it through the standing decider.
    clock[0] += 15.0
    processed = publication_job.run_publication_job(work_budget_seconds=10)
    assert processed.errors == 1
    assert processed.standing_report == ["proj:opened:selection_error:attempt1"]

    # Once tracked, skipped ticks stay quiet whether deferred or backing off.
    for _ in range(5):
        clock[0] += 15.0
        quiet = publication_job.run_publication_job(work_budget_seconds=0)
        assert quiet.errors == 0
        assert quiet.diagnostics == []
        assert quiet.standing_report == []


def test_budget_deferred_project_in_backoff_is_not_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    _quiet_queues(monkeypatch)
    bells = _record_bells(monkeypatch)
    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_a, **_k: [_project_record("alpha"), _project_record("proj")],
    )
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(), outcomes=()),
    )
    monkeypatch.setattr(
        job_run,
        "drain_project",
        lambda *_a, **_k: pytest.fail("drain must not start after the budget expires"),
    )
    alerts = publication_standing.load_standing_alerts()
    publication_standing.apply_project_observations(
        alerts,
        "proj",
        [("drain_error", "git push failed: boom")],
        now=clock[0],
    )
    publication_standing.save_standing_alerts(alerts)
    assert not publication_standing.is_due(alerts, "proj", clock[0] + 1.0)

    clock[0] += 1.0
    summary = publication_job.run_publication_job(work_budget_seconds=0)

    # "alpha" exhausts the budget, so both projects take the deferred branch;
    # only the one that is due is rung.
    assert summary.project_stats["alpha"]["last_outcome"] == "deferred_budget"
    assert summary.project_stats["proj"]["last_outcome"] == "deferred_budget"
    assert bells == ["alpha"]
    assert summary.errors == 0
