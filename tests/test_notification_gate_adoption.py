"""A successor gate adopts its predecessor's notification row in place."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

import sase.notification_gates.service_creation as service_creation
from sase.core.time import get_timezone
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.service import create_gate
from sase.notifications.models import Notification
from sase.notifications.pending_actions import read_pending_action_store
from sase.notifications.store import (
    load_notifications,
    mark_dismissed,
    mark_read,
)
from tests._notification_gates_fixtures import gate_spec


def _rows(*, include_dismissed: bool = True) -> list[Notification]:
    return load_notifications(include_dismissed=include_dismissed)


def _row(notification_id: str) -> Notification:
    return next(row for row in _rows() if row.id == notification_id)


def _pending_entry(notification_id: str) -> dict[str, object]:
    actions = read_pending_action_store()["actions"].values()
    return next(
        entry for entry in actions if entry.get("notification_id") == notification_id
    )


def _successor_spec(request_id: str) -> dict[str, object]:
    spec = gate_spec(request_id=request_id)
    spec["presentation"] = {**spec["presentation"], "notes": ["Review again"]}  # type: ignore[dict-item]
    return spec


def test_successor_refreshes_the_row_and_keeps_its_inbox_state(
    gate_home: Path,
) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None
    mark_read(first.notification_id)
    before = _row(first.notification_id)

    second = create_gate(
        _successor_spec("second"), notification_id=first.notification_id
    )

    assert second.notification_id == first.notification_id
    rows = _rows()
    assert [row.id for row in rows] == [first.notification_id]
    row = rows[0]
    assert row.read is True
    assert row.dismissed is False
    assert row.timestamp == before.timestamp
    assert row.notes == ["Review again"]
    assert row.action_data["request_id"] == "second"
    assert row.action_data["bundle_path"] == str(second.bundle_path)
    assert row.files == [str(second.bundle_path / "preview.md")]
    entry = _pending_entry(first.notification_id)
    assert entry["state"] == "available"
    assert entry["action_data"]["request_id"] == "second"  # type: ignore[index]


def test_retiring_the_predecessor_without_settling_keeps_the_row(
    gate_home: Path,
) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None
    create_gate(_successor_spec("second"), notification_id=first.notification_id)

    cancel_gate(first.bundle_path, reason="superseded", settle_notification=False)

    row = _row(first.notification_id)
    assert row.dismissed is False
    assert row.action_data["request_id"] == "second"
    assert _pending_entry(first.notification_id)["state"] == "available"
    assert (first.bundle_path / "cancellation.json").is_file()


def test_settling_cancellation_still_dismisses_the_row(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(gate_spec(request_id="only"))
    assert gate.notification_id is not None

    cancel_gate(gate.bundle_path, reason="requester_cancelled")

    assert _row(gate.notification_id).dismissed is True


def test_adoption_keeps_a_user_dismissal(gate_home: Path) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None
    mark_dismissed(first.notification_id)

    create_gate(_successor_spec("second"), notification_id=first.notification_id)

    row = _row(first.notification_id)
    assert row.dismissed is True
    assert row.action_data["request_id"] == "second"


def test_adopting_a_missing_row_creates_it_unread(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(
        gate_spec(request_id="fresh"),
        notification_id="0b6f4c3e-9b0e-4c55-8d1f-7a0f5d7b1a11",
    )

    assert gate.notification_id == "0b6f4c3e-9b0e-4c55-8d1f-7a0f5d7b1a11"
    row = _row(gate.notification_id)
    assert row.read is False
    assert row.dismissed is False
    assert row.action_data["request_id"] == "fresh"


def test_born_snoozed_successor_resnoozes_the_adopted_row(gate_home: Path) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None
    wake = (datetime.now(get_timezone()) + timedelta(days=2)).replace(microsecond=0)
    spec = _successor_spec("second")
    spec["presentation"] = {**spec["presentation"], "snooze_until": wake.isoformat()}  # type: ignore[dict-item]

    create_gate(spec, notification_id=first.notification_id)

    row = _row(first.notification_id)
    assert row.muted is True
    assert row.snooze_until is not None
    assert datetime.fromisoformat(row.snooze_until) == wake


def test_failed_adoption_returns_the_row_to_its_predecessor(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(service_creation, "_complete_manual_gate", fail)
    with pytest.raises(OSError, match="disk full"):
        create_gate(_successor_spec("second"), notification_id=first.notification_id)

    row = _row(first.notification_id)
    assert row.dismissed is False
    assert row.notes == ["Review requested"]
    assert row.action_data["request_id"] == "first"
    assert _pending_entry(first.notification_id)["state"] == "available"


def test_adoption_failing_before_publication_leaves_the_row_alone(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    first = create_gate(gate_spec(request_id="first"))
    assert first.notification_id is not None

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("cannot build envelope")

    monkeypatch.setattr(service_creation, "build_gate_envelope", fail)
    with pytest.raises(OSError, match="cannot build envelope"):
        create_gate(_successor_spec("second"), notification_id=first.notification_id)

    row = _row(first.notification_id)
    assert row.dismissed is False
    assert row.action_data["request_id"] == "first"
    assert _pending_entry(first.notification_id)["state"] == "available"
