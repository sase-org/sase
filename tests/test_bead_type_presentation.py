"""Shared accessible bead-type chip presentation tests."""

from __future__ import annotations

import pytest
from rich.style import Style

from sase.bead.model import IssueType
from sase.bead_type_presentation import (
    BEAD_TYPE_CHIP_WIDTH,
    BEAD_TYPE_PRESENTATIONS,
    BEAD_TYPE_VALUES,
    BeadTypeValue,
    _BeadTypePresentation,
    _normalize_bead_type,
    bead_type_chip,
    bead_type_cli_cell,
    bead_type_presentation,
)


def test_bead_type_presentations_follow_model_display_order() -> None:
    assert BEAD_TYPE_VALUES == ("plan", "phase", "task")
    assert tuple(BEAD_TYPE_PRESENTATIONS) == BEAD_TYPE_VALUES
    assert tuple(issue_type.value for issue_type in IssueType) == BEAD_TYPE_VALUES


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        (IssueType.PLAN, "plan"),
        ("phase", "phase"),
        (IssueType.TASK, "task"),
        ("TASK", None),
        (" follow-up ", None),
        (None, None),
    ],
)
def test_bead_type_normalization_accepts_only_exact_known_values(
    value: object,
    normalized: str | None,
) -> None:
    assert _normalize_bead_type(value) == normalized


@pytest.mark.parametrize(
    ("value", "glyph", "accent_color", "chip_style", "label"),
    [
        (IssueType.PLAN, "▸", "#FFD700", "bold black on #FFD700", "Plan"),
        (IssueType.PHASE, "↳", "#87D7FF", "bold black on #87D7FF", "Phase"),
        (IssueType.TASK, "◆", "#D787FF", "bold black on #D787FF", "Task"),
    ],
)
def test_bead_type_presentations_are_shared_across_rich_surfaces(
    value: IssueType,
    glyph: str,
    accent_color: str,
    chip_style: str,
    label: str,
) -> None:
    presentation = bead_type_presentation(value)

    assert presentation.glyph == glyph
    assert presentation.accent_color == accent_color
    assert presentation.rich_style == f"bold {accent_color}"
    assert presentation.chip_style == chip_style
    assert presentation.label == label


@pytest.mark.parametrize("value", BEAD_TYPE_VALUES)
def test_bead_type_chips_keep_literal_labels_and_canonical_palette(
    value: BeadTypeValue,
) -> None:
    chip = bead_type_chip(value)
    presentation = BEAD_TYPE_PRESENTATIONS[value]

    assert chip.plain == f" {presentation.glyph} {value} "
    assert Style.parse(str(chip.style)) == Style.parse(presentation.chip_style)


def test_fixed_width_and_unavailable_bead_type_presentations_are_honest() -> None:
    fixed = bead_type_chip("plan", width=BEAD_TYPE_CHIP_WIDTH)
    unavailable = bead_type_chip("invalid", unavailable_style="dim italic")

    assert fixed.plain == " ▸ plan  "
    assert len(fixed.plain) == BEAD_TYPE_CHIP_WIDTH
    assert BEAD_TYPE_CHIP_WIDTH == 9
    assert unavailable.plain == "unavailable"
    assert Style.parse(str(unavailable.style)) == Style.parse("dim italic")


def test_unknown_bead_type_is_not_presented() -> None:
    with pytest.raises(ValueError, match="unknown bead type"):
        bead_type_presentation("follow-up")


@pytest.mark.parametrize(
    ("value", "expected_cli_style"),
    [
        (IssueType.PLAN, "\x1b[38;5;220m"),
        (IssueType.PHASE, "\x1b[38;5;117m"),
        (IssueType.TASK, "\x1b[38;5;177m"),
    ],
)
def test_bead_type_cli_style_matches_pinned_xterm256_accent(
    value: IssueType,
    expected_cli_style: str,
) -> None:
    assert bead_type_presentation(value).cli_style == expected_cli_style


def test_bead_type_cli_style_is_derived_from_accent_color() -> None:
    """``cli_style`` must track ``accent_color`` so the two cannot drift apart."""
    presentation = _BeadTypePresentation(
        glyph="x",
        accent_color="#000000",
        chip_style="",
        label="",
    )
    assert presentation.cli_style == "\x1b[38;5;16m"

    other = _BeadTypePresentation(
        glyph="x",
        accent_color="#FFFFFF",
        chip_style="",
        label="",
    )
    assert other.cli_style == "\x1b[38;5;231m"


@pytest.mark.parametrize("value", BEAD_TYPE_VALUES)
def test_bead_type_cli_cell_renders_glyph_only(
    value: BeadTypeValue,
) -> None:
    presentation = BEAD_TYPE_PRESENTATIONS[value]

    cell = bead_type_cli_cell(value, use_color=False)
    assert cell == presentation.glyph

    colored = bead_type_cli_cell(value, use_color=True)
    assert colored == f"{presentation.cli_style}{presentation.glyph}\x1b[0m"


def test_bead_type_cli_cell_pads_to_requested_width() -> None:
    cell = bead_type_cli_cell("plan", use_color=False, width=4)

    assert cell == "▸   "


def test_bead_type_cli_cell_keeps_padding_outside_color_reset() -> None:
    presentation = BEAD_TYPE_PRESENTATIONS["plan"]

    cell = bead_type_cli_cell("plan", use_color=True, width=4)

    assert cell == f"{presentation.cli_style}▸\x1b[0m   "


def test_bead_type_cli_cell_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown bead type"):
        bead_type_cli_cell("follow-up", use_color=False)
