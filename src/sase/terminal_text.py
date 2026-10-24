"""Sanitize terminal-produced text before using it in prompts or wire records."""

from __future__ import annotations

import re
import unicodedata

_TERMINAL_ESCAPE_SEQUENCE = re.compile(
    r"\x1b\][\s\S]*?(?:\x07|\x1b\\)"
    r"|\x1b[PX^_][\s\S]*?\x1b\\"
    r"|\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b[ -/]+[0-~]"
    r"|\x1b[0-~]"
)


def strip_terminal_controls(text: str) -> str:
    """Remove terminal sequences and controls, then collapse overwritten lines."""
    if not _has_forbidden_controls(text):
        return text

    text = _TERMINAL_ESCAPE_SEQUENCE.sub("", text)
    text = text.replace("\r\n", "\n")
    text = "\n".join(line.rsplit("\r", 1)[-1] for line in text.split("\n"))
    return _drop_forbidden_controls(text)


def continuation_wire_text(text: str) -> str:
    """Return text accepted by Rust ``continuation::schema::validate_text``.

    Rust's ``char::is_control`` matches Unicode general category ``Cc``. This
    applies the same predicate while preserving tabs and newlines in the wire
    text.
    """
    if not _has_forbidden_controls(text):
        return text

    text = _TERMINAL_ESCAPE_SEQUENCE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _drop_forbidden_controls(text)


def _has_forbidden_controls(text: str) -> bool:
    return any(
        char not in "\n\t" and unicodedata.category(char) == "Cc" for char in text
    )


def _drop_forbidden_controls(text: str) -> str:
    return "".join(
        char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc"
    )


__all__ = ["continuation_wire_text", "strip_terminal_controls"]
