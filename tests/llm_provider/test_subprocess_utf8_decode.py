"""Regression tests for partial UTF-8 handling in non-blocking subprocess streams.

When the Claude CLI (and other LLM CLIs) emits a multi-byte UTF-8 sequence whose
bytes land across a non-blocking read boundary, the default ``'strict'`` error
handler on the underlying ``TextIOWrapper`` raises ``UnicodeDecodeError`` and
kills the agent. ``prepare_nonblocking_text_stream`` reconfigures the wrapper
to ``errors='replace'`` so a bad partial yields ``U+FFFD`` instead of an
exception.
"""

import io
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider._subprocess_stream import (
    prepare_nonblocking_text_stream,
    stream_json_lines,
)
from sase.llm_provider._subprocess_muse import stream_and_parse_muse_json_output


def test_prepare_nonblocking_text_stream_reconfigures_errors_replace() -> None:
    """The helper reconfigures TextIOWrapper streams to errors='replace'."""
    stream = MagicMock(spec=io.TextIOWrapper)
    stream.fileno.return_value = 99

    with patch("sase.llm_provider._subprocess_stream.os.set_blocking") as set_blocking:
        prepare_nonblocking_text_stream(stream)

    stream.reconfigure.assert_called_once_with(errors="replace")
    set_blocking.assert_called_once_with(99, False)


def test_prepare_nonblocking_text_stream_handles_none() -> None:
    """Passing None is a safe no-op (matches the old ``if process.stdout:``)."""
    prepare_nonblocking_text_stream(None)  # must not raise


def test_prepare_nonblocking_text_stream_skips_reconfigure_for_non_textio() -> None:
    """Non-TextIOWrapper streams still get set_blocking but no reconfigure."""
    stream = MagicMock()  # no spec — does not pass isinstance check
    stream.fileno.return_value = 7

    with patch("sase.llm_provider._subprocess_stream.os.set_blocking") as set_blocking:
        prepare_nonblocking_text_stream(stream)

    stream.reconfigure.assert_not_called()
    set_blocking.assert_called_once_with(7, False)


def test_textiowrapper_with_replace_errors_swallows_partial_utf8() -> None:
    """End-to-end: a partial em-dash byte decodes to U+FFFD, not an exception.

    Simulates the exact failure mode: a multi-byte UTF-8 sequence (em-dash
    ``0xe2 0x80 0x94``) truncated to its first byte. With the default
    ``'strict'`` handler this raises ``UnicodeDecodeError``; after
    ``reconfigure(errors='replace')`` it returns the replacement character.
    """
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b"\xe2")  # leading byte of em-dash, no continuation
        os.close(write_fd)
        write_fd = -1
        binary = os.fdopen(read_fd, "rb", buffering=0)
        read_fd = -1
        wrapper = io.TextIOWrapper(binary, encoding="utf-8")  # errors='strict'

        wrapper.reconfigure(errors="replace")

        decoded = wrapper.read()
        assert decoded == "�"
    finally:
        if write_fd != -1:
            os.close(write_fd)
        if read_fd != -1:
            os.close(read_fd)


def _run_stream_in_thread(
    process: subprocess.Popen[str], handler: Callable[[str], None]
) -> tuple[threading.Thread, list[tuple[str, int]], list[BaseException]]:
    results: list[tuple[str, int]] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(stream_json_lines(process, handler, suppress_output=True))
        except BaseException as exc:  # propagate reader-thread failures to the test
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, results, failures


def _muse_delta(text: str) -> str:
    event = {
        "schema_version": 1,
        "record_type": "status",
        "durability": "ephemeral",
        "payload_type": "run.output.delta",
        "payload_schema_version": 1,
        "payload": {"kind": "run_output_delta", "text": text, "command_id": "cmd"},
    }
    return json.dumps(event) + "\n"


def _muse_terminal(text: str) -> str:
    event = {
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": "run.terminal.completed",
        "payload_schema_version": 1,
        "payload": {"terminal": "completed", "text": text, "command_id": "cmd"},
    }
    return json.dumps(event) + "\n"


