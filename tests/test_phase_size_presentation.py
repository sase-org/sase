"""Shared accessible phase-size chip presentation tests."""

from __future__ import annotations

import pytest
from rich.style import Style

from sase.bead.model import PhaseSize
from sase.phase_size_presentation import (
    PHASE_SIZE_CHIP_WIDTH,
    PHASE_SIZE_STYLES,
    normalize_phase_size,
    phase_size_chip,
)


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("small", "small"),
        (PhaseSize.MEDIUM, "medium"),
        ("large", "large"),
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


@pytest.mark.parametrize("value", ["small", "medium", "large"])
def test_phase_size_chips_keep_literal_labels_and_canonical_palette(
    value: str,
) -> None:
    chip = phase_size_chip(value)

    assert chip.plain == f" {value} "
    assert Style.parse(str(chip.style)) == Style.parse(
        PHASE_SIZE_STYLES[value]  # type: ignore[index]
    )


def test_fixed_width_and_unavailable_phase_size_presentations_are_honest() -> None:
    fixed = phase_size_chip("small", width=PHASE_SIZE_CHIP_WIDTH)
    unavailable = phase_size_chip("invalid", unavailable_style="dim italic")

    assert fixed.plain == " small  "
    assert len(fixed.plain) == PHASE_SIZE_CHIP_WIDTH
    assert unavailable.plain == "unavailable"
    assert Style.parse(str(unavailable.style)) == Style.parse("dim italic")
