"""Result-contract coverage for gate-shell reclaim sweeps."""

from __future__ import annotations

import pytest

import sase.gate_shell.reclaim as reclaim_mod
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.reclaim import (
    _MAX_ERROR_DETAILS,
    GateShellReclaimSummary,
    reclaim_pending_gate_shells,
)


def _record(
    *,
    gate_id: str,
    member_agent_name: str,
    gate_state: str = "pending",
) -> GateShellRecord:
    return GateShellRecord(
        gate_id=gate_id,
        member_agent_name=member_agent_name,
        lane="lane",
        project_name="proj",
        artifacts_dir="/tmp/artifacts",
        timestamp="20260828120000",
        kind="custom",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="WAIT",
        stop_status="DONE",
        accent="#00D7AF",
        label="Review",
        reason="wait",
        creator_agent="lane--0",
        bundle_path="/tmp/bundle",
        notification_id="notif-1",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def test_reclaim_records_error_details_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _record(gate_id="gate-bad", member_agent_name="lane--gate-bad")
    succeeding = _record(gate_id="gate-good", member_agent_name="lane--gate-good")
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_shells",
        lambda *, project=None: [failing, succeeding],
    )

    def _reclaim_one(
        record: GateShellRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        if record.gate_id == "gate-bad":
            raise RuntimeError("bundle exploded")
        return "answered"

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_shells()

    assert summary.scanned == 2
    assert summary.errors == 1
    assert summary.answered == 1
    assert len(summary.error_details) == 1
    detail = summary.error_details[0]
    assert detail.startswith("lane--gate-bad: RuntimeError: bundle exploded")


def test_reclaim_error_details_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        _record(gate_id=f"gate-{index}", member_agent_name=f"lane--gate-{index}")
        for index in range(_MAX_ERROR_DETAILS + 2)
    ]
    monkeypatch.setattr(
        reclaim_mod,
        "list_gate_shells",
        lambda *, project=None: records,
    )

    def _reclaim_one(
        record: GateShellRecord,
        *,
        now: float,
        grace_seconds: int,
    ) -> str | None:
        del now, grace_seconds
        raise RuntimeError(record.gate_id)

    monkeypatch.setattr(reclaim_mod, "_reclaim_one", _reclaim_one)

    summary = reclaim_pending_gate_shells()

    assert summary.scanned == _MAX_ERROR_DETAILS + 2
    assert summary.errors == _MAX_ERROR_DETAILS + 2
    assert len(summary.error_details) == _MAX_ERROR_DETAILS


def test_reclaim_summary_to_dict_omits_error_details() -> None:
    summary = GateShellReclaimSummary(
        scanned=2,
        answered=1,
        errors=1,
        error_details=("lane--gate: RuntimeError: boom",),
    )

    payload = summary.to_dict()

    assert payload == {
        "scanned": 2,
        "answered": 1,
        "stopped": 0,
        "timed_out": 0,
        "lost": 0,
        "errors": 1,
    }
    assert "error_details" not in payload
