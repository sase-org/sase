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
    _normalize_bead_type,
    bead_type_chip,
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
