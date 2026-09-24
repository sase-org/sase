"""Fake agent runners with real process trees, shared by termination tests."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.agent.process_registry import ProcessRegistry
from sase.agent.process_tree import process_is_running
from sase.core.process_identity import process_identity_token
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV

SLEEPER = (
    "import os, signal, sys, time\n"
    "{setup}\n"
    "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
    "time.sleep(120)\n"
)

# A fake agent runner. It spawns one child of every shape a real runner tree
# produces and then sleeps: a same-group child, a child in its own process
# group (same session), a ``setsid`` child that inherits the launch scratch
# key, and a same-group child that ignores SIGTERM.
RUNNER = f"""
import os, signal, subprocess, sys, time
ready = sys.argv[1]
sleeper = {SLEEPER!r}
def spawn(name, setup="pass", **kwargs):
    path = os.path.join(ready, name)
    subprocess.Popen(
        [sys.executable, "-c", sleeper.format(setup=setup), path], **kwargs
    )
spawn("same_group")
spawn("own_group", preexec_fn=os.setpgrp)
spawn("setsid", start_new_session=True)
spawn("ignores_term", "signal.signal(signal.SIGTERM, signal.SIG_IGN)")
open(os.path.join(ready, "runner"), "w").write(str(os.getpid()))
time.sleep(120)
"""

CHILDREN = ("same_group", "own_group", "setsid", "ignores_term")


def no_registry(_pid: int) -> ProcessRegistry:
    return ProcessRegistry()


def wait_for_files(directory: Path, names: tuple[str, ...]) -> dict[str, int]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        pids: dict[str, int] = {}
        for name in names:
            try:
                text = (directory / name).read_text().strip()
            except OSError:
                break
            if not text:
                break
            pids[name] = int(text)
        else:
            return pids
        time.sleep(0.02)  # sase-test-wait: polls a real child's readiness file
    raise AssertionError(f"fake runner never became ready: {names}")


@pytest.fixture
def reap() -> Iterator[list[int]]:
    """Collect pids to SIGKILL at teardown so a failing test leaks nothing."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.fixture
def scratch_key() -> str:
    return f"termtest-{uuid.uuid4().hex}"


def launch_runner(
    tmp_path: Path,
    key: str,
    reap: list[int],
    *,
    new_session: bool = True,
) -> tuple[subprocess.Popen[bytes], dict[str, int]]:
    ready = tmp_path / "ready"
    ready.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-c", RUNNER, str(ready)],
        env={**os.environ, SASE_LAUNCH_SCRATCH_KEY_ENV: key},
        start_new_session=new_session,
    )
    reap.append(proc.pid)
    pids = wait_for_files(ready, ("runner", *CHILDREN))
    reap.extend(pids.values())
    return proc, pids


def write_meta(artifacts_dir: Path, pid: int, **extra: object) -> None:
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {"pid": pid, "process_identity": process_identity_token(pid), **extra}
        )
    )


def wait_until_gone(*pids: int, timeout: float = 5.0) -> None:
    """Wait for the kernel to report every pid dead (zombies count as dead)."""
    deadline = time.monotonic() + timeout
    while any(process_is_running(pid) for pid in pids):
        assert time.monotonic() < deadline, f"still running: {pids}"
        time.sleep(0.02)  # sase-test-wait: polls the kernel for process exit


def assert_dead(pids: dict[str, int]) -> None:
    alive = {name: pid for name, pid in pids.items() if process_is_running(pid)}
    assert alive == {}
