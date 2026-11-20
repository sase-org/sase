"""Standing publication alerts with backoff for the publication job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_queue as publication_queue
from sase.agents_sync import (
    _publication_job_drain as job_drain,
    _publication_job_run as job_run,
    _publication_job_shared as job_shared,
    publication_doorbell,
    publication_job,
    publication_standing,
)
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.models import SyncOutcome
from sase.notifications.store import load_notifications
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import (
    configure_single_project_job,
    publication_item,
    publication_target,
)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, start: float = 1_000_000.0):
    clock = [start]
    monkeypatch.setattr(job_run.time, "time", lambda: clock[0])
    return clock


def _quiet_refby(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_shared, "list_referenced_by_requests", lambda *_a, **_k: ())


def _run_one_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    queue_items: tuple = (),
    drain=None,
) -> None:
    target = publication_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(
        job_shared, "active_agent_publications", lambda _key: tuple(queue_items)
    )
    _quiet_refby(monkeypatch)
    if drain is not None:
        monkeypatch.setattr(
            publication_queue, "drain_selected_agent_publications", drain
        )


def _standing_rows():
    return [
        notification
        for notification in load_notifications()
        if (notification.dedup_key or "").startswith("agent-publication-standing:")
    ]


def test_twenty_ticks_of_one_failure_report_once_with_true_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    bells: list[str] = []
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    drains = {"calls": 0}

    def timeout_drain(_key, _selected, **_kwargs):
        drains["calls"] += 1
        return CommitPublicationOutcome(
            error="agent-hood publication did not complete within 120s",
            failure_scope="repository",
        )

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=timeout_drain)

    diagnostics_total = 0
    for tick in range(20):
        clock[0] += 1.0
        summary = publication_job.run_publication_job(work_budget_seconds=10)
        diagnostics_total += len(summary.diagnostics)
        if tick == 0:
            assert summary.errors == 1
            assert summary.standing_report == ["proj:opened:drain_timeout:attempt1"]
            assert summary.diagnostics == [
                "proj: agent-hood publication did not complete within 120s"
            ]
        else:
            assert summary.errors == 0, f"tick {tick} must stay silent"
            assert summary.diagnostics == []
            assert summary.standing_report == []
        assert summary.standing == 1

    # One ring entry, one notification, and attempts=20 with first/last times.
    assert diagnostics_total == 1
    assert bells == []
    rows = _standing_rows()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 0
    alerts = publication_standing.load_standing_alerts()
    assert len(alerts) == 1
    [stored] = alerts.values()
    assert stored.failure_kind == "drain_timeout"
    assert stored.attempts == 20
    assert stored.last_seen > stored.first_seen
    # The first tick drained; the rest backed off and skipped the drain.
    assert drains["calls"] == 1


def test_backoff_skips_drain_and_doorbell_until_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    bells: list[str] = []
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: bells.append(key),
    )
    drains = {"calls": 0}

    def failing_drain(_key, _selected, **_kwargs):
        drains["calls"] += 1
        return CommitPublicationOutcome(
            error="git push failed: boom", failure_scope="repository"
        )

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=failing_drain)

    first = publication_job.run_publication_job(work_budget_seconds=10)
    assert first.errors == 1
    assert drains["calls"] == 1

    clock[0] += 10.0
    second = publication_job.run_publication_job(work_budget_seconds=10)
    assert second.errors == 0
    assert drains["calls"] == 1
    assert second.project_stats["proj"]["last_outcome"] == "standing_backoff"
    alerts = publication_standing.load_standing_alerts()
    assert len(alerts) == 1
    [blocked] = alerts.values()
    assert blocked.attempts == 2

    clock[0] += 121.0
    third = publication_job.run_publication_job(work_budget_seconds=10)
    assert third.errors == 0
    assert drains["calls"] == 2
    assert third.project_stats["proj"]["last_outcome"] != "standing_backoff"

    assert bells == []


def test_signature_change_reports_once_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    failures = ["git push failed: boom"]

    def flapping_drain(_key, _selected, **_kwargs):
        return CommitPublicationOutcome(error=failures[0], failure_scope="repository")

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=flapping_drain)

    first = publication_job.run_publication_job(work_budget_seconds=10)
    assert first.errors == 1

    # Advance past the first alert's backoff so the next tick drains again.
    clock[0] += 61.0
    failures[0] = "connection reset by peer"
    second = publication_job.run_publication_job(work_budget_seconds=10)
    # The new signature opens (one error); the old alert clears quietly.
    assert second.errors == 1
    assert second.standing_report == ["proj:opened:drain_error:attempt1"]
    alerts = publication_standing.load_standing_alerts()
    assert len(alerts) == 1
    [stored] = alerts.values()
    assert "connection reset" in stored.detail
    # One row per alert: the old row stays, the new one is created.
    assert len(_standing_rows()) == 2


def test_clean_pass_clears_without_a_new_unread_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    calls = {"drain": 0, "fail": True}

    def sometimes_failing_drain(_key, selected, **_kwargs):
        calls["drain"] += 1
        if calls["fail"]:
            return CommitPublicationOutcome(
                error="git push failed: boom", failure_scope="repository"
            )
        return CommitPublicationOutcome(drained=len(selected), published=True)

    queue = [item]
    _run_one_project(
        monkeypatch, tmp_path, queue_items=tuple(queue), drain=sometimes_failing_drain
    )
    # Drain removes the item on success so the next pass is clean.
    original = sometimes_failing_drain

    def draining_drain(key, selected, **kwargs):
        outcome = original(key, selected, **kwargs)
        if not calls["fail"]:
            queue.clear()
        return outcome

    monkeypatch.setattr(
        publication_queue, "drain_selected_agent_publications", draining_drain
    )
    monkeypatch.setattr(
        job_shared, "active_agent_publications", lambda _key: tuple(queue)
    )

    first = publication_job.run_publication_job(work_budget_seconds=10)
    assert first.errors == 1
    assert len(_standing_rows()) == 1

    calls["fail"] = False
    # Advance past the backoff so the clean tick actually drains.
    clock[0] += 61.0
    second = publication_job.run_publication_job(work_budget_seconds=10)
    assert second.errors == 0
    assert second.diagnostics == []
    assert publication_standing.load_standing_alerts() == {}
    # Cleared updates the row without creating a new unread row.
    rows = _standing_rows()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 1


def test_escalates_once_after_24h_then_stays_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    clock = _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: None,
    )

    def failing_drain(_key, _selected, **_kwargs):
        return CommitPublicationOutcome(
            error="agents sync lock is busy", failure_scope="repository"
        )

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=failing_drain)

    first = publication_job.run_publication_job(work_budget_seconds=10)
    assert first.errors == 1

    clock[0] += 86_401.0
    escalated = publication_job.run_publication_job(work_budget_seconds=10)
    assert escalated.errors == 1
    assert escalated.standing_report == ["proj:escalated:lock_busy:attempt2"]
    rows = _standing_rows()
    assert len(rows) == 1
    assert rows[0].plus_one_count == 1

    clock[0] += 3_600.0
    quiet = publication_job.run_publication_job(work_budget_seconds=10)
    assert quiet.errors == 0
    assert quiet.standing_report == []
    assert len(_standing_rows()) == 1


def _selection_job(monkeypatch: pytest.MonkeyPatch, outcome: SyncOutcome) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_a, **_k: [
            SimpleNamespace(
                project_name="proj", workspace_dir="/tmp/proj", is_project=True
            )
        ],
    )
    target = publication_target(Path("/tmp/standing-kind"))
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=(outcome,)),
    )
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: ())
    monkeypatch.setattr(job_shared, "list_referenced_by_requests", lambda *_a, **_k: ())


@pytest.mark.parametrize(
    ("scenario", "expected_kind", "expected_outcome"),
    [
        ("selection_error", "selection_error", "idle"),
        ("target_unavailable", "target_unavailable", "target_unavailable"),
        ("drain_timeout", "drain_timeout", "repository_error"),
        ("drain_error", "drain_error", "error"),
        ("charged_item", "charged_item_error", "hood_error"),
        ("artifact_link", "artifact_link_error", "link_error"),
        ("referenced_by", "referenced_by_error", "referenced_by_error"),
        ("heartbeat_write", "heartbeat_write", "idle"),
    ],
)
def test_each_failure_kind_opens_its_own_standing_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_kind: str,
    expected_outcome: str,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _freeze_clock(monkeypatch)
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: None,
    )

    if scenario == "selection_error":
        _selection_job(
            monkeypatch, SyncOutcome("proj", "Project", error="selection boom")
        )
    elif scenario == "target_unavailable":
        monkeypatch.setattr(
            job_run,
            "list_project_records",
            lambda *_a, **_k: [
                SimpleNamespace(
                    project_name="proj", workspace_dir="/tmp/proj", is_project=True
                )
            ],
        )
        monkeypatch.setattr(
            job_run,
            "resolve_sync_targets",
            lambda _keys: SimpleNamespace(
                targets=(),
                outcomes=(
                    SyncOutcome(
                        "proj",
                        "Project",
                        skip_reason="agents sidecar is disabled",
                    ),
                ),
            ),
        )
        item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
        monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: (item,))
        monkeypatch.setattr(
            job_shared, "list_referenced_by_requests", lambda *_a, **_k: ()
        )
    elif scenario == "heartbeat_write":
        target = publication_target(tmp_path)
        configure_single_project_job(monkeypatch, target)
        monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: ())
        monkeypatch.setattr(
            job_shared, "list_referenced_by_requests", lambda *_a, **_k: ()
        )
        monkeypatch.setattr(
            job_run,
            "write_publication_heartbeat",
            lambda _stats: (_ for _ in ()).throw(RuntimeError("disk full")),
        )
    else:
        item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
        target = publication_target(tmp_path)
        configure_single_project_job(monkeypatch, target)
        monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: (item,))
        monkeypatch.setattr(
            job_shared, "list_referenced_by_requests", lambda *_a, **_k: ()
        )
        if scenario == "drain_timeout":

            def drain(_key, _selected, **_kwargs):
                return CommitPublicationOutcome(
                    error="agent-hood publication did not complete within 120s",
                    failure_scope="repository",
                )

            monkeypatch.setattr(
                publication_queue, "drain_selected_agent_publications", drain
            )
        elif scenario == "drain_error":

            def drain(_key, _selected, **_kwargs):
                raise RuntimeError("git push failed: boom")

            monkeypatch.setattr(
                publication_queue, "drain_selected_agent_publications", drain
            )
        elif scenario == "charged_item":

            def drain(_key, _selected, **_kwargs):
                return CommitPublicationOutcome(error="withheld row failed")

            monkeypatch.setattr(
                publication_queue, "drain_selected_agent_publications", drain
            )
        elif scenario == "artifact_link":
            monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: ())
            hint = {
                "local_agent": "worker",
                "global_agent": "alice.athena.worker",
                "primary_revision": "a" * 40,
                "run_id": "run-1",
                "link_outbox_agent_name": "alice.athena.worker",
            }
            publication_doorbell.ring_publication_doorbell("proj", hint)
            monkeypatch.setattr(
                job_drain,
                "resolve_machine_artifact_link_store",
                lambda *_a, **_k: object(),
            )

            def drain_links(**_kwargs):
                raise RuntimeError("link store unavailable")

            monkeypatch.setattr(job_drain, "drain_artifact_link_outbox", drain_links)
        elif scenario == "referenced_by":
            monkeypatch.setattr(job_shared, "active_agent_publications", lambda _k: ())

            def refby_items(_key, **_kwargs):
                return [object()]

            monkeypatch.setattr(job_shared, "list_referenced_by_requests", refby_items)
            import sase.agents_sync.referenced_by_publication as refby_pub

            def drain_refby(_target, **_kwargs):
                raise RuntimeError("boom")

            monkeypatch.setattr(refby_pub, "drain_referenced_by_requests", drain_refby)

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 1
    assert len(summary.standing_report) == 1
    expected_owner = "*publisher*" if scenario == "heartbeat_write" else "proj"
    assert summary.standing_report[0].startswith(
        f"{expected_owner}:opened:{expected_kind}"
    )
    if scenario != "heartbeat_write":
        assert summary.project_stats["proj"]["last_outcome"] == expected_outcome
    alerts = publication_standing.load_standing_alerts()
    if scenario == "heartbeat_write":
        assert len(alerts) == 1
        [stored] = alerts.values()
        assert stored.project == "*publisher*"
        assert stored.failure_kind == expected_kind
    else:
        assert len(alerts) == 1
        [stored] = alerts.values()
        assert stored.project == "proj"
        assert stored.failure_kind == expected_kind


def test_corrupt_store_fails_open_and_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _freeze_clock(monkeypatch)
    path = publication_standing._standing_alerts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)

    def failing_drain(_key, _selected, **_kwargs):
        return CommitPublicationOutcome(
            error="git push failed: boom", failure_scope="repository"
        )

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=failing_drain)

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 1
    assert tuple(path.parent.glob("standing_alerts.json.corrupt-*"))
    alerts = publication_standing.load_standing_alerts()
    assert len(alerts) == 1


def test_standing_chop_line_round_trips_through_the_summary_grammar() -> None:
    from sase.chops.sdk import emit_summary, parse_summary

    line = emit_summary(
        "agent_publication",
        {
            "projects": 1,
            "hood_drained": 0,
            "link_drained": 0,
            "referenced_by_drained": 0,
            "active_remaining": 1,
            "parked": 0,
            "lock_busy": 0,
            "deferred_projects": 0,
            "errors": 1,
            "standing": 2,
        },
        reason="proj:opened:drain_error:attempt1,*publisher*:opened:heartbeat_write:attempt1",
    )
    parsed = parse_summary(line)
    assert parsed is not None
    assert parsed.counters["standing"] == 2
    assert parsed.counters["errors"] == 1
    assert (
        parsed.reason
        == "proj:opened:drain_error:attempt1,*publisher*:opened:heartbeat_write:attempt1"
    )


def test_row_scoped_failures_take_no_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _freeze_clock(monkeypatch)
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    drains = {"calls": 0}

    def withheld_drain(_key, _selected, **_kwargs):
        drains["calls"] += 1
        return CommitPublicationOutcome(error="withheld row failed")

    _run_one_project(monkeypatch, tmp_path, queue_items=(item,), drain=withheld_drain)

    first = publication_job.run_publication_job(work_budget_seconds=10)
    assert first.errors == 1
    alerts = publication_standing.load_standing_alerts()
    [stored] = alerts.values()
    assert stored.failure_kind == "charged_item_error"
    assert not stored.project_scoped
    assert publication_standing.is_due(alerts, "proj", 1_000_000.0 + 10.0)

    second = publication_job.run_publication_job(work_budget_seconds=10)
    # Row-scoped failures keep draining every tick; only the first reports.
    assert drains["calls"] == 2
    assert second.errors == 0
    assert (
        publication_standing.load_standing_alerts()[("proj", stored.signature)].attempts
        == 2
    )
