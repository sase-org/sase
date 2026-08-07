"""Snoozed task-bead wake-gate reconciliation tests for the task triage chop."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.model import Issue

from tests._axe_chop_bead_task_triage_helpers import (
    make_runtime,
    make_snoozed_task,
    make_task,
    patch_project,
    patch_snooze_gate,
)


def test_snoozed_task_raises_a_wake_gate_carrying_its_snooze_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed = make_snoozed_task()
    patch_project(monkeypatch, tmp_path, [snoozed])
    created: list[dict[str, Any]] = []
    patch_snooze_gate(monkeypatch, created)
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **_kwargs: pytest.fail("a snoozed task raised a triage gate"),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 1,
        "canceled": 0,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert created[0]["snooze"] == snoozed.snooze
    assert created[0]["request_id"].startswith("bead-snooze-")
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.BEAD_SNOOZE_KIND}


def test_snoozing_a_ready_task_replaces_its_triage_gate_with_a_wake_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live = [make_task()]
    patch_project(monkeypatch, tmp_path, live)
    triage_created: list[dict[str, Any]] = []
    snooze_created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: triage_created.append(kwargs),
    )
    patch_snooze_gate(monkeypatch, snooze_created)
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )

    task_triage._run(make_runtime(tmp_path))
    live[:] = [make_snoozed_task()]
    swapped = task_triage._run(make_runtime(tmp_path))

    assert swapped.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [
        (
            task_triage.TASK_TRIAGE_KIND,
            triage_created[0]["request_id"],
            "bead_status_changed",
        )
    ]
    assert len(snooze_created) == 1
    assert snooze_created[0]["request_id"].endswith("-g2")
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.BEAD_SNOOZE_KIND}
    assert state.gates == {"sase-task.1": snooze_created[0]["request_id"]}


def test_waking_a_snoozed_task_replaces_its_wake_gate_with_a_triage_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live = [make_snoozed_task()]
    patch_project(monkeypatch, tmp_path, live)
    triage_created: list[dict[str, Any]] = []
    snooze_created: list[dict[str, Any]] = []
    canceled: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: triage_created.append(kwargs),
    )
    patch_snooze_gate(monkeypatch, snooze_created)
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, *, reason: (
            canceled.append((kind, request_id, reason)) or True
        ),
    )
    monkeypatch.setattr(task_triage, "_heal_snoozed_notification", lambda *_args: False)

    task_triage._run(make_runtime(tmp_path))
    live[:] = [make_task()]
    swapped = task_triage._run(make_runtime(tmp_path))

    assert swapped.counters == {
        "gated": 1,
        "canceled": 1,
        "skipped": 0,
        "resnoozed": 0,
    }
    assert canceled == [
        (
            task_triage.BEAD_SNOOZE_KIND,
            snooze_created[0]["request_id"],
            "bead_status_changed",
        )
    ]
    state = task_triage._read_state(tmp_path / task_triage._STATE_FILENAME)["sase"]
    assert state.kinds == {"sase-task.1": task_triage.TASK_TRIAGE_KIND}


def test_no_task_bead_ever_holds_two_pending_gates_across_a_status_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The bead-side counterpart to the notification-side one-tab guarantee."""
    live = [make_task()]
    patch_project(monkeypatch, tmp_path, live)
    pending: dict[tuple[str, str], bool] = {}
    monkeypatch.setattr(
        task_triage,
        "create_task_triage_gate",
        lambda **kwargs: pending.__setitem__(
            (task_triage.TASK_TRIAGE_KIND, kwargs["request_id"]), True
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **kwargs: pending.__setitem__(
            (task_triage.BEAD_SNOOZE_KIND, kwargs["request_id"]), True
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_gate_state",
        lambda kind, request_id: (
            "pending" if pending.get((kind, request_id)) else ("terminal")
        ),
    )
    monkeypatch.setattr(
        task_triage,
        "_cancel_pending_gate",
        lambda kind, request_id, **_kwargs: bool(
            pending.pop((kind, request_id), False)
        ),
    )
    monkeypatch.setattr(task_triage, "_heal_snoozed_notification", lambda *_args: False)

    for status_swap in ([make_snoozed_task()], [make_task()], [make_snoozed_task()]):
        task_triage._run(make_runtime(tmp_path))
        assert sum(pending.values()) <= 1
        live[:] = status_swap
    task_triage._run(make_runtime(tmp_path))

    assert sum(pending.values()) == 1


def _patch_notification_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[Any],
    snoozed: list[tuple[str, datetime]],
) -> None:
    import sase.notifications.store as notification_store

    monkeypatch.setattr(notification_store, "load_notifications", lambda: list(rows))
    monkeypatch.setattr(
        notification_store,
        "mark_snoozed",
        lambda notification_id, until: (
            bool(snoozed.append((notification_id, until))) or True
        ),
    )


def _notification_row(*, muted: bool, snooze_until: str | None) -> Any:
    from sase.notifications.models import Notification

    return Notification(
        id="notif-1",
        timestamp="2026-08-01T00:00:00+00:00",
        sender="bead",
        muted=muted,
        snooze_until=snooze_until,
    )


def _run_with_pending_snooze_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    snoozed_task: Issue,
    rows: list[Any],
    snoozed: list[tuple[str, datetime]],
) -> Any:
    """Reconcile once over an already-gated snoozed bead whose gate is current."""
    patch_project(monkeypatch, tmp_path, [snoozed_task])
    request_id = task_triage._request_id(
        "sase", snoozed_task.id, 1, task_triage.BEAD_SNOOZE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={snoozed_task.id: request_id},
                generations={snoozed_task.id: 1},
                fingerprints={
                    snoozed_task.id: task_triage._presentation_fingerprint(snoozed_task)
                },
                kinds={snoozed_task.id: task_triage.BEAD_SNOOZE_KIND},
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage, "_gate_notification_id", lambda _kind, _id: "notif-1"
    )
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **_kwargs: pytest.fail("a current wake gate was recreated"),
    )
    _patch_notification_store(monkeypatch, rows=rows, snoozed=snoozed)
    return task_triage._run(make_runtime(tmp_path))


