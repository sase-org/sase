"""Golden coverage for the shared flag-bead visual language."""

from __future__ import annotations

from datetime import date

import pytest
from rich.style import Style

from sase.ace.query_profile.profiles import beads_query_schema
from sase.ace.tui.widgets.artifacts.bead_filter_bar import BeadFilterBar
from sase.ansi_style import ANSI_RESET
from sase.bead.filter_query import parse_bead_filter_query
from sase.bead.flag_due import FlagRemovalState
from sase.bead_flag_presentation import (
    FLAG_DUE_GLYPH,
    FLAG_DUE_STYLES,
    flag_due_chip,
    flag_due_cli_cell,
    flag_due_presentation,
    flag_key_chip,
    flag_key_cli_cell,
)
from sase.bead_type_presentation import (
    BEAD_TYPE_CHIP_WIDTH,
    BEAD_TYPE_VALUES,
    bead_type_chip,
    bead_type_presentation,
)

REMOVE_BY_DATE = "2026-12-01"
REMOVE_BY_RELEASE = "0.19.0"

# Dates chosen so the three countdown labels match the epic plan's examples:
# live 84d, soon 12d, due +6d overshoot.
LIVE_TODAY = date(2026, 9, 8)
SOON_TODAY = date(2026, 11, 19)
DUE_TODAY = date(2026, 12, 7)
# Rust ANSI_TYPE_FLAG in sase-core ``bead/cli.rs``.
RUST_ANSI_TYPE_FLAG = "\x1b[38;5;209m"


def test_flag_type_glyph_and_accent_are_the_look_vocabulary() -> None:
    presentation = bead_type_presentation("flag")

    assert presentation.glyph == "⚑"
    assert presentation.accent_color == "#FF875F"
    assert FLAG_DUE_GLYPH == "⧗"
    assert presentation.chip_style == "bold black on #FF875F"
    assert presentation.label == "Flag"
    assert presentation.rich_style == "bold #FF875F"
    assert presentation.cli_style == RUST_ANSI_TYPE_FLAG
    assert BEAD_TYPE_CHIP_WIDTH == 9
    assert len(bead_type_chip("flag").plain) <= BEAD_TYPE_CHIP_WIDTH


def test_flag_cli_style_matches_rust_ansi_type_flag() -> None:
    assert bead_type_presentation("flag").cli_style == RUST_ANSI_TYPE_FLAG


def test_flag_key_chip_uses_the_type_accent_on_both_surfaces() -> None:
    chip = flag_key_chip("plugins_enabled")
    plain = flag_key_cli_cell("plugins_enabled", use_color=False)
    colored = flag_key_cli_cell("plugins_enabled", use_color=True)
    presentation = bead_type_presentation("flag")

    assert chip.plain == "⚑ plugins_enabled"
    assert Style.parse(str(chip.style)) == Style.parse(presentation.rich_style)
    assert plain == "⚑ plugins_enabled"
    assert colored == f"{RUST_ANSI_TYPE_FLAG}⚑ plugins_enabled{ANSI_RESET}"


@pytest.mark.parametrize(
    ("today", "release", "state", "label"),
    [
        (LIVE_TODAY, "0.10.0", "live", "⧗ 84d · v0.19.0"),
        (SOON_TODAY, "0.19.0", "soon", "⧗ 12d · v0.19.0"),
        (DUE_TODAY, "0.19.0", "due", "DUE ⧗ +6d"),
    ],
)
def test_due_chips_pin_all_three_countdown_states_on_both_surfaces(
    today: date,
    release: str,
    state: FlagRemovalState,
    label: str,
) -> None:
    presentation = flag_due_presentation(
        REMOVE_BY_DATE, REMOVE_BY_RELEASE, today=today, release=release
    )
    chip = flag_due_chip(
        REMOVE_BY_DATE, REMOVE_BY_RELEASE, today=today, release=release
    )
    plain = flag_due_cli_cell(
        REMOVE_BY_DATE,
        REMOVE_BY_RELEASE,
        today=today,
        release=release,
        use_color=False,
    )
    colored = flag_due_cli_cell(
        REMOVE_BY_DATE,
        REMOVE_BY_RELEASE,
        today=today,
        release=release,
        use_color=True,
    )
    style = FLAG_DUE_STYLES[state]

    assert presentation.state == state
    assert presentation.label == label
    assert presentation.style is style
    assert chip.plain == label
    assert Style.parse(str(chip.style)) == Style.parse(style.rich)
    assert plain == label
    assert colored == f"{style.cli}{label}{ANSI_RESET}"


def test_due_styles_are_the_shared_urgency_ramp() -> None:
    assert set(FLAG_DUE_STYLES) == {"live", "soon", "due"}
    assert FLAG_DUE_STYLES["live"].rich == "dim"
    assert FLAG_DUE_STYLES["soon"].rich == "bold #FFAF00"
    assert FLAG_DUE_STYLES["due"].rich == "bold reverse"
    assert FLAG_DUE_STYLES["live"].cli.startswith("\x1b[")
    assert FLAG_DUE_STYLES["soon"].cli.startswith("\x1b[")
    assert FLAG_DUE_STYLES["due"].cli == "\x1b[1;7m"


def test_soon_after_the_date_shows_calendar_overshoot_not_due() -> None:
    chip = flag_due_chip(
        REMOVE_BY_DATE, REMOVE_BY_RELEASE, today=date(2026, 12, 7), release="0.10.0"
    )

    assert chip.plain == "⧗ +6d · v0.19.0"
    assert Style.parse(str(chip.style)) == Style.parse(FLAG_DUE_STYLES["soon"].rich)


def test_derived_surfaces_accept_type_flag_from_the_type_table() -> None:
    assert "flag" in BEAD_TYPE_VALUES
    parsed = parse_bead_filter_query("type:flag")
    assert parsed.types == ("flag",)
    due = parse_bead_filter_query("due:soon -due:live")
    assert due.due == ("soon",)
    assert due.excluded_due == ("live",)

    type_field = next(
        field for field in beads_query_schema().fields if field.key == "type"
    )
    due_field = next(
        field for field in beads_query_schema().fields if field.key == "due"
    )
    assert type_field.static_values == BEAD_TYPE_VALUES
    assert "flag" in type_field.static_values
    assert type_field.hint == ", ".join(BEAD_TYPE_VALUES)
    assert due_field.static_values == ("live", "soon", "due")
    assert due_field.hint == "live, soon, or due"

    assert BeadFilterBar.STATIC_VALUE_COMPLETIONS["type"] == BEAD_TYPE_VALUES
    assert BeadFilterBar.STATIC_VALUE_COMPLETIONS["due"] == ("live", "soon", "due")
    assert dict(BeadFilterBar.KEY_COMPLETIONS)["type"] == ", ".join(BEAD_TYPE_VALUES)
    assert dict(BeadFilterBar.KEY_COMPLETIONS)["due"] == "live, soon, or due"
