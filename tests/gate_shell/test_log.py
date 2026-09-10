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


def test_bind_execution_callbacks_claims_gate_capacity_before_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "member"
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
    calls: list[dict[str, object]] = []

    def fake_wait_for_runner_slot(
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
        "wait_for_runner_slot",
        fake_wait_for_runner_slot,
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
    assert gate_shell_log_path(str(directory)).read_text(encoding="utf-8") == (
        "$ commands/cleanup\n"
    )


def test_gate_shell_output_tail_reads_back_the_newest_lines(artifacts_dir: str) -> None:
    for index in range(5):
        append_gate_shell_log_text(artifacts_dir, f"line {index}\n")

    assert gate_shell_output_tail(artifacts_dir, lines=2) == "line 3\nline 4\n"


def test_gate_shell_output_tail_is_empty_before_any_output(artifacts_dir: str) -> None:
    assert gate_shell_output_tail(artifacts_dir) == ""
