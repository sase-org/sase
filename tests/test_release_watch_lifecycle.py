"""Run-loop, signal, close, and install tests for the release watcher.

Split from ``tests.test_release_watch``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests._release_watch_helpers import (
    NOW,
    SHA,
    FakeClock,
    Reader,
    engine,
    fake_process,
    options,
    pr,
    run,
    run_payload,
    signal_values,
    watch,
)

__all__ = [
    "FakeClock",
    "FakeSignals",
    "test_already_closed_bead_exits_without_watching",
    "test_close_retries_three_times_and_waits_between_attempts",
    "test_close_retry_stops_when_bead_closes_elsewhere",
    "test_close_skipped_when_bead_already_closed",
    "test_deadline_and_startup_failure_verdicts",
    "test_deadline_while_awaiting_core",
    "test_idempotent_close_check_fails_open_on_error",
    "test_install_attempt_uses_fresh_venv_and_records_core_version",
    "test_once_preflight_prints_one_state_and_close_argv_without_running_it",
    "test_polling_sigterm_restores_handlers",
    "test_repeated_malformed_completed_reads_close_broken",
    "test_signal_during_close_retry_starts_detached_closer",
    "test_sigterm_detaches_closer_with_stopped_verdict",
    "test_sigterm_then_group_sigkill_still_closes_bead",
    "test_startup_sigterm_is_stopped_and_restores_handlers",
    "test_three_consecutive_malformed_reads_write_broken_verdict",
]


def closed_read_output(bead_id: str) -> str:
    return f"↳   ✓  M {bead_id} · Fake bead ← sase-9zz  ⧖ 18h\n"


def open_read_output(bead_id: str) -> str:
    return f"▸   ◐ {bead_id} · Fake bead ← sase-9zz  ⧖ 1m\n"


def bead_aware_process(
    reads: dict[str, str],
    *,
    returncodes: list[int] | None = None,
):
    """Fake process routing `sase bead read` to canned output by bead id."""
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = list(returncodes or [0])

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            return subprocess.CompletedProcess(argv, 0, reads.get(argv[3], ""), "")
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    return process, calls


class FakeSignals:
    SIGTERM = 15
    SIGINT = 2
    SIGHUP = 1

    def __init__(self) -> None:
        self.handlers: dict[int, Any] = {}

    def getsignal(self, signum: int) -> Any:
        return self.handlers.get(signum)

    def signal(self, signum: int, handler: Any) -> None:
        self.handlers[signum] = handler


def test_three_consecutive_malformed_reads_write_broken_verdict(tmp_path: Path) -> None:
    clock = FakeClock()
    values = signal_values(release=pr())
    values["pypi"] = watch.SignalFailure("pypi", "releases was not a list")

    class BrokenReader(Reader):
        def read_signals(self) -> dict[str, object]:
            self.reads += 1
            return values

    output: list[str] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        BrokenReader(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=output.append,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert watcher.reader.reads == 3
    assert "three consecutive failed reads" in watcher.final_detail
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: WATCHER_BROKEN")
    )


def test_deadline_and_startup_failure_verdicts(tmp_path: Path) -> None:
    clock = FakeClock()
    reader = Reader()
    process, _ = fake_process()
    deadline_watcher = watch.ReleaseWatcher(
        options(tmp_path, deadline=1),
        reader,
        process=process,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert deadline_watcher.run() == watch.EXIT_CODES["DEADLINE"]

    broken_reader = Reader()
    broken_reader.validation_error = RuntimeError("unknown workflow")
    broken = watch.ReleaseWatcher(options(tmp_path), broken_reader)
    assert broken.run() == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert "startup validation failed" in broken.final_detail


def test_sigterm_detaches_closer_with_stopped_verdict(tmp_path: Path) -> None:
    clock = FakeClock()
    fake_signals = FakeSignals()
    process, calls = fake_process()
    spawns: list[tuple[list[str], dict[str, Any]]] = []

    def spawn(argv: list[str], **kwargs: Any) -> Any:
        spawns.append((argv, kwargs))
        return SimpleNamespace(pid=4242)

    def terminate(_seconds: float) -> None:
        fake_signals.handlers[fake_signals.SIGTERM](fake_signals.SIGTERM, None)

    output: list[str] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(
            signal_values(
                release=pr(), full=(run(70, status="in_progress", conclusion=None),)
            )
        ),
        process=process,
        spawn=spawn,
        monotonic=clock.monotonic,
        sleep=terminate,
        output=output.append,
        signal_module=fake_signals,
    )

    assert watcher.run() == watch.EXIT_CODES["STOPPED"]
    assert watcher.final_verdict == "STOPPED"
    bead_calls = [call for call in calls if call[0][:2] == ["sase", "bead"]]
    assert bead_calls
    assert all(call[0][2] == "read" for call in bead_calls)
    assert len(spawns) == 1
    close_argv, spawn_kwargs = spawns[0]
    assert close_argv[:6] == [
        "sase",
        "bead",
        "close",
        "sase-1kx.3",
        "-R",
        "canceled",
    ]
    assert "--note" in close_argv
    assert spawn_kwargs["start_new_session"] is True
    assert "detached closer launched" in watcher.close_outcome
    assert (tmp_path / "release_verdict.close.log").parent == tmp_path
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: STOPPED")
    )


def test_close_retries_three_times_and_waits_between_attempts(tmp_path: Path) -> None:
    process, calls = bead_aware_process({}, returncodes=[1, 1, 0])
    sleeps: list[float] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(),
        process=process,
        sleep=sleeps.append,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    code = watcher.finalize()

    closes = [call for call in calls if call[0][:3] == ["sase", "bead", "close"]]
    assert code == watch.EXIT_CODES["DEADLINE"]
    assert len(closes) == 3
    assert sleeps == [30, 30]
    assert watcher.close_outcome == "closed on attempt 3"


def test_once_preflight_prints_one_state_and_close_argv_without_running_it(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    process, calls = fake_process()
    reader = Reader(signal_values(release=pr()))
    watcher = watch.ReleaseWatcher(
        options(tmp_path, once=True, dry_run=True, close_bead="sase-1kx.3"),
        reader,
        process=process,
        output=output.append,
    )

    code = watcher.run()

    state_lines = [line for line in output if "stage=watch" in line]
    assert code == 0
    assert reader.reads == 1
    assert len(state_lines) == 1
    assert "would dispatch:full_ci" in state_lines[0]
    assert 'close_argv=["sase", "bead", "close", "sase-1kx.3"' in output[1]
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


def test_install_attempt_uses_fresh_venv_and_records_core_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if argv[-1] == "--version":
            stdout = "sase 0.18.0\n"
        elif "importlib.metadata" in argv[-1]:
            stdout = "0.40.1\n"
        else:
            stdout = ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(
        engine.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None
    )
    watcher = watch.ReleaseWatcher(options(tmp_path), Reader(), process=process)

    success, detail = watcher.install_attempt(tmp_path / "new-venv")

    assert success
    assert "sase-core-rs=0.40.1" in detail
    assert commands[0][:2] == ["/usr/bin/uv", "venv"]
    assert commands[1][1:4] == ["pip", "install", "--refresh"]
    assert commands[2][-1] == "--version"
    assert commands[3][-1].startswith("import importlib.metadata")


def test_repeated_malformed_completed_reads_close_broken(tmp_path: Path) -> None:
    clock = FakeClock()
    output: list[str] = []
    ok = signal_values(release=pr())

    class MalformedReader(Reader):
        def read_signals(self) -> dict[str, object]:
            self.reads += 1
            values = dict(ok)
            try:
                watch.parse_run(run_payload(conclusion=""), "full.yml run[0]")
            except Exception as exc:
                values["full_ci"] = watch.SignalFailure("full_ci", str(exc))
            return values

    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        MalformedReader(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=output.append,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["WATCHER_BROKEN"]
    assert watcher.reader.reads == 3
    assert "three consecutive failed reads" in watcher.final_detail
    assert "full_ci" in watcher.final_detail


def test_startup_sigterm_is_stopped_and_restores_handlers(tmp_path: Path) -> None:
    fake_signals = FakeSignals()
    sentinel = object()
    fake_signals.handlers[fake_signals.SIGTERM] = sentinel
    fake_signals.handlers[fake_signals.SIGINT] = sentinel
    fake_signals.handlers[fake_signals.SIGHUP] = sentinel
    process, calls = fake_process()
    spawns: list[tuple[list[str], dict[str, Any]]] = []

    def spawn(argv: list[str], **kwargs: Any) -> Any:
        spawns.append((argv, kwargs))
        return SimpleNamespace(pid=4242)

    class TerminatingReader(Reader):
        def validate(self) -> None:
            handler = fake_signals.handlers[fake_signals.SIGTERM]
            handler(fake_signals.SIGTERM, None)

        def read_signals(self) -> dict[str, object]:
            raise AssertionError("startup signal must not enter polling")

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.5.2"),
        TerminatingReader(),
        process=process,
        spawn=spawn,
        output=lambda _line: None,
        signal_module=fake_signals,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["STOPPED"]
    assert watcher.final_verdict == "STOPPED"
    assert "WATCHER_BROKEN" not in watcher.final_detail
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: STOPPED")
    )
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )
    assert len(spawns) == 1
    assert spawns[0][0][:4] == ["sase", "bead", "close", "sase-1kx.5.2"]
    assert spawns[0][1]["start_new_session"] is True
    assert fake_signals.handlers[fake_signals.SIGTERM] is sentinel
    assert fake_signals.handlers[fake_signals.SIGINT] is sentinel
    assert fake_signals.handlers[fake_signals.SIGHUP] is sentinel


def test_polling_sigterm_restores_handlers(tmp_path: Path) -> None:
    fake_signals = FakeSignals()
    sentinel = object()
    fake_signals.handlers[fake_signals.SIGTERM] = sentinel

    def terminate(_seconds: float) -> None:
        fake_signals.handlers[fake_signals.SIGTERM](fake_signals.SIGTERM, None)

    watcher = watch.ReleaseWatcher(
        options(tmp_path),
        Reader(
            signal_values(
                release=pr(), full=(run(70, status="in_progress", conclusion=None),)
            )
        ),
        process=fake_process()[0],
        monotonic=FakeClock().monotonic,
        sleep=terminate,
        output=lambda _line: None,
        signal_module=fake_signals,
    )

    assert watcher.run() == watch.EXIT_CODES["STOPPED"]
    assert watcher.final_verdict == "STOPPED"
    assert fake_signals.handlers[fake_signals.SIGTERM] is sentinel


def test_deadline_while_awaiting_core(tmp_path: Path) -> None:
    clock = FakeClock()
    output: list[str] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, deadline=1, poll=60, await_core_version="0.40.0"),
        Reader(
            signal_values(
                release=pr(floor="failure"),
                core=("0.39.1", NOW - timedelta(hours=3)),
            )
        ),
        process=fake_process()[0],
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        output=output.append,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["DEADLINE"]
    assert any("awaiting_core" in line for line in watcher.state_history)
    assert watcher.final_verdict == "DEADLINE"


def test_already_closed_bead_exits_without_watching(tmp_path: Path) -> None:
    process, calls = bead_aware_process(
        {"sase-1lh.5": closed_read_output("sase-1lh.5")}
    )
    output: list[str] = []
    reader = Reader(signal_values(release=pr()))
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        reader,
        process=process,
        output=output.append,
    )

    assert watcher.run() == 0
    assert reader.reads == 0
    assert any(line.startswith("ALREADY_CLOSED") for line in output)
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


def test_close_skipped_when_bead_already_closed(tmp_path: Path) -> None:
    process, calls = bead_aware_process(
        {"sase-1lh.5": closed_read_output("sase-1lh.5")}
    )
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        output=lambda _line: None,
    )
    watcher.set_verdict("FULL_CI_RED", "two red runs")

    assert watcher.finalize() == watch.EXIT_CODES["FULL_CI_RED"]
    assert watcher.close_outcome == "already closed (verified before attempt 1)"
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


def test_close_retry_stops_when_bead_closes_elsewhere(tmp_path: Path) -> None:
    reads = iter(
        ["", closed_read_output("sase-1lh.5"), closed_read_output("sase-1lh.5")]
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = [1]

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            return subprocess.CompletedProcess(argv, 0, next(reads), "")
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    sleeps: list[float] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        sleep=sleeps.append,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    assert watcher.finalize() == watch.EXIT_CODES["DEADLINE"]
    closes = [call for call in calls if call[0][:3] == ["sase", "bead", "close"]]
    assert len(closes) == 1
    assert sleeps == [30]
    assert watcher.close_outcome == "already closed (verified before attempt 2)"


def test_idempotent_close_check_fails_open_on_error(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            raise RuntimeError("bead store unreachable")
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    assert watcher.finalize() == watch.EXIT_CODES["DEADLINE"]
    assert watcher.close_outcome == "closed on attempt 1"
    assert calls[0][:4] == ["sase", "bead", "close", "sase-1lh.5"]


def test_sigterm_then_group_sigkill_still_closes_bead(tmp_path: Path) -> None:
    """A group SIGKILL 5 s after SIGTERM must not take the bead close with it."""
    repo_root = Path(__file__).parents[1]
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    close_log = tmp_path / "fake_sase_close.log"
    verdict_file = tmp_path / "release_verdict.md"
    fake_sase = fake_bin / "sase"
    fake_sase.write_text(
        "#!/bin/bash\n"
        'if [ "$1 $2" = "bead read" ]; then\n'
        '  echo "◐ $3 · fake bead [IN_PROGRESS]"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "bead close" ]; then\n'
        "  sleep 8\n"
        '  echo "CLOSE $*" >> "$FAKE_SASE_LOG"\n'
        "  exit 0\n"
        "fi\n"
        'echo "unexpected: $*" >> "$FAKE_SASE_LOG"\n'
        "exit 1\n",
        encoding="utf-8",
    )
    fake_sase.chmod(0o755)
    driver = tmp_path / "watch_driver.py"
    driver.write_text(
        "import sys\n"
        "from datetime import UTC, datetime, timedelta\n"
        "sys.path.insert(0, @@TOOLS@@)\n"
        "from _release_watch_api import ReleasePullRequest, WatchOptions, WorkflowRun\n"
        "from _release_watch_engine import ReleaseWatcher\n"
        "NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)\n"
        "SHA = @@SHA@@\n"
        "url = 'https://github.com/sase-org/sase/actions/runs/70'\n"
        "release_pr = ReleasePullRequest(299, 'chore: release 0.18.0', 'OPEN', None,\n"
        "    'CLEAN', SHA, NOW - timedelta(hours=2), 'https://example.invalid/pr',\n"
        "    {'release-core-floor-smoke': 'success'})\n"
        "in_flight = WorkflowRun(70, SHA, 'in_progress', None,\n"
        "    NOW - timedelta(hours=1), NOW - timedelta(hours=1), url)\n"
        "values = {'pypi': (), 'release_pr': release_pr, 'full_ci': (in_flight,),\n"
        "    'master_gate': (SHA, None), 'publish': (),\n"
        "    'core_pypi': ('0.40.0', NOW - timedelta(hours=3))}\n"
        "class Reader:\n"
        "    def validate(self):\n"
        "        return None\n"
        "    def read_signals(self):\n"
        "        return values\n"
        "options = WatchOptions('sase-org/sase', '0.18.0', SHA, 3600.0, 1.0, 2,\n"
        "    False, False, @@VERDICT@@, 'sase-9zz.9', None)\n"
        "raise SystemExit(ReleaseWatcher(options, Reader()).run())\n".replace(
            "@@TOOLS@@", repr(str(repo_root / "tools"))
        )
        .replace("@@SHA@@", repr(SHA))
        .replace("@@VERDICT@@", repr(str(verdict_file))),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_SASE_LOG": str(close_log),
    }
    proc = subprocess.Popen(
        [sys.executable, str(driver)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    try:
        time.sleep(4)  # sase-test-wait: let the driver install handlers and poll
        assert proc.poll() is None, "watcher exited before SIGTERM"
        os.killpg(proc.pid, signal.SIGTERM)
        assert proc.wait(timeout=30) == watch.EXIT_CODES["STOPPED"]
        time.sleep(5)  # sase-test-wait: supervisor grace before group SIGKILL
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if close_log.exists() and "CLOSE" in close_log.read_text(encoding="utf-8"):
                break
            time.sleep(0.5)  # sase-test-wait: poll for the detached closer
        else:
            raise AssertionError("detached closer never closed the fake bead")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
    assert "CLOSE" in close_log.read_text(encoding="utf-8")
    assert "sase-9zz.9" in close_log.read_text(encoding="utf-8")
    assert verdict_file.read_text(encoding="utf-8").startswith(
        "RELEASE NOT CONFIRMED: STOPPED"
    )


def test_signal_during_close_retry_starts_detached_closer(tmp_path: Path) -> None:
    fake_signals = FakeSignals()
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = [1]

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    spawns: list[tuple[list[str], dict[str, Any]]] = []

    def spawn(argv: list[str], **kwargs: Any) -> Any:
        spawns.append((argv, kwargs))
        return SimpleNamespace(pid=4242)

    def sleep_then_term(_seconds: float) -> None:
        handler = fake_signals.handlers[fake_signals.SIGTERM]
        handler(fake_signals.SIGTERM, None)

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        spawn=spawn,
        sleep=sleep_then_term,
        output=lambda _line: None,
        signal_module=fake_signals,
    )
    watcher._install_signals()
    watcher.set_verdict("DEADLINE", "time elapsed")

    code = watcher.finalize()

    assert code == watch.EXIT_CODES["DEADLINE"]
    assert watcher.final_verdict == "DEADLINE"
    assert len(spawns) == 1
    assert spawns[0][0][:4] == ["sase", "bead", "close", "sase-1lh.5"]
    assert spawns[0][1]["start_new_session"] is True
    assert "detached closer launched" in watcher.close_outcome
    closes = [call for call in calls if call[0][:3] == ["sase", "bead", "close"]]
    assert len(closes) == 1
