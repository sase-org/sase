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

import os
import subprocess
import sys
import time
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

#: The real long-lived-process guard, as ``"module:factory"``. The factory
#: runs once at process start and returns a zero-argument predicate that turns
#: true once the process must stop lazy in-process work and restart. Scheduler
#: routines use it (``Lumberjack._held_for_code_swap``).
LONG_LIVED_SWAP_GUARD = "sase.core.code_swap_epoch:long_lived_swap_guard"


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


def test_long_lived_process_never_mixes_versions_across_a_swap(
    sandbox: SwapSandbox,
) -> None:
    """The real guard stops lazy work and asks for a restart after a swap."""
    proc = sandbox.start_long_lived(guard=LONG_LIVED_SWAP_GUARD)
    try:
        with sandbox.writer():
            sandbox.install_package(2)
        reply = request_work(proc)
        assert not reply.startswith("import-error"), reply
        assert reply == "restart-requested"
        assert proc.wait(timeout=HARNESS_TIMEOUT_SECONDS) == RESTART_EXIT_CODE
    finally:
        stop(proc)


def test_long_lived_guard_holds_lazy_work_while_the_writer_is_live(
    sandbox: SwapSandbox,
) -> None:
    """Lazy work requested mid-swap is refused before it can import torn code."""
    proc = sandbox.start_long_lived(guard=LONG_LIVED_SWAP_GUARD)
    try:
        with sandbox.writer():
            assert request_work(proc) == "restart-requested"
    finally:
        stop(proc)


def test_long_lived_guard_lets_work_run_when_no_swap_happened(
    sandbox: SwapSandbox,
) -> None:
    """Control: without a swap the guarded process keeps serving work."""
    proc = sandbox.start_long_lived(guard=LONG_LIVED_SWAP_GUARD)
    try:
        assert request_work(proc) == "ok executor v1 types v1"
        assert request_work(proc) == "ok executor v1 types v1"
    finally:
        stop(proc)


# -- launches: the guarded bootstrap waits out the swap ------------------------


def test_guarded_launch_waits_out_the_swap_and_sees_the_restored_binding(
    sandbox: SwapSandbox,
) -> None:
    """Host-owned epic launches already defer across a swap.

    ``code_swap_guarded_exec`` imports nothing editable until it holds the
    shared lock, so a launch issued while the binding is missing waits, then
    execs against the reinstalled binding. ``sase run``, direct ``sase bead
    work``, and agent runner start wait in-process and re-exec instead
    (``sase.agent.launch_swap_retry``); finalizers preload their surface.
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


# -- launches: an armed CLI launch waits out the swap and reruns once ----------

_RETRYING_LAUNCH = """\
import os
import sys
import time
from pathlib import Path

from sase.agent import launch_swap_retry

signals = Path({signals!r})
is_retry = os.environ.get(launch_swap_retry.ENV_CODE_SWAP_RETRY) == "1"
launch_swap_retry.arm_code_swap_retry()
print("attempt", "retry" if is_retry else "first", flush=True)
if not is_retry:
    (signals / "armed").write_text("1", encoding="utf-8")
    deadline = time.monotonic() + {timeout!r}
    while not (signals / "go").exists():
        if time.monotonic() >= deadline:
            sys.exit(3)
        time.sleep(0.01)
error = ImportError("cannot import name 'BeforeSpawnCallback'")
launch_swap_retry.retry_launch_after_code_swap(error, [sys.executable, __file__])
print("failed as before", "child-marker", os.environ.get("SASE_CODE_SWAP_RETRY"), flush=True)
sys.exit(1)
"""


def test_armed_launch_waits_for_the_writer_then_reruns_fresh_once(
    sandbox: SwapSandbox,
) -> None:
    """A launch that booted before a swap retries once, after the writer ends.

    The child process arms the retry the way ``sase run`` does at entry. The
    swap starts after it booted and is still live when its launch fails, so
    it waits for the writer, then execs itself. The rerun sees the marker,
    cannot retry again, and fails as it would have without the retry.
    """
    script = sandbox.root / "retrying_launch.py"
    script.write_text(
        _RETRYING_LAUNCH.format(
            signals=str(sandbox.signals), timeout=HARNESS_TIMEOUT_SECONDS
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTEST_CURRENT_TEST", "PYTEST_VERSION"}
    }
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        sandbox.wait_for_signal("armed")
        with sandbox.writer():
            sandbox.release()
            # Negative window: the child must still be waiting on the writer.
            time.sleep(0.5)  # sase-test-wait: retry must hold while writer lives
            assert proc.poll() is None, "the retry must wait for the live writer"
        stdout, stderr = proc.communicate(timeout=HARNESS_TIMEOUT_SECONDS)
    finally:
        stop(proc)

    assert stdout.splitlines() == [
        "attempt first",
        "attempt retry",
        "failed as before child-marker None",
    ]
    assert "waiting for the code swap to finish" in stderr
    assert "retrying in a fresh process after a code swap" in stderr
    assert proc.returncode == 1
