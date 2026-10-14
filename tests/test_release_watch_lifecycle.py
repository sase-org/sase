"""Run-loop, signal, close, and install tests for the release watcher.

Split from ``tests.test_release_watch``; shared builders live in
``tests._release_watch_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests._release_watch_helpers import (
    NOW,
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
    "test_close_retries_three_times_and_waits_between_attempts",
    "test_deadline_and_startup_failure_verdicts",
    "test_deadline_while_awaiting_core",
    "test_install_attempt_uses_fresh_venv_and_records_core_version",
    "test_once_preflight_prints_one_state_and_close_argv_without_running_it",
    "test_polling_sigterm_restores_handlers",
    "test_repeated_malformed_completed_reads_close_broken",
    "test_sigterm_writes_verdict_then_closes_bead",
    "test_startup_sigterm_is_deadline_and_restores_handlers",
    "test_three_consecutive_malformed_reads_write_broken_verdict",
]


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


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


def test_sigterm_writes_verdict_then_closes_bead(tmp_path: Path) -> None:
    clock = FakeClock()
    fake_signals = FakeSignals()
    process, calls = fake_process()
    output: list[str] = []

    def terminate(_seconds: float) -> None:
        fake_signals.handlers[fake_signals.SIGTERM](fake_signals.SIGTERM, None)

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(
            signal_values(
                release=pr(), full=(run(70, status="in_progress", conclusion=None),)
            )
        ),
        process=process,
        monotonic=clock.monotonic,
        sleep=terminate,
        output=output.append,
        signal_module=fake_signals,
    )

    assert watcher.run() == watch.EXIT_CODES["DEADLINE"]
    assert calls[0][0][:6] == [
        "sase",
        "bead",
        "close",
        "sase-1kx.3",
        "-R",
        "canceled",
    ]
    assert "--note" in calls[0][0]
    assert "closed on attempt 1" in watcher.close_outcome
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: DEADLINE")
    )


def test_close_retries_three_times_and_waits_between_attempts(tmp_path: Path) -> None:
    process, calls = fake_process(returncodes=[1, 1, 0])
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

    assert code == watch.EXIT_CODES["DEADLINE"]
    assert len(calls) == 3
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
    assert calls == []


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


def test_startup_sigterm_is_deadline_and_restores_handlers(tmp_path: Path) -> None:
    fake_signals = FakeSignals()
    sentinel = object()
    fake_signals.handlers[fake_signals.SIGTERM] = sentinel
    fake_signals.handlers[fake_signals.SIGINT] = sentinel
    fake_signals.handlers[fake_signals.SIGHUP] = sentinel
    process, calls = fake_process()

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
        output=lambda _line: None,
        signal_module=fake_signals,
    )

    code = watcher.run()

    assert code == watch.EXIT_CODES["DEADLINE"]
    assert watcher.final_verdict == "DEADLINE"
    assert "WATCHER_BROKEN" not in watcher.final_detail
    assert (
        (tmp_path / "release_verdict.md")
        .read_text()
        .startswith("RELEASE NOT CONFIRMED: DEADLINE")
    )
    assert calls[0][0][:4] == ["sase", "bead", "close", "sase-1kx.5.2"]
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

    assert watcher.run() == watch.EXIT_CODES["DEADLINE"]
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
