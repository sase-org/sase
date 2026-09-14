"""Gate-shell live-output streaming, pid recording, and log tailing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.axe import run_agent_wait_slots
from sase.gate_shell.log import (
    _append_gate_shell_log_text as append_gate_shell_log_text,
    _gate_shell_log_path as gate_shell_log_path,
    bind_gate_shell_execution_callbacks,
    gate_shell_output_tail,
)


@pytest.fixture()
def artifacts_dir(tmp_path: Path) -> str:
    directory = tmp_path / "member"
    directory.mkdir()
    (directory / "agent_meta.json").write_text(json.dumps({"name": "lane--gate"}))
    return str(directory)


def test_append_gate_shell_log_text_appends_bounded(artifacts_dir: str) -> None:
    append_gate_shell_log_text(artifacts_dir, "$ commands/cleanup\n")
    append_gate_shell_log_text(artifacts_dir, "line one\n")
    append_gate_shell_log_text(artifacts_dir, "")

    text = gate_shell_log_path(artifacts_dir).read_text(encoding="utf-8")
    assert text == "$ commands/cleanup\nline one\n"


def test_bind_execution_callbacks_streams_command_header_and_lines(
    artifacts_dir: str,
) -> None:
    callbacks = bind_gate_shell_execution_callbacks(artifacts_dir)
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))
    callbacks.on_output_line("option", "cleanup", "stdout", "deleted 3 files")
    callbacks.on_output_line("option", "cleanup", "stderr", "warning: slow disk")

    text = gate_shell_log_path(artifacts_dir).read_text(encoding="utf-8")
    assert text == ("$ commands/cleanup\ndeleted 3 files\n! warning: slow disk\n")


def test_bind_execution_callbacks_records_the_running_pid(artifacts_dir: str) -> None:
    callbacks = bind_gate_shell_execution_callbacks(artifacts_dir)
    process = subprocess.Popen(["true"])
    try:
        callbacks.on_process_state(process, True)
        meta = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
        assert meta["pid"] == process.pid
    finally:
        process.wait()

    # A stop notification must not clobber the recorded pid.
    callbacks.on_process_state(process, False)
    meta = json.loads(
        (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["pid"] == process.pid


def _pending_gate_dir(tmp_path: Path, *, name: str = "member") -> Path:
    directory = tmp_path / name
    directory.mkdir()
    (directory / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "lane--gate",
                "agent_family": "lane",
                "agent_family_role": "gate",
                "parent_timestamp": "20260910120000",
                "gate_id": "gate-1",
                "gate_kind": "custom",
                "gate_state": "pending",
                "queue_weight": 2.0,
                "queue_weight_explicit": False,
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_bind_execution_callbacks_claims_gate_capacity_before_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _pending_gate_dir(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_try_claim(
        artifacts_dir: str,
        cl_name: str,
        timestamp: str,
        agent_meta: dict[str, object],
        *,
        wait_runners: int | None,
        wait_priority: int | None,
        queue_weight: float,
        queue_weight_explicit: bool,
        claim,
    ) -> str:
        calls.append(
            {
                "artifacts_dir": artifacts_dir,
                "cl_name": cl_name,
                "timestamp": timestamp,
                "gate_state": agent_meta["gate_state"],
                "wait_runners": wait_runners,
                "wait_priority": wait_priority,
                "queue_weight": queue_weight,
                "queue_weight_explicit": queue_weight_explicit,
            }
        )
        return claim()

    monkeypatch.setattr(
        run_agent_wait_slots,
        "try_claim_runner_slot_without_parking",
        fake_try_claim,
    )
    monkeypatch.setattr(
        run_agent_wait_slots,
        "wait_for_runner_slot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gate execution must not wait for a runner slot")
        ),
    )

    callbacks = bind_gate_shell_execution_callbacks(str(directory))
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))

    meta = json.loads((directory / "agent_meta.json").read_text(encoding="utf-8"))
    assert calls == [
        {
            "artifacts_dir": str(directory),
            "cl_name": "lane--gate",
            "timestamp": "member",
            "gate_state": "pending",
            "wait_runners": None,
            "wait_priority": None,
            "queue_weight": 2.0,
            "queue_weight_explicit": False,
        }
    ]
    assert meta["gate_state"] == "settling"
    assert meta["run_started_at"]
    assert isinstance(meta["pid"], int)
    assert not (directory / "waiting.json").exists()
    assert gate_shell_log_path(str(directory)).read_text(encoding="utf-8") == (
        "$ commands/cleanup\n"
    )


def test_bind_execution_callbacks_proceeds_unclaimed_when_capacity_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _pending_gate_dir(tmp_path)
    calls: list[dict[str, object]] = []

    def fake_try_claim(
        artifacts_dir: str,
        cl_name: str,
        timestamp: str,
        agent_meta: dict[str, object],
        *,
        wait_runners: int | None,
        wait_priority: int | None,
        queue_weight: float,
        queue_weight_explicit: bool,
        claim,
    ) -> None:
        assert wait_runners is None
        assert wait_priority is None
        assert queue_weight_explicit is False
        assert callable(claim)
        calls.append(
            {
                "artifacts_dir": artifacts_dir,
                "cl_name": cl_name,
                "timestamp": timestamp,
                "gate_state": agent_meta["gate_state"],
                "queue_weight": queue_weight,
            }
        )

    monkeypatch.setattr(
        run_agent_wait_slots,
        "try_claim_runner_slot_without_parking",
        fake_try_claim,
    )
    monkeypatch.setattr(
        run_agent_wait_slots,
        "wait_for_runner_slot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gate execution must not wait for a runner slot")
        ),
    )

    callbacks = bind_gate_shell_execution_callbacks(str(directory))
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))

    meta = json.loads((directory / "agent_meta.json").read_text(encoding="utf-8"))
    assert calls == [
        {
            "artifacts_dir": str(directory),
            "cl_name": "lane--gate",
            "timestamp": "member",
            "gate_state": "pending",
            "queue_weight": 2.0,
        }
    ]
    assert meta["gate_state"] == "pending"
    assert "run_started_at" not in meta
    assert "runner_claim_owner_key" not in meta
    assert isinstance(meta["pid"], int)
    assert not (directory / "waiting.json").exists()
    assert gate_shell_log_path(str(directory)).read_text(encoding="utf-8") == (
        "$ commands/cleanup\n"
    )


def test_unclaimed_execution_still_records_the_running_command_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _pending_gate_dir(tmp_path)

    monkeypatch.setattr(
        run_agent_wait_slots,
        "try_claim_runner_slot_without_parking",
        lambda *_args, **_kwargs: None,
    )

    callbacks = bind_gate_shell_execution_callbacks(str(directory))
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))
    process = subprocess.Popen(["true"])
    try:
        callbacks.on_process_state(process, True)
        meta = json.loads((directory / "agent_meta.json").read_text(encoding="utf-8"))
        assert meta["pid"] == process.pid
        assert meta["gate_state"] == "pending"
    finally:
        process.wait()


def _patch_real_claim_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    records: list[object],
    *,
    cap: int,
) -> None:
    from sase.axe import run_agent_wait_markers

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        run_agent_wait_slots,
        "_scan_runner_slot_records",
        lambda: list(records),
    )
    monkeypatch.setattr(
        run_agent_wait_slots, "is_process_alive", lambda *_a, **_k: True
    )
    monkeypatch.setattr(run_agent_wait_slots, "get_max_running_agents", lambda: cap)
    monkeypatch.setattr(
        run_agent_wait_markers,
        "update_agent_artifact_index_for_marker_mutation",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        run_agent_wait_slots,
        "wait_for_runner_slot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("gate execution must not wait for a runner slot")
        ),
    )


def test_bind_execution_callbacks_real_claim_proceeds_unclaimed_at_full_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._runner_slot_fixtures import artifact, record

    directory = _pending_gate_dir(tmp_path)
    running = artifact(tmp_path, "20260910120000", 100, queue_weight=1.0)
    _patch_real_claim_scan(
        monkeypatch,
        tmp_path,
        [record(running, started=True)],
        cap=1,
    )

    callbacks = bind_gate_shell_execution_callbacks(str(directory))
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))

    meta = json.loads((directory / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["gate_state"] == "pending"
    assert "run_started_at" not in meta
    assert "runner_claim_owner_key" not in meta
    assert isinstance(meta["pid"], int)
    assert not (directory / "waiting.json").exists()


def test_bind_execution_callbacks_real_claim_publishes_ownership_when_capacity_is_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _pending_gate_dir(tmp_path)
    _patch_real_claim_scan(monkeypatch, tmp_path, [], cap=2)

    callbacks = bind_gate_shell_execution_callbacks(str(directory))
    callbacks.on_command_start("option", "cleanup", "Cleanup", ("commands/cleanup",))

    meta = json.loads((directory / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["gate_state"] == "settling"
    assert meta["run_started_at"]
    assert isinstance(meta.get("runner_claim_owner_key"), str)
    assert meta["runner_claim_owner_key"]
    assert not (directory / "waiting.json").exists()


def test_gate_shell_output_tail_reads_back_the_newest_lines(artifacts_dir: str) -> None:
    for index in range(5):
        append_gate_shell_log_text(artifacts_dir, f"line {index}\n")

    assert gate_shell_output_tail(artifacts_dir, lines=2) == "line 3\nline 4\n"


def test_gate_shell_output_tail_is_empty_before_any_output(artifacts_dir: str) -> None:
    assert gate_shell_output_tail(artifacts_dir) == ""
