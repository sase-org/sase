"""Run-loop failure and deadline tests for the release watcher."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from tests._release_watch_helpers import (
    NOW,
    FakeClock,
    Reader,
    fake_process,
    options,
    pr,
    run_payload,
    signal_values,
    watch,
)


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
