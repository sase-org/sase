"""Bootstrap the proc supervisor before importing the proc stack.

This file is executed by filename, not with ``python -m``. That keeps
``sase.procs.__init__`` out of the startup path until after the signal
dispositions below are installed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

_IMPORT_DELAY_ENV = "SASE_PROC_BOOTSTRAP_IMPORT_DELAY_SECONDS"
_STARTUP_SIGNAL: int | None = None


def _record_startup_signal(signum: int, _frame: object) -> None:
    global _STARTUP_SIGNAL
    if _STARTUP_SIGNAL is None:
        _STARTUP_SIGNAL = signum


signal.signal(signal.SIGHUP, signal.SIG_IGN)
signal.signal(signal.SIGTERM, _record_startup_signal)
signal.signal(signal.SIGINT, _record_startup_signal)


def main() -> int:
    args = _parser().parse_args()
    try:
        child_pid = os.fork()
    except OSError as exc:
        _write_pid_payload(args.pid_fd, {"error": f"could not fork supervisor: {exc}"})
        return 1

    if child_pid:
        _write_pid_payload(args.pid_fd, {"pid": child_pid})
        return 0

    _close_pid_fd(args.pid_fd)
    _delay_import_if_requested()

    from sase.procs.supervisor import run_supervisor

    return run_supervisor(args.proc_id, startup_signal=_STARTUP_SIGNAL)


def _write_pid_payload(pid_fd: int, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    try:
        os.write(pid_fd, encoded + b"\n")
    except OSError:
        pass
    finally:
        _close_pid_fd(pid_fd)


def _close_pid_fd(pid_fd: int) -> None:
    try:
        os.close(pid_fd)
    except OSError:
        pass


def _delay_import_if_requested() -> None:
    raw = os.environ.get(_IMPORT_DELAY_ENV)
    if raw is None:
        return
    try:
        delay_seconds = max(0.0, float(raw))
    except ValueError:
        return
    deadline = time.monotonic() + delay_seconds
    while True:
        if _STARTUP_SIGNAL is not None:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap one SASE proc supervisor.")
    parser.add_argument("--proc-id", required=True)
    parser.add_argument("--pid-fd", required=True, type=int)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
