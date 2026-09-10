"""Bounded live-output log for a gate shell's approved command execution."""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
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


def append_gate_shell_log_text(artifacts_dir: str, text: str) -> None:
    """Append text to a gate shell's bounded live-output log."""

    _append_gate_shell_log_text(artifacts_dir, text)


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
        _claim_gate_shell_execution_capacity(artifacts_dir)
        _append_gate_shell_log_text(artifacts_dir, f"$ {argv[0]}\n")

    def on_output_line(_scope: str, _target_id: str, stream: str, line: str) -> None:
        prefix = "! " if stream == "stderr" else ""
        _append_gate_shell_log_text(artifacts_dir, f"{prefix}{line}\n")

    def on_process_state(process: subprocess.Popen[bytes], started: bool) -> None:
        if started:
            from sase.core.process_identity import process_identity_token

            update_meta_fields(
                artifacts_dir,
                {
                    "pid": process.pid,
                    "process_identity": process_identity_token(process.pid),
                },
            )

    return _GateShellExecutionCallbacks(
        on_command_start=on_command_start,
        on_output_line=on_output_line,
        on_process_state=on_process_state,
    )


def _read_gate_shell_meta(artifacts_dir: str) -> dict[str, Any]:
    try:
        with open(
            Path(artifacts_dir) / "agent_meta.json",
            encoding="utf-8",
        ) as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _positive_finite_weight(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight <= 0:
        return None
    return weight


def _gate_shell_queue_weight(meta: dict[str, Any]) -> float:
    if meta.get("queue_weight_invalid") is True:
        raise RuntimeError(
            "Invalid queue_weight in gate shell metadata: expected a positive "
            f"finite number, got {meta.get('queue_weight')!r}."
        )
    if "queue_weight" not in meta:
        return 1.0
    queue_weight = _positive_finite_weight(meta.get("queue_weight"))
    if queue_weight is None:
        raise RuntimeError(
            "Invalid queue_weight in gate shell metadata: expected a positive "
            f"finite number, got {meta.get('queue_weight')!r}."
        )
    return queue_weight


def _is_real_pending_gate_shell(meta: dict[str, Any]) -> bool:
    return (
        meta.get("agent_family_role") == "gate"
        and isinstance(meta.get("gate_id"), str)
        and bool(str(meta.get("gate_id") or "").strip())
        and meta.get("gate_state") == "pending"
    )


def _claim_gate_shell_execution_capacity(artifacts_dir: str) -> None:
    meta = _read_gate_shell_meta(artifacts_dir)
    if not _is_real_pending_gate_shell(meta):
        return

    queue_weight = _gate_shell_queue_weight(meta)

    timestamp = Path(artifacts_dir).name
    cl_name = (
        str(meta.get("cl_name") or meta.get("patch_name") or meta.get("name") or "")
        or "gate"
    )
    shell_pid = os.getpid()
    run_started_at = datetime.now(UTC).isoformat()

    def claim() -> str:
        from sase.core.process_identity import process_identity_token

        meta.update(
            {
                "pid": shell_pid,
                "process_identity": process_identity_token(shell_pid),
                "gate_state": "settling",
                "run_started_at": run_started_at,
            }
        )
        update_meta_fields(
            artifacts_dir,
            {
                "pid": shell_pid,
                "process_identity": meta["process_identity"],
                "gate_state": "settling",
                "run_started_at": run_started_at,
            },
        )
        return run_started_at

    from sase.axe.run_agent_wait_slots import wait_for_runner_slot

    wait_for_runner_slot(
        artifacts_dir,
        cl_name,
        timestamp,
        meta,
        wait_runners=None,
        wait_priority=None,
        queue_weight=queue_weight,
        queue_weight_explicit=meta.get("queue_weight_explicit") is True,
        claim=claim,
    )


def gate_shell_output_tail(artifacts_dir: str, *, lines: int = 200) -> str:
    """Return the newest retained lines of a gate shell's live-output log."""
    from sase.axe.state import read_tail_seek

    return read_tail_seek(_gate_shell_log_path(artifacts_dir), lines)


__all__ = [
    "GATE_SHELL_LOG_FILENAME",
    "append_gate_shell_log_text",
    "bind_gate_shell_execution_callbacks",
    "gate_shell_output_tail",
]
