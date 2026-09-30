"""Shared ``@<path>`` resolution for SASE CLI free-text values."""

from __future__ import annotations

import os
import sys
from pathlib import Path

AT_PATH_PREFIX = "@"
_LITERAL_AT_HINT = " (use @@ for a literal leading @)"
#: A whole-argument ``@<file>`` note value is read as UTF-8 text only up to
#: this many bytes; larger or binary files must be attached instead.
NOTE_TEXT_VALUE_MAX_BYTES = 262144


class CliFileValueError(ValueError):
    """A user-facing problem reading an ``@<path>`` CLI value."""


def read_at_path_value(raw: str, *, target: str) -> str:
    """Resolve one CLI text value that may name a file with ``@<path>``.

    A leading ``@@`` is an escape that stores one literal ``@``. A bare ``@``
    stays literal. Any other ``@<path>`` is read as UTF-8, verbatim, with
    ``~`` expanded. Missing, unreadable, or non-UTF-8 paths raise
    :class:`CliFileValueError` instead of falling back to the raw token.
    """

    if not raw.startswith(AT_PATH_PREFIX):
        return raw
    if raw.startswith(AT_PATH_PREFIX * 2):
        return raw[1:]
    if raw == AT_PATH_PREFIX:
        return raw
    path = Path(raw[len(AT_PATH_PREFIX) :]).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise CliFileValueError(
            f"{target}: file not found: {path}{_LITERAL_AT_HINT}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise CliFileValueError(
            f"{target}: file is not valid UTF-8: {path}{_LITERAL_AT_HINT}"
        ) from exc
    except OSError as exc:
        raise CliFileValueError(
            f"{target}: cannot read {path}: {exc}{_LITERAL_AT_HINT}"
        ) from exc


def read_note_text_value(raw: str, *, target: str, bead_id: str) -> str:
    """Resolve one bead-note text value.

    Only a whole-argument ``@<path>`` still reads note text from a file
    (UTF-8, at most :data:`NOTE_TEXT_VALUE_MAX_BYTES` bytes); inline
    ``@<path>`` references are left for the attachment authoring service,
    ``@@`` stays untouched so the scanner collapses the escape once, and a
    bare ``@`` stays literal. A binary or oversized file fails with a
    :class:`CliFileValueError` naming the attach command and the inline
    ``"… @<path>"`` form. On a TTY, a dim stderr line confirms the read.
    """

    if not raw.startswith(AT_PATH_PREFIX):
        return raw
    if raw.startswith(AT_PATH_PREFIX * 2):
        return raw
    if raw == AT_PATH_PREFIX:
        return raw
    display = raw[len(AT_PATH_PREFIX) :]
    path = Path(display).expanduser()
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise CliFileValueError(
            f"{target}: file not found: {path}{_LITERAL_AT_HINT}"
        ) from exc
    except OSError as exc:
        raise CliFileValueError(
            f"{target}: cannot read {path}: {exc}{_LITERAL_AT_HINT}"
        ) from exc
    if len(data) > NOTE_TEXT_VALUE_MAX_BYTES:
        raise CliFileValueError(
            f"{target}: file exceeds the 256 KiB note-text limit: {path} — "
            f"attach it with `sase bead attach {bead_id} {display}` or "
            f'reference it inline as "… @{display}"'
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliFileValueError(
            f"{target}: file is not valid UTF-8: {path} — attach it with "
            f"`sase bead attach {bead_id} {display}` or reference it inline "
            f'as "… @{display}"'
        ) from exc
    _confirm_note_text_read(display, bead_id, len(data))
    return text


def _confirm_note_text_read(display: str, bead_id: str, size_bytes: int) -> None:
    """Confirm a whole-argument note-text read on an interactive terminal."""
    if not sys.stderr.isatty() or os.environ.get("SASE_AGENT"):
        return
    if size_bytes < 1024:
        size = f"{size_bytes} bytes"
    else:
        size = f"{size_bytes / 1024:.1f} KiB"
    from rich.console import Console

    Console(stderr=True).print(
        f"[dim]note text read from {display} ({size}) · to attach it "
        f"instead: sase bead attach {bead_id} {display}[/dim]"
    )


__all__ = [
    "AT_PATH_PREFIX",
    "CliFileValueError",
    "NOTE_TEXT_VALUE_MAX_BYTES",
    "read_at_path_value",
    "read_note_text_value",
]
