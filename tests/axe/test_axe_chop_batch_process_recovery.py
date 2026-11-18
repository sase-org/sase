"""Fresh-process acceptance for chop-batch stop, cancellation, and replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.axe.chop_batch_process_harness import run_scenario


@pytest.mark.parametrize("k", [0, 2, 4])
def test_ordinary_restart_launches_only_remaining_members_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, k: int
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    result = run_scenario(tmp_path / "ordinary", f"ordinary-k-{k}")

    assert result["total"] == 4
    assert result["k"] == k
    assert result["remaining"] == 4 - k
    assert result["receipt_names"] == result["original_names"]
    assert result["batch_status"] == "complete"
    assert result["second_restart_new_launches"] == 0


@pytest.mark.parametrize("scenario", ["spawn-before-ack", "reserved-before-spawn"])
def test_sigkill_windows_reconcile_spawn_evidence_and_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / scenario, scenario)

    assert result["total"] == 4
    assert len(result["receipt_names"]) == 4
    assert len(set(result["receipt_names"])) == 4
    assert result["second_restart_new_launches"] == 0
    if scenario == "spawn-before-ack":
        assert result["spawned_before_stop"] == 1
    else:
        assert result["spawned_before_stop"] == 0


def test_sigterm_finishes_current_launch_then_pauses_before_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "sigterm", "sigterm-pause")

    assert result["k"] == 1
    assert result["remaining"] == 3
    assert result["receipt_names"] == result["original_names"]
    assert "interrupted" in result["notification_events"]
    assert "resumed" in result["notification_events"]
    assert result["notification_events"].count("interrupted") == 1
    assert result["notification_events"].count("resumed") == 1
    assert result["second_restart_new_launches"] == 0


def test_typed_sigterm_reopens_frozen_admission_in_fresh_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "typed", "typed-sigterm-pause")

    assert result["k"] == 1
    assert result["remaining"] == 3
    assert result["receipt_names"] == result["original_names"]
    assert result["batch_status"] == "complete"
    assert result["second_restart_new_launches"] == 0


@pytest.mark.parametrize("scenario", ["cancel-paused", "cancel-active"])
def test_cancelled_batch_never_revives_after_runtime_receipt_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / scenario, scenario)

    assert result["cancelled_batches"] == 1
    assert result["retained_status"] == "cancelled"
    assert result["launches_after_cleanup_restart"] == 0


def test_routine_tick_and_manual_run_race_single_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "race", "race")

    assert result["total"] == 4
    assert result["loser_kind"] == "blocked"
    assert result["receipt_names"] == result["original_names"]
    assert result["notification_events"].count("interrupted") == 1
    assert result["notification_events"].count("resumed") == 1
    assert result["second_restart_new_launches"] == 0


def test_clan_kill_while_recovery_active_settles_crossing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "cancel-during-recovery", "cancel-during-recovery")

    assert result["retained_status"] == "cancelled"
    assert result["settled_launches"] == 2
    assert "cancelled" in result["notification_events"]
    assert result["second_restart_new_launches"] == 0


def test_multi_clan_batch_cancelled_by_either_clan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "multi-clan", "multi-clan")

    assert result["cancelled_batches"] == 1
    assert result["retained_status"] == "cancelled"
    assert result["launches_after_restart"] == 0
    assert "cancelled" in result["notification_events"]


def test_two_interruptions_produce_two_notice_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "two-episodes", "two-episodes")

    assert result["total"] == 4
    assert result["receipt_names"] == result["original_names"]
    assert result["delivered_episodes"] == 2
    assert result["notification_events"].count("interrupted") == 2
    assert result["notification_events"].count("resumed") == 2
    assert result["second_restart_new_launches"] == 0


def test_typed_sigkill_before_ack_loses_no_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "typed-kill", "typed-kill")

    assert result["total"] == 4
    assert result["receipt_names"] == result["original_names"]
    assert result["batch_status"] == "complete"
    assert result["second_restart_new_launches"] == 0


def test_typed_clan_kill_after_pause_stays_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "typed-cancel-paused", "typed-cancel-paused")

    assert result["cancelled_batches"] == 1
    assert result["retained_status"] == "cancelled"
    assert result["settled_launches"] == 1
    assert "cancelled" in result["notification_events"]


def test_typed_first_run_wins_manual_recovery_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    result = run_scenario(tmp_path / "typed-race", "typed-race")

    assert result["total"] == 4
    assert result["loser_kind"] == "blocked"
    assert result["receipt_names"] == result["original_names"]
    assert result["notification_events"] == []
    assert result["second_restart_new_launches"] == 0


def test_manual_disposable_acceptance_demo_records_both_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.axe.chop_batch_process_harness import run_demo

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    evidence: dict[str, Any] = run_demo(tmp_path / "demo")

    recovery = evidence["manual_stop_resume"]
    assert recovery["total"] == 4
    assert recovery["spawned_before_stop"] == 1
    assert recovery["remaining_after_restart"] == 3
    assert recovery["second_restart_new_launches"] == 0
    assert recovery["run_identity"]
    assert recovery["clan_identity"]
    assert recovery["notifications"]
    recovery_events = {
        tag for item in recovery["notifications"] for tag in item["tags"]
    }
    assert {"interrupted", "resumed"}.issubset(recovery_events)
    assert "1 launched, 3 remaining" in recovery["log_tail"]
    assert "4 launched, 0 remaining" in recovery["log_tail"]

    cancellation = evidence["manual_clan_kill"]
    assert cancellation["cancelled_batches"] == 1
    assert cancellation["retained_status"] == "cancelled"
    assert cancellation["launches_after_cleanup_restart"] == 0
    assert any("cancelled" in item["tags"] for item in cancellation["notifications"])
