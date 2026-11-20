"""Update-overlap reproducer: Python imports and launches across a code swap.

The two-version package mirrors the field failure: ``launch_types`` is
imported at process start (as ``sase.agent.launch_executor_types`` is) and
``launch_executor`` lazily (as ``multi_prompt_launch_execution`` and
``launch_cwd_single`` import ``sase.agent.launch_executor``). Version 2 of the
executor needs ``BeforeSpawnCallback``, which only version 2 of the types
module defines. Every swap happens under the real code-swap writer lock on a
sandbox lock file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sase.axe.runner_failure_facts import capture_failure_facts
from sase.dev_update.code_swap_lock import guarded_exec_argv
from tests.dev_update._swap_harness import (
    HARNESS_TIMEOUT_SECONDS,
    PACKAGE,
    RESTART_EXIT_CODE,
    SwapSandbox,
    make_sandbox,
    request_work,
    stop,
)

#: ``swap_launch_guards`` wires its long-lived-process guard here as
#: ``"module:factory"``. The factory runs once at process start and returns a
#: zero-argument predicate that turns true once the process must stop lazy
#: in-process work and restart. If that phase chooses eager imports instead,
#: it replaces the xfail below with a test of the real long-lived entry point.
LONG_LIVED_SWAP_GUARD: str | None = None


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwapSandbox:
    sandbox = make_sandbox(tmp_path, monkeypatch)
    sandbox.install_package(1)
    return sandbox


# -- (d) a long-lived process mixes module versions across a swap ------------


@pytest.mark.parametrize("mode", ["in_place", "rename"])
def test_long_lived_process_mixes_versions_after_swap(
    sandbox: SwapSandbox, mode: str
) -> None:
    """The BeforeSpawnCallback failure reproduces, however files are replaced.

    Atomic replacement does not help Python sources: the stale module is the
    one already in ``sys.modules``, not a torn file on disk.
    """
    proc = sandbox.start_long_lived()
    try:
        with sandbox.writer():
            sandbox.install_package(2, mode=mode)
        reply = request_work(proc)
        assert reply.startswith("import-error ImportError:"), reply
        assert "cannot import name 'BeforeSpawnCallback'" in reply
        assert proc.wait(timeout=HARNESS_TIMEOUT_SECONDS) == 1
    finally:
        stop(proc)

    facts = capture_failure_facts(None, phase="launch", error_text=reply)
    assert facts["skew_suspect"] is True


def test_eager_import_at_start_keeps_one_consistent_version(
    sandbox: SwapSandbox,
) -> None:
    """Evidence for the eager-import option: no lazy import, no mixing."""
    proc = sandbox.start_long_lived(eager=(f"{PACKAGE}.launch_executor",))
    try:
        with sandbox.writer():
            sandbox.install_package(2)
        assert request_work(proc) == "ok executor v1 types v1"
    finally:
        stop(proc)


def test_process_started_after_swap_sees_one_consistent_version(
    sandbox: SwapSandbox,
) -> None:
    """Evidence for the restart option: a fresh process is coherent."""
    with sandbox.writer():
        sandbox.install_package(2)
    proc = sandbox.start_long_lived()
    try:
        assert request_work(proc) == "ok executor v2 types v2"
    finally:
        stop(proc)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "swap_launch_guards: a long-lived process that outlives a swap must "
        "restart or keep one module version, never mix them"
    ),
)
def test_long_lived_process_never_mixes_versions_across_a_swap(
    sandbox: SwapSandbox,
) -> None:
    proc = sandbox.start_long_lived(guard=LONG_LIVED_SWAP_GUARD)
    try:
        with sandbox.writer():
            sandbox.install_package(2)
        reply = request_work(proc)
        assert not reply.startswith("import-error"), reply
        if reply == "restart-requested":
            assert proc.wait(timeout=HARNESS_TIMEOUT_SECONDS) == RESTART_EXIT_CODE
        else:
            assert reply in {"ok executor v1 types v1", "ok executor v2 types v2"}
    finally:
        stop(proc)


# -- launches: the guarded bootstrap waits out the swap ------------------------


def test_guarded_launch_waits_out_the_swap_and_sees_the_restored_binding(
    sandbox: SwapSandbox,
) -> None:
    """Host-owned epic launches already defer across a swap.

    ``code_swap_guarded_exec`` imports nothing editable until it holds the
    shared lock, so a launch issued while the binding is missing waits, then
    execs against the reinstalled binding. Unguarded launch paths (agent
    runner start, finalizers, direct ``sase bead work``) have no such wait;
    ``swap_launch_guards`` owns them.
    """
    payload = sandbox.root / "launch_payload.py"
    payload.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(sandbox.binding_root)!r})\n"
        "import sase_core_rs\n"
        "print('launched wire', sase_core_rs.WIRE_VERSION)\n",
        encoding="utf-8",
    )
    sandbox.install_binding(1)
    with sandbox.writer():
        sandbox.remove_binding()
        proc = subprocess.Popen(
            guarded_exec_argv([sys.executable, "-I", "-S", str(payload)]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                proc.wait(timeout=0.5)
            sandbox.install_binding(2)
        except BaseException:
            stop(proc)
            raise
    stdout, stderr = proc.communicate(timeout=HARNESS_TIMEOUT_SECONDS)

    assert proc.returncode == 0, stderr
    assert "launched wire 2" in stdout
