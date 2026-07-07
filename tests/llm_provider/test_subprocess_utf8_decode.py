"""Regression tests for partial UTF-8 handling in non-blocking subprocess streams.

When the Claude CLI (and other LLM CLIs) emits a multi-byte UTF-8 sequence whose
bytes land across a non-blocking read boundary, the default ``'strict'`` error
handler on the underlying ``TextIOWrapper`` raises ``UnicodeDecodeError`` and
kills the agent. ``prepare_nonblocking_text_stream`` reconfigures the wrapper
to ``errors='replace'`` so a bad partial yields ``U+FFFD`` instead of an
exception.
"""

import io
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

from sase.llm_provider._subprocess_stream import (
    prepare_nonblocking_text_stream,
    stream_json_lines,
)


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


def test_stream_json_lines_prepares_both_streams() -> None:
    """``stream_json_lines`` calls the prepare helper on stdout and stderr."""
    stdout = MagicMock(spec=io.TextIOWrapper)
    stderr = MagicMock(spec=io.TextIOWrapper)

    process = MagicMock()
    process.stdout = stdout
    process.stderr = stderr
    process.poll.return_value = 0  # already exited; loop short-circuits
    process.stdout.__iter__ = lambda self: iter([])
    process.stderr.__iter__ = lambda self: iter([])
    process.wait.return_value = 0

    handled: list[str] = []

    with (
        patch(
            "sase.llm_provider._subprocess_stream.prepare_nonblocking_text_stream"
        ) as prepare,
        patch("sase.llm_provider._subprocess_stream.os.set_blocking"),
        patch(
            "sase.llm_provider._subprocess_stream.select.select",
            return_value=([], [], []),
        ),
    ):
        stderr_content, return_code = stream_json_lines(
            process, handled.append, suppress_output=True
        )

    assert prepare.call_args_list[0].args == (stdout,)
    assert prepare.call_args_list[1].args == (stderr,)
    assert stderr_content == ""
    assert return_code == 0


def test_stream_json_lines_reassembles_partial_stdout_line() -> None:
    """Fragments from non-blocking readline are dispatched as one JSON line."""
    stdout = MagicMock(spec=io.TextIOWrapper)
    stderr = MagicMock(spec=io.TextIOWrapper)
    stdout.readline.side_effect = ['{"payload":', '"ok"}\n']

    process = MagicMock()
    process.stdout = stdout
    process.stderr = stderr
    process.poll.side_effect = [None, 0]
    process.stdout.__iter__ = lambda self: iter([])
    process.stderr.__iter__ = lambda self: iter([])
    process.wait.return_value = 0

    handled: list[str] = []

    with (
        patch("sase.llm_provider._subprocess_stream.prepare_nonblocking_text_stream"),
        patch("sase.llm_provider._subprocess_stream.os.set_blocking"),
        patch(
            "sase.llm_provider._subprocess_stream.select.select",
            side_effect=[([stdout], [], []), ([stdout], [], [])],
        ),
    ):
        stderr_content, return_code = stream_json_lines(
            process, handled.append, suppress_output=True
        )

    assert handled == ['{"payload":"ok"}\n']
    assert stderr_content == ""
    assert return_code == 0


def test_stream_json_lines_flushes_buffered_stdout_on_exit_drain() -> None:
    """A line split between non-blocking and post-exit drain still survives."""
    stdout = MagicMock(spec=io.TextIOWrapper)
    stderr = MagicMock(spec=io.TextIOWrapper)
    stdout.readline.return_value = '{"payload":'

    process = MagicMock()
    process.stdout = stdout
    process.stderr = stderr
    process.poll.return_value = 0
    process.stdout.__iter__ = lambda self: iter(['"ok"}'])
    process.stderr.__iter__ = lambda self: iter([])
    process.wait.return_value = 0

    handled: list[str] = []

    with (
        patch("sase.llm_provider._subprocess_stream.prepare_nonblocking_text_stream"),
        patch("sase.llm_provider._subprocess_stream.os.set_blocking"),
        patch(
            "sase.llm_provider._subprocess_stream.select.select",
            return_value=([stdout], [], []),
        ),
    ):
        stderr_content, return_code = stream_json_lines(
            process, handled.append, suppress_output=True
        )

    assert handled == ['{"payload":"ok"}']
    assert stderr_content == ""
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
