"""Shared presentation for flag-bead identity and removal urgency.

Every surface that shows a flag bead -- the CLI, the TUI, bead pages, and the
FlagTriage preview -- renders the key and the removal countdown through this
module, so the glyph, accent, wording, and urgency colors agree everywhere.

The type glyph and coral accent live on the ``flag`` entry of
:mod:`sase.bead_type_presentation`. This module owns the two chips that sit
beside that type marker:

- :func:`flag_key_chip` / :func:`flag_key_cli_cell` -- ``⚑ plugins_enabled``,
  the flag's identity, on the type accent.
- :func:`flag_due_chip` / :func:`flag_due_cli_cell` -- the urgency-graded
  removal meter, driven by the one :func:`sase.bead.flag_due.flag_removal_due`
  predicate. Nothing here recomputes due-ness.

Callers own the clock and the current release string. Relative day counts
belong on surfaces that re-render on every read; a persisted, hashed, or
byte-compared surface (bead pages, gate previews) must not embed this
countdown unless it also pins ``today`` and ``release`` into the bytes it
compares.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rich.text import Text

from sase.ansi_style import ANSI_RESET, ansi_sgr
from sase.bead.flag_due import FlagRemovalState, flag_removal_due
from sase.bead.model import FlagRecord
from sase.bead_type_presentation import bead_type_presentation

_FLAG_TYPE = bead_type_presentation("flag")
FLAG_DUE_GLYPH = "⧗"
_FLAG_SOON_ACCENT = "#FFAF00"


@dataclass(frozen=True)
class _FlagDueStyle:
    """Rich and ANSI styling for one removal-urgency state."""

    rich: str
    cli: str


FLAG_DUE_STYLES: dict[FlagRemovalState, _FlagDueStyle] = {
    "live": _FlagDueStyle(rich="dim", cli=ansi_sgr(dim=True)),
    "soon": _FlagDueStyle(
        rich=f"bold {_FLAG_SOON_ACCENT}",
        cli=ansi_sgr(color=_FLAG_SOON_ACCENT, bold=True),
    ),
    "due": _FlagDueStyle(rich="bold reverse", cli="\x1b[1;7m"),
}


@dataclass(frozen=True)
class FlagDuePresentation:
    """Unstyled countdown label plus the shared style for one due state."""

    state: FlagRemovalState
    label: str

    @property
    def style(self) -> _FlagDueStyle:
        """Return the shared style for this presentation's due state."""
        return FLAG_DUE_STYLES[self.state]


def flag_key_chip(key: str) -> Text:
    """Return the ``⚑ <key>`` Rich identity cell on the flag type accent."""
    return Text(
        f"{_FLAG_TYPE.glyph} {key}",
        style=_FLAG_TYPE.rich_style,
        no_wrap=True,
    )


def flag_key_cli_cell(key: str, *, use_color: bool) -> str:
    """Return the ``⚑ <key>`` ANSI identity cell for compact CLI rows."""
    cell = f"{_FLAG_TYPE.glyph} {key}"
    if use_color:
        return f"{_FLAG_TYPE.cli_style}{cell}{ANSI_RESET}"
    return cell


def flag_due_presentation(
    record: FlagRecord, *, today: date, release: str
) -> FlagDuePresentation:
    """Return the shared countdown record for *record* as of *today*/*release*."""
    state = flag_removal_due(record, today=today, release=release)
    return FlagDuePresentation(state=state, label=_due_label(record, today, state))


def flag_due_chip(record: FlagRecord, *, today: date, release: str) -> Text:
    """Return the urgency-graded Rich removal meter."""
    presentation = flag_due_presentation(record, today=today, release=release)
    return Text(
        presentation.label,
        style=presentation.style.rich,
        no_wrap=True,
    )


def flag_due_cli_cell(
    record: FlagRecord, *, today: date, release: str, use_color: bool
) -> str:
    """Return the urgency-graded ANSI removal meter for compact CLI rows."""
    presentation = flag_due_presentation(record, today=today, release=release)
    if use_color:
        return f"{presentation.style.cli}{presentation.label}{ANSI_RESET}"
    return presentation.label


def _due_label(record: FlagRecord, today: date, state: FlagRemovalState) -> str:
    remaining = (date.fromisoformat(record.remove_by_date) - today).days
    if state == "due":
        return f"DUE {FLAG_DUE_GLYPH} +{-remaining}d"
    day_part = f"{remaining}d" if remaining >= 0 else f"+{-remaining}d"
    return f"{FLAG_DUE_GLYPH} {day_part} · v{record.remove_by_release}"


__all__ = [
    "FLAG_DUE_GLYPH",
    "FLAG_DUE_STYLES",
    "FlagDuePresentation",
    "flag_due_chip",
    "flag_due_cli_cell",
    "flag_due_presentation",
    "flag_key_chip",
    "flag_key_cli_cell",
]
