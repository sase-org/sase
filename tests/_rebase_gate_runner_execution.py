"""Execution and process tests for the after-rebase gate runner."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.workflows.commit import rebase_gate_process as process
from sase.workflows.commit import rebase_gate_runner as runner
from sase.workflows.commit.rebase_gate_budget import (
    GateBudgetExhausted,
    GateWorkBudget,
)
from tests._rebase_gate_runner_helpers import (
    GateHarness,
    harness as harness,
    make_context,
    make_report,
    write_checker,
)

__all__ = [
    "harness",
    "test_cancellation_kills_and_reaps_hook_group",
    "test_cleanup_failure_keeps_decision",
    "test_excessive_output_is_bounded",
    "test_failed_log_creation_warns_without_launching",
    "test_one_budget_passes_decreasing_timeouts_and_stops_exhausted_work",
    "test_signalled_hook_reports_signal",
    "test_spawn_failure_warns",
    "test_surviving_child_is_killed_after_group_leader_exits",
    "test_timeout_kills_process_group_and_warns",
]


def test_one_budget_passes_decreasing_timeouts_and_stops_exhausted_work() -> None:
    now = [0.0]
    budget = GateWorkBudget(
        timeout_seconds=3.0,
        teardown_reserve_seconds=0.5,
        clock=lambda: now[0],
    )
    received: list[float] = []

    def query(*, timeout: float) -> None:
        received.append(timeout)
        now[0] += 0.75

    budget.run(query)
    budget.run(query)
    budget.run(query)
    budget.run(query)
    assert received == [2.5, 1.75, 1.0, 0.25]
    with pytest.raises(GateBudgetExhausted):
        budget.run(query)
    assert received == [2.5, 1.75, 1.0, 0.25]


def test_signalled_hook_reports_signal(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "kill -TERM $$")
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["timed_out"] is False
    assert harness.captured["command"]["signal"] == 15
    assert "exit_code" not in harness.captured["command"]


def test_spawn_failure_warns(harness: GateHarness, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    harness.configure(root, "true")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no fork for you")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert "no fork" in (harness.captured["command"]["spawn_error"] or "")


def test_timeout_kills_process_group_and_warns(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    # A background child inherits stdout; the group kill must still reap
    # promptly instead of hanging on the open pipe.
    harness.configure(root, "sleep 30 & exec sleep 30", timeout=0.5)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert harness.captured["command"]["timed_out"] is True
    assert outcome.duration_seconds < 8.0
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "warned"
    assert metadata["timed_out"] is True


def test_surviving_child_is_killed_after_group_leader_exits(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    pid_file = tmp_path / "child.pid"
    release_file = tmp_path / "release-child"
    alive_file = tmp_path / "child-survived"
    script = tmp_path / "descendant.py"
    script.write_text(
        "import os, signal, time\n"
        f"pid_file = {str(pid_file)!r}\n"
        f"release_file = {str(release_file)!r}\n"
        f"alive_file = {str(alive_file)!r}\n"
        "pid = os.fork()\n"
        "if pid:\n"
        "    while not os.path.exists(pid_file): time.sleep(0.01)\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "open(pid_file, 'w').write(str(os.getpid()))\n"
        "while not os.path.exists(release_file): time.sleep(0.01)\n"
        "open(alive_file, 'w').write('alive')\n",
        encoding="utf-8",
    )
    harness.configure(root, f"{sys.executable} {script}", timeout=2.0)
    harness.fake_classify("warn")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert pid_file.is_file()
    release_file.touch()

    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline and not alive_file.exists():
        time.sleep(0.01)  # sase-test-wait: observe cleanup after releasing the child
    assert not alive_file.exists()


def test_cancellation_kills_and_reaps_hook_group(
    harness: GateHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    root = tmp_path / "repo"
    root.mkdir()
    started = tmp_path / "hook-started"
    harness.configure(root, f"touch {started} && exec sleep 30", timeout=2.0)

    def cancel_after_start(*args: Any, **kwargs: Any) -> Any:
        import time

        deadline = time.monotonic() + 1
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)  # sase-test-wait: wait for the hook start marker
        raise asyncio.CancelledError()

    monkeypatch.setattr(process, "_wait_gate_process", cancel_after_start)

    with pytest.raises(asyncio.CancelledError):
        runner.run_after_rebase_gate(make_context(), str(root))

    assert started.exists()


def test_excessive_output_is_bounded(
    harness: GateHarness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.workflows.commit.hook_utils as hook_utils

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(hook_utils, "HOOK_LOG_CAP_BYTES", 1024)
    script = tmp_path / "noisy.py"
    script.write_text(
        "import os, sys\n"
        "sys.stdout.write('x' * 100000 + chr(10))\n"
        "sys.stderr.write('tail-marker' + chr(10))\n"
        "open(os.environ['SASE_REBASE_RESULT'], 'w').write"
        f"({json.dumps(json.dumps(make_report('clean')))!r})\n",
        encoding="utf-8",
    )
    harness.configure(root, f"{sys.executable} {script}")
    harness.fake_classify("pass")

    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "pass"
    assert "tail-marker" in outcome.stderr_tail
    assert outcome.metadata_path is not None
    metadata = json.loads(outcome.metadata_path.read_text(encoding="utf-8"))
    assert metadata["stdout_truncated"] is True
    paths = metadata["paths"]
    stdout_log = Path(str(paths["stdout"])).read_text(encoding="utf-8")
    assert "truncated after 1024 bytes" in stdout_log
    assert len(outcome.stdout_tail.encode("utf-8")) <= 16_384


def test_failed_log_creation_warns_without_launching(
    harness: GateHarness, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    harness.monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(blocker))
    harness.configure(root, "true")
    harness.fake_classify("pass")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("gate must not launch without evidence")

    harness.monkeypatch.setattr(subprocess, "Popen", boom)
    outcome = runner.run_after_rebase_gate(make_context(), str(root))

    assert outcome.decision["verdict"] == "warn"
    assert outcome.metadata_path is None


def test_cleanup_failure_keeps_decision(
    harness: GateHarness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil as shutil_module

    root = tmp_path / "repo"
    root.mkdir()
    hook = write_checker(
        tmp_path / "clean.py", exit_code=0, report=make_report("clean")
    )
    harness.configure(root, hook)
    harness.fake_classify("pass")

    real_rmtree = shutil_module.rmtree
    attempted: list[str] = []

    def boom(path: Any, *args: Any, **kwargs: Any) -> Any:
        attempted.append(str(path))
        if "sase-rebase-gate-" in str(path):
            raise OSError("cannot clean")
        return real_rmtree(path, *args, **kwargs)

    harness.monkeypatch.setattr(shutil_module, "rmtree", boom)
    try:
        outcome = runner.run_after_rebase_gate(make_context(), str(root))
    finally:
        for path_text in attempted:
            if "sase-rebase-gate-" in path_text:
                real_rmtree(path_text, ignore_errors=True)

    assert outcome.decision["verdict"] == "pass"
    assert "could not remove temporary directory" in capsys.readouterr().out
