"""Tests for non-interactive captured subprocess execution."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from sase.noninteractive_subprocess import run_noninteractive


def test_run_noninteractive_child_stdin_is_not_a_tty() -> None:
    result = run_noninteractive(
        [sys.executable, "-c", "import sys; print(sys.stdin.isatty())"]
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False"


def test_run_noninteractive_input_gets_eof_instead_of_blocking() -> None:
    started = time.monotonic()

    result = run_noninteractive([sys.executable, "-c", "input()"], timeout=2.0)

    assert time.monotonic() - started < 1.0
    assert result.returncode != 0
    assert "EOFError" in result.stderr


def test_run_noninteractive_child_gets_new_process_group() -> None:
    result = run_noninteractive(
        [sys.executable, "-c", "import os; print(os.getpgrp())"]
    )

    assert result.returncode == 0
    assert int(result.stdout.strip()) != os.getpgrp()


def test_run_noninteractive_timeout_kills_process_group() -> None:
    code = "import os, time; print(os.getpgrp(), flush=True); time.sleep(30)"

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        run_noninteractive([sys.executable, "-c", code], timeout=0.2)

    output = exc_info.value.output
    assert isinstance(output, str)
    child_pgid = int(output.strip().splitlines()[0])

    for _ in range(20):
        try:
            os.killpg(child_pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)  # sase-test-wait: process-group cleanup race window
    else:
        pytest.fail(f"process group {child_pgid} survived timeout cleanup")
