"""Quiet-terminal key reader for the inspect-first video view.

Session-scoped ``quiet`` mode keeps ``ECHO``/``ICANON`` off while the inspect
loop runs with the default stdin reader, so bursts typed during a render are
queued instead of flushed (``TCSAFLUSH``) or echoed. Injected readers (tests)
and non-tty stdin skip quiet mode entirely.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import tty
from collections.abc import Callable

_INSPECT_ESC_TIMEOUT_SECONDS = 0.03
_ARROW_KEY_SEQUENCES = {
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1bOC": "right",
    "\x1bOD": "left",
}


def _decode_inspect_key(sequence: str) -> str:
    """Map a raw inspect-loop byte sequence onto a key name."""

    if sequence in _ARROW_KEY_SEQUENCES:
        return _ARROW_KEY_SEQUENCES[sequence]
    return sequence


def _completed_inspect_escape(sequence: str) -> str | None:
    mapped = _ARROW_KEY_SEQUENCES.get(sequence)
    if mapped is not None:
        return mapped
    if sequence.startswith("\x1b[") and len(sequence) >= 3 and sequence[-1].isalpha():
        return _decode_inspect_key(sequence)
    if sequence.startswith("\x1bO") and len(sequence) >= 3:
        return _decode_inspect_key(sequence)
    return None


def _assemble_inspect_key(
    read_chunk: Callable[[float | None], bytes | None],
    *,
    timeout: float | None = 0.05,
    esc_timeout: float = _INSPECT_ESC_TIMEOUT_SECONDS,
) -> str | None:
    """Read one inspect key, assembling arrow escapes split across chunks.

    ``read_chunk(wait)`` returns the next bytes, or ``None`` when *wait*
    elapses. A leading ESC waits *esc_timeout* for the rest of a CSI/SS3
    sequence so a lone Escape does not steal the next key.
    """

    first = read_chunk(timeout)
    if not first:
        return None
    sequence = first.decode(errors="ignore")
    if not sequence:
        return None
    if not sequence.startswith("\x1b"):
        return sequence[:1]
    while True:
        completed = _completed_inspect_escape(sequence)
        if completed is not None:
            return completed
        more = read_chunk(esc_timeout)
        if not more:
            break
        sequence += more.decode(errors="ignore")
    return _decode_inspect_key(sequence)


def read_inspect_key(*, timeout: float | None = 0.05) -> str | None:
    """Nonblocking, escape-aware stdin reader for the video inspect loop."""

    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
    except (OSError, termios.error, ValueError):
        return None
    try:
        tty.setraw(fd, termios.TCSANOW)

        def _read_chunk(wait: float | None) -> bytes | None:
            ready, _, _ = select.select([fd], [], [], wait)
            if not ready:
                return None
            return os.read(fd, 1)

        return _assemble_inspect_key(_read_chunk, timeout=timeout)
    except (OSError, termios.error, ValueError):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def enter_quiet_terminal() -> list | None:
    """Enter session quiet mode; return saved attrs for later restore.

    Clears ``ECHO``/``ICANON``, sets ``VMIN=1``/``VTIME=0``, applied with
    ``TCSANOW`` so queued input is never flushed. ``OPOST`` and ``ISIG`` are
    left as they are. Returns ``None`` when stdin is not a usable tty.
    """

    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return None
        saved = termios.tcgetattr(fd)
    except (OSError, termios.error, ValueError):
        return None
    try:
        quiet = [
            saved[0],
            saved[1],
            saved[2],
            saved[3],
            saved[4],
            saved[5],
            list(saved[6]),
        ]
        quiet[3] = quiet[3] & ~(termios.ECHO | termios.ICANON)
        quiet[6][termios.VMIN] = 1
        quiet[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, quiet)
    except (OSError, termios.error, ValueError):
        return None
    return saved


def exit_quiet_terminal(saved: list | None) -> None:
    """Restore attributes saved by :func:`enter_quiet_terminal`."""

    if saved is None:
        return
    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError):
        return
    try:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
    except (OSError, termios.error, ValueError):
        pass


__all__ = [
    "enter_quiet_terminal",
    "exit_quiet_terminal",
    "read_inspect_key",
]
