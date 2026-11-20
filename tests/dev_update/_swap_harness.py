"""Test-only harness that simulates an install swap entirely in temp dirs.

The reproducer tests in ``test_swap_repro_*.py`` use this module to drive the
real chop runner, the real code-swap writer lock, and real subprocesses through
the update-overlap failure modes seen on live hosts.

Nothing here touches the live install or the account's ``~/.sase``:

* ``SASE_HOME`` points at a per-test sandbox, so the writer is the real
  :func:`~sase.dev_update.code_swap_lock.code_swap_writer_lock` on a sandbox
  lock file (:meth:`SwapSandbox.assert_isolated` checks this).
* Job scripts live in a sandbox bin dir and run ``python -I -S``, so a stub
  ``sase_core_rs`` that vanishes can never fall back to the real binding.
* The two-version package and every mapped file live under ``tmp_path``.

Harness failures raise :class:`HarnessError`, never ``AssertionError``, so a
strict ``xfail(raises=AssertionError)`` only absorbs the behavior under test.
"""

from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.config import AxeConfig, ChopConfig
from sase.dev_update.code_swap_lock import code_swap_lock_path, code_swap_writer_lock

#: Bound on every handshake, chop run, and child process in the reproducer.
HARNESS_TIMEOUT_SECONDS = 60.0

#: Routine name used for every reproducer chop run.
LUMBERJACK = "swaprepro"

#: Name of the stub native binding. It matches the real module on purpose so
#: the failure text is the field text (``No module named 'sase_core_rs'``).
BINDING_MODULE = "sase_core_rs"

#: Name of the two-version package for mixed-version lazy imports.
PACKAGE = "swaprepro_pkg"

#: Exit status a long-lived child uses to ask for a clean restart.
RESTART_EXIT_CODE = 75

_PAGE = 4096
_POLL_SECONDS = 0.01


class HarnessError(RuntimeError):
    """The harness itself broke (timeout, missing handshake, bad setup)."""


# Stdlib-only prelude shared by every job script and mapped reader. It runs
# under ``python -I -S``, so it must not import anything outside the stdlib.
_PRELUDE = """\
import os
import sys
import time
from pathlib import Path

SIGNALS = Path({signals!r})


def handshake(name="started"):
    (SIGNALS / name).write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + {timeout!r}
    while not (SIGNALS / "go").exists():
        if time.monotonic() >= deadline:
            print("handshake timeout", flush=True)
            sys.exit(3)
        time.sleep(0.01)
"""

_JOB_BODIES = {
    # A job that does no swap-sensitive work.
    "noop": """\
handshake()
print("job ok", flush=True)
""",
    # A job whose binding import is deferred until after the swap starts.
    "binding": """\
handshake()
(SIGNALS / "importing").write_text("1", encoding="utf-8")
sys.path.insert(0, {binding_root!r})
import sase_core_rs

print("binding wire", sase_core_rs.WIRE_VERSION, flush=True)
""",
    # A job holding a shared mapping of a native-style file across the swap.
    "mmap": """\
import mmap

with open({mapped_path!r}, "rb") as handle:
    mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
handshake()
(SIGNALS / "touching").write_text("1", encoding="utf-8")
data = mapping[:]
print("mapped", data[:2].decode(), len(data), flush=True)
""",
}

_TYPES_SOURCE = {
    1: 'VERSION = 1\nSpawnCallback = "spawn"\n',
    2: 'VERSION = 2\nSpawnCallback = "spawn"\nBeforeSpawnCallback = "before"\n',
}

_EXECUTOR_SOURCE = {
    1: f"from {PACKAGE}.launch_types import SpawnCallback\n\nVERSION = 1\n",
    2: (
        f"from {PACKAGE}.launch_types import BeforeSpawnCallback, SpawnCallback\n"
        "\nVERSION = 2\n"
    ),
}

# The long-lived process: ``launch_types`` is imported at start (top level, as
# ``sase.agent.launch_executor_types`` is) and ``launch_executor`` lazily per
# work request (as ``multi_prompt_launch_execution`` imports it).
_LONG_LIVED_DRIVER = """\
import importlib
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, {package_root!r})
import {package}.launch_types as launch_types

for name in {eager!r}:
    importlib.import_module(name)

guard = None
if {guard!r}:
    module_name, _, attr = {guard!r}.partition(":")
    guard = getattr(importlib.import_module(module_name), attr)()

print("ready", flush=True)
for _request in sys.stdin:
    if guard is not None and guard():
        print("restart-requested", flush=True)
        sys.exit({restart!r})
    try:
        executor = importlib.import_module("{package}.launch_executor")
    except ImportError as exc:
        print(f"import-error {{type(exc).__name__}}: {{exc}}", flush=True)
        sys.exit(1)
    print(f"ok executor v{{executor.VERSION}} types v{{launch_types.VERSION}}", flush=True)
"""


