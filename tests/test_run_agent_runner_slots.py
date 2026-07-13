"""Runtime tests for the global root-agent runner-slot gate."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)


def _artifact(tmp_path: Path, name: str, pid: int) -> Path:
    path = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / name
    path.mkdir(parents=True)
    (path / "agent_meta.json").write_text(json.dumps({"pid": pid}))
    return path


def _record(path: Path, *, started: bool = False) -> AgentArtifactRecordWire:
    waiting_path = path / "waiting.json"
    waiting_data = (
        json.loads(waiting_path.read_text()) if waiting_path.exists() else None
    )
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(path.parents[3]),
        project_file=str(path.parents[3] / "proj.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(path),
        timestamp=path.name,
        agent_meta=AgentMetaWire(
            pid=int(json.loads((path / "agent_meta.json").read_text())["pid"]),
            run_started_at=("2026-07-12T12:00:00+00:00" if started else None),
        ),
        waiting=(
            WaitingMarkerWire(
                waiting_for=list(waiting_data.get("waiting_for") or []),
                wait_runners=waiting_data.get("wait_runners"),
                wait_runners_explicit=bool(
                    waiting_data.get("wait_runners_explicit", False)
                ),
                slot_requested_at=waiting_data.get("slot_requested_at"),
            )
            if waiting_data is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=True),
    )


def test_uncontended_gate_claims_without_parking(tmp_path: Path) -> None:
    waiter = _artifact(tmp_path, "20260712120000", 101)
    claims: list[str] = []
    with (
        patch.object(
            run_agent_wait, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.object(run_agent_wait.time, "sleep") as sleep,
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started_at = run_agent_wait.wait_for_runner_slot(
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


def test_live_config_raise_releases_queued_agent(tmp_path: Path) -> None:
    running = _artifact(tmp_path, "20260712120000", 100)
    waiter = _artifact(tmp_path, "20260712120001", 101)
    config_cap = 1
    started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [_record(running, started=True), _record(waiter, started=started)]

    def claim() -> str:
        nonlocal started
        started = True
        return "started"

    with (
        patch.object(run_agent_wait, "_scan_runner_slot_records", side_effect=scan),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait,
            "get_max_running_agents",
            side_effect=lambda: config_cap,
        ),
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=claim,
        )
        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["wait_runners"] == 0
        assert marker["wait_runners_explicit"] is False

        config_cap = 2
        second, parked = run_agent_wait._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=claim,
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_parked_marker_edit_overrides_original_directive(tmp_path: Path) -> None:
    running = [
        _artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(2)
    ]
    waiter = _artifact(tmp_path, "20260712120002", 102)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 2,
                "wait_runners_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:02+00:00",
            }
        )
    )

    with (
        patch.object(
            run_agent_wait,
            "_scan_runner_slot_records",
            return_value=[
                *[_record(path, started=True) for path in running],
                _record(waiter),
            ],
        ),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(run_agent_wait, "get_max_running_agents") as get_config,
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=0,
            claim=lambda: "started",
        )

    assert result == "started"
    assert not parked
    get_config.assert_not_called()


def test_concurrent_claimants_cannot_overshoot_threshold(tmp_path: Path) -> None:
    waiters = [
        _artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(4)
    ]
    started: set[str] = set()
    start_barrier = threading.Barrier(len(waiters))
    results: list[tuple[str | None, bool]] = []
    result_lock = threading.Lock()

    def scan() -> list[AgentArtifactRecordWire]:
        return [_record(path, started=str(path) in started) for path in waiters]

    def contend(path: Path) -> None:
        start_barrier.wait()

        def claim() -> str:
            started.add(str(path))
            return str(path)

        result = run_agent_wait._try_claim_runner_slot(
            artifacts_dir=str(path),
            cl_name="cl",
            timestamp=path.name,
            directive_threshold=0,
            claim=claim,
        )
        with result_lock:
            results.append(result)

    with (
        patch.object(run_agent_wait, "_scan_runner_slot_records", side_effect=scan),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait,
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


def test_child_agent_is_exempt_from_scanning_and_queueing(tmp_path: Path) -> None:
    child = _artifact(tmp_path, "20260712120000", 101)
    with patch.object(run_agent_wait, "_scan_runner_slot_records") as scan:
        started_at = run_agent_wait.wait_for_runner_slot(
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
