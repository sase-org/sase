"""Settle orphaned triage gates and reap settled bundles (gate_reconcile)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

import sase.scripts._bead_task_triage_reconcile as task_triage
from sase.bead.model import SnoozeRecord, Status
from sase.notification_gates.paths import bundle_paths
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications, mark_dismissed
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


def _settle_bundle(kind: str, request_id: str, *, age_days: float) -> None:
    """Mark a bundle settled with a backdated settlement mtime."""
    root = bundle_paths(kind, request_id).root
    root.mkdir(parents=True, exist_ok=True)
    (root / "request.json").write_text(
        json.dumps({"request_id": request_id, "kind": kind}), encoding="utf-8"
    )
    stamp = time.time() - age_days * 86400.0
    (root / "cancellation.json").write_text(
        json.dumps({"request_id": request_id, "reason": "done"}), encoding="utf-8"
    )
    os.utime(root / "cancellation.json", (stamp, stamp))


def _pending_bundle(kind: str, request_id: str) -> None:
    root = bundle_paths(kind, request_id).root
    root.mkdir(parents=True, exist_ok=True)
    (root / "request.json").write_text(
        json.dumps({"request_id": request_id, "kind": kind}), encoding="utf-8"
    )


def test_dismissed_pending_triage_gate_is_cancelled_and_not_recreated(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (first,) = _rows()
    mark_dismissed(first.id)

    result = _run(gate_home)

    assert result.counters["canceled"] == 1
    assert _cancel_reason(_request_id(1)) == "notification_dismissed"
    state = task_triage._read_state(gate_home / task_triage._STATE_FILENAME)
    assert state["sase"].gates == {}
    assert state["sase"].dismissed == {_BEAD: task_triage.TASK_TRIAGE_KIND}
    # Sticky: still ready, still no gate.
    again = _run(gate_home)
    assert again.counters.get("gated", 0) == 0
    state = task_triage._read_state(gate_home / task_triage._STATE_FILENAME)
    assert state.get("sase") is None or state["sase"].gates == {}


def test_reentering_ready_recreates_after_dismissal_cancel(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready: list[Any] = [make_task(_BEAD)]
    patch_project(monkeypatch, gate_home, ready)
    _run(gate_home)
    (first,) = _rows()
    mark_dismissed(first.id)
    _run(gate_home)

    ready.clear()
    _run(gate_home)
    ready.append(make_task(_BEAD))
    result = _run(gate_home)

    assert result.counters["gated"] == 1
    rows = _rows()
    assert len(rows) == 2
    fresh = next(row for row in rows if row.id != first.id)
    assert fresh.dismissed is False


def test_resolved_bead_gate_is_cancelled(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready: list[Any] = [make_task(_BEAD)]
    patch_project(monkeypatch, gate_home, ready)
    _run(gate_home)
    first_id = _request_id(1)

    ready.clear()
    result = _run(gate_home)

    assert result.counters["canceled"] == 1
    assert _cancel_reason(first_id) == "task_bead_no_longer_ready"
    state = task_triage._read_state(gate_home / task_triage._STATE_FILENAME)
    assert state.get("sase") is None or state["sase"].gates == {}


def test_old_settled_bundles_are_reaped_while_fresh_and_pending_kept(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_project(monkeypatch, gate_home, [])
    _settle_bundle(task_triage.TASK_TRIAGE_KIND, "old-settled-1", age_days=31)
    _settle_bundle(task_triage.TASK_TRIAGE_KIND, "fresh-settled-1", age_days=2)
    _pending_bundle(task_triage.TASK_TRIAGE_KIND, "still-pending-1")
    _settle_bundle(task_triage.BEAD_SNOOZE_KIND, "old-snooze-1", age_days=45)

    result = _run(gate_home)

    assert result.counters.get("reaped_bundles", 0) == 2
    root = bundle_paths(task_triage.TASK_TRIAGE_KIND, "old-settled-1").root
    assert not root.exists()
    assert bundle_paths(task_triage.TASK_TRIAGE_KIND, "fresh-settled-1").root.exists()
    assert bundle_paths(task_triage.TASK_TRIAGE_KIND, "still-pending-1").root.exists()
    assert not bundle_paths(task_triage.BEAD_SNOOZE_KIND, "old-snooze-1").root.exists()


def test_other_kinds_are_untouched(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_project(monkeypatch, gate_home, [])
    _settle_bundle("plan", "old-plan-1", age_days=60)

    result = _run(gate_home)

    assert result.counters.get("reaped_bundles", 0) == 0
    assert bundle_paths("plan", "old-plan-1").root.exists()


def test_reap_cap_holds(gate_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_project(monkeypatch, gate_home, [])
    monkeypatch.setattr(
        task_triage, "get_task_triage_settled_bundle_reap_cap", lambda: 2
    )
    for slug in ("cap-old-1", "cap-old-2", "cap-old-3"):
        _settle_bundle(task_triage.TASK_TRIAGE_KIND, slug, age_days=40)

    result = _run(gate_home)

    assert result.counters.get("reaped_bundles", 0) == 2
    remaining = [
        slug
        for slug in ("cap-old-1", "cap-old-2", "cap-old-3")
        if bundle_paths(task_triage.TASK_TRIAGE_KIND, slug).root.exists()
    ]
    assert len(remaining) == 1


def test_kind_change_recreates_after_dismissal_suppression(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = make_task(_BEAD)
    patch_project(monkeypatch, gate_home, [task])
    _run(gate_home)
    (first,) = _rows()
    mark_dismissed(first.id)
    _run(gate_home)

    task.status = Status.SNOOZED
    task.snooze = SnoozeRecord(
        until=future_instant(days=3),
        snoozed_at="2026-08-01T00:00:00+00:00",
        snoozed_by="bryan",
    )
    result = _run(gate_home)

    assert result.counters["gated"] == 1
    rows = _rows()
    assert len(rows) == 2
