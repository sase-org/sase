"""Shared accessible task-type chip presentation tests."""

from __future__ import annotations

import pytest
from rich.style import Style

from sase.bead_type_presentation import BEAD_TYPE_PRESENTATIONS
from sase.task_type_presentation import (
    DEFAULT_TASK_TYPE_GLYPH,
    UNKNOWN_TASK_TYPE_GLYPH,
    UNTYPED_TASK_TYPE_GLYPH,
    format_task_type_chip,
    task_type_chip,
    task_type_cli_cell,
    task_type_presentation,
)
from sase.task_types import UNTYPED_TASK_TYPE, get_task_type_registry


def test_untyped_slug_is_a_dim_presentation_never_a_catalog_member() -> None:
    presentation = task_type_presentation("")

    assert presentation.glyph == UNTYPED_TASK_TYPE_GLYPH
    assert presentation.known is False
    assert presentation.rich_style == "dim italic"
    assert UNTYPED_TASK_TYPE not in get_task_type_registry().by_slug


def test_unknown_slug_degrades_to_a_dim_presentation_naming_the_slug() -> None:
    presentation = task_type_presentation("totally-unregistered-slug")

    assert presentation.glyph == UNKNOWN_TASK_TYPE_GLYPH
    assert presentation.known is False
    assert presentation.rich_style == "dim italic"


@pytest.mark.parametrize(
    ("slug", "glyph", "accent_color"),
    [
        ("bug", "⨯", "#FF5F5F"),
        ("ci", "⚙", "#D7D700"),
        ("feature", "✦", "#5FD75F"),
        ("flake", "≈", "#00D7D7"),
        ("memory", "▤", "#8787FF"),
    ],
)
def test_builtin_task_types_resolve_their_pinned_presentation(
    slug: str,
    glyph: str,
    accent_color: str,
) -> None:
    presentation = task_type_presentation(slug)

    assert presentation.known is True
    assert presentation.glyph == glyph
    assert presentation.accent_color == accent_color
    assert presentation.rich_style == f"bold {accent_color}"
    assert presentation.chip_style == f"bold black on {accent_color}"


def test_every_known_task_type_accent_is_pairwise_distinct_from_every_bead_type() -> (
    None
):
    task_type_accents = {
        record.task_type: task_type_presentation(record.task_type).accent_color
        for record in get_task_type_registry().records
    }
    bead_type_accents = {
        value: presentation.accent_color
        for value, presentation in BEAD_TYPE_PRESENTATIONS.items()
    }
    # The project-local `flag` task type reuses the flag issue-type accent so a
    # migrated flag bead looks identical. No other task type may share it.
    flag_accent = task_type_accents.pop("flag", None)
    if flag_accent is not None:
        assert flag_accent == bead_type_accents["flag"]
        assert flag_accent not in task_type_accents.values()

    all_accents = list(task_type_accents.values()) + list(bead_type_accents.values())
    assert len(all_accents) == len(set(all_accents)), (
        f"task-type accents {task_type_accents} collide with "
        f"bead-type accents {bead_type_accents}"
    )


def test_task_type_chip_renders_glyph_and_slug() -> None:
    chip = task_type_chip("flake")

    assert format_task_type_chip("≈", "flake") == "≈ flake"
    assert chip.plain == f" {format_task_type_chip('≈', 'flake')} "
    assert Style.parse(str(chip.style)) == Style.parse("bold black on #00D7D7")


def test_task_type_chip_for_untyped_and_unknown_slugs_is_dim() -> None:
    untyped = task_type_chip("")
    unknown = task_type_chip("not-a-real-type")

    assert untyped.plain == f" {UNTYPED_TASK_TYPE_GLYPH} untyped "
    assert Style.parse(str(untyped.style)) == Style.parse("dim italic")
    assert unknown.plain == f" {UNKNOWN_TASK_TYPE_GLYPH} not-a-real-type "
    assert Style.parse(str(unknown.style)) == Style.parse("dim italic")


def test_task_type_chip_pads_to_a_fixed_width() -> None:
    chip = task_type_chip("flake", width=20)

    assert chip.plain == " ≈ flake ".ljust(20)
    assert len(chip.plain) == 20


def test_task_type_cli_cell_renders_glyph_only() -> None:
    assert task_type_cli_cell("flake", use_color=False) == "≈"
    assert task_type_cli_cell("", use_color=False) == UNTYPED_TASK_TYPE_GLYPH

    colored = task_type_cli_cell("flake", use_color=True)
    assert colored.endswith("≈\x1b[0m")
    assert colored.startswith("\x1b[38;5;")


def test_task_type_cli_cell_pads_to_requested_width() -> None:
    cell = task_type_cli_cell("flake", use_color=False, width=4)

    assert cell == "≈   "


def test_unrecognized_glyph_falls_back_to_the_default_marker() -> None:
    # No builtin spec omits both glyph and accent, so this exercises the
    # resolver's own fallback constant directly rather than a live record.
    assert DEFAULT_TASK_TYPE_GLYPH == "•"