def test_unmuted_wake_notification_is_re_snoozed_to_the_bead_wake_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed_task = make_snoozed_task()
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=False, snooze_until=None)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 1,
    }
    assert result.reason is None
    assert snoozed == [("notif-1", datetime.fromisoformat(snoozed_task.snooze.until))]


def test_wake_notification_already_snoozed_to_its_wake_time_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    snoozed_task = make_snoozed_task()
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=True, snooze_until=snoozed_task.snooze.until)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
    assert result.reason == "no_triage_changes"
    assert snoozed == []


def test_a_past_wake_time_leaves_the_resurfaced_notification_unread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """After the wake, the row is meant to be visible — re-snoozing would hide it."""
    snoozed_task = make_snoozed_task(until="2020-01-01T00:00:00+00:00")
    snoozed: list[tuple[str, datetime]] = []
    rows = [_notification_row(muted=False, snooze_until=None)]

    result = _run_with_pending_snooze_gate(
        monkeypatch,
        tmp_path,
        snoozed_task=snoozed_task,
        rows=rows,
        snoozed=snoozed,
    )

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
    assert snoozed == []


def test_a_pending_triage_gate_never_touches_the_notification_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    request_id = task_triage._request_id(
        "sase", task.id, 1, task_triage.TASK_TRIAGE_KIND
    )
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={task.id: request_id},
                generations={task.id: 1},
                fingerprints={task.id: task_triage._presentation_fingerprint(task)},
                kinds={task.id: task_triage.TASK_TRIAGE_KIND},
            )
        },
    )
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    monkeypatch.setattr(
        task_triage,
        "_gate_notification_id",
        lambda *_args: pytest.fail("a triage gate read the notification store"),
    )

    result = task_triage._run(make_runtime(tmp_path))

    assert result.counters == {
        "gated": 0,
        "canceled": 0,
        "skipped": 1,
        "resnoozed": 0,
    }
