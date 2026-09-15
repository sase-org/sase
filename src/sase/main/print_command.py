"""Render the copyable command header for root ``--print-command``."""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Sequence
from typing import TextIO

_PROMPT_MARKER = "\u276f"
_ASCII_MARKER = ">"
_CONTROL_ESCAPES = {
    "\a": r"\a",
    "\b": r"\b",
    "\f": r"\f",
    "\n": r"\n",
    "\r": r"\r",
    "\t": r"\t",
    "\v": r"\v",
    "\x1b": r"\e",
}


def write_print_command_header(
    args: Sequence[str], *, stream: TextIO | None = None
) -> None:
    """Write the copyable ``sase`` invocation header and flush it."""
    output = sys.stderr if stream is None else stream
    encoding = _stream_encoding(output)
    marker = _PROMPT_MARKER if _can_encode(_PROMPT_MARKER, encoding) else _ASCII_MARKER
    if _stream_supports_color(output):
        command = _format_command(args, encoding=encoding)
        line = f"\033[2;36m{marker}\033[0m \033[1msase\033[0m{command}\n"
    else:
        line = f"{_format_print_command(args, encoding=encoding)}\n"
    _write_encoded(output, line, encoding)
    output.flush()


def _format_print_command(args: Sequence[str], *, encoding: str = "utf-8") -> str:
    """Return the unstyled command header text without its trailing newline."""
    marker = _PROMPT_MARKER if _can_encode(_PROMPT_MARKER, encoding) else _ASCII_MARKER
    return f"{marker} sase{_format_command(args, encoding=encoding)}"


def _quote_command_arg(arg: str, *, encoding: str = "utf-8") -> str:
    """Quote one argv token for bash/zsh replay."""
    if _needs_ansi_c_quote(arg, encoding=encoding):
        return _ansi_c_quote(arg, encoding=encoding)
    return shlex.quote(arg)


def _format_command(args: Sequence[str], *, encoding: str) -> str:
    if not args:
        return ""
    quoted = [_quote_command_arg(arg, encoding=encoding) for arg in args]
    return " " + " ".join(quoted)


def _needs_ansi_c_quote(arg: str, *, encoding: str) -> bool:
    return any(_is_control(char) or not _can_encode(char, encoding) for char in arg)


def _ansi_c_quote(arg: str, *, encoding: str) -> str:
    return "$'" + "".join(_ansi_c_char(char, encoding=encoding) for char in arg) + "'"


def _ansi_c_char(char: str, *, encoding: str) -> str:
    if char == "'":
        return r"\'"
    if char == "\\":
        return r"\\"
    escape = _CONTROL_ESCAPES.get(char)
    if escape is not None:
        return escape
    if _is_control(char) or not _can_encode(char, encoding):
        return _codepoint_escape(char)
    return char


def _codepoint_escape(char: str) -> str:
    codepoint = ord(char)
    if codepoint <= 0xFF:
        return f"\\x{codepoint:02x}"
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"


def _is_control(char: str) -> bool:
    return not char.isprintable()


def _stream_supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty is not None and isatty())


def _stream_encoding(stream: TextIO) -> str:
    encoding = getattr(stream, "encoding", None)
    return encoding or sys.getdefaultencoding() or "utf-8"


def _can_encode(text: str, encoding: str) -> bool:
    try:
        text.encode(encoding)
    except UnicodeError:
        return False
    return True


def _write_encoded(stream: TextIO, text: str, encoding: str) -> None:
    try:
        stream.write(text)
    except UnicodeEncodeError:
        stream.write(text.encode(encoding, errors="backslashreplace").decode(encoding))


__all__ = [
    "write_print_command_header",
]
