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
    PendingQuestionMarkerWire,
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
                wait_priority=waiting_data.get("wait_priority"),
                slot_requested_at=waiting_data.get("slot_requested_at"),
            )
            if waiting_data is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=True),
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if (path / "pending_question.json").exists()
            else None
        ),
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
            directive_priority=7,
            claim=claim,
        )
        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["wait_runners"] == 0
        assert marker["wait_runners_explicit"] is False
        assert marker["wait_priority"] == 7

        config_cap = 2
        second, parked = run_agent_wait._try_claim_runner_slot(
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


def test_implicit_gate_fails_closed_when_effective_limit_is_unavailable(
    tmp_path: Path,
) -> None:
    waiter = _artifact(tmp_path, "20260712120001", 101)
    claims: list[str] = []
    with (
        patch.object(
            run_agent_wait,
            "get_max_running_agents",
            side_effect=[TimeoutError("override lock busy"), 2],
        ),
        patch.object(
            run_agent_wait, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
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
            claim=lambda: claims.append("claim") or "started",
        )
        marker = json.loads((waiter / "waiting.json").read_text())
        assert first is None
        assert parked is True
        assert marker["wait_runners_explicit"] is False
        assert marker["runner_limit_unavailable"] == "override lock busy"
        scan.assert_not_called()

        second, parked = run_agent_wait._try_claim_runner_slot(
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


def test_repeated_slot_polls_preserve_foreign_waiting_marker_fields(
    tmp_path: Path,
) -> None:
    running = [
        _artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(2)
    ]
    waiter = _artifact(tmp_path, "20260712120002", 102)
    requested_at = "2026-07-12T12:00:02+00:00"
    foreign_fields = {
        "waiting_for": ["upstream"],
        "wait_for_artifacts": [{"artifact_dir": "/upstream"}],
        "wait_for_beads": ["sase-87.2"],
        "wait_duration": 300.0,
        "wait_until": "2026-07-12T13:00:00Z",
        "resolved_deps": ["finished"],
        "extension": {"owner": "another-waiter"},
    }
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                **foreign_fields,
                "cl_name": "stale",
                "timestamp": "stale",
                "wait_runners": 99,
                "wait_runners_explicit": False,
                "wait_priority": -1,
                "slot_requested_at": requested_at,
            }
        )
    )

    with (
        patch.object(
            run_agent_wait,
            "_scan_runner_slot_records",
            side_effect=lambda: [
                *[_record(path, started=True) for path in running],
                _record(waiter),
            ],
        ),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait,
            "get_max_running_agents",
            side_effect=[2, 1],
        ),
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        for expected_threshold in (1, 0):
            claimed, parked = run_agent_wait._try_claim_runner_slot(
                artifacts_dir=str(waiter),
                cl_name="fresh-cl",
                timestamp=waiter.name,
                directive_threshold=None,
                directive_priority=4,
                claim=lambda: "unexpected",
            )

            assert claimed is None
            assert parked is False
            marker = json.loads((waiter / "waiting.json").read_text())
            for key, value in foreign_fields.items():
                assert marker[key] == value
            assert marker["cl_name"] == "fresh-cl"
            assert marker["timestamp"] == waiter.name
            assert marker["wait_runners"] == expected_threshold
            assert marker["wait_runners_explicit"] is False
            assert marker["wait_priority"] == 4
            assert marker["slot_requested_at"] == requested_at


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


def test_parked_priority_edit_overrides_original_directive(tmp_path: Path) -> None:
    waiter = _artifact(tmp_path, "20260712120001", 101)
    competitor = _artifact(tmp_path, "20260712120002", 102)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 1,
                "slot_requested_at": "2026-07-12T12:00:01+00:00",
            }
        )
    )
    (competitor / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": competitor.name,
                "wait_runners": 9,
                "wait_runners_explicit": True,
                "wait_priority": 5,
                "slot_requested_at": "2026-07-12T12:00:00+00:00",
            }
        )
    )

    with (
        patch.object(
            run_agent_wait,
            "_scan_runner_slot_records",
            return_value=[_record(waiter), _record(competitor)],
        ),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
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
            directive_threshold=9,
            directive_priority=20,
            claim=lambda: "started",
        )

    assert result == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_marker_priority_resolution_rejects_boolean_and_invalid_values() -> None:
    assert run_agent_wait._marker_priority(None, None) == 10
    assert run_agent_wait._marker_priority({"slot_requested_at": "now"}, 3) == 3
    assert (
        run_agent_wait._marker_priority(
            {"slot_requested_at": "now", "wait_priority": True},
            None,
        )
        == 10
    )
    assert (
        run_agent_wait._marker_priority(
            {"slot_requested_at": "now", "wait_priority": -1},
            4,
        )
        == 4
    )


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


def test_serial_child_agent_is_exempt_from_scanning_and_queueing(
    tmp_path: Path,
) -> None:
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


def test_parallel_family_member_participates_in_runner_admission(
    tmp_path: Path,
) -> None:
    child = _artifact(tmp_path, "20260712120000", 101)
    with (
        patch.object(
            run_agent_wait, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started_at = run_agent_wait.wait_for_runner_slot(
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


def test_answered_root_reacquires_after_yield_without_oversubscribing(
    tmp_path: Path,
) -> None:
    paused = _artifact(tmp_path, "20260712120000", 100)
    newcomer = _artifact(tmp_path, "20260712120001", 101)
    (paused / "pending_question.json").write_text(
        json.dumps({"session_id": "question"})
    )
    newcomer_started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [
            _record(paused, started=True),
            _record(newcomer, started=newcomer_started),
        ]

    with (
        patch.object(run_agent_wait, "_scan_runner_slot_records", side_effect=scan),
        patch.object(run_agent_wait, "is_process_alive", return_value=True),
        patch.object(run_agent_wait, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        admitted, parked = run_agent_wait._try_claim_runner_slot(
            artifacts_dir=str(newcomer),
            cl_name="cl",
            timestamp=newcomer.name,
            directive_threshold=None,
            claim=lambda: "newcomer-started",
        )
        assert admitted == "newcomer-started"
        assert not parked
        newcomer_started = True

        resumed, parked = run_agent_wait._try_claim_runner_slot(
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

        resumed, parked = run_agent_wait._try_claim_runner_slot(
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
