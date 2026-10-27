"""Waiter alerts for strands whose bead work has ended without closing."""

from __future__ import annotations

import os
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import sase.bead.stranded_facts as stranded_facts
import sase.scripts._chop_wait_checks_run as wait_checks_run
import sase.scripts._chop_wait_checks_run_waiters as wait_checks_waiters
import sase.scripts._chop_wait_checks_stranded as stranded_cache
from sase.agent.pending_handoff import GATE_PENDING_MARKER, MONITOR_PENDING_MARKER
from sase.bead.model import Status
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict
from sase.notifications.models import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
)
from sase.scripts._chop_wait_checks_common import StrandedBeadWaiter
import sase.scripts._chop_wait_checks_terminal as wait_checks_terminal

from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._stranded_collector_helpers import (
    PROJECT,
    child_plan,
    epic,
    phase,
    record,
    wire_collector,
)

_BEAD_ID = "sase-1.2"
_PARENT_ID = "sase-1"


def _point_wait_bead_status(
    monkeypatch: pytest.MonkeyPatch,
    closed: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        wait_checks_waiters,
        "closed_bead_ids_for_waits",
        lambda *_args, **_kwargs: SimpleNamespace(closed_ids=frozenset(closed or ())),
    )


def _wire_targeted_collector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    issues: list,
    records: list,
) -> Path:
    beads_dir = wire_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(
        stranded_cache,
        "canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    def statuses_for_project(_project: str, bead_ids: object) -> dict[str, str]:
        wanted = {str(bead_id) for bead_id in bead_ids}
        return {issue.id: issue.status.value for issue in issues if issue.id in wanted}

    monkeypatch.setattr(
        wait_checks_run,
        "bead_statuses_for_project",
        statuses_for_project,
    )
    return beads_dir


def _seed_stranded_notification(project: str, bead_id: str) -> None:
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=[f"Stranded bead: {bead_id}"],
            tags=["wait", "blocked", "stranded"],
            dedup_key=f"wait_checks:stranded-bead:{project}:{bead_id}",
        )
    )


def _ensure_projects_dir(tmp_path: Path) -> None:
    (tmp_path / ".sase" / "projects" / "proj").mkdir(parents=True, exist_ok=True)


def _capture_collection_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    real = wait_checks_run.collect_targeted_stranded_report

    def wrapped(
        project: str,
        bead_ids: set[str] | frozenset[str] | tuple[str, ...],
        *,
        now: float,
    ):
        calls.append((project, tuple(sorted(bead_ids))))
        return real(project, bead_ids, now=now)

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", wrapped)
    return calls


def _make_waiters(tmp_path: Path, *suffixes: str) -> list[Path]:
    waiters = [
        make_waiting_agent(
            tmp_path,
            suffix=suffix,
            wait_for_beads=[_BEAD_ID],
        )
        for suffix in suffixes
    ]
    for index, waiter_dir in enumerate(waiters, start=1):
        path = waiter_dir / "waiting.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cl_name"] = f"waiter-{index}"
        path.write_text(json.dumps(data), encoding="utf-8")
    return waiters


def test_stranded_bead_waiters_share_one_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    first_waiter = _make_waiters(tmp_path, "phase-two")[0]

    run_wait_checks(tmp_path, monkeypatch)

    assert not (first_waiter / "ready.json").exists()
    notifications = load_notifications()
    assert len(notifications) == 1
    row = notifications[0]
    assert row.sender == "wait_checks"
    assert row.dedup_key == f"wait_checks:stranded-bead:proj:{_BEAD_ID}"
    assert row.color == "#D14343"
    assert set(row.tags) == {"wait", "blocked", "stranded"}
    assert row.action == "JumpToAgent"
    assert row.action_data["cl_name"] == _BEAD_ID
    assert row.action_data["raw_suffix"] == artifact.name
    assert any(f"{_BEAD_ID} — Phase" in note for note in row.notes)
    assert any("ended without closing the bead" in note for note in row.notes)
    assert any("Last turn:" in note and "1h ago" in note for note in row.notes)
    assert any("waiter-1" in note for note in row.notes)
    assert any(
        f"sase bead work {_PARENT_ID} --yes-to-all" in note for note in row.notes
    )
    assert any(f"sase bead close {_BEAD_ID} --note" in note for note in row.notes)

    second_waiter = make_waiting_agent(
        tmp_path,
        suffix="land",
        wait_for_beads=[_BEAD_ID],
    )
    second_marker = second_waiter / "waiting.json"
    second_data = json.loads(second_marker.read_text(encoding="utf-8"))
    second_data["cl_name"] = "waiter-2"
    second_marker.write_text(json.dumps(second_data), encoding="utf-8")
    run_wait_checks(tmp_path, monkeypatch)
    assert not (second_waiter / "ready.json").exists()
    row = load_notifications()[0]
    assert row.plus_one_count == 1
    assert "waiter-1" in row.plus_ones[0].note
    assert "waiter-2" in row.plus_ones[0].note


