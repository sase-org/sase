"""Runtime tests for the global root-agent runner-slot gate."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots

from tests._runner_slot_fixtures import artifact


def test_uncontended_gate_claims_without_parking(tmp_path: Path) -> None:
    waiter = artifact(tmp_path, "20260712120000", 101)
    claims: list[str] = []
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.object(run_agent_wait_slots.time, "sleep") as sleep,
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started_at = run_agent_wait_slots.wait_for_runner_slot(
            str(waiter),
            "cl",
            waiter.name,
            {"pid": 101},
            wait_runners=None,
            claim=lambda: claims.append("claim") or "started",
        )

    assert started_at == "started"
    assert claims == ["claim"]
    assert not (waiter / "waiting.json").exists()
    scan.assert_called_once_with()
    sleep.assert_not_called()


def test_serial_child_agent_is_exempt_from_scanning_and_queueing(
    tmp_path: Path,
) -> None:
    child = artifact(tmp_path, "20260712120000", 101)
    with patch.object(run_agent_wait_slots, "_scan_runner_slot_records") as scan:
        started_at = run_agent_wait_slots.wait_for_runner_slot(
            str(child),
            "cl",
            child.name,
            {"pid": 101, "parent_timestamp": "20260712115959"},
            wait_runners=0,
            claim=lambda: "started",
        )

    assert started_at == "started"
    scan.assert_not_called()
    assert not (child / "waiting.json").exists()


def test_monitor_followup_agent_is_exempt_from_scanning_and_queueing(
    tmp_path: Path,
) -> None:
    followup = artifact(tmp_path, "20260812120000", 101)
    with patch.object(run_agent_wait_slots, "_scan_runner_slot_records") as scan:
        started_at = run_agent_wait_slots.wait_for_runner_slot(
            str(followup),
            "cl",
            followup.name,
            {
                "pid": 101,
                "parent_timestamp": "20260812115959",
                "agent_family": "watcher",
            },
            wait_runners=0,
            claim=lambda: "started",
        )

    assert started_at == "started"
    scan.assert_not_called()
    assert not (followup / "waiting.json").exists()


def test_parallel_family_member_participates_in_runner_admission(
    tmp_path: Path,
) -> None:
    child = artifact(tmp_path, "20260712120000", 101)
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started_at = run_agent_wait_slots.wait_for_runner_slot(
            str(child),
            "cl",
            child.name,
            {
                "pid": 101,
                "parent_timestamp": "20260712115959",
                "agent_family_parallel": True,
            },
            wait_runners=None,
            claim=lambda: "started",
        )

    assert started_at == "started"
    scan.assert_called_once_with()
    assert not (child / "waiting.json").exists()
