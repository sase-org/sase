"""Runtime tests for runner-slot monitor occupancy and no-parking claims."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_wire import AgentArtifactRecordWire

from tests._runner_slot_fixtures import artifact, record


def test_running_monitor_occupying_last_slot_parks_new_launch(tmp_path: Path) -> None:
    monitor = artifact(
        tmp_path,
        "20260812120000",
        500,
        agent_family_role="monitor",
        monitor_id="mon-1",
    )
    newcomer = artifact(tmp_path, "20260812120001", 501)

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(monitor), record(newcomer)]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(newcomer),
            cl_name="cl",
            timestamp=newcomer.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert result is None
    assert parked
    marker = json.loads((newcomer / "waiting.json").read_text())
    assert marker["slot_requested_at"]


def test_releasing_monitor_admits_the_parked_waiter(tmp_path: Path) -> None:
    monitor = artifact(
        tmp_path,
        "20260812120000",
        500,
        agent_family_role="monitor",
        monitor_id="mon-1",
    )
    waiter = artifact(tmp_path, "20260812120001", 501)
    monitor_alive = True

    def scan() -> list[AgentArtifactRecordWire]:
        records = [record(waiter)]
        if monitor_alive:
            records.insert(0, record(monitor))
        return records

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )
        assert first is None
        assert parked

        monitor_alive = False
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_blocked_claim_without_parking_leaves_no_waiting_marker(
    tmp_path: Path,
) -> None:
    running = artifact(tmp_path, "20260910121000", 100, queue_weight=1.0)
    blocked = artifact(
        tmp_path,
        "20260910121001",
        101,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    leftover = {
        "cl_name": "stale",
        "timestamp": blocked.name,
        "queue_capacity": 0,
        "queue_capacity_explicit": False,
        "slot_requested_at": "2026-09-10T12:10:01+00:00",
    }
    (blocked / "waiting.json").write_text(json.dumps(leftover), encoding="utf-8")

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(blocked)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(blocked),
            cl_name="cl",
            timestamp=blocked.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
            park_on_block=False,
        )

    assert result is None
    assert not parked
    assert not (blocked / "waiting.json").exists()
    meta = json.loads((blocked / "agent_meta.json").read_text())
    assert "runner_claim_owner_key" not in meta


def test_unavailable_limit_without_parking_leaves_no_waiting_marker(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260910121002", 102)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=RuntimeError("limit unavailable"),
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "unexpected",
            park_on_block=False,
        )

    assert result is None
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_try_claim_without_parking_still_acquires_when_capacity_is_free(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260910121003", 103)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started = run_agent_wait_slots.try_claim_runner_slot_without_parking(
            str(waiter),
            "cl",
            waiter.name,
            {"pid": 103},
            wait_runners=None,
            claim=lambda: "started",
        )

    assert started == "started"
    assert not (waiter / "waiting.json").exists()
    meta = json.loads((waiter / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == waiter.name
