"""SIGTERM-then-SIGKILL escalation for supervised child processes."""

import os
import signal
import subprocess
import time
from collections.abc import Mapping


def send_sigterm(children: Mapping[str, subprocess.Popen[bytes]]) -> None:
    """Send SIGTERM to every still-running child process."""
    for proc in children.values():
        if proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


def wait_with_escalation(
    children: Mapping[str, subprocess.Popen[bytes]],
    *,
    term_timeout: float = 10.0,
    kill_timeout: float = 5.0,
) -> None:
    """Wait up to *term_timeout* for children to exit, then SIGKILL stragglers."""
    deadline = time.monotonic() + term_timeout
    for proc in children.values():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=kill_timeout)
