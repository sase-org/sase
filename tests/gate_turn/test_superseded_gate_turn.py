"""Settling the gate turn of a lost intent a later declaration superseded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.gate_turn import _superseded as superseded_module
from sase.gate_turn.models import GateTurnRecord
from sase.gate_turn.reclaim import settle_superseded_gate_turn


def _record(
    tmp_path: Path,
    *,
    gate_id: str,
    gate_state: str = "pending",
    notification_id: str | None = None,
) -> GateTurnRecord:
    return GateTurnRecord(
        gate_id=gate_id,
        member_agent_name="agent--gate",
        lane="agent",
        project_name="proj",
        artifacts_dir=str(tmp_path / gate_id),
        timestamp="20260916120000",
        kind="custom",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="GATE",
        stop_status="GATED",
        accent="yellow",
        label="custom",
        reason="gate pending",
        creator_agent="agent",
        bundle_path=None,
        notification_id=notification_id,
        timeout_seconds=30.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def _patch_settlement(
    monkeypatch: pytest.MonkeyPatch,
    record: GateTurnRecord | None,
    outcome: str | None,
) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    def _settle(rec: GateTurnRecord, reason: str) -> str | None:
        calls.append((rec.gate_id, reason))
        return outcome

    monkeypatch.setattr(
        superseded_module, "find_gate_turn_by_gate_id", lambda *_: record
    )
    monkeypatch.setattr(superseded_module, "settle_lost_unless_creating", _settle)
    return calls


def test_settled_member_is_withdrawn_like_a_lost_gate(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del gate_home
    from sase.notification_gates.paths import bundle_paths
    from sase.notification_gates.service import create_gate
    from sase.notifications import pending_actions
    from sase.notifications.store import load_notifications
    from tests._notification_gates_fixtures import custom_gate_spec

    gate = create_gate(custom_gate_spec(request_id="superseded-1"))
    assert gate.notification_id is not None
    record = _record(
        tmp_path, gate_id="superseded-1", notification_id=gate.notification_id
    )
    calls = _patch_settlement(monkeypatch, record, "settled")

    assert settle_superseded_gate_turn("superseded-1") is True

    assert [gate_id for gate_id, _ in calls] == ["superseded-1"]
    assert "superseded" in calls[0][1]
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is True
    actions: dict[str, Any] = pending_actions.read_pending_action_store().get(
        "actions", {}
    )
    assert all(
        not isinstance(entry, dict)
        or entry.get("notification_id") != notification.id
        or entry.get("state") != "available"
        for entry in actions.values()
    )
    journal = json.loads(
        bundle_paths("custom", "superseded-1").journal.read_text(encoding="utf-8")
    )
    assert journal["state"] == "failed"


@pytest.mark.parametrize("outcome", ["creating", "reachable", None])
def test_unsettled_member_is_not_withdrawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str | None
) -> None:
    record = _record(tmp_path, gate_id="superseded-2", notification_id="notif-2")
    _patch_settlement(monkeypatch, record, outcome)
    withdrawn: list[GateTurnRecord] = []
    monkeypatch.setattr(
        superseded_module, "withdraw_lost_gate", lambda rec: withdrawn.append(rec)
    )

    assert settle_superseded_gate_turn("superseded-2") is False
    assert withdrawn == []


def test_missing_or_terminal_member_is_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_settlement(monkeypatch, None, "settled")
    assert settle_superseded_gate_turn("superseded-3") is False
    assert settle_superseded_gate_turn(None) is False

    terminal = _record(tmp_path, gate_id="superseded-3", gate_state="answered")
    calls = _patch_settlement(monkeypatch, terminal, "settled")
    assert settle_superseded_gate_turn("superseded-3") is False
    assert calls == []