def _muse_model_metadata() -> str:
    event = {
        "schema_version": 1,
        "record_type": "event",
        "durability": "durable",
        "payload_type": "run.model.configured",
        "payload_schema_version": 1,
        "payload": {"model_id": "test-model", "provider_id": "test-provider"},
    }
    return json.dumps(event) + "\n"


def test_muse_burst_is_written_to_live_reply_before_child_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gated provider's whole burst is parsed while it is still running."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    deltas = ["It doesn", "'t split caf\u00e9", " or `inline code`.\n"]
    burst = _muse_model_metadata() + "".join(_muse_delta(text) for text in deltas)
    terminal = _muse_terminal("".join(deltas))
    script = (
        "import os, sys\n"
        "data = sys.argv[1].encode()\n"
        "while data:\n"
        "    count = os.write(1, data)\n"
        "    data = data[count:]\n"
        "sys.stdin.readline()\n"
        "os.write(1, sys.argv[2].encode())\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, burst, terminal],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    results: list[tuple[str, str, int, dict[str, int]]] = []
    failures: list[BaseException] = []

    def parse() -> None:
        try:
            results.append(
                stream_and_parse_muse_json_output(process, suppress_output=True)
            )
        except BaseException as exc:  # propagate reader-thread failures to the test
            failures.append(exc)

    thread = threading.Thread(target=parse, daemon=True)
    thread.start()
    try:
        live_reply = tmp_path / "live_reply.md"
        for _ in range(500):
            if live_reply.exists() and live_reply.read_text(
                encoding="utf-8"
            ) == "".join(deltas):
                break
            if failures:
                raise failures[0]
            threading.Event().wait(0.01)
        assert live_reply.read_text(encoding="utf-8") == "".join(deltas)
        assert process.poll() is None

        assert process.stdin is not None
        process.stdin.write("release\n")
        process.stdin.flush()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not failures
        assert results[0][0] == "".join(deltas)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        thread.join(timeout=5)


def test_stream_json_lines_services_record_backlog_without_new_pipe_writes() -> None:
    """More than one dispatch budget is delivered while the child waits."""
    event_count = 600
    payload = "".join(
        json.dumps({"index": index}) + "\n" for index in range(event_count)
    )
    script = (
        "import os, sys\n"
        "data = sys.argv[1].encode()\n"
        "while data:\n"
        "    count = os.write(1, data)\n"
        "    data = data[count:]\n"
        "sys.stdin.readline()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    handled: list[str] = []
    delivered = threading.Event()

    def handle(line: str) -> None:
        handled.append(line)
        if len(handled) == event_count:
            delivered.set()

    thread, results, failures = _run_stream_in_thread(process, handle)
    try:
        assert delivered.wait(timeout=5)
        assert process.poll() is None
        assert [json.loads(line)["index"] for line in handled] == list(
            range(event_count)
        )
        assert process.stdin is not None
        process.stdin.write("release\n")
        process.stdin.flush()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not failures
        assert results == [("", 0)]
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        thread.join(timeout=5)


def test_stream_json_lines_incrementally_decodes_split_utf8_and_invalid_bytes() -> None:
    """Valid characters span descriptor reads; malformed input stays lenient."""
    script = (
        "import os\n"
        'os.write(1, b\'{"reply":"caf\\xc3\\xa9 \\xf0\\x9f\\x8c\\x8d"}\\r\\n{"bad":"\\xff"}\')\n'
        "os.write(2, b'stderr caf\\xc3\\xa9 \\xf0\\x9f\\x8c\\x8d \\xff')\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    real_read = os.read

    def one_byte_at_a_time(fd: int, size: int) -> bytes:
        return real_read(fd, min(size, 1))

    handled: list[str] = []
    with patch(
        "sase.llm_provider._subprocess_stream.os.read", side_effect=one_byte_at_a_time
    ):
        stderr_content, return_code = stream_json_lines(
            process, handled.append, suppress_output=True
        )

    assert return_code == 0
    assert handled == ['{"reply":"caf\u00e9 \U0001f30d"}\r\n', '{"bad":"\ufffd"}']
    assert stderr_content == "stderr caf\u00e9 \U0001f30d \ufffd"


def test_stream_json_lines_keeps_reading_stderr_after_stdout_eof() -> None:
    script = (
        "import os, time\n"
        "os.write(1, b'{\"done\":true}\\n')\n"
        "os.close(1)\n"
        "os.write(2, b'after stdout eof')\n"
        "time.sleep(0.05)\n"
        "os.write(2, b' and still open')\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    handled: list[str] = []
    stderr_content, return_code = stream_json_lines(
        process, handled.append, suppress_output=True
    )

    assert return_code == 0
    assert handled == ['{"done":true}\n']
    assert stderr_content == "after stdout eof and still open"


def test_stream_json_lines_dispatches_stderr_during_a_large_stdout_burst() -> None:
    event_count = 1200
    payload = "".join(
        json.dumps({"index": index}) + "\n" for index in range(event_count)
    )
    script = (
        "import os, sys\n"
        "data = sys.argv[1].encode()\n"
        "while data:\n"
        "    count = os.write(1, data)\n"
        "    data = data[count:]\n"
        "os.write(2, b'stderr-ready')\n"
        "sys.stdin.readline()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, payload],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    handled = 0
    stderr_seen = threading.Event()
    stderr_position: list[int] = []

    def handle(line: str) -> None:
        nonlocal handled
        handled += 1
        json.loads(line)

    assert process.stderr is not None
    stderr_fd = process.stderr.fileno()
    real_read = os.read

    def observe_stderr_read(fd: int, size: int) -> bytes:
        data = real_read(fd, size)
        if fd == stderr_fd and b"stderr-ready" in data:
            stderr_position.append(handled)
            stderr_seen.set()
        return data

    try:
        with patch(
            "sase.llm_provider._subprocess_stream.os.read",
            side_effect=observe_stderr_read,
        ):
            thread, results, failures = _run_stream_in_thread(process, handle)
            assert stderr_seen.wait(timeout=5)
            assert process.poll() is None
            assert 0 <= stderr_position[0] < event_count
            assert process.stdin is not None
            process.stdin.write("release\n")
            process.stdin.flush()
            thread.join(timeout=5)
            assert not thread.is_alive()
            assert not failures
            assert results == [("stderr-ready", 0)]
            assert handled == event_count
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


@pytest.mark.parametrize("exit_code", [0, 3])
def test_stream_json_lines_handles_absent_streams_and_preserves_exit_code(
    exit_code: int,
) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", f"import sys; sys.exit({exit_code})"], text=True
    )

    stderr_content, return_code = stream_json_lines(
        process, lambda _line: None, suppress_output=True
    )

    assert stderr_content == ""
    assert return_code == exit_code


def test_stream_json_lines_supports_one_absent_stream() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import os; os.write(2, b'stderr only')"],
        stdout=None,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_content, return_code = stream_json_lines(
        process, lambda _line: None, suppress_output=True
    )

    assert stderr_content == "stderr only"
    assert return_code == 0


def test_stream_json_lines_preserves_dribbled_large_json_and_trailing_line() -> None:
    """End-to-end repro: large JSON lines dribbled in chunks are not shredded."""
    script = r"""
import json
import sys
import time

events = [
    json.dumps({"index": 0, "payload": "x" * 400_000}) + "\n",
    json.dumps({"index": 1, "payload": "tail"}),
]
for event in events:
    for index in range(0, len(event), 50_000):
        sys.stdout.write(event[index:index + 50_000])
        sys.stdout.flush()
        time.sleep(0.001)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    handled: list[str] = []

    stderr_content, return_code = stream_json_lines(
        process, handled.append, suppress_output=True
    )

    assert return_code == 0
    assert stderr_content == ""
    assert len(handled) == 2
    assert handled[0].endswith("\n")
    assert '"index": 0' in handled[0]
    assert len(handled[0]) > 400_000
    assert handled[1] == '{"index": 1, "payload": "tail"}'
