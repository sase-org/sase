"""Shared CLI duration parsing for bare-seconds / ``90s`` / ``45m`` / ``2h`` flags."""

from __future__ import annotations

import re

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smh]?)$")
_DURATION_UNIT_SECONDS = {"s": 1.0, "m": 60.0, "h": 3600.0}


def parse_cli_duration(raw: str, *, flag: str) -> tuple[float, str]:
    """Parse a bare-seconds or unit-suffixed duration flag value.

    Accepts bare seconds or ``s``/``m``/``h`` suffixed values (``90``, ``90s``,
    ``45m``, ``2h``). Returns the value in seconds plus a display label
    pairing the raw text with its resolved seconds.
    """
    text = (raw or "").strip()
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid {flag} value {raw!r}; use e.g. 90, 90s, 45m, 2h")
    value = float(match.group(1))
    unit = match.group(2) or "s"
    seconds = value * _DURATION_UNIT_SECONDS[unit]
    if seconds <= 0:
        raise ValueError(f"{flag} must be greater than zero")
    return seconds, f"{text} ({_format_cli_duration_seconds(seconds)})"


def _format_cli_duration_seconds(seconds: float) -> str:
    """Format *seconds* the way :func:`parse_cli_duration` labels its input."""
    if seconds == int(seconds):
        return f"{int(seconds)}s"
    return f"{seconds}s"


__all__ = [
    "parse_cli_duration",
]