@pytest.mark.parametrize("state", ["settling", "owned", "delegated"])
def test_wait_checks_does_not_notify_before_stranding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "active-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    if state == "settling":
        records = [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 30),
            )
        ]
    elif state == "owned":
        records = [record(artifact, name=_BEAD_ID, session=_BEAD_ID, pid=os.getpid())]
    else:
        from sase.agent.pending_handoff import PLAN_PENDING_MARKER

        (artifact / PLAN_PENDING_MARKER).write_text("", encoding="utf-8")
        records = [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    _make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


@pytest.mark.parametrize("marker", [MONITOR_PENDING_MARKER, GATE_PENDING_MARKER])
def test_pending_monitor_or_gate_handoff_suppresses_stranded_wait_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "pending-turn"
    artifact.mkdir()
    (artifact / marker).write_text("", encoding="utf-8")
    _wire_targeted_collector(
        monkeypatch,
        tmp_path,
        [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)],
        [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ],
    )
    _make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_open_child_plan_suppresses_stranded_wait_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    _wire_targeted_collector(
        monkeypatch,
        tmp_path,
        [
            phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID),
            epic(
                f"{_BEAD_ID}.1",
                parent_id=_BEAD_ID,
                status=Status.IN_PROGRESS,
                title="Open child plan",
            ),
        ],
        [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ],
    )
    _make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_stranded_bead_notification_dismisses_after_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    _point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = _make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    closed_ids.add(_BEAD_ID)
    run_wait_checks(tmp_path, monkeypatch)

    assert (waiter / "ready.json").exists()
    assert load_notifications() == []


def test_task_stranded_bead_notification_has_task_relaunch_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    monkeypatch.setattr(
        wait_checks_terminal,
        "upsert_notification",
        lambda notification, **kwargs: captured.append((notification, kwargs)),
    )

    wait_checks_terminal.upsert_stranded_bead_wait_notification(
        "proj",
        StrandedWorkVerdict(
            bead_id="sase-9",
            kind="task",
            state="stranded",
            reason="unclosed",
            last_turn="sase-9",
            last_turn_artifact_dir="/tmp/20261026120000",
            since=1_700_000_000.0,
        ),
        "Task title",
        (StrandedBeadWaiter(name="waiter", artifact_dir="/tmp/waiter"),),
        now=1_700_000_060.0,
    )

    notification, upsert_kwargs = captured[0]
    assert any("sase bead work sase-9 --yes" in note for note in notification.notes)
    assert (
        upsert_kwargs["plus_one_note"] == "Still blocked waiters: waiter (/tmp/waiter)"
    )


