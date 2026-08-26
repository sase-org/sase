"""Bounded live-output log for a gate shell's approved command execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.axe.run_agent_helpers_artifacts import update_meta_field
from sase.logs._bounded import DEFAULT_MAX_BYTES, append_bytes_locked, log_file_lock

GATE_SHELL_LOG_FILENAME = "gate.log"


def _gate_shell_log_path(artifacts_dir: str) -> Path:
    """Return the live-output log path for a gate shell's artifacts dir."""
    return Path(artifacts_dir) / GATE_SHELL_LOG_FILENAME


def _append_gate_shell_log_text(artifacts_dir: str, text: str) -> None:
    """Append *text* to a gate shell's bounded live-output log.

    Producers that already own their output in memory flush through this
    shared bounded-log primitive, the same pattern the proc store's own
    ``append_proc_log_text`` uses.
    """
    if not text:
        return
    path = _gate_shell_log_path(artifacts_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_file_lock(path):
        append_bytes_locked(
            path,
            text.encode("utf-8"),
            max_bytes=DEFAULT_MAX_BYTES,
            truncate_oversized=True,
        )


@dataclass(frozen=True)
class _GateShellExecutionCallbacks:
    """The three ``execute_gate_selection`` callbacks bound to one gate shell."""

    on_command_start: Callable[[str, str, str, tuple[str, ...]], None]
    on_output_line: Callable[[str, str, str, str], None]
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None]

    def as_kwargs(self) -> dict[str, Callable[..., None]]:
        """Return this binding as ``execute_gate_selection`` keyword arguments."""
        return {
            "on_command_start": self.on_command_start,
            "on_output_line": self.on_output_line,
            "on_process_state": self.on_process_state,
        }


def bind_gate_shell_execution_callbacks(
    artifacts_dir: str,
) -> _GateShellExecutionCallbacks:
    """Bind gate.log streaming and pid recording for one gate shell's execution.

    ``on_command_start`` writes a ``$ commands/cleanup``-style header so an AND
    branch's multiple commands read as one attributable stream;
    ``on_output_line`` appends each line, tagging stderr; ``on_process_state``
    records the running command's pid so ``sase gate`` can report and
    interrupt a runaway approved command.
    """

    def on_command_start(
        _scope: str, _target_id: str, _label: str, argv: tuple[str, ...]
    ) -> None:
        _append_gate_shell_log_text(artifacts_dir, f"$ {argv[0]}\n")

    def on_output_line(_scope: str, _target_id: str, stream: str, line: str) -> None:
        prefix = "! " if stream == "stderr" else ""
        _append_gate_shell_log_text(artifacts_dir, f"{prefix}{line}\n")

    def on_process_state(process: subprocess.Popen[bytes], started: bool) -> None:
        if started:
            update_meta_field(artifacts_dir, "pid", process.pid)

    return _GateShellExecutionCallbacks(
        on_command_start=on_command_start,
        on_output_line=on_output_line,
        on_process_state=on_process_state,
    )


def gate_shell_output_tail(artifacts_dir: str, *, lines: int = 200) -> str:
    """Return the newest retained lines of a gate shell's live-output log."""
    from sase.axe.state import read_tail_seek

    return read_tail_seek(_gate_shell_log_path(artifacts_dir), lines)


__all__ = [
    "GATE_SHELL_LOG_FILENAME",
    "bind_gate_shell_execution_callbacks",
    "gate_shell_output_tail",
]
