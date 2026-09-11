"""Runtime tests for runner-slot capacity limits and queue admission."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_wire import AgentArtifactRecordWire

from tests._runner_slot_fixtures import artifact, record


def test_live_config_raise_releases_queued_agent(tmp_path: Path) -> None:
    running = artifact(tmp_path, "20260712120000", 100)
    waiter = artifact(tmp_path, "20260712120001", 101)
    config_cap = 1
    started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(running, started=True), record(waiter, started=started)]

    def claim() -> str:
        nonlocal started
        started = True
        return "started"

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=lambda: config_cap,
        ),
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
            directive_priority=7,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=claim,
        )
        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["wait_runners"] == 0
        assert marker["wait_runners_explicit"] is False
        assert marker["wait_priority"] == 7
        assert marker["wait_priority_explicit"] is True
        assert marker["queue_weight"] == 0.25
        assert marker["queue_weight_explicit"] is True

        config_cap = 2
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            directive_priority=7,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=False,
            claim=claim,
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_fractional_agents_fill_capacity_exactly_and_block_next(
    tmp_path: Path,
) -> None:
    agents = [
        artifact(
            tmp_path,
            f"2026091012000{index}",
            100 + index,
            queue_weight=0.25,
            queue_weight_explicit=True,
        )
        for index in range(5)
    ]
    started: set[str] = set()

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(path, started=str(path) in started) for path in agents]

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
        for path in agents[:4]:
            result, parked = run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(path),
                cl_name="cl",
                timestamp=path.name,
                directive_threshold=None,
                directive_queue_weight=0.25,
                directive_queue_weight_explicit=True,
                claim=lambda path=path: started.add(str(path)) or "started",
            )
            assert result == "started"
            assert not parked

        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(agents[4]),
            cl_name="cl",
            timestamp=agents[4].name,
            directive_threshold=None,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    assert len(started) == 4
    marker = json.loads((agents[4] / "waiting.json").read_text())
    assert marker["queue_weight"] == 0.25
    assert marker["wait_runners_explicit"] is False


def test_heavy_weight_cannot_start_with_only_one_unit_free(tmp_path: Path) -> None:
    running = artifact(tmp_path, "20260910121000", 100, queue_weight=1.0)
    heavy = artifact(
        tmp_path,
        "20260910121001",
        101,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(heavy)],
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
            artifacts_dir=str(heavy),
            cl_name="cl",
            timestamp=heavy.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    marker = json.loads((heavy / "waiting.json").read_text())
    assert marker["queue_weight"] == 2.0
    assert marker["wait_runners_explicit"] is False


def test_high_explicit_runner_condition_cannot_bypass_capacity(
    tmp_path: Path,
) -> None:
    running = artifact(tmp_path, "20260910122000", 100)
    waiter = artifact(tmp_path, "20260910122001", 101)

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(waiter)],
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
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=99,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    marker = json.loads((waiter / "waiting.json").read_text())
    assert marker["wait_runners"] == 99
    assert marker["wait_runners_explicit"] is True
    assert marker["queue_weight"] == 0.25


def test_lighter_waiter_can_pass_non_fitting_heavy_waiter(
    tmp_path: Path,
) -> None:
    occupied = artifact(tmp_path, "20260910123000", 100, queue_weight=0.75)
    heavy = artifact(
        tmp_path,
        "20260910123001",
        101,
        queue_weight=0.5,
        queue_weight_explicit=True,
    )
    light = artifact(
        tmp_path,
        "20260910123002",
        102,
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    light_started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [
            record(occupied, started=True),
            record(heavy),
            record(light, started=light_started),
        ]

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
        heavy_result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(heavy),
            cl_name="cl",
            timestamp=heavy.name,
            directive_threshold=None,
            directive_queue_weight=0.5,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )
        assert heavy_result is None
        assert parked

        light_result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(light),
            cl_name="cl",
            timestamp=light.name,
            directive_threshold=None,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "started",
        )

    assert light_result == "started"
    assert not parked
    assert (heavy / "waiting.json").exists()
    assert not (light / "waiting.json").exists()


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
