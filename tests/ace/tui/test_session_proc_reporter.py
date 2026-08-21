"""Unit tests for session-local ACE proc reporting."""

from __future__ import annotations

import subprocess
import sys

import pytest

from sase.ace.tui._proc_observer_log import ProcLogStream
from tests.ace.tui._session_reporter import session_reporter


def _streams(reporter: object) -> list[tuple[str, ProcLogStream]]:
    snapshot = reporter.proc.log.snapshot()  # type: ignore[attr-defined]
    return [(line.text, line.stream) for line in snapshot.lines]


def test_session_reporter_records_phase_section_command_and_streams() -> None:
    reporter = session_reporter(proc_type="sase-update")

    reporter.phase("Resolving sase update")
    reporter.section("Summary")
    reporter.log("hello stdout")
    reporter.log("boom", stream="stderr")
    reporter.log("OK: done", stream="result")
    reporter.set_command(["uv", "tool", "upgrade", "sase"])

    assert reporter.proc.phase == "Resolving sase update"
    assert reporter.proc.command == ["uv", "tool", "upgrade", "sase"]
    assert _streams(reporter) == [
        ("==> Resolving sase update", "progress"),
        ("--- Summary", "header"),
        ("hello stdout", "stdout"),
        ("boom", "stderr"),
        ("OK: done", "result"),
        ("$ uv tool upgrade sase", "header"),
    ]


def test_session_reporter_log_is_bounded() -> None:
    reporter = session_reporter()
    reporter.proc.log.max_lines = 2
    reporter.proc.log.max_chars = 10_000

    reporter.log("one")
    reporter.log("two")
    reporter.log("three")

    snapshot = reporter.proc.log.snapshot()
    assert [line.text for line in snapshot.lines] == ["two", "three"]
    assert snapshot.trimmed_count == 1
    assert reporter.proc.get_live_output().startswith("... 1 earlier lines trimmed\n")


def test_session_reporter_run_streams_combined_child_output() -> None:
    reporter = session_reporter()

    result = reporter.run(
        [
            sys.executable,
            "-c",
            "import sys; print('out', flush=True); print('err', file=sys.stderr, flush=True)",
        ]
    )

    assert result.returncode == 0
    assert reporter.proc.exit_code == 0
    assert reporter.proc.command[:2] == [sys.executable, "-c"]
    texts = [text for text, _stream in _streams(reporter)]
    assert "$ " in texts[0]
    assert "out" in texts
    assert "err" in texts
    assert "out" in result.stdout
    assert "err" in result.stdout


def test_session_reporter_run_timeout_raises_with_captured_output() -> None:
    reporter = session_reporter()

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        reporter.run(
            [
                sys.executable,
                "-c",
                "import os, time; os.write(1, b'started\\n'); time.sleep(5)",
            ],
            timeout=1.0,
        )

    output = exc_info.value.output
    assert isinstance(output, str)
    assert "started" in output


def test_session_reporter_command_runner_streams_incremental_lines() -> None:
    reporter = session_reporter()
    result = reporter.command_runner()(
        (sys.executable, "-c", "print('cli-line', flush=True)")
    )

    assert result.returncode == 0
    assert "cli-line" in reporter.proc.get_live_output()
    assert "cli-line" in result.output
