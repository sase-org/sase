"""Runner modules must not replace SIGTERM at import time.

The agent and mentor handlers belong to the runner-owned entry lifecycle so
pytest workers and other importers keep the caller's SIGTERM handler.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else os.pathsep.join((src, existing))
    return env


def _run_import_probe(module: str) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        f"""
        import signal
        import sys

        def _caller(_signum, _frame):
            pass

        signal.signal(signal.SIGTERM, _caller)
        before = signal.getsignal(signal.SIGTERM)
        __import__({module!r})
        after = signal.getsignal(signal.SIGTERM)
        if after is before:
            print("untouched")
            raise SystemExit(0)
        print("replaced", after, file=sys.stderr)
        raise SystemExit(2)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@contextmanager
def _spawn_entry(script: str) -> Iterator[subprocess.Popen[str]]:
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=_child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)


@pytest.mark.parametrize(
    "module",
    [
        "sase.axe.run_agent_runner",
        "sase.axe.mentor_runner",
    ],
)
def test_importing_runner_module_leaves_caller_sigterm_handler(
    module: str,
) -> None:
    result = _run_import_probe(module)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "untouched"


def test_agent_entry_installs_soft_sigterm_handler_and_settles() -> None:
    script = textwrap.dedent(
        """
        import signal
        import sys
        import time

        def _caller(_signum, _frame):
            pass

        signal.signal(signal.SIGTERM, _caller)
        import sase.axe.run_agent_runner as runner
        from sase.axe.runner_signals import was_killed

        if signal.getsignal(signal.SIGTERM) is not _caller:
            print("import-replaced", flush=True)
            raise SystemExit(3)

        def _wait_for_kill(env=None):
            print("ready", flush=True)
            deadline = time.time() + 10
            while not was_killed():
                if time.time() > deadline:
                    print("timeout", flush=True)
                    raise SystemExit(4)
                time.sleep(0.01)
            print("settled", flush=True)
            raise SystemExit(0)

        runner._stamp_host_path_snapshot = _wait_for_kill
        runner.main()
        """
    )
    with _spawn_entry(script) as proc:
        assert proc.stdout is not None
        assert proc.stdout.readline() == "ready\n"
        os.kill(proc.pid, signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=15)

    assert proc.returncode == 0, stderr
    assert "settled\n" in stdout
    assert "Received SIGTERM - agent was killed" in stderr


def test_mentor_entry_installs_sigterm_handler_and_settles() -> None:
    script = textwrap.dedent(
        """
        import signal
        import sys
        import time

        def _caller(_signum, _frame):
            pass

        signal.signal(signal.SIGTERM, _caller)
        import sase.axe.mentor_runner as mentor

        if signal.getsignal(signal.SIGTERM) is not _caller:
            print("import-replaced", flush=True)
            raise SystemExit(3)

        def _wait_forever(*_args, **_kwargs):
            print("ready", flush=True)
            while True:
                time.sleep(0.05)

        mentor.init_telemetry = _wait_forever
        sys.argv = [
            "mentor_runner",
            "cl",
            "project",
            "mentor",
            "out",
            "entry",
            "profile",
            "timestamp",
        ]
        mentor.main()
        """
    )
    with _spawn_entry(script) as proc:
        assert proc.stdout is not None
        assert proc.stdout.readline() == "ready\n"
        os.kill(proc.pid, signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=15)

    assert proc.returncode == 128 + signal.SIGTERM, stderr
    assert "Received SIGTERM - mentor was killed" in stderr
    assert "import-replaced" not in stdout
