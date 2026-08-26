"""Gate-shell live-output streaming, pid recording, and log tailing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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


def test_gate_shell_output_tail_reads_back_the_newest_lines(artifacts_dir: str) -> None:
    for index in range(5):
        append_gate_shell_log_text(artifacts_dir, f"line {index}\n")

    assert gate_shell_output_tail(artifacts_dir, lines=2) == "line 3\nline 4\n"


def test_gate_shell_output_tail_is_empty_before_any_output(artifacts_dir: str) -> None:
    assert gate_shell_output_tail(artifacts_dir) == ""
