"""Transcript restore, pruned flags, and lazy tails for the Command Line.

On the first panel open per app session, the transcript is rebuilt from
durable proc-store rows carrying the ``command-line`` tag and
``origin == "ace"`` from the last 24 hours (up to 20 rows). Restored rows go
below an ``── earlier ──`` divider and their output loads lazily when the
block becomes visible or expanded. Pruned store rows are never restored; a
live block whose proc later vanishes keeps its cached tail and shows
``record pruned``.
"""

from __future__ import annotations

import shlex
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sase.ace.tui.command_line.session import CommandLineBlock, CommandLineSession
from sase.procs.command_line import COMMAND_LINE_PROC_TAG
from sase.procs.models import TERMINAL_PROC_STATUSES

#: Restore window in seconds: only procs created in the last 24 hours.
RESTORE_WINDOW_SECONDS = 24 * 60 * 60
#: Maximum restored blocks per app session.
RESTORE_LIMIT = 20


class _ProcRow(Protocol):
    """Structural subset of :class:`Proc` needed for transcript restore."""

    @property
    def proc_id(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def command(self) -> list[str]: ...
    @property
    def origin(self) -> str: ...
    @property
    def tags(self) -> list[str]: ...
    @property
    def status(self) -> str: ...
    @property
    def exit_code(self) -> int | None: ...
    @property
    def created_at(self) -> str: ...
    @property
    def started_at(self) -> str | None: ...
    @property
    def finished_at(self) -> str | None: ...
    @property
    def log_path(self) -> str: ...


def _command_line_from_proc(proc: _ProcRow) -> str:
    """Derive the panel input line that submitted a command-line proc."""
    command = list(proc.command or [])
    if len(command) >= 2 and command[0] == "sase":
        return shlex.join(command[1:])
    label = (proc.label or "").strip()
    if label.startswith(": "):
        return label[2:].strip()
    if label.startswith(":"):
        return label[1:].strip()
    return label


def _parse_proc_time(value: str | None) -> float | None:
    """Parse an ISO-8601 proc timestamp to epoch seconds."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def block_from_proc(proc: _ProcRow) -> CommandLineBlock | None:
    """Build a restored transcript block from one store row.

    Returns ``None`` when the row carries no recoverable command line.
    Active procs restore as running blocks so tail polling and exit watches
    keep them live; terminal rows settle immediately.
    """
    line = _command_line_from_proc(proc)
    if not line:
        return None
    block = CommandLineBlock(block_id=f"cmdline-{proc.proc_id}", line=line)
    block.proc_id = proc.proc_id
    block.restored = True
    block.tail_loaded = False
    if proc.status in TERMINAL_PROC_STATUSES:
        block.exit_code = proc.exit_code
        finished = _parse_proc_time(proc.finished_at)
        started = _parse_proc_time(proc.started_at)
        if finished is not None and started is not None:
            block.elapsed = max(0.0, finished - started)
            block.finished_at = finished
            block.started_at = finished - block.elapsed
        elif finished is not None:
            block.finished_at = finished
        if proc.status == "killed":
            block.status = "error"
            block.error = "killed"
        elif proc.exit_code == 0:
            block.status = "success"
        else:
            block.status = "error"
    else:
        block.status = "running"
    return block


def _select_restore_rows(
    procs: Sequence[_ProcRow],
    *,
    now: float | None = None,
    limit: int = RESTORE_LIMIT,
    window_seconds: int = RESTORE_WINDOW_SECONDS,
) -> list[_ProcRow]:
    """Pick the store rows to restore: tagged, ace-owned, fresh, oldest first.

    *procs* arrives newest-first (the store snapshot order); the result is
    chronological so appending preserves transcript order. Pruned records are
    absent from the snapshot and therefore never selected.
    """
    moment = now if now is not None else time.time()
    selected: list[_ProcRow] = []
    for proc in procs:
        if proc.origin != "ace":
            continue
        if COMMAND_LINE_PROC_TAG not in list(proc.tags or []):
            continue
        created = _parse_proc_time(proc.created_at)
        if created is None or moment - created > window_seconds:
            continue
        selected.append(proc)
        if len(selected) >= limit:
            break
    selected.reverse()
    return selected


def restore_missing_blocks(
    session: CommandLineSession,
    procs: Sequence[_ProcRow],
    *,
    now: float | None = None,
    limit: int = RESTORE_LIMIT,
    window_seconds: int = RESTORE_WINDOW_SECONDS,
) -> list[CommandLineBlock]:
    """Append restored blocks for rows the transcript lacks; return them."""
    known = {block.proc_id for block in session.blocks if block.proc_id is not None}
    added: list[CommandLineBlock] = []
    for proc in _select_restore_rows(
        procs, now=now, limit=limit, window_seconds=window_seconds
    ):
        if proc.proc_id in known:
            continue
        block = block_from_proc(proc)
        if block is None:
            continue
        session.blocks.append(block)
        known.add(proc.proc_id)
        added.append(block)
    while len(session.blocks) > 200:
        session.blocks.pop(0)
    return added


def ensure_block_for_proc(
    session: CommandLineSession, proc_id: str
) -> CommandLineBlock | None:
    """Return the block tracking *proc_id*, adding it when the store has it.

    Used by the Procs-pane ``⏎`` jump: the transcript gains the block when it
    lacks it. Returns ``None`` when the proc record was pruned (or is not a
    command-line proc); the caller then reports the pruned record.
    """
    block = session.block_for_proc(proc_id)
    if block is not None:
        return block
    try:
        from sase.procs.store import get_proc

        proc = get_proc(proc_id)
    except Exception:  # noqa: BLE001 - store reads are best effort here.
        return None
    if proc is None:
        return None
    if COMMAND_LINE_PROC_TAG not in list(proc.tags or []):
        return None
    block = block_from_proc(proc)
    if block is None:
        return None
    session.blocks.append(block)
    while len(session.blocks) > 200:
        session.blocks.pop(0)
    return block


def refresh_pruned_flags(
    session: CommandLineSession, live_proc_ids: set[str]
) -> list[CommandLineBlock]:
    """Mark finished blocks whose proc left the store; return newly pruned ones."""
    newly: list[CommandLineBlock] = []
    for block in session.blocks:
        if block.proc_id is None or block.running or block.pruned:
            continue
        if block.proc_id not in live_proc_ids:
            block.pruned = True
            newly.append(block)
    return newly


def load_block_tail_text(block: CommandLineBlock, *, max_bytes: int = 524_288) -> bool:
    """Lazily read a restored block's tail from its proc log.

    Returns True when the tail loaded. When the log is gone the cached tail
    stays and the block is flagged ``record pruned``.
    """
    if block.tail_loaded or block.proc_id is None:
        return False
    from sase.procs.logs import ProcLogCursor

    cursor = ProcLogCursor(proc_id=block.proc_id)
    chunks: list[str] = []
    budget = max_bytes
    try:
        while budget > 0:
            read = cursor.read_new()
            if not read.text and not read.lost_bytes:
                break
            if read.lost_bytes:
                block.lost_bytes += read.lost_bytes
            if read.text:
                chunks.append(read.text)
                budget -= len(read.text.encode("utf-8", errors="ignore"))
            else:
                break
    except OSError:
        block.pruned = True
        block.tail_loaded = True
        return False
    text = "".join(chunks)
    if not text and not block.tail_text:
        try:
            from sase.procs.store import get_proc

            if get_proc(block.proc_id) is None:
                block.pruned = True
        except Exception:  # noqa: BLE001 - pruned checks are best effort.
            pass
    block.tail_text = text or block.tail_text
    block.tail_loaded = True
    return bool(text)


def read_command_line_store_rows() -> list[Any]:
    """Read live store rows carrying the ``command-line`` tag (newest first)."""
    from sase.procs.store import read_procs

    return read_procs(tag=COMMAND_LINE_PROC_TAG)


__all__ = [
    "RESTORE_LIMIT",
    "RESTORE_WINDOW_SECONDS",
    "block_from_proc",
    "ensure_block_for_proc",
    "load_block_tail_text",
    "read_command_line_store_rows",
    "refresh_pruned_flags",
    "restore_missing_blocks",
]
