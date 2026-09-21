"""Tests for the line-streaming subprocess primitive."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sase.dev_update.command import run_dev_update_command, run_recorded_command
from sase.dev_update.models import DevCommandResult, DevExecutedCommand
from sase.dev_update.stream_command import _sanitize_line, run_streaming
from sase.git_lock_retry import run_with_git_lock_retry
from sase.uv_tool.runner import run_uv

PY = sys.executable


def _collect(
    argv: list[str], **kwargs: object
) -> tuple[subprocess.CompletedProcess[str], list[tuple[str, str]]]:
    lines: list[tuple[str, str]] = []

    def on_line(stream: str, line: str) -> None:
        lines.append((stream, line))

    result = run_streaming(argv, on_line=on_line, **kwargs)  # type: ignore[arg-type]
    return result, lines


def test_per_stream_order_preserved() -> None:
    script = (
        "import sys; "
        "print('out1', flush=True); "
        "print('err1', file=sys.stderr, flush=True); "
        "print('out2', flush=True); "
        "print('err2', file=sys.stderr, flush=True)"
    )
    result, lines = _collect([PY, "-c", script])
    assert result.returncode == 0
    stdout_lines = [line for stream, line in lines if stream == "stdout"]
    stderr_lines = [line for stream, line in lines if stream == "stderr"]
    assert stdout_lines == ["out1", "out2"]
    assert stderr_lines == ["err1", "err2"]
    assert "out1" in result.stdout
    assert "err1" in result.stderr


def test_carriage_return_collapses_to_last_segment() -> None:
    script = (
        "import sys; "
        "sys.stdout.write('Downloading 10%\\rDownloading 20%\\rDone\\n'); "
        "sys.stdout.flush()"
    )
    result, lines = _collect([PY, "-c", script])
    assert result.returncode == 0
    stdout_lines = [line for stream, line in lines if stream == "stdout"]
    assert stdout_lines == ["Done"]
    # Full text stays unsanitized with the raw redraws.
    assert "\r" in result.stdout
    assert "Downloading" in result.stdout


def test_ansi_stripped_from_sink_but_kept_in_result() -> None:
    script = "print('\\x1b[31mred\\x1b[0m plain', flush=True)"
    result, lines = _collect([PY, "-c", script])
    assert result.returncode == 0
    assert lines == [("stdout", "red plain")]
    assert "\x1b[31m" in result.stdout


def test_osc_sequence_stripped() -> None:
    assert _sanitize_line("\x1b]0;title\x07hello") == "hello"
    assert _sanitize_line("a\x1b[31mb\x1b[0mc") == "abc"
    assert _sanitize_line("[red]x[/] literal") == "[red]x[/] literal"
    assert _sanitize_line("a\x00b\x1fc") == "abc"
    assert _sanitize_line("a\tb") == "a\tb"


def test_invalid_utf8_decoded_with_replace() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'\\xff\\xfe hello\\n'); "
        "sys.stdout.buffer.flush()"
    )
    result, lines = _collect([PY, "-c", script])
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert lines and "hello" in lines[0][1]


def test_timeout_raises_and_kills_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, time; "
        f"p = subprocess.Popen(['sleep', '30']); "
        f"open({str(pidfile)!r}, 'w').write(str(p.pid)); "
        "print('ready', flush=True); "
        "time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        run_streaming(
            [PY, "-c", script],
            timeout=1.0,
            on_line=lambda stream, line: None,
        )
    assert "ready" in (excinfo.value.output or "")
    grandchild_pid = int(pidfile.read_text(encoding="utf-8").strip())
    for _ in range(50):
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            break
        time.sleep(0.1)  # sase-test-wait: poll until timeout-killed grandchild reaped
    else:
        pytest.fail("grandchild sleep survived the streaming timeout")


def test_raising_callback_does_not_fail_command() -> None:
    calls: list[tuple[str, str]] = []

    def on_line(stream: str, line: str) -> None:
        calls.append((stream, line))
        raise ValueError("sink boom")

    result = run_streaming(
        [PY, "-c", "print('one', flush=True); print('two', flush=True)"],
        on_line=on_line,
    )
    assert result.returncode == 0
    assert "one" in result.stdout
    assert "two" in result.stdout
    assert len(calls) == 1


def test_keyboard_interrupt_via_callback_terminates_and_propagates() -> None:
    def on_line(stream: str, line: str) -> None:
        raise KeyboardInterrupt()

    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_streaming(
            [PY, "-c", "print('hello', flush=True); import time; time.sleep(30)"],
            timeout=30.0,
            on_line=on_line,
        )
    assert time.monotonic() - start < 10.0


def test_return_type_works_with_git_lock_retry(tmp_path: Path) -> None:
    result = run_streaming([PY, "-c", "print('hi')"])
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)

    outcome_result, outcome = run_with_git_lock_retry(
        lambda: run_streaming([PY, "-c", "print('hi')"]),
        cwd=tmp_path,
    )
    assert outcome.attempts == 1
    assert outcome_result.returncode == 0


def test_run_dev_update_command_streams_with_on_output() -> None:
    lines: list[tuple[str, str]] = []
    result = run_dev_update_command(
        (PY, "-c", "print('streamed', flush=True)"),
        on_output=lambda stream, line: lines.append((stream, line)),
    )
    assert result.returncode == 0
    assert "streamed" in result.stdout
    assert ("stdout", "streamed") in lines


def test_run_dev_update_command_git_env_preserved_with_streaming() -> None:
    lines: list[tuple[str, str]] = []
    result = run_dev_update_command(
        ("git", "--version"),
        on_output=lambda stream, line: lines.append((stream, line)),
    )
    assert result.returncode == 0
    assert lines, "expected git --version output through the streaming sink"


def test_run_recorded_command_forwards_on_output_only_when_set() -> None:
    seen: list[object] = []

    def accepting_run(
        argv: object,
        *,
        cwd: object = None,
        env: object = None,
        timeout: object = None,
        on_output: object = None,
    ) -> DevCommandResult:
        seen.append(on_output)
        return DevCommandResult(0, stdout="ok")

    commands: list[DevExecutedCommand] = []
    sink = lambda stream, line: None  # noqa: E731
    result = run_recorded_command(
        accepting_run,  # type: ignore[arg-type]
        ("echo", "hi"),
        cwd=None,
        on_output=sink,
        label="echo",
        commands=commands,
        clock=time.monotonic,
    )
    assert result.returncode == 0
    assert seen == [sink]
    assert commands and commands[0].returncode == 0

    # Without a sink the optional keyword stays unset so legacy fakes work.
    def legacy_run(argv: object, *, cwd: object = None) -> DevCommandResult:
        return DevCommandResult(0, stdout="ok")

    commands.clear()
    result = run_recorded_command(
        legacy_run,  # type: ignore[arg-type]
        ("echo", "hi"),
        cwd=None,
        label="echo",
        commands=commands,
        clock=time.monotonic,
    )
    assert result.returncode == 0


def test_run_uv_streams_with_on_output() -> None:
    lines: list[tuple[str, str]] = []
    script = "import sys; print(' + foo==1.0', file=sys.stderr, flush=True)"
    changeset = run_uv(
        [PY, "-c", script],
        on_output=lambda stream, line: lines.append((stream, line)),
    )
    assert changeset.get("foo") is not None
    assert any("foo==1.0" in line for _, line in lines)
