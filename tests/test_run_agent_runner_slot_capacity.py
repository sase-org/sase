"""Runtime tests for runner-slot capacity limits and contention."""

from __future__ import annotations

import json
import threading
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
            claim=claim,
        )
        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["wait_runners"] == 0
        assert marker["wait_runners_explicit"] is False
        assert marker["wait_priority"] == 7
        assert marker["wait_priority_explicit"] is True

        config_cap = 2
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            directive_priority=7,
            claim=claim,
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


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


def test_implicit_gate_fails_closed_when_effective_limit_is_unavailable(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260712120001", 101)
    claims: list[str] = []
    with (
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=[TimeoutError("override lock busy"), 2],
        ),
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
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: claims.append("claim") or "started",
        )
        marker = json.loads((waiter / "waiting.json").read_text())
        assert first is None
        assert parked is True
        assert marker["wait_runners_explicit"] is False
        assert marker["wait_priority_explicit"] is False
        assert marker["runner_limit_unavailable"] == "override lock busy"
        scan.assert_not_called()

        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: claims.append("claim") or "started",
        )

    assert second == "started"
    assert parked is False
    assert claims == ["claim"]
    assert not (waiter / "waiting.json").exists()


def test_concurrent_claimants_cannot_overshoot_threshold(tmp_path: Path) -> None:
    waiters = [
        artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(4)
    ]
    started: set[str] = set()
    start_barrier = threading.Barrier(len(waiters))
    results: list[tuple[str | None, bool]] = []
    result_lock = threading.Lock()

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(path, started=str(path) in started) for path in waiters]

    def contend(path: Path) -> None:
        start_barrier.wait()

        def claim() -> str:
            started.add(str(path))
            return str(path)

        result = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(path),
            cl_name="cl",
            timestamp=path.name,
            directive_threshold=0,
            claim=claim,
        )
        with result_lock:
            results.append(result)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        threads = [threading.Thread(target=contend, args=(path,)) for path in waiters]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert len(started) == 1
    assert sum(result is not None for result, _parked in results) == 1
    assert sum(parked for _result, parked in results) == 3


def test_answered_root_reacquires_after_yield_without_oversubscribing(
    tmp_path: Path,
) -> None:
    paused = artifact(tmp_path, "20260712120000", 100)
    newcomer = artifact(tmp_path, "20260712120001", 101)
    (paused / "pending_question.json").write_text(
        json.dumps({"session_id": "question"})
    )
    newcomer_started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [
            record(paused, started=True),
            record(newcomer, started=newcomer_started),
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
        admitted, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(newcomer),
            cl_name="cl",
            timestamp=newcomer.name,
            directive_threshold=None,
            claim=lambda: "newcomer-started",
        )
        assert admitted == "newcomer-started"
        assert not parked
        newcomer_started = True

        resumed, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(paused),
            cl_name="cl",
            timestamp=paused.name,
            directive_threshold=None,
            claim=lambda: "resumed",
        )
        assert resumed is None
        assert parked
        assert (paused / "pending_question.json").exists()
        queued = json.loads((paused / "waiting.json").read_text())
        assert queued["wait_runners"] == 0
        assert queued["wait_runners_explicit"] is False

        newcomer_started = False

        def claim_resume() -> str:
            (paused / "pending_question.json").unlink()
            return "resumed"

        resumed, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(paused),
            cl_name="cl",
            timestamp=paused.name,
            directive_threshold=None,
            claim=claim_resume,
        )

    assert resumed == "resumed"
    assert not parked
    assert not (paused / "pending_question.json").exists()
    assert not (paused / "waiting.json").exists()
