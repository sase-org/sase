"""One task-triage notification row per bead across gate re-presentations.

These run the chop against real gate bundles and a real notification store
(``gate_home``), so they cover the adopt-then-retire handoff end to end.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.gate_lookup import find_pending_bead_gates
from sase.bead.model import SnoozeRecord, Status, TaskPlusOneEvidence
from sase.notification_gates.paths import bundle_paths
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications, mark_dismissed, mark_read
from tests._axe_chop_bead_task_triage_helpers import (
    future_instant,
    make_runtime,
    make_task,
    patch_project,
)

_BEAD = "sase-task.1"


def _run(tmp_path: Path) -> Any:
    return task_triage._run(make_runtime(tmp_path))


def _rows() -> list[Notification]:
    return load_notifications(include_dismissed=True)


def _row(notification_id: str) -> Notification:
    return next(row for row in _rows() if row.id == notification_id)


def _tracked_request_id(tmp_path: Path) -> str:
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)
    return state["sase"].gates[_BEAD]


def _request_id(generation: int, kind: str = task_triage.TASK_TRIAGE_KIND) -> str:
    return task_triage._request_id("sase", _BEAD, generation, kind)


def _cancel_reason(request_id: str, kind: str = task_triage.TASK_TRIAGE_KIND) -> Any:
    path = bundle_paths(kind, request_id).root / "cancellation.json"
    return json.loads(path.read_text(encoding="utf-8"))["reason"]


def _add_plus_one(issue: Any, note: str, *, reporter: str | None = None) -> None:
    count = len(issue.plus_one_evidence)
    issue.plus_one_evidence = [
        *issue.plus_one_evidence,
        TaskPlusOneEvidence(
            timestamp=f"2026-01-0{count + 2}T00:00:00Z",
            reporter=reporter or f"reporter-{count + 1}",
            note=note,
        ),
    ]


def test_rendered_changes_refresh_one_row_in_place(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (first,) = _rows()
    mark_read(first.id)

    for count in range(1, 4):
        _add_plus_one(task, f"Seen again ({count}).")
        result = _run(gate_home)
        assert result.counters["gated"] == 1
        assert result.counters["canceled"] == 1

    rows = _rows()
    assert [row.id for row in rows] == [first.id]
    (row,) = rows
    assert row.read is True
    assert row.dismissed is False
    assert row.notes != first.notes
    assert row.action_data["request_id"] == _tracked_request_id(gate_home)
    assert _tracked_request_id(gate_home) == _request_id(4)
    for generation in (1, 2, 3):
        assert (
            _cancel_reason(_request_id(generation))
            == "task_triage_presentation_changed"
        )


def test_a_user_dismissal_survives_a_rerender(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (first,) = _rows()
    mark_dismissed(first.id)

    _add_plus_one(task, "Still failing.")
    _run(gate_home)

    (row,) = _rows()
    assert row.id == first.id
    assert row.dismissed is True
    assert row.action_data["request_id"] == _request_id(2)


def test_a_kind_change_raises_a_new_row(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (triage,) = _rows()
    mark_read(triage.id)

    task.status = Status.SNOOZED
    task.snooze = SnoozeRecord(
        until=future_instant(days=3),
        snoozed_at="2026-08-01T00:00:00+00:00",
        snoozed_by="bryan",
    )
    _run(gate_home)
    wake = next(row for row in _rows() if row.id != triage.id)
    assert _row(triage.id).dismissed is True
    assert wake.dismissed is False
    assert wake.read is False

    task.status = Status.READY
    task.snooze = None
    _run(gate_home)
    retriage = next(row for row in _rows() if row.id not in {triage.id, wake.id})
    assert _row(wake.id).dismissed is True
    assert retriage.read is False
    assert retriage.dismissed is False


def test_reentering_ready_raises_a_new_unread_row(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    ready = [task]
    patch_project(monkeypatch, gate_home, ready)
    _run(gate_home)
    (first,) = _rows()
    mark_read(first.id)

    ready.clear()
    _run(gate_home)
    assert _row(first.id).dismissed is True
    assert _cancel_reason(_request_id(1)) == "task_bead_no_longer_ready"

    ready.append(task)
    _run(gate_home)
    fresh = next(row for row in _rows() if row.id != first.id)
    assert fresh.read is False
    assert fresh.dismissed is False


def test_conflicting_successor_holding_the_row_is_retired_without_settling(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (row,) = _rows()

    # A pass that crashed after its successor adopted the row but before it
    # retired the predecessor or saved state left generation 2 pending.
    stale = make_task(_BEAD)
    _add_plus_one(stale, "An older +1.", reporter="someone-else")
    task_triage._create_gate(
        task_triage.TASK_TRIAGE_KIND,
        request_id=_request_id(2),
        bead_id=_BEAD,
        project_name="sase",
        issue=stale,
        notification_id=row.id,
    )
    _add_plus_one(task, "A newer +1.")

    result = _run(gate_home)

    assert result.counters["gated"] == 1
    assert _tracked_request_id(gate_home) == _request_id(3)
    assert _cancel_reason(_request_id(2)) == "request_id_conflict"
    assert _cancel_reason(_request_id(1)) == "task_triage_presentation_changed"
    (current,) = _rows()
    assert current.id == row.id
    assert current.dismissed is False
    assert current.action_data["request_id"] == _request_id(3)


def test_untracked_superseded_gate_leaves_the_successors_row(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    monkeypatch.setattr(task_triage, "find_pending_bead_gates", find_pending_bead_gates)
    _run(gate_home)
    (row,) = _rows()

    real_retire = task_triage._retire_superseded_gate
    calls: list[str] = []

    def flaky_retire(kind: str, request_id: str, *, reason: str) -> bool:
        calls.append(reason)
        if len(calls) == 1:
            raise TimeoutError("acceptance lock held")
        return real_retire(kind, request_id, reason=reason)

    monkeypatch.setattr(task_triage, "_retire_superseded_gate", flaky_retire)
    _add_plus_one(task, "Seen again.")
    _run(gate_home)

    assert calls == ["task_triage_presentation_changed", "gate_no_longer_tracked"]
    assert _cancel_reason(_request_id(1)) == "gate_no_longer_tracked"
    (current,) = _rows()
    assert current.dismissed is False
    assert current.action_data["request_id"] == _request_id(2)


def test_failed_successor_keeps_tracking_the_pending_gate(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (row,) = _rows()
    fingerprint = task_triage._read_state(gate_home / task_triage._STATE_FILENAME)[
        "sase"
    ].fingerprints[_BEAD]

    def fail(**kwargs: object) -> None:
        raise OSError(f"disk full creating {kwargs['request_id']}")

    monkeypatch.setattr(task_triage, "create_task_triage_gate", fail)
    _add_plus_one(task, "Seen again.")
    result = _run(gate_home)

    assert result.counters["gated"] == 0
    assert result.counters["canceled"] == 0
    state = task_triage._read_state(gate_home / task_triage._STATE_FILENAME)["sase"]
    assert state.gates[_BEAD] == _request_id(1)
    assert state.fingerprints[_BEAD] == fingerprint
    assert task_triage._gate_state(task_triage.TASK_TRIAGE_KIND, _request_id(1)) == (
        "pending"
    )
    assert _row(row.id).dismissed is False
