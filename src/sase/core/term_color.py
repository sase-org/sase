"""Shared stdout/stderr color contract for the ``sase`` CLI.

Every command that emits ANSI color to stdout or stderr resolves it here, so
a piped ``sase`` child (for example one run from the TUI Command Line, which
sets ``FORCE_COLOR=1``) renders in color the way a terminal does.

Precedence inside :func:`should_colorize`:

1. An explicit ``-c/--color`` mode (``always``/``never``) wins where it exists.
2. ``NO_COLOR`` (set to anything, including empty) means off.
3. ``FORCE_COLOR`` or ``CLICOLOR_FORCE`` (non-empty and not ``"0"``) means on.
4. Otherwise the stream's ``isatty()`` decides.

``NO_COLOR`` always wins over the force variables. ``TERM=dumb`` is treated
as off unless an explicit mode or a force variable says otherwise.

Stdin interactivity checks are intentionally out of scope: confirmation
fail-closed semantics must keep reading ``stdin.isatty()`` directly.
"""

from __future__ import annotations

import os
from typing import TextIO

_FORCE_ENV_VARS = ("FORCE_COLOR", "CLICOLOR_FORCE")


def _env_forces_color() -> bool:
    """Return whether ``FORCE_COLOR``/``CLICOLOR_FORCE`` requests color."""
    for name in _FORCE_ENV_VARS:
        value = os.environ.get(name)
        if value is not None and value != "" and value != "0":
            return True
    return False


def should_colorize(stream: TextIO | None, *, mode: str = "auto") -> bool:
    """Return whether ANSI color should be emitted to *stream*.

    *mode* is a ``-c/--color`` value: ``"always"`` forces color on,
    ``"never"`` forces it off, and ``"auto"`` (the default) resolves the
    process environment per the module contract. Unknown modes behave like
    ``"auto"``. *stream* may be ``None`` (treated as non-TTY).
    """
    normalized = (mode or "auto").strip().lower()
    if normalized == "always":
        return True
    if normalized == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if _env_forces_color():
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    if stream is None:
        return False
    try:
        isatty = getattr(stream, "isatty", None)
        return bool(isatty is not None and isatty())
    except Exception:
        return False


__all__ = ["should_colorize"]
