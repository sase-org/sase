"""Shared accessible phase-size chip presentation tests."""

from __future__ import annotations

import re

import pytest
from rich.cells import cell_len
from rich.style import Style

from sase.ansi_style import ANSI_RESET, xterm256_foreground_style
from sase.bead.model import PhaseSize
from sase.phase_size_presentation import (
    PHASE_SIZE_ABBREVIATIONS,
    PHASE_SIZE_ACCENTS,
    PHASE_SIZE_CHIP_WIDTH,
    PHASE_SIZE_STYLES,
    PHASE_SIZE_TOKEN_WIDTH,
    PHASE_SIZE_VALUES,
    PhaseSizeValue,
    normalize_phase_size,
    phase_size_chip,
    phase_size_cli_token,
)

STRIP_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _strip_sgr(text: str) -> str:
    return STRIP_SGR.sub("", text)


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


def test_phase_size_abbreviations_are_canonical_and_unique() -> None:
    assert set(PHASE_SIZE_ABBREVIATIONS) == set(PHASE_SIZE_VALUES)
    assert PHASE_SIZE_ABBREVIATIONS == {
        "xsmall": "XS",
        "small": "S",
        "medium": "M",
        "large": "L",
        "xlarge": "XL",
    }
    assert len(set(PHASE_SIZE_ABBREVIATIONS.values())) == len(PHASE_SIZE_VALUES)


def test_fixed_width_and_unavailable_phase_size_presentations_are_honest() -> None:
    fixed = phase_size_chip("small", width=PHASE_SIZE_CHIP_WIDTH)
    unavailable = phase_size_chip("invalid", unavailable_style="dim italic")

    assert fixed.plain == " small  "
    assert len(fixed.plain) == PHASE_SIZE_CHIP_WIDTH
    assert PHASE_SIZE_CHIP_WIDTH == 8
    assert unavailable.plain == "unavailable"
    assert Style.parse(str(unavailable.style)) == Style.parse("dim italic")


@pytest.mark.parametrize("value", PHASE_SIZE_VALUES)
def test_phase_size_cli_tokens_are_equal_width_and_right_aligned(
    value: PhaseSizeValue,
) -> None:
    token = phase_size_cli_token(value, use_color=False)

    assert cell_len(token) == PHASE_SIZE_TOKEN_WIDTH
    assert token == PHASE_SIZE_ABBREVIATIONS[value].rjust(PHASE_SIZE_TOKEN_WIDTH)


def test_phase_size_cli_token_colors_only_the_token_and_strips_to_plain() -> None:
    plain = phase_size_cli_token("small", use_color=False)
    colored = phase_size_cli_token("small", use_color=True)

    assert plain == " S"
    assert colored == (
        f" {xterm256_foreground_style(PHASE_SIZE_ACCENTS['small'])}S{ANSI_RESET}"
    )
    assert _strip_sgr(colored) == plain


def test_phase_size_cli_token_blanks_none_and_rejects_unknown_values() -> None:
    assert phase_size_cli_token(None, use_color=False) == " " * PHASE_SIZE_TOKEN_WIDTH

    with pytest.raises(ValueError, match="unknown phase size"):
        phase_size_cli_token("invalid", use_color=False)
