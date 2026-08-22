"""Wait for the code-swap shared lock, then exec a command while holding it.

This file is executed by filename, not with ``python -m``. That keeps the
editable ``sase`` package out of the waiting process. Direct ``sase bead
work`` stays fail-fast; only the host-owned epic launcher uses this path.
"""

from __future__ import annotations

import fcntl
import os
import sys

_DISABLE_ENV = "SASE_DISABLE_CODE_SWAP_LOCK"
_WAITING_MESSAGE = "sase: waiting for the source-tree swap to finish before launching"


def main(argv: list[str] | None = None) -> int:
    parsed = _parse_argv(argv if argv is not None else sys.argv[1:])
    if parsed is None:
        return 2
    lock_path, command = parsed
    if os.environ.get(_DISABLE_ENV) == "1":
        return _exec(command)
    try:
        fd = _acquire_shared_lock(lock_path)
    except OSError as exc:
        print(f"sase: could not acquire the code-swap lock: {exc}", file=sys.stderr)
        return 1
    try:
        os.set_inheritable(fd, True)
        return _exec(command)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _parse_argv(argv: list[str]) -> tuple[str, list[str]] | None:
    usage = "usage: code_swap_guarded_exec.py <lock-path> -- <command>..."
    try:
        separator = argv.index("--")
    except ValueError:
        print(usage, file=sys.stderr)
        return None
    lock_parts = argv[:separator]
    command = argv[separator + 1 :]
    if len(lock_parts) != 1 or not lock_parts[0] or not command:
        print(usage, file=sys.stderr)
        return None
    return lock_parts[0], command


def _acquire_shared_lock(lock_path: str) -> int:
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        if not _try_shared_nonblocking(fd):
            print(_WAITING_MESSAGE, file=sys.stderr, flush=True)
            _lock_shared_blocking(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _try_shared_nonblocking(fd: int) -> bool:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return True
        except InterruptedError:
            continue
        except BlockingIOError:
            return False


def _lock_shared_blocking(fd: int) -> None:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return
        except InterruptedError:
            continue


def _exec(command: list[str]) -> int:
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        print(f"sase: could not exec {command[0]}: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
