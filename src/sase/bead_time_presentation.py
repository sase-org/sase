"""Shared presentation helpers for bead creation and update timestamps.

Every surface that shows *when* a bead was created or last updated renders it
through this module, so the glyph, accent color, wording, and timezone agree
everywhere. Three density tiers are available:

- **Full** -- :func:`bead_created_label`, the labeled row on detail surfaces
  (``2026-04-28 01:34:17 EDT · 3mo ago``).
- **Compact** -- :func:`bead_created_chip` / :func:`bead_created_cli`, the
  glyph-prefixed cell on single-line rows (``⧖ 3mo``).
- **Data** -- the raw stored ISO string, which callers pass through untouched;
  this module is never involved.

The live-vs-persisted rule governs which form a surface may use: a relative age
may appear only on surfaces re-rendered on every read. Any surface whose bytes
are persisted, hashed, or reconstructed for validation (bead pages, gate
previews) must pass ``relative=False`` and render the absolute instant only,
otherwise its bytes drift as the bead ages.

"Now" is resolved through the :mod:`sase.core.time` module object rather than a
module-level ``local_now`` binding, so the test clock pins that patch
``sase.core.time.local_now`` reach this module too.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ansi_style import ANSI_RESET as _ANSI_RESET
from sase.ansi_style import xterm256_foreground_style
from sase.core import time as core_time

BEAD_CREATED_GLYPH = "⧖"
BEAD_UPDATED_GLYPH = "✎"
BEAD_TIME_ACCENT = "#5FAFAF"
BEAD_TIME_RICH_STYLE = BEAD_TIME_ACCENT
BEAD_TIME_CLI_STYLE = xterm256_foreground_style(BEAD_TIME_ACCENT)

BEAD_TIME_UNKNOWN_LABEL = "unknown"
BEAD_TIME_UNKNOWN_STYLE = "dim italic"

_INSTANT_FORMAT = "%Y-%m-%d %H:%M:%S %Z"
_DATE_FORMAT = "%Y-%m-%d"
_NOW_LABEL = "now"


def bead_instant_label(value: str | int | float | datetime | None) -> str:
    """Return the absolute configured-tz instant, or an honest placeholder.

    The format matches what bead pages already write to disk, so persisted
    surfaces can adopt this helper without moving a single byte.
    """
    parsed = core_time.parse_local(value)
    if parsed is None:
        return BEAD_TIME_UNKNOWN_LABEL
    return parsed.strftime(_INSTANT_FORMAT)


def bead_date_label(
    value: str | int | float | datetime | None,
    *,
    default: str = BEAD_TIME_UNKNOWN_LABEL,
) -> str:
    """Return the date-only ``YYYY-MM-DD`` label for dense persisted surfaces.

    Table cells and note suffixes carry only the calendar date; the full
    instant lives in the surface's identity block. Like every persisted form
    this is a pure function of *value*, so the bytes never drift.
    """
    return core_time.format_local(value, _DATE_FORMAT, default=default)


def bead_age_label(
    value: str | int | float | datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    """Return the compact elapsed-time label, or ``""`` when unparseable.

    Elapsed time is clamped at zero so clock skew renders ``now`` rather than a
    negative age. *now* exists for unit tests; production callers omit it and
    let the helper resolve the clock through :mod:`sase.core.time`.
    """
    parsed = core_time.parse_local(value)
    if parsed is None:
        return ""

    reference = core_time.local_now() if now is None else core_time.to_local(now)
    elapsed = max(0, int((reference - core_time.to_local(parsed)).total_seconds()))
    if elapsed < 60:
        return _NOW_LABEL
    minutes = elapsed // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def bead_created_label(
    value: str | int | float | datetime | None,
    *,
    relative: bool = True,
    now: datetime | None = None,
) -> str:
    """Return the full-tier creation label for a detail surface.

    Pass ``relative=False`` on every persisted, hashed, or reconstructed
    surface; the returned string is then a pure function of *value*.
    """
    instant = bead_instant_label(value)
    if not relative or instant == BEAD_TIME_UNKNOWN_LABEL:
        return instant

    age = bead_age_label(value, now=now)
    if not age:
        return instant
    if age == _NOW_LABEL:
        return f"{instant} · {_NOW_LABEL}"
    return f"{instant} · {age} ago"


def _time_chip(
    glyph: str,
    value: str | int | float | datetime | None,
    *,
    now: datetime | None,
) -> Text:
    age = bead_age_label(value, now=now)
    if not age:
        return Text("")
    return Text(f"{glyph} {age}", style=BEAD_TIME_RICH_STYLE, no_wrap=True)


def bead_created_chip(
    value: str | int | float | datetime | None,
    *,
    now: datetime | None = None,
) -> Text:
    """Return the compact ``⧖ <age>`` Rich cell, empty when unparseable."""
    return _time_chip(BEAD_CREATED_GLYPH, value, now=now)


def bead_updated_chip(
    value: str | int | float | datetime | None,
    *,
    now: datetime | None = None,
) -> Text:
    """Return the compact ``✎ <age>`` Rich cell, empty when unparseable."""
    return _time_chip(BEAD_UPDATED_GLYPH, value, now=now)


def bead_created_cli(
    value: str | int | float | datetime | None,
    *,
    use_color: bool,
    relative: bool = True,
    now: datetime | None = None,
) -> str:
    """Return the compact glyph-prefixed creation cell for ANSI CLI rows.

    Returns ``""`` when *value* is unparseable, so a caller can append the
    fragment unconditionally and simply get nothing for a bead without a
    usable timestamp.
    """
    if relative:
        body = bead_age_label(value, now=now)
    else:
        body = bead_date_label(value, default="")
    if not body:
        return ""

    cell = f"{BEAD_CREATED_GLYPH} {body}"
    if use_color:
        return f"{BEAD_TIME_CLI_STYLE}{cell}{_ANSI_RESET}"
    return cell


def suppress_duplicate_updated(
    created: str | int | float | datetime | None,
    updated: str | int | float | datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Report whether a row should omit its updated cell.

    Dense rows stay quiet when the updated cell would say nothing new: either
    there is no usable update timestamp, or it renders the same compact label
    as the creation timestamp (the common case for a freshly filed bead).
    """
    updated_age = bead_age_label(updated, now=now)
    if not updated_age:
        return True
    return updated_age == bead_age_label(created, now=now)


__all__ = [
    "BEAD_CREATED_GLYPH",
    "BEAD_TIME_ACCENT",
    "BEAD_TIME_CLI_STYLE",
    "BEAD_TIME_RICH_STYLE",
    "BEAD_TIME_UNKNOWN_LABEL",
    "BEAD_TIME_UNKNOWN_STYLE",
    "BEAD_UPDATED_GLYPH",
    "bead_age_label",
    "bead_created_chip",
    "bead_created_cli",
    "bead_created_label",
    "bead_date_label",
    "bead_instant_label",
    "bead_updated_chip",
    "suppress_duplicate_updated",
]
