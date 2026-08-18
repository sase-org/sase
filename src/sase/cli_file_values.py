"""Shared ``@<path>`` resolution for SASE CLI free-text values."""

from __future__ import annotations

from pathlib import Path

AT_PATH_PREFIX = "@"
_LITERAL_AT_HINT = " (use @@ for a literal leading @)"


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


__all__ = [
    "AT_PATH_PREFIX",
    "CliFileValueError",
    "read_at_path_value",
]