def test_collector_failure_leaves_waiter_parked_and_notifications_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    waiter = _make_waiters(tmp_path, "waiter")[0]

    def fail(*_args, **_kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", fail)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter / "ready.json").exists()
    assert load_notifications() == []


def test_targeted_report_cache_is_shared_across_ticks_and_invalidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    monkeypatch.setattr(
        stranded_cache, "canonical_beads_dir_for_project", lambda _p: beads_dir
    )
    fingerprint = ["store-v1"]
    monkeypatch.setattr(
        stranded_cache.bead_read_facade,
        "store_fingerprint",
        lambda _path: SimpleNamespace(token=fingerprint[0]),
    )
    facts_calls: list[tuple[str, ...]] = []
    reduce_calls = 0

    def collect(project: str, *, now: float, bead_ids):
        facts_calls.append((project, *tuple(bead_ids)))
        return {"now": now, "beads": []}

    def reduce(_facts):
        nonlocal reduce_calls
        reduce_calls += 1
        return StrandedWorkReport()

    monkeypatch.setattr(stranded_cache, "collect_stranded_work_input", collect)
    monkeypatch.setattr(stranded_cache, "collect_issue_titles", lambda *_a, **_k: {})
    monkeypatch.setattr(stranded_cache, "reduce_stranded_work", reduce)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-2", "sase-1"), now=100.0
    )
    for moment in range(101, 160):
        stranded_cache.collect_targeted_stranded_report(
            "proj", ("sase-1", "sase-2"), now=float(moment)
        )
    assert len(facts_calls) == 1
    assert reduce_calls == 1

    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-1", "sase-2"), now=160.0
    )
    assert len(facts_calls) == 2
    fingerprint[0] = "store-v2"
    stranded_cache.collect_targeted_stranded_report(
        "proj", ("sase-1", "sase-2"), now=161.0
    )
    assert len(facts_calls) == 3
    assert reduce_calls == 3


def test_targeted_collector_loads_only_named_candidates_and_child_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "target-turn"
    artifact.mkdir()
    issues = [
        phase(_BEAD_ID, assignee=_BEAD_ID, title="Target"),
        phase("sase-1.3", assignee="sase-1.3", title="Other"),
        child_plan("sase-1.2.plan", parent_id=_BEAD_ID, title="Context"),
        child_plan("sase-1.3.plan", parent_id="sase-1.3", title="Other context"),
    ]
    wire_collector(
        monkeypatch,
        tmp_path,
        issues,
        [record(artifact, name=_BEAD_ID, session=_BEAD_ID)],
    )

    facts = stranded_facts.collect_stranded_work_input(
        PROJECT,
        now=time.time(),
        bead_ids=[_BEAD_ID],
    )

    assert {item["id"] for item in facts["beads"]} == {_BEAD_ID, "sase-1.2.plan"}
    assert stranded_facts.collect_issue_titles(
        PROJECT,
        bead_ids=[_BEAD_ID],
    ) == {_BEAD_ID: "Target", "sase-1.2.plan": "Context"}


def test_parse_stranded_bead_wait_dedup_key_ignores_malformed() -> None:
    parse = wait_checks_terminal._parse_stranded_bead_wait_dedup_key
    assert parse(f"wait_checks:stranded-bead:proj:{_BEAD_ID}") == ("proj", _BEAD_ID)
    assert parse("wait_checks:stranded-bead:proj") is None
    assert parse("wait_checks:stranded-bead:") is None
    assert parse("wait_checks:terminal-blocked:/tmp/waiter") is None
    assert parse("other:stranded-bead:proj:sase-1") is None
    assert parse(None) is None


def test_stranded_alert_dismisses_when_waiter_is_already_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    _point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = _make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    closed_ids.add(_BEAD_ID)
    (waiter / "ready.json").write_text("{}", encoding="utf-8")
    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 0

    (waiter / "waiting.json").unlink()
    run_wait_checks(tmp_path, monkeypatch)
    assert load_notifications() == []


def test_stranded_alert_dismisses_when_waiting_marker_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    _point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = _make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    closed_ids.add(_BEAD_ID)
    (waiter / "waiting.json").unlink()
    run_wait_checks(tmp_path, monkeypatch)
    assert load_notifications() == []


