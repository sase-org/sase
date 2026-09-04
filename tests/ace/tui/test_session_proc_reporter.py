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


def test_session_reporter_run_can_suppress_line_logging() -> None:
    reporter = session_reporter()

    result = reporter.run(
        [sys.executable, "-c", "print('secret-json', flush=True)"],
        log_lines=False,
    )

    assert result.returncode == 0
    assert "secret-json" in result.stdout
    texts = [text for text, _stream in _streams(reporter)]
    assert "secret-json" not in texts
    assert any(text.startswith("$ ") for text in texts)


def test_session_reporter_run_on_line_survives_callback_errors() -> None:
    reporter = session_reporter()
    seen: list[str] = []

    def on_line(line: str) -> None:
        seen.append(line)
        if line == "one":
            raise RuntimeError("boom")

    result = reporter.run(
        [
            sys.executable,
            "-c",
            "print('one', flush=True); print('two', flush=True)",
        ],
        on_line=on_line,
    )

    assert result.returncode == 0
    assert seen == ["one", "two"]
    texts = [text for text, _stream in _streams(reporter)]
    assert "one" in texts
    assert "two" in texts
    assert any("on_line callback failed" in text for text in texts)
    assert any("boom" in text for text in texts)


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


def test_session_reporter_subprocess_run_fn_can_target_stderr() -> None:
    reporter = session_reporter()
    run_fn = reporter.subprocess_run_fn(output_target="stderr")

    result = run_fn(
        [sys.executable, "-c", "print('from-stdout', flush=True)"],
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert "from-stdout" in result.stderr
    assert "from-stdout" in reporter.proc.get_live_output()


def test_session_reporter_subprocess_run_fn_check_raises() -> None:
    reporter = session_reporter()
    run_fn = reporter.subprocess_run_fn()

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_fn([sys.executable, "-c", "import sys; sys.exit(2)"], check=True)

    assert exc_info.value.returncode == 2


def test_session_reporter_uv_runner_streams_through_stderr_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.uv_tool.runner import UvChangeSet

    reporter = session_reporter()
    seen: list[tuple[list[str], object]] = []

    def fake_run_uv(argv: list[str], *, run_fn: object) -> UvChangeSet:
        seen.append((list(argv), run_fn))
        completed = run_fn(  # type: ignore[operator]
            [
                sys.executable,
                "-c",
                "import sys; print('uv-err', file=sys.stderr, flush=True)",
            ]
        )
        return UvChangeSet(raw_output=completed.stderr)

    monkeypatch.setattr("sase.uv_tool.runner.run_uv", fake_run_uv)
    change_set = reporter.uv_runner()(["uv", "tool", "upgrade", "sase"])

    assert seen[0][0] == ["uv", "tool", "upgrade", "sase"]
    assert "uv-err" in change_set.raw_output
    assert "uv-err" in reporter.proc.get_live_output()
    assert "$ " in reporter.proc.get_live_output()


def test_session_reporter_dev_command_runner_streams_and_sets_phase() -> None:
    reporter = session_reporter()
    result = reporter.dev_command_runner()(
        (sys.executable, "-c", "print('dev-line', flush=True)")
    )

    assert result.returncode == 0
    assert "dev-line" in result.stdout
    assert "dev-line" in reporter.proc.get_live_output()
    assert reporter.proc.phase is not None
    assert reporter.proc.phase.startswith("Running ")
