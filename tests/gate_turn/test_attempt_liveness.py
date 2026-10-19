"""Liveness checks for persisted gate follow-up attempts."""

from __future__ import annotations

import os

import pytest

from sase.gate_turn.attempt_liveness import gate_followup_attempt_is_live


def test_recorded_live_attempt_without_pid_is_live() -> None:
    assert gate_followup_attempt_is_live({"gate_followup_attempt_live": True})


@pytest.mark.parametrize("owner_is_live", [True, False], ids=["running", "dead"])
def test_recorded_live_attempt_checks_owner_pid(
    monkeypatch: pytest.MonkeyPatch,
    owner_is_live: bool,
) -> None:
    checked_pids: list[int] = []

    def is_process_running(pid: int) -> bool:
        checked_pids.append(pid)
        return owner_is_live

    monkeypatch.setattr(
        "sase.ace.hooks.processes.is_process_running", is_process_running
    )

    assert (
        gate_followup_attempt_is_live(
            {
                "gate_followup_attempt_live": True,
                "gate_followup_attempt_owner_pid": os.getpid(),
            }
        )
        is owner_is_live
    )
    assert checked_pids == [os.getpid()]


def test_unrecorded_attempt_is_not_live() -> None:
    assert not gate_followup_attempt_is_live({"gate_followup_attempt_live": False})
