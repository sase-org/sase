"""Shared accessible phase-size chip presentation tests."""

from __future__ import annotations

import pytest
from rich.style import Style

from sase.bead.model import PhaseSize
from sase.phase_size_presentation import (
    PHASE_SIZE_CHIP_WIDTH,
    PHASE_SIZE_STYLES,
    PHASE_SIZE_VALUES,
    PhaseSizeValue,
    normalize_phase_size,
    phase_size_chip,
)


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        (PhaseSize.XSMALL, "xsmall"),
        ("small", "small"),
        (PhaseSize.MEDIUM, "medium"),
        ("large", "large"),
        (PhaseSize.XLARGE, "xlarge"),
        ("SMALL", None),
        (" enormous ", None),
        (None, None),
    ],
)
def test_phase_size_normalization_accepts_only_exact_known_values(
    value: object,
    normalized: str | None,
) -> None:
    assert normalize_phase_size(value) == normalized


@pytest.mark.parametrize("value", PHASE_SIZE_VALUES)
def test_phase_size_chips_keep_literal_labels_and_canonical_palette(
    value: PhaseSizeValue,
) -> None:
    chip = phase_size_chip(value)

    assert chip.plain == f" {value} "
    assert Style.parse(str(chip.style)) == Style.parse(PHASE_SIZE_STYLES[value])


def test_phase_size_palette_and_order_match_the_five_step_ramp() -> None:
    assert PHASE_SIZE_VALUES == ("xsmall", "small", "medium", "large", "xlarge")
    assert PHASE_SIZE_STYLES == {
        "xsmall": "bold black on #5FD7AF",
        "small": "bold black on #87D7FF",
        "medium": "bold black on #FFD75F",
        "large": "bold white on #D75F87",
        "xlarge": "bold white on #AF5FFF",
    }


def test_fixed_width_and_unavailable_phase_size_presentations_are_honest() -> None:
    fixed = phase_size_chip("small", width=PHASE_SIZE_CHIP_WIDTH)
    unavailable = phase_size_chip("invalid", unavailable_style="dim italic")

    assert fixed.plain == " small  "
    assert len(fixed.plain) == PHASE_SIZE_CHIP_WIDTH
    assert PHASE_SIZE_CHIP_WIDTH == 8
    assert unavailable.plain == "unavailable"
    assert Style.parse(str(unavailable.style)) == Style.parse("dim italic")
