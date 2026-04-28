"""Shared helpers for sase.axe.lumberjack tests.

Not a conftest so files opt in by importing the helpers directly. Each test
file defines its own pytest fixtures (matching the rest of the axe test suite,
which redefines ``temp_state_dir`` per-file) and imports these helpers.
"""

import subprocess


def ok_result() -> subprocess.CompletedProcess[str]:
    """Return a successful CompletedProcess for mocking."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def fail_result(
    code: int = 1, stderr: str = "error"
) -> subprocess.CompletedProcess[str]:
    """Return a failed CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout="", stderr=stderr
    )
