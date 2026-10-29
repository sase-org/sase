"""Liveness checks for persisted gate follow-up attempts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.gate_turn.attempt_liveness import gate_followup_attempt_is_live
from sase.gate_turn.handoff import with_gate_followup_lock


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


def test_running_owner_with_unheld_lock_is_an_orphaned_attempt(tmp_path: Path) -> None:
    (tmp_path / ".gate_followup.lock").touch()

    assert not gate_followup_attempt_is_live(
        {
            "gate_followup_attempt_live": True,
            "gate_followup_attempt_owner_pid": os.getpid(),
        },
        artifacts_dir=str(tmp_path),
    )


def test_held_followup_lock_proves_attempt_is_live(tmp_path: Path) -> None:
    with with_gate_followup_lock(str(tmp_path)):
        assert gate_followup_attempt_is_live(
            {
                "gate_followup_attempt_live": True,
                "gate_followup_attempt_owner_pid": -1,
            },
            artifacts_dir=str(tmp_path),
        )


def test_missing_followup_lock_means_attempt_is_not_live(tmp_path: Path) -> None:
    assert not gate_followup_attempt_is_live(
        {
            "gate_followup_attempt_live": True,
            "gate_followup_attempt_owner_pid": os.getpid(),
        },
        artifacts_dir=str(tmp_path),
    )