def test_stranded_alert_dismisses_when_waiter_died(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    _point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = _make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    (waiter / "agent_meta.json").write_text(
        json.dumps({"stopped_at": "2026-10-26T00:00:00Z", "pid": 1}),
        encoding="utf-8",
    )
    issues[:] = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    closed_ids.add(_BEAD_ID)
    run_wait_checks(tmp_path, monkeypatch)
    assert load_notifications() == []


@pytest.mark.parametrize("state", ["settling", "owned", "delegated"])
def test_notification_only_reconciliation_dismisses_resolved_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "active-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    if state == "settling":
        records = [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 30),
            )
        ]
    elif state == "owned":
        records = [record(artifact, name=_BEAD_ID, session=_BEAD_ID, pid=os.getpid())]
    else:
        from sase.agent.pending_handoff import PLAN_PENDING_MARKER

        (artifact / PLAN_PENDING_MARKER).write_text("", encoding="utf-8")
        records = [
            record(
                artifact,
                name=_BEAD_ID,
                session=_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _ensure_projects_dir(tmp_path)
    _seed_stranded_notification("proj", _BEAD_ID)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_closed_bead_absent_from_reducer_still_dismisses_outstanding_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _ensure_projects_dir(tmp_path)
    _seed_stranded_notification("proj", _BEAD_ID)
    calls = _capture_collection_targets(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []
    assert calls == []


def test_status_read_failure_retains_outstanding_stranded_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, status=Status.CLOSED)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _ensure_projects_dir(tmp_path)
    _seed_stranded_notification("proj", _BEAD_ID)
    monkeypatch.setattr(
        wait_checks_run,
        "bead_statuses_for_project",
        lambda *_args, **_kwargs: None,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert len(load_notifications()) == 1


def test_collection_failure_retains_outstanding_stranded_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID)]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _ensure_projects_dir(tmp_path)
    _seed_stranded_notification("proj", _BEAD_ID)

    def fail(*_args, **_kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", fail)
    run_wait_checks(tmp_path, monkeypatch)

    assert len(load_notifications()) == 1


def test_no_stranded_work_without_pending_waits_or_active_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_calls: list[object] = []
    collect_calls: list[object] = []

    def record_status(*args: object, **kwargs: object) -> dict[str, str]:
        status_calls.append((args, kwargs))
        return {}

    def record_collect(*args: object, **kwargs: object) -> None:
        collect_calls.append((args, kwargs))

    monkeypatch.setattr(wait_checks_run, "bead_statuses_for_project", record_status)
    monkeypatch.setattr(
        wait_checks_run,
        "collect_targeted_stranded_report",
        record_collect,
    )
    _ensure_projects_dir(tmp_path)

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []
    assert status_calls == []
    assert collect_calls == []


def test_reconciliation_collects_only_pending_and_outstanding_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    other_id = "sase-9"
    issues = [
        phase(_BEAD_ID, assignee=_BEAD_ID, parent_id=_PARENT_ID),
        phase(other_id, assignee=other_id, parent_id="sase-8"),
        phase("sase-1.3", assignee="sase-1.3", parent_id=_PARENT_ID),
    ]
    records = [
        record(
            artifact,
            name=_BEAD_ID,
            session=_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    _wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    _make_waiters(tmp_path, "waiter")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _seed_stranded_notification("other-proj", other_id)
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=["malformed"],
            tags=["wait", "blocked", "stranded"],
            dedup_key="wait_checks:stranded-bead:proj",
        )
    )
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="wait_checks",
            notes=["unrelated"],
            tags=["wait", "blocked"],
            dedup_key="wait_checks:terminal-blocked:/tmp/waiter",
        )
    )
    append_notification(
        Notification(
            id=str(uuid4()),
            timestamp="2026-10-26T00:00:00+00:00",
            sender="other",
            notes=["wrong sender"],
            tags=["stranded"],
            dedup_key=f"wait_checks:stranded-bead:proj:{_BEAD_ID}",
        )
    )
    calls = _capture_collection_targets(monkeypatch)

    run_wait_checks(tmp_path, monkeypatch)

    assert sorted(calls) == [
        ("other-proj", (other_id,)),
        ("proj", (_BEAD_ID,)),
    ]
    assert any(
        row.dedup_key == f"wait_checks:stranded-bead:proj:{_BEAD_ID}"
        for row in load_notifications()
        if row.sender == "wait_checks"
    )
