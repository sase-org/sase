"""Tests for non-interactive captured subprocess execution."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import sase.noninteractive_subprocess as noninteractive_subprocess


def test_run_noninteractive_child_stdin_is_not_a_tty() -> None:
    result = noninteractive_subprocess.run_noninteractive(
        [sys.executable, "-c", "import sys; print(sys.stdin.isatty())"]
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False"


def test_run_noninteractive_input_gets_eof_instead_of_blocking() -> None:
    started = time.monotonic()

    result = noninteractive_subprocess.run_noninteractive(
        [sys.executable, "-c", "input()"], timeout=2.0
    )

    assert time.monotonic() - started < 1.0
    assert result.returncode != 0
    assert "EOFError" in result.stderr


def test_run_noninteractive_child_gets_new_process_group() -> None:
    result = noninteractive_subprocess.run_noninteractive(
        [sys.executable, "-c", "import os; print(os.getpgrp())"]
    )

    assert result.returncode == 0
    assert int(result.stdout.strip()) != os.getpgrp()


def test_run_noninteractive_timeout_kills_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = "import os, time; print(os.getpgrp(), flush=True); time.sleep(30)"
    child_pgid: int | None = None
    real_start = noninteractive_subprocess._start_noninteractive_process

    def start_and_wait_for_pgid(
        args: list[str],
        *,
        cwd: str | os.PathLike[str] | None,
        env: dict[str, str] | None,
    ) -> subprocess.Popen[str]:
        nonlocal child_pgid
        process = real_start(args, cwd=cwd, env=env)
        assert process.stdout is not None
        child_pgid = int(process.stdout.readline().strip())
        return process

    monkeypatch.setattr(
        noninteractive_subprocess,
        "_start_noninteractive_process",
        start_and_wait_for_pgid,
    )

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        noninteractive_subprocess.run_noninteractive(
            [sys.executable, "-c", code], timeout=0.2
        )

    assert isinstance(exc_info.value.output, str)
    assert child_pgid is not None

    for _ in range(20):
        try:
            os.killpg(child_pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)  # sase-test-wait: process-group cleanup race window
    else:
        pytest.fail(f"process group {child_pgid} survived timeout cleanup")
