"""Shared presentation for flag-bead identity and removal urgency.

Every surface that shows a flag bead -- the CLI, the TUI, bead pages, and the
FlagTriage preview -- renders the key and the removal countdown through this
module, so the glyph, accent, wording, and urgency colors agree everywhere.

This module owns the flag glyph, coral accent, and the two chips that sit
beside a flag task-type marker:

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

from sase.ansi_style import ANSI_RESET, ansi_sgr, xterm256_foreground_style
from sase.bead.flag_due import FlagRemovalState, flag_removal_due

FLAG_GLYPH = "⚑"
FLAG_ACCENT = "#FF875F"
FLAG_CHIP_STYLE = f"bold black on {FLAG_ACCENT}"
FLAG_RICH_STYLE = f"bold {FLAG_ACCENT}"
FLAG_CLI_STYLE = xterm256_foreground_style(FLAG_ACCENT)
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
        f"{FLAG_GLYPH} {key}",
        style=FLAG_RICH_STYLE,
        no_wrap=True,
    )


def flag_key_cli_cell(key: str, *, use_color: bool) -> str:
    """Return the ``⚑ <key>`` ANSI identity cell for compact CLI rows."""
    cell = f"{FLAG_GLYPH} {key}"
    if use_color:
        return f"{FLAG_CLI_STYLE}{cell}{ANSI_RESET}"
    return cell


def flag_due_presentation(
    remove_by_date: str, remove_by_release: str, *, today: date, release: str
) -> FlagDuePresentation:
    """Return the shared countdown record for the thresholds as of *today*/*release*."""
    state = flag_removal_due(
        remove_by_date, remove_by_release, today=today, release=release
    )
    return FlagDuePresentation(
        state=state,
        label=_due_label(remove_by_date, remove_by_release, today, state),
    )


def flag_due_chip(
    remove_by_date: str, remove_by_release: str, *, today: date, release: str
) -> Text:
    """Return the urgency-graded Rich removal meter."""
    presentation = flag_due_presentation(
        remove_by_date, remove_by_release, today=today, release=release
    )
    return Text(
        presentation.label,
        style=presentation.style.rich,
        no_wrap=True,
    )


def flag_due_cli_cell(
    remove_by_date: str,
    remove_by_release: str,
    *,
    today: date,
    release: str,
    use_color: bool,
) -> str:
    """Return the urgency-graded ANSI removal meter for compact CLI rows."""
    presentation = flag_due_presentation(
        remove_by_date, remove_by_release, today=today, release=release
    )
    if use_color:
        return f"{presentation.style.cli}{presentation.label}{ANSI_RESET}"
    return presentation.label


def _due_label(
    remove_by_date: str,
    remove_by_release: str,
    today: date,
    state: FlagRemovalState,
) -> str:
    remaining = (date.fromisoformat(remove_by_date) - today).days
    if state == "due":
        return f"DUE {FLAG_DUE_GLYPH} +{-remaining}d"
    day_part = f"{remaining}d" if remaining >= 0 else f"+{-remaining}d"
    return f"{FLAG_DUE_GLYPH} {day_part} · v{remove_by_release}"


__all__ = [
    "FLAG_ACCENT",
    "FLAG_CHIP_STYLE",
    "FLAG_CLI_STYLE",
    "FLAG_DUE_GLYPH",
    "FLAG_DUE_STYLES",
    "FLAG_GLYPH",
    "FLAG_RICH_STYLE",
    "FlagDuePresentation",
    "flag_due_chip",
    "flag_due_cli_cell",
    "flag_due_presentation",
    "flag_key_chip",
    "flag_key_cli_cell",
]
