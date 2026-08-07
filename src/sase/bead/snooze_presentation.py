"""Shared language and palette for snoozed task bead surfaces.

Every surface that shows a snooze -- the CLI detail block, the CLI
confirmation line, the ACE Beads pane and its detail properties, and the
published bead page -- renders its wake conditions through this module, so
the wording, glyph, and accent agree everywhere.

The accent is the grey the notification indicator uses for its snoozed count
and :mod:`sase.bead_status_presentation` uses for the ``snoozed`` status: one
visual language for "deferred" across both subsystems.
"""

from __future__ import annotations

from datetime import datetime

from sase.ansi_style import ansi_sgr
from sase.bead.model import Issue, SnoozeRecord
from sase.bead_time_presentation import (
    BEAD_TIME_UNKNOWN_LABEL,
    bead_instant_label,
)
from sase.core import time as core_time

SNOOZE_ACCENT = "#6C6C6C"
SNOOZE_RICH_STYLE = f"bold {SNOOZE_ACCENT}"
SNOOZE_CLI_STYLE = ansi_sgr(color=SNOOZE_ACCENT, bold=True)
SNOOZE_SECTION_LABEL = "SNOOZE"
SNOOZE_GLYPH = "◈"

_WAKE_NOW_LABEL = "now"


def _snooze_remaining_label(
    until: str,
    *,
    now: datetime | None = None,
) -> str:
    """Return the compact time left before a wake, or ``""`` if unparseable.

    A wake time that has already arrived renders as ``now`` rather than a
    negative duration: the bead is waiting on its gate, not on the clock.
    """
    parsed = core_time.parse_local(until)
    if parsed is None:
        return ""

    reference = core_time.local_now() if now is None else core_time.to_local(now)
    remaining = int((core_time.to_local(parsed) - reference).total_seconds())
    if remaining < 60:
        return _WAKE_NOW_LABEL
    # Remaining time rounds to the nearest unit rather than truncating the way
    # an elapsed age does: a bead snoozed for `3d` is read back seconds later,
    # and reporting "in 2d" for it reads as though the command lost a day.
    minutes = round(remaining / 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = round(remaining / 3600)
    if hours < 24:
        return f"{hours}h"
    days = round(remaining / 86_400)
    if days < 30:
        return f"{days}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{round(days / 365)}y"


def snooze_until_label(
    until: str,
    *,
    relative: bool = True,
    now: datetime | None = None,
) -> str:
    """Return the full-tier wake label for a detail surface.

    Pass ``relative=False`` on every persisted, hashed, or reconstructed
    surface -- bead pages and gate previews -- so the bytes stay a pure
    function of *until* instead of drifting as the wake approaches.
    """
    instant = bead_instant_label(until)
    if not relative or instant == BEAD_TIME_UNKNOWN_LABEL:
        return instant
    remaining = _snooze_remaining_label(until, now=now)
    if not remaining:
        return instant
    if remaining == _WAKE_NOW_LABEL:
        return f"{instant} · due {_WAKE_NOW_LABEL}"
    return f"{instant} · in {remaining}"


def snooze_wake_chip(
    until: str,
    *,
    now: datetime | None = None,
) -> str:
    """Return the compact ``◈ in 3d`` cell, empty when unparseable."""
    remaining = _snooze_remaining_label(until, now=now)
    if not remaining:
        return ""
    if remaining == _WAKE_NOW_LABEL:
        return f"{SNOOZE_GLYPH} due {_WAKE_NOW_LABEL}"
    return f"{SNOOZE_GLYPH} in {remaining}"


def snooze_readiness_label(
    record: SnoozeRecord | None,
    *,
    now: datetime | None = None,
) -> str:
    """Return the readiness wording a snoozed bead shows in the TUI."""
    if record is None:
        return "snoozed"
    remaining = _snooze_remaining_label(record.until, now=now)
    if not remaining:
        return "snoozed"
    if remaining == _WAKE_NOW_LABEL:
        return f"snoozed · due {_WAKE_NOW_LABEL}"
    return f"snoozed · wakes in {remaining}"


def snooze_plus_ones_remaining(issue: Issue) -> int | None:
    """Return how many more +1s would wake *issue*, or ``None`` for no target.

    This is measured against the bead's *current* count rather than the
    baseline the snooze started from, so a bead that collected one of its two
    required +1s reports one remaining rather than two.
    """
    record = issue.snooze
    if record is None or record.plus_one_target is None:
        return None
    return max(0, record.plus_one_target - issue.plus_one_count)


def snooze_plus_one_label(issue: Issue) -> str:
    """Return the ``2 more (3 total)`` +1 wake label, or ``""`` for no target."""
    record = issue.snooze
    remaining = snooze_plus_ones_remaining(issue)
    if record is None or remaining is None or record.plus_one_target is None:
        return ""
    if remaining == 0:
        return f"target reached ({record.plus_one_target} total)"
    return f"{remaining} more ({record.plus_one_target} total)"


def snooze_summary(record: SnoozeRecord, *, now: datetime | None = None) -> str:
    """Return the one-line ``until <instant> (in 3d)`` confirmation summary."""
    instant = bead_instant_label(record.until)
    remaining = _snooze_remaining_label(record.until, now=now)
    if not remaining or instant == BEAD_TIME_UNKNOWN_LABEL:
        return f"until {instant}"
    if remaining == _WAKE_NOW_LABEL:
        return f"until {instant} (due {_WAKE_NOW_LABEL})"
    return f"until {instant} (in {remaining})"


__all__ = [
    "SNOOZE_ACCENT",
    "SNOOZE_CLI_STYLE",
    "SNOOZE_GLYPH",
    "SNOOZE_RICH_STYLE",
    "SNOOZE_SECTION_LABEL",
    "snooze_plus_one_label",
    "snooze_plus_ones_remaining",
    "snooze_readiness_label",
    "snooze_summary",
    "snooze_until_label",
    "snooze_wake_chip",
]