@dataclass
class SwapSandbox:
    """Temp-dir stand-in for one host's install and SASE home."""

    root: Path
    sase_home: Path
    bin_dir: Path
    binding_root: Path
    package_root: Path
    signals: Path

    # -- isolation -------------------------------------------------------

    def assert_isolated(self) -> None:
        """Refuse to run unless the writer lock lives inside this sandbox."""
        lock_path = code_swap_lock_path().resolve()
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if not lock_path.is_relative_to(self.root.resolve()):
            raise HarnessError(f"code-swap lock escaped the sandbox: {lock_path}")
        if lock_path.is_relative_to(account_home / ".sase"):
            raise HarnessError(f"code-swap lock is the live one: {lock_path}")

    # -- writer ------------------------------------------------------------

    @contextmanager
    def writer(self) -> Iterator[None]:
        """Hold the real code-swap writer lock on the sandbox lock file."""
        self.assert_isolated()
        with code_swap_writer_lock() as lock:
            if not lock.acquired:
                raise HarnessError(f"writer lock refused: {lock.blocked_by}")
            yield

    # -- job scripts -------------------------------------------------------

    def write_job_script(
        self, name: str, kind: str, *, mapped_path: Path | None = None
    ) -> Path:
        """Install a fake uv console script that runs a stdlib-only body."""
        body = _JOB_BODIES[kind].format(
            binding_root=str(self.binding_root),
            mapped_path=str(mapped_path) if mapped_path is not None else "",
        )
        source = self.root / "job_sources" / f"{name}.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(self._prelude() + body, encoding="utf-8")
        script = self.bin_dir / name
        script.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -I -S "{source}" "$@"\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        return script

    def remove_job_script(self, name: str) -> None:
        """Vanish a console script, as ``uv tool install`` does mid-swap."""
        (self.bin_dir / name).unlink()

    # -- stub binding --------------------------------------------------------

    def install_binding(self, wire_version: int = 1) -> None:
        package = self.binding_root / BINDING_MODULE
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text(
            f"WIRE_VERSION = {wire_version}\n", encoding="utf-8"
        )

    def remove_binding(self) -> None:
        """Vanish the binding, as an uninstall-then-install swap does."""
        shutil.rmtree(self.binding_root / BINDING_MODULE)

    # -- two-version package -------------------------------------------------

    def install_package(self, version: int, *, mode: str = "rename") -> None:
        """Write *version* of the package, in place or by atomic rename."""
        package = self.package_root / PACKAGE
        package.mkdir(parents=True, exist_ok=True)
        files = {
            "__init__.py": "",
            "launch_types.py": _TYPES_SOURCE[version],
            "launch_executor.py": _EXECUTOR_SOURCE[version],
        }
        for filename, text in files.items():
            write_file(package / filename, text.encode("utf-8"), mode=mode)

    def start_long_lived(
        self,
        *,
        eager: tuple[str, ...] = (),
        guard: str | None = None,
    ) -> subprocess.Popen[str]:
        """Start a long-lived process and wait until it imported v-current types."""
        driver = self.root / "long_lived_driver.py"
        driver.write_text(
            _LONG_LIVED_DRIVER.format(
                package_root=str(self.package_root),
                package=PACKAGE,
                eager=list(eager),
                guard=guard or "",
                restart=RESTART_EXIT_CODE,
            ),
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            [sys.executable, "-I", str(driver)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = read_line(proc)
        if ready != "ready":
            proc.kill()
            _, stderr = proc.communicate(timeout=HARNESS_TIMEOUT_SECONDS)
            raise HarnessError(f"long-lived child failed to start: {ready!r} {stderr}")
        return proc

    # -- mapped readers ------------------------------------------------------

    def start_mapped_reader(self, mapped_path: Path) -> subprocess.Popen[str]:
        """Start a child that maps *mapped_path*, then waits for ``go``."""
        source = self.root / "mapped_reader.py"
        source.write_text(
            self._prelude()
            + _JOB_BODIES["mmap"].format(binding_root="", mapped_path=str(mapped_path)),
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            [sys.executable, "-I", "-S", str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.wait_for_signal("started")
        return proc

    # -- handshakes ----------------------------------------------------------

    def wait_for_signal(self, name: str) -> None:
        deadline = time.monotonic() + HARNESS_TIMEOUT_SECONDS
        path = self.signals / name
        while not path.exists():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HarnessError(f"timed out waiting for handshake {name!r}")
            time.sleep(min(_POLL_SECONDS, max(0.0, deadline - time.monotonic())))

    def release(self) -> None:
        """Let every waiting child continue past its handshake."""
        (self.signals / "go").write_text("go", encoding="utf-8")

    def _prelude(self) -> str:
        return _PRELUDE.format(
            signals=str(self.signals), timeout=HARNESS_TIMEOUT_SECONDS
        )


def make_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwapSandbox:
    """Build a fresh sandbox and point ``SASE_HOME`` at it."""
    root = tmp_path / "swap-sandbox"
    sandbox = SwapSandbox(
        root=root,
        sase_home=root / ".sase",
        bin_dir=root / "bin",
        binding_root=root / "binding",
        package_root=root / "pkgs",
        signals=root / "signals",
    )
    for directory in (
        sandbox.sase_home,
        sandbox.bin_dir,
        sandbox.binding_root,
        sandbox.package_root,
        sandbox.signals,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(sandbox.sase_home))
    monkeypatch.delenv("SASE_DISABLE_CODE_SWAP_LOCK", raising=False)
    sandbox.assert_isolated()
    return sandbox


def write_file(path: Path, data: bytes, *, mode: str) -> None:
    """Replace *path* the way a given installer does.

    ``in_place``
        Truncate and rewrite the existing inode (``cp`` onto a live file).
    ``rename``
        Write a sibling temp file and ``os.replace`` it (prebuild consumer).
    ``unlink_copy``
        Unlink, then write a new inode (``maturin develop``, uv reinstall).
    """
    if mode == "in_place":
        with open(path, "r+b" if path.exists() else "wb") as handle:
            handle.truncate(0)
            handle.write(data)
    elif mode == "rename":
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    elif mode == "unlink_copy":
        path.unlink(missing_ok=True)
        path.write_bytes(data)
    else:
        raise HarnessError(f"unknown replacement mode {mode!r}")


def mapped_payload(tag: str, pages: int = 4) -> bytes:
    """Return *pages* pages of data that start with the two-byte *tag*."""
    return tag.encode("ascii") * (pages * _PAGE // 2)


def read_line(proc: subprocess.Popen[str]) -> str:
    """Read one stdout line from *proc*, failing the harness on EOF."""
    if proc.stdout is None:
        raise HarnessError("child has no stdout pipe")
    line = proc.stdout.readline()
    if not line:
        raise HarnessError(f"child exited early with {proc.wait(timeout=5)}")
    return line.strip()


def request_work(proc: subprocess.Popen[str]) -> str:
    """Send one work request to a long-lived child and return its reply."""
    if proc.stdin is None:
        raise HarnessError("child has no stdin pipe")
    proc.stdin.write("work\n")
    proc.stdin.flush()
    return read_line(proc)


def stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=HARNESS_TIMEOUT_SECONDS)


class ChopRun:
    """Run one configured chop through the real runner on a worker thread."""

    def __init__(self, sandbox: SwapSandbox, script_name: str) -> None:
        self._sandbox = sandbox
        self._chop = ChopConfig(name=script_name, description="")
        self._config = AxeConfig(chop_script_dirs=[str(sandbox.bin_dir)])
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._future: Future[ChopRunOutcome] | None = None

    def run_now(self) -> ChopRunOutcome:
        """Run synchronously; the script passes its handshake immediately."""
        self._sandbox.release()
        with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
            return self._run()

    @contextmanager
    def started(self) -> Iterator[ChopRun]:
        """Start the chop and yield once its script reached its handshake."""
        with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
            self._future = self._pool.submit(self._run)
            try:
                self._sandbox.wait_for_signal("started")
                yield self
            finally:
                self._sandbox.release()
                self._future.result(timeout=HARNESS_TIMEOUT_SECONDS)
                self._pool.shutdown(wait=True)

    def finish(self) -> ChopRunOutcome:
        """Release the script and wait for the runner's outcome."""
        if self._future is None:
            raise HarnessError("finish() called before started()")
        self._sandbox.release()
        return self._future.result(timeout=HARNESS_TIMEOUT_SECONDS)

    def _run(self) -> ChopRunOutcome:
        return run_configured_chop_once(
            lumberjack_name=LUMBERJACK,
            chop=self._chop,
            axe_config=self._config,
            chop_timeout_default=int(HARNESS_TIMEOUT_SECONDS),
            source="scheduled",
        )
