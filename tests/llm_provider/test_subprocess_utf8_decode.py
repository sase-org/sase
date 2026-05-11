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
