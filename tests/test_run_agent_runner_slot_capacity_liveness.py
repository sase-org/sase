"""Runtime tests for runner-slot liveness and concurrent capacity admission."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core import agent_scan_source
from sase.core import process_identity
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.runner_slots._scan import record_liveness_probe
from sase.core.runner_slots import (
    live_runner_slot_waiters,
    runner_capacity_snapshot,
    running_agent_slot_count,
)

from tests._runner_slot_fixtures import artifact, record


@pytest.mark.parametrize(
    ("agent_meta", "running", "expected_identity"),
    [
        (
            {"pid": 99, "process_identity": "boot:99"},
            {"pid": 99},
            "boot:99",
        ),
        (
            {"pid": 99},
            {"pid": 99, "process_identity": "boot:100"},
            "boot:100",
        ),
    ],
)
def test_scanned_process_identity_reaches_runner_liveness_probe(
    tmp_path: Path,
    monkeypatch,
    agent_meta: dict[str, object],
    running: dict[str, object],
    expected_identity: str,
) -> None:
    payload = {
        "schema_version": 12,
        "projects_root": str(tmp_path),
        "records": [
            {
                "project_name": "proj",
                "project_dir": str(tmp_path / "proj"),
                "project_file": str(tmp_path / "proj/proj.sase"),
                "workflow_dir_name": "ace-run",
                "artifact_dir": str(tmp_path / "proj/ace-run/20260827120000"),
                "timestamp": "20260827120000",
                "agent_meta": agent_meta,
                "running": running,
            }
        ],
    }
    monkeypatch.setattr(
        agent_scan_source,
        "require_rust_binding",
        lambda _name: lambda _root, _options: payload,
    )
    scanned = agent_scan_source.scan_agent_artifacts(tmp_path)
    record = scanned.records[0]
    observed: dict[str, object] = {}
    probe = record_liveness_probe(
        is_alive=lambda meta, _path: observed.update(meta) or True
    )

    assert probe(record)
    assert observed["process_identity"] == expected_identity


def _write_proc_entry(
    root: Path,
    pid: int,
    *,
    boot_id: str = "boot-a",
    start_ticks: int = 123,
    tgid: int | None = None,
) -> None:
    (root / "sys/kernel/random").mkdir(parents=True, exist_ok=True)
    (root / "sys/kernel/random/boot_id").write_text(boot_id, encoding="utf-8")
    proc_dir = root / str(pid)
    proc_dir.mkdir(parents=True, exist_ok=True)
    stat_tail = ["S", *["0"] * 18, str(start_ticks)]
    (proc_dir / "stat").write_text(
        f"{pid} (python) {' '.join(stat_tail)}\n",
        encoding="utf-8",
    )
    (proc_dir / "status").write_text(
        "\n".join(
            (
                "Name:\tdconf worker",
                f"Tgid:\t{pid if tgid is None else tgid}",
                f"Pid:\t{pid}",
            )
        ),
        encoding="utf-8",
    )
    (proc_dir / "cmdline").write_bytes(b"/usr/bin/python3\0/usr/bin/blueman-applet\0")


def test_recycled_thread_pid_does_not_hold_runner_slot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    proc_root = tmp_path / "proc"
    live_paths: list[Path] = []
    max_running_agents = 10
    for index in range(max_running_agents - 1):
        pid = 2000 + index
        start_ticks = 5000 + index
        _write_proc_entry(proc_root, pid, start_ticks=start_ticks)
        live_paths.append(
            artifact(
                tmp_path,
                f"2026082712000{index}",
                pid,
                process_identity=f"boot-a:{start_ticks}",
            )
        )

    phantom = artifact(
        tmp_path,
        "20260827120100",
        17549,
        process_identity="old-boot:111",
    )
    _write_proc_entry(proc_root, 17549, start_ticks=9000, tgid=17441)

    waiter = artifact(
        tmp_path,
        "20260827120101",
        3000,
        process_identity="boot-a:7000",
    )
    _write_proc_entry(proc_root, 3000, start_ticks=7000)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "slot_requested_at": "2026-08-27T12:01:01+00:00",
                "wait_runners": max_running_agents,
            }
        ),
        encoding="utf-8",
    )

    records = [
        *(record(path, started=True) for path in live_paths),
        record(phantom, started=True),
        record(waiter),
    ]
    monkeypatch.setattr(process_identity, "_PROC_ROOT", proc_root)

    with patch("sase.ace.hooks.processes.is_process_running", return_value=True):
        is_live = run_agent_wait_slots._record_liveness_probe()
        running_count = running_agent_slot_count(records, is_live)
        queue = live_runner_slot_waiters(records, is_live)
        snapshot = runner_capacity_snapshot(
            records,
            is_live,
            effective_limit=float(max_running_agents),
        )

    assert running_count == max_running_agents - 1
    assert [entry.artifact_dir for entry in queue] == [str(waiter)]
    assert snapshot.get("first_eligible_artifact_dir") == str(waiter)


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
        assert marker["queue_capacity_explicit"] is False
        assert "wait_runners" not in marker
        assert "wait_runners_explicit" not in marker
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
        assert queued["queue_capacity"] == 0
        assert queued["queue_capacity_explicit"] is False
        assert "wait_runners" not in queued
        assert "wait_runners_explicit" not in queued

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
