"""Stranded-bead waiter alert lifecycle tests.

Split from ``tests.test_axe_chop_wait_checks_stranded_beads``; the
original module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import sase.scripts._chop_wait_checks_run as wait_checks_run
import sase.scripts._chop_wait_checks_terminal as wait_checks_terminal
from sase.agent.pending_handoff import GATE_PENDING_MARKER, MONITOR_PENDING_MARKER
from sase.bead.model import Status
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.stranded_work_facade import StrandedWorkVerdict
from sase.notifications.store import load_notifications
from sase.scripts._chop_wait_checks_common import StrandedBeadWaiter

from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._axe_chop_wait_checks_stranded_beads_helpers import (
    STRANDED_BEAD_ID,
    STRANDED_PARENT_ID,
    make_waiters,
    point_wait_bead_status,
    wire_targeted_collector,
)
from tests._stranded_collector_helpers import epic, phase, record

__all__ = [
    "test_collector_failure_leaves_waiter_parked_and_notifications_unchanged",
    "test_open_child_plan_suppresses_stranded_wait_alert",
    "test_pending_monitor_or_gate_handoff_suppresses_stranded_wait_alert",
    "test_stranded_alert_dismisses_when_waiter_died",
    "test_stranded_alert_dismisses_when_waiter_is_already_ready",
    "test_stranded_alert_dismisses_when_waiting_marker_is_removed",
    "test_stranded_bead_notification_dismisses_after_close",
    "test_stranded_bead_waiters_share_one_notification",
    "test_task_stranded_bead_notification_has_task_relaunch_command",
    "test_wait_checks_does_not_notify_before_stranding",
]


def test_stranded_bead_waiters_share_one_notification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    first_waiter = make_waiters(tmp_path, "phase-two")[0]

    run_wait_checks(tmp_path, monkeypatch)

    assert not (first_waiter / "ready.json").exists()
    notifications = load_notifications()
    assert len(notifications) == 1
    row = notifications[0]
    assert row.sender == "wait_checks"
    assert row.dedup_key == f"wait_checks:stranded-bead:proj:{STRANDED_BEAD_ID}"
    assert row.color == "#D14343"
    assert set(row.tags) == {"wait", "blocked", "stranded"}
    assert row.action == "JumpToAgent"
    assert row.action_data["cl_name"] == STRANDED_BEAD_ID
    assert row.action_data["raw_suffix"] == artifact.name
    assert any(f"{STRANDED_BEAD_ID} — Phase" in note for note in row.notes)
    assert any("ended without closing the bead" in note for note in row.notes)
    assert any("Last turn:" in note and "1h ago" in note for note in row.notes)
    assert any("waiter-1" in note for note in row.notes)
    assert any(
        f"sase bead work {STRANDED_PARENT_ID} --yes-to-all" in note
        for note in row.notes
    )
    assert any(
        f"sase bead close {STRANDED_BEAD_ID} --note" in note for note in row.notes
    )

    second_waiter = make_waiting_agent(
        tmp_path,
        suffix="land",
        wait_for_beads=[STRANDED_BEAD_ID],
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
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "active-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    if state == "settling":
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 30),
            )
        ]
    elif state == "owned":
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                pid=os.getpid(),
            )
        ]
    else:
        from sase.agent.pending_handoff import PLAN_PENDING_MARKER

        (artifact / PLAN_PENDING_MARKER).write_text("", encoding="utf-8")
        records = [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


@pytest.mark.parametrize("marker", [MONITOR_PENDING_MARKER, GATE_PENDING_MARKER])
def test_pending_monitor_or_gate_handoff_suppresses_stranded_wait_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "pending-turn"
    artifact.mkdir()
    (artifact / marker).write_text("", encoding="utf-8")
    wire_targeted_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                STRANDED_BEAD_ID,
                assignee=STRANDED_BEAD_ID,
                parent_id=STRANDED_PARENT_ID,
            )
        ],
        [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ],
    )
    make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_open_child_plan_suppresses_stranded_wait_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_wait_bead_status(monkeypatch)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    wire_targeted_collector(
        monkeypatch,
        tmp_path,
        [
            phase(
                STRANDED_BEAD_ID,
                assignee=STRANDED_BEAD_ID,
                parent_id=STRANDED_PARENT_ID,
            ),
            epic(
                f"{STRANDED_BEAD_ID}.1",
                parent_id=STRANDED_BEAD_ID,
                status=Status.IN_PROGRESS,
                title="Open child plan",
            ),
        ],
        [
            record(
                artifact,
                name=STRANDED_BEAD_ID,
                session=STRANDED_BEAD_ID,
                done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
            )
        ],
    )
    make_waiters(tmp_path, "waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert load_notifications() == []


def test_stranded_bead_notification_dismisses_after_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)
    ]
    closed_ids.add(STRANDED_BEAD_ID)
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
    point_wait_bead_status(monkeypatch)
    waiter = make_waiters(tmp_path, "waiter")[0]

    def fail(*_args, **_kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr(wait_checks_run, "collect_targeted_stranded_report", fail)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter / "ready.json").exists()
    assert load_notifications() == []


def test_stranded_alert_dismisses_when_waiter_is_already_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)
    ]
    closed_ids.add(STRANDED_BEAD_ID)
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
    point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    issues[:] = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)
    ]
    closed_ids.add(STRANDED_BEAD_ID)
    (waiter / "waiting.json").unlink()
    run_wait_checks(tmp_path, monkeypatch)
    assert load_notifications() == []


def test_stranded_alert_dismisses_when_waiter_died(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_ids: set[str] = set()
    point_wait_bead_status(monkeypatch, closed_ids)
    now = time.time()
    artifact = tmp_path / "stranded-turn"
    artifact.mkdir()
    issues = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, parent_id=STRANDED_PARENT_ID)
    ]
    records = [
        record(
            artifact,
            name=STRANDED_BEAD_ID,
            session=STRANDED_BEAD_ID,
            done=DoneMarkerWire(outcome="completed", finished_at=now - 3600),
        )
    ]
    wire_targeted_collector(monkeypatch, tmp_path, issues, records)
    waiter = make_waiters(tmp_path, "waiter")[0]

    run_wait_checks(tmp_path, monkeypatch)
    assert len(load_notifications()) == 1

    (waiter / "agent_meta.json").write_text(
        json.dumps({"stopped_at": "2026-10-26T00:00:00Z", "pid": 1}),
        encoding="utf-8",
    )
    issues[:] = [
        phase(STRANDED_BEAD_ID, assignee=STRANDED_BEAD_ID, status=Status.CLOSED)
    ]
    closed_ids.add(STRANDED_BEAD_ID)
    run_wait_checks(tmp_path, monkeypatch)
    assert load_notifications() == []
