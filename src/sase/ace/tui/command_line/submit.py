"""Command Line submission: optimistic blocks, worker submit, exit watches.

The panel tokenizes with ``shlex`` (the grammar resolver replaces this seam
in the completion-popup phase). A ``submitting`` block and an observer
placeholder are created at once, then :func:`submit_command_line_proc` runs
in a thread worker. A 300 ms double-Enter guard drops accidental duplicate
submissions; submit failures turn the block red and restore the line.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
    tokenize_command_line,
)

#: Double-Enter guard window in seconds.
SUBMIT_DEDUP_SECONDS = 0.3


@dataclass(frozen=True)
class PreparedSubmit:
    """A validated submission ready for the worker thread."""

    tokens: list[str]
    line: str


def prepare_submit(
    session: CommandLineSession,
    line: str,
    *,
    tokens: list[str] | None = None,
) -> PreparedSubmit | None:
    """Validate a line for submission; ``None`` means drop it silently.

    The completion-popup phase passes the resolver's ``LineContext.argv``
    as *tokens* so submission runs what the grammar saw; otherwise the
    line is tokenized with ``shlex`` as before.
    """
    resolved = tokens if tokens is not None else tokenize_command_line(line)
    if not resolved:
        return None
    now = time.monotonic()
    if (
        line.strip() == session.last_submit_line
        and now - session.last_submit_at < SUBMIT_DEDUP_SECONDS
    ):
        return None
    session.last_submit_at = now
    session.last_submit_line = line.strip()
    return PreparedSubmit(tokens=list(resolved), line=line.strip())


def submit_in_worker(
    *,
    tokens: list[str],
    cwd: str,
    project: str | None,
    width: int,
    session_id: str | None = None,
) -> Any:
    """Run :func:`submit_command_line_proc` (thread-worker entry point)."""
    from sase.procs.command_line import submit_command_line_proc

    return submit_command_line_proc(
        tokens,
        cwd=cwd,
        project=project,
        width=width,
        session_id=session_id,
    )


def apply_submit_success(
    block: CommandLineBlock,
    proc: Any,
    *,
    placeholder_id: str | None,
) -> None:
    """Attach a submitted proc to its optimistic block."""
    block.proc_id = proc.proc_id
    block.placeholder_id = placeholder_id
    block.status = "running"


def apply_exit_completion(
    block: CommandLineBlock,
    *,
    exit_code: int | None,
    status: str,
) -> None:
    """Settle a block from an observer exit completion."""
    from sase.ace.tui.command_line.policies import is_confirmation_declined

    block.exit_code = exit_code
    block.finished_at = time.time()
    block.elapsed = block.elapsed_seconds()
    if status == "killed":
        block.status = "error"
        block.error = "killed"
    elif exit_code == 0:
        block.status = "success"
    else:
        block.status = "error"
    block.declined = is_confirmation_declined(
        confirms=block.confirms,
        confirm_flag_present=block.confirm_flag_present,
        exit_code=exit_code,
    )


def capture_resolve_context(
    block: CommandLineBlock, context: dict[str, Any] | None
) -> None:
    """Capture the resolver's confirm flags on a block for declined logic."""
    if not context:
        block.confirms = False
        block.confirm_flag_present = False
        return
    block.confirms = bool(context.get("confirms", False))
    block.confirm_flag_present = bool(context.get("confirm_flag_present", False))


def apply_local_block(
    block: CommandLineBlock,
    *,
    status: str,
    text: str,
    exit_code: int | None = None,
) -> None:
    """Finish a non-proc block (denied, foreground, built-in) instantly."""
    block.status = status  # type: ignore[assignment]
    block.tail_text = text
    block.tail_loaded = True
    block.exit_code = exit_code
    block.finished_at = time.time()
    block.elapsed = block.elapsed_seconds()


def apply_submit_failure(block: CommandLineBlock, error: str) -> None:
    """Turn an optimistic block red when submission fails."""
    block.status = "submit_failed"
    block.error = error
    block.finished_at = time.time()


__all__ = [
    "SUBMIT_DEDUP_SECONDS",
    "PreparedSubmit",
    "apply_exit_completion",
    "apply_local_block",
    "apply_submit_failure",
    "apply_submit_success",
    "capture_resolve_context",
    "prepare_submit",
    "submit_in_worker",
]
