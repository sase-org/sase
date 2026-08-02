"""Advisory lock protecting editable source-tree swaps.

The lock prevents ``sase dev update`` from fast-forwarding and reinstalling the
editable checkout while ``sase bead work`` is running from that same checkout.
Both sides are fail-fast because a waiting reader may already have imported
pre-swap modules, and a waiting writer would stall ACE.

There is still a small residual race: a reader that starts while a swap is
already in progress can import torn modules before it reaches this lock. Fully
closing that requires re-execing readers and is intentionally out of scope.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import json
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.paths import sase_subdir

_logger = logging.getLogger(__name__)

ENV_DISABLE_CODE_SWAP_LOCK = "SASE_DISABLE_CODE_SWAP_LOCK"


@dataclass(frozen=True)
class _CodeSwapLockResult:
    """Result yielded by code-swap reader and writer lock contexts."""

    acquired: bool
    blocked_by: str | None = None


@contextmanager
def code_swap_reader_lock(
    *,
    op: str,
    command: Sequence[str] | None = None,
) -> Iterator[_CodeSwapLockResult]:
    """Take a non-blocking shared lock for a running source-tree reader."""
    if _lock_disabled():
        yield _CodeSwapLockResult(acquired=True)
        return

    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = _open_lock_file(lock_path)
    holder_path: Path | None = None
    try:
        if not _try_lock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB):
            yield _CodeSwapLockResult(
                acquired=False,
                blocked_by=_format_writer_holder(_read_writer_holder()),
            )
            return

        holder = _holder(op=op, command=command)
        holder_path = _write_reader_holder(holder)
        try:
            yield _CodeSwapLockResult(acquired=True)
        finally:
            if holder_path is not None:
                _remove_holder_file(holder_path)
            _unlock(fd)
    finally:
        os.close(fd)


@contextmanager
def code_swap_writer_lock() -> Iterator[_CodeSwapLockResult]:
    """Take a non-blocking exclusive lock for an editable source-tree swap."""
    if _lock_disabled():
        yield _CodeSwapLockResult(acquired=True)
        return

    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = _open_lock_file(lock_path)
    try:
        if not _try_lock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB):
            yield _CodeSwapLockResult(
                acquired=False,
                blocked_by=_format_reader_holders(_live_reader_holders()),
            )
            return

        _write_writer_holder(fd, _holder(op="dev.update", command=sys.argv))
        try:
            yield _CodeSwapLockResult(acquired=True)
        finally:
            _clear_writer_holder(fd)
            _unlock(fd)
    finally:
        os.close(fd)


def code_swap_readers_active() -> str | None:
    """Return a best-effort description of active readers, if any."""
    if _lock_disabled():
        return None
    holders = _live_reader_holders()
    if not holders:
        return None
    return _format_reader_holders(holders)


def _lock_path() -> Path:
    return sase_subdir("locks") / "code-swap.lock"


def _holders_dir() -> Path:
    return sase_subdir("locks") / "code-swap.holders"


def _lock_disabled() -> bool:
    return os.environ.get(ENV_DISABLE_CODE_SWAP_LOCK) == "1"


def _open_lock_file(path: Path) -> int:
    while True:
        try:
            return os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        except InterruptedError:
            continue


def _try_lock(fd: int, flags: int) -> bool:
    while True:
        try:
            fcntl.flock(fd, flags)
            return True
        except InterruptedError:
            continue
        except BlockingIOError:
            return False


def _unlock(fd: int) -> None:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return
        except InterruptedError:
            continue


def _holder(*, op: str, command: Sequence[str] | None) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "op": op,
        "command": list(command or ()),
        "started_at": datetime.now(UTC).isoformat(),
    }


def _write_reader_holder(holder: dict[str, Any]) -> Path | None:
    try:
        holders_dir = _holders_dir()
        holders_dir.mkdir(parents=True, exist_ok=True)
        holder_path = holders_dir / f"{os.getpid()}.json"
        holder_path.write_text(
            json.dumps(holder, sort_keys=True),
            encoding="utf-8",
        )
        return holder_path
    except OSError:
        _logger.debug("Failed to write code-swap reader holder", exc_info=True)
        return None


def _remove_holder_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _logger.debug("Failed to remove code-swap holder %s", path, exc_info=True)


def _write_writer_holder(fd: int, holder: dict[str, Any]) -> None:
    try:
        _write_fd_json(fd, holder)
    except OSError:
        _logger.debug("Failed to write code-swap writer holder", exc_info=True)


def _clear_writer_holder(fd: int) -> None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
    except OSError:
        _logger.debug("Failed to clear code-swap writer holder", exc_info=True)


def _write_fd_json(fd: int, value: dict[str, Any]) -> None:
    data = json.dumps(value, sort_keys=True).encode("utf-8")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, data)


def _read_writer_holder() -> dict[str, Any] | None:
    try:
        raw = _lock_path().read_text(encoding="utf-8").strip()
        value = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _live_reader_holders() -> tuple[dict[str, Any], ...]:
    holders_dir = _holders_dir()
    try:
        paths = tuple(holders_dir.glob("*.json"))
    except OSError:
        _logger.debug("Failed to list code-swap reader holders", exc_info=True)
        return ()

    holders: list[dict[str, Any]] = []
    for path in paths:
        holder = _read_reader_holder(path)
        pid = _holder_pid(holder)
        if pid is None or not is_process_running(pid):
            _remove_holder_file(path)
            continue
        holders.append(holder)
    return tuple(
        sorted(
            holders,
            key=lambda holder: (
                str(holder.get("started_at", "")),
                int(holder.get("pid", 0)),
            ),
        )
    )


def _read_reader_holder(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _holder_pid(holder: dict[str, Any]) -> int | None:
    try:
        pid = int(holder.get("pid", ""))
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _format_writer_holder(holder: dict[str, Any] | None) -> str:
    if holder is None:
        return "the active source-tree swap did not record its identity"
    return _format_holder(holder)


def _format_reader_holders(holders: tuple[dict[str, Any], ...]) -> str:
    if not holders:
        return "one or more active readers did not record their identity"
    first = _format_holder(holders[0])
    if len(holders) == 1:
        return first
    return f"{first} and {len(holders) - 1} more reader(s)"


def _format_holder(holder: dict[str, Any]) -> str:
    op = _display_op(str(holder.get("op") or "sase process"))
    pid = holder.get("pid", "unknown")
    started = holder.get("started_at")
    command = _format_command(holder.get("command"))
    pieces = [f"{op} (pid {pid})"]
    if command:
        pieces.append(f"running `{command}`")
    if started:
        pieces.append(f"started {started}")
    return "; ".join(pieces)


def _display_op(op: str) -> str:
    return {
        "bead.work": "sase bead work",
        "dev.update": "sase dev update",
    }.get(op, op)


def _format_command(raw: object) -> str:
    if not isinstance(raw, list) or not raw:
        return ""
    command = shlex.join(str(part) for part in raw)
    if len(command) <= 160:
        return command
    return f"{command[:157]}..."
