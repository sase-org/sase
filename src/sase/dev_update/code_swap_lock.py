"""Advisory lock protecting editable source-tree swaps.

The lock prevents ``sase dev update`` from fast-forwarding and reinstalling the
editable checkout while ``sase bead work`` is running from that same checkout.

Direct ``sase bead work`` stays fail-fast: a process that has already imported
editable SASE modules must not wait across a swap. Host-owned epic launches
wait in ``code_swap_guarded_exec.py`` (executed by filename, not as a
package import). The bootstrap owns the shared lock while waiting, then execs
a fresh ``sase bead work`` and publishes the held descriptor for exactly one
handoff. :func:`code_swap_reader_lock` adopts that descriptor, restores
close-on-exec, and releases it when launch orchestration finishes. The handoff
marker must not survive into agent execution.

There is still a small residual race for unguarded readers: a process that
starts while a swap is already in progress can import torn modules before it
reaches this lock. The guarded epic-launch bootstrap is the re-exec path
for that host-owned case.
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
# Private bootstrap-to-reader contract. ``code_swap_guarded_exec.py`` cannot
# import this module, so it duplicates the string; it authorizes exactly one
# exec handoff and must be consumed before any agent runner is spawned.
_ENV_CODE_SWAP_LOCK_FD = "SASE_CODE_SWAP_LOCK_FD"
_GUARDED_EXEC_SEPARATOR = "--"
_GUARDED_EXEC_BOOTSTRAP = Path(__file__).with_name("code_swap_guarded_exec.py")
CODE_SWAP_LOCK_FILENAME = "code-swap-v2.lock"
_LEGACY_LOCK_FILENAMES = ("code-swap.lock",)


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
    """Take a non-blocking shared lock for a running source-tree reader.

    A guarded launch may hand off an already-held descriptor through a private
    environment marker. This function always consumes that marker. A matching
    open descriptor becomes this context's sole owned lock; an absent,
    malformed, closed, or mismatched marker falls back to opening the lock
    file and never closes an unrelated descriptor.
    """
    raw_handoff_fd = os.environ.pop(_ENV_CODE_SWAP_LOCK_FD, None)
    if _lock_disabled():
        yield _CodeSwapLockResult(acquired=True)
        return

    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    adopted = _adopt_handoff_lock_fd(raw_handoff_fd, lock_path)
    legacy_fd: int | None = None
    if adopted is None:
        fd = _open_lock_file(lock_path)
    else:
        handoff_fd, current_generation = adopted
        if current_generation:
            fd = handoff_fd
        else:
            # A bootstrap loaded before the v2 migration can still hand off
            # the legacy inode. Hold it until the current lock is open so the
            # transition never leaves the reader entirely unprotected.
            legacy_fd = handoff_fd
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
        holder_path = _write_reader_holder(
            holder, path=_reader_holder_path(pid=os.getpid(), blocking=True)
        )
        try:
            yield _CodeSwapLockResult(acquired=True)
        finally:
            if holder_path is not None:
                _remove_holder_file(holder_path)
            _unlock(fd)
    finally:
        os.close(fd)
        if legacy_fd is not None:
            _unlock(legacy_fd)
            os.close(legacy_fd)


@contextmanager
def code_swap_advisory_reader_lock(
    *,
    op: str,
    command: Sequence[str] | None = None,
) -> Iterator[None]:
    """Register a non-blocking advisory reader for the caller's lifetime.

    Unlike :func:`code_swap_reader_lock`, this never takes the shared ``flock``,
    so it can never refuse a writer and can never itself be refused. It exists
    so a long-lived process (an agent runner) that cannot afford to block
    ``sase dev update`` can still be named by :func:`code_swap_advisory_warning`
    while it is live.
    """
    if _lock_disabled():
        yield
        return

    holder = _holder(op=op, command=command, blocking=False)
    holder_path = _write_reader_holder(
        holder, path=_reader_holder_path(pid=os.getpid(), blocking=False)
    )
    try:
        yield
    finally:
        if holder_path is not None:
            _remove_holder_file(holder_path)


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

        # ``code-swap.lock`` could remain shared-locked forever when a
        # pre-handoff-fix bootstrap leaked its descriptor into an agent
        # runner. The v2 inode deliberately leaves anonymous legacy locks
        # behind, but a live holder record still identifies a real legacy
        # bead-work reader whose orchestration must finish before the swap.
        legacy_blocked_by = _legacy_reader_blocked_by()
        if legacy_blocked_by is not None:
            yield _CodeSwapLockResult(
                acquired=False,
                blocked_by=legacy_blocked_by,
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
    """Return a best-effort description of active blocking readers, if any.

    Advisory readers (long-lived agent runners) are excluded: they never take
    the shared lock, so they must never be reported as something that could
    defer ``sase dev update`` or the ACE update preview.
    """
    if _lock_disabled():
        return None
    holders = _live_reader_holders()
    if not holders:
        return None
    return _format_reader_holders(holders)


def code_swap_advisory_warning() -> str | None:
    """Return a warning naming live advisory readers, if any.

    Purely informational: advisory readers never block a swap, so this is safe
    to surface alongside a swap that is about to proceed anyway.
    """
    if _lock_disabled():
        return None
    holders = _live_advisory_holders()
    if not holders:
        return None
    return (
        f"{len(holders)} agent runner(s) are running from this checkout and a "
        "swap now can break their deferred imports."
    )


def guarded_exec_argv(command: Sequence[str]) -> list[str]:
    """Build argv that waits for the shared lock, then execs *command*.

    The returned process imports no editable SASE modules until the lock is
    held. Direct ``sase bead work`` callers must not use this path: they
    stay fail-fast through :func:`code_swap_reader_lock`.
    """
    parts = [str(part) for part in command]
    if not parts or not parts[0]:
        raise ValueError("guarded exec requires a non-empty command")
    return [
        sys.executable,
        str(_GUARDED_EXEC_BOOTSTRAP.resolve()),
        str(_lock_path()),
        _GUARDED_EXEC_SEPARATOR,
        *parts,
    ]


def logical_argv_from_guarded_exec(argv: Sequence[str]) -> list[str]:
    """Return the logical command wrapped by :func:`guarded_exec_argv`.

    An unguarded argv is returned unchanged so callers can accept both the
    historical ``sase bead work ...`` form and the bootstrap wrapper.
    """
    parts = [str(part) for part in argv]
    try:
        separator = parts.index(_GUARDED_EXEC_SEPARATOR)
    except ValueError:
        return parts
    if separator >= 2 and Path(parts[1]).name == _GUARDED_EXEC_BOOTSTRAP.name:
        return parts[separator + 1 :]
    return parts


def _lock_path() -> Path:
    return sase_subdir("locks") / CODE_SWAP_LOCK_FILENAME


def _legacy_lock_paths() -> tuple[Path, ...]:
    locks_dir = sase_subdir("locks")
    return tuple(locks_dir / name for name in _LEGACY_LOCK_FILENAMES)


def _legacy_reader_blocked_by() -> str | None:
    holders = _live_reader_holders()
    if not holders:
        return None
    for path in _legacy_lock_paths():
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            if not _try_lock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB):
                return _format_reader_holders(holders)
            _unlock(fd)
        finally:
            os.close(fd)
    return None


def _holders_dir() -> Path:
    return sase_subdir("locks") / "code-swap.holders"


def _lock_disabled() -> bool:
    return os.environ.get(ENV_DISABLE_CODE_SWAP_LOCK) == "1"


def _adopt_handoff_lock_fd(raw: str | None, lock_path: Path) -> tuple[int, bool] | None:
    """Return the inherited lock fd and whether it names the current lock.

    Never closes *raw*: a malformed, closed, or mismatched value may identify
    an unrelated descriptor that this process must keep. A recognized legacy
    descriptor is adopted so the caller can migrate it without leaking it.
    """
    if raw is None:
        return None
    try:
        fd = int(raw)
    except (TypeError, ValueError):
        return None
    if fd <= 0:
        return None
    try:
        fd_stat = os.fstat(fd)
    except OSError:
        return None

    fd_key = (fd_stat.st_dev, fd_stat.st_ino)
    current_generation: bool | None = None
    for candidate, is_current in (
        (lock_path, True),
        *((path, False) for path in _legacy_lock_paths()),
    ):
        try:
            candidate_stat = candidate.stat()
        except OSError:
            continue
        if fd_key == (candidate_stat.st_dev, candidate_stat.st_ino):
            current_generation = is_current
            break
    if current_generation is None:
        return None
    try:
        os.set_inheritable(fd, False)
    except OSError:
        return None
    return fd, current_generation


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


def _holder(
    *, op: str, command: Sequence[str] | None, blocking: bool = True
) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "op": op,
        "command": list(command or ()),
        "started_at": datetime.now(UTC).isoformat(),
        "blocking": blocking,
    }


def _reader_holder_path(*, pid: int, blocking: bool) -> Path:
    suffix = "" if blocking else ".advisory"
    return _holders_dir() / f"{pid}{suffix}.json"


def _write_reader_holder(holder: dict[str, Any], *, path: Path) -> Path | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(holder, sort_keys=True),
            encoding="utf-8",
        )
        return path
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
    """Return live *blocking* reader holders (e.g. a running ``sase bead work``)."""
    return _live_holders(blocking=True)


def _live_advisory_holders() -> tuple[dict[str, Any], ...]:
    """Return live *advisory* reader holders (e.g. a running agent runner)."""
    return _live_holders(blocking=False)


def _live_holders(*, blocking: bool) -> tuple[dict[str, Any], ...]:
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
        if bool(holder.get("blocking", True)) != blocking:
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
        "agent.runner": "agent runner",
    }.get(op, op)


def _format_command(raw: object) -> str:
    if not isinstance(raw, list) or not raw:
        return ""
    command = shlex.join(str(part) for part in raw)
    if len(command) <= 160:
        return command
    return f"{command[:157]}..."
