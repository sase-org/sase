"""Guarded-exec bootstrap for host-owned epic launches."""

from __future__ import annotations

import ast
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.dev_update import code_swap_guarded_exec as bootstrap_mod
from sase.core.paths import sase_subdir
from sase.dev_update.code_swap_lock import (
    ENV_DISABLE_CODE_SWAP_LOCK,
    code_swap_writer_lock,
    guarded_exec_argv,
    logical_argv_from_guarded_exec,
)

_BOOTSTRAP = Path(bootstrap_mod.__file__).resolve()
_WAITING_NEEDLE = "waiting for the source-tree swap to finish"


def test_bootstrap_module_does_not_import_sase() -> None:
    tree = ast.parse(_BOOTSTRAP.read_text(encoding="utf-8"), filename=str(_BOOTSTRAP))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("sase") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("sase")


def test_guarded_exec_argv_wraps_logical_command_and_round_trips() -> None:
    logical = ["sase", "bead", "work", "/tmp/epic plan.md", "--yes-to-all"]
    argv = guarded_exec_argv(logical)

    assert argv[0] == sys.executable
    assert argv[1] == str(_BOOTSTRAP.resolve())
    assert argv[2] == str(sase_subdir("locks") / "code-swap.lock")
    assert argv[3] == "--"
    assert argv[4:] == logical
    assert "-m" not in argv
    assert logical_argv_from_guarded_exec(argv) == logical
    assert logical_argv_from_guarded_exec(logical) == logical


def test_guarded_exec_argv_rejects_empty_command() -> None:
    with pytest.raises(ValueError, match="non-empty command"):
        guarded_exec_argv([])


def test_guarded_exec_waits_for_writer_then_execs_once(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    payload = tmp_path / "payload.py"
    payload.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    argv = guarded_exec_argv([sys.executable, str(payload), "once"])
    with code_swap_writer_lock() as writer:
        assert writer.acquired is True
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            line = _readline_until(proc, _WAITING_NEEDLE, timeout=5.0)
            assert line is not None
            assert proc.poll() is None
            assert not marker.exists()
        except BaseException:
            proc.kill()
            proc.wait(timeout=5)
            raise
    assert proc.wait(timeout=10) == 0
    assert marker.read_text(encoding="utf-8") == "once"


def test_guarded_exec_skips_wait_when_lock_disabled(tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    payload = tmp_path / "payload.py"
    payload.write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ok')\n",
        encoding="utf-8",
    )
    child_env = os.environ.copy()
    child_env[ENV_DISABLE_CODE_SWAP_LOCK] = "1"
    with code_swap_writer_lock() as writer:
        assert writer.acquired is True
        completed = subprocess.run(
            guarded_exec_argv([sys.executable, str(payload)]),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=child_env,
        )
    assert completed.returncode == 0
    assert _WAITING_NEEDLE not in completed.stdout
    assert _WAITING_NEEDLE not in completed.stderr
    assert marker.read_text(encoding="utf-8") == "ok"


def test_guarded_exec_rejects_missing_separator() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(_BOOTSTRAP),
            str(sase_subdir("locks") / "code-swap.lock"),
            "true",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 2
    assert "usage:" in completed.stderr


def _readline_until(
    proc: subprocess.Popen[str], needle: str, *, timeout: float
) -> str | None:
    stream = proc.stdout
    if stream is None:
        return None
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], max(0.0, remaining))
        if not ready:
            continue
        chunk = stream.readline()
        if chunk == "":
            return None
        buf += chunk
        if needle in buf:
            return buf
    return None
