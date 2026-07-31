"""Tests for shared bead status presentation metadata."""

from __future__ import annotations

import pytest

from sase.bead.model import Status
from sase.bead_status_presentation import (
    BEAD_STATUS_PRESENTATIONS,
    bead_status_display_order,
    bead_status_presentation,
)


def test_status_presentations_follow_lifecycle_display_order() -> None:
    assert bead_status_display_order() == (
        "open",
        "claimed",
        "ready",
        "in_progress",
        "closed",
    )
    assert tuple(BEAD_STATUS_PRESENTATIONS) == bead_status_display_order()
    assert tuple(status.value for status in Status) == bead_status_display_order()


@pytest.mark.parametrize(
    ("status", "cli_glyph", "tui_glyph", "cli_style", "rich_color", "label"),
    [
        (Status.OPEN, "○", "○", "\x1b[36m", "#87D7FF", "OPEN"),
        (Status.CLAIMED, "◎", "◎", "\x1b[35m", "#AF87FF", "CLAIMED"),
        (Status.READY, "◇", "◇", "\x1b[96m", "#00D7AF", "Ready"),
        (Status.IN_PROGRESS, "◐", "◐", "\x1b[33m", "#FFD700", "IN_PROGRESS"),
        (Status.CLOSED, "✓", "●", "\x1b[32m", "#5FD787", "CLOSED"),
    ],
)
def test_status_presentation_is_shared_across_cli_and_rich_surfaces(
    status: Status,
    cli_glyph: str,
    tui_glyph: str,
    cli_style: str,
    rich_color: str,
    label: str,
) -> None:
    presentation = bead_status_presentation(status)

    assert presentation.glyph == cli_glyph
    assert presentation.cli_glyph == cli_glyph
    assert presentation.tui_glyph == tui_glyph
    assert presentation.cli_style == cli_style
    assert presentation.rich_color == rich_color
    assert presentation.rich_style == f"bold {rich_color}"
    assert presentation.label == label


def test_unknown_status_is_not_normalized_or_presented() -> None:
    with pytest.raises(ValueError, match="unknown bead status"):
        bead_status_presentation("waiting")
