"""Pure tests for the shared breadcrumb-strip renderer."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.modals.trail_strip import (
    TrailStripEntry,
    append_trail_entry,
    build_trail_strip,
)


def test_plain_trail_strip_keeps_existing_shape_when_it_fits() -> None:
    strip = build_trail_strip(("aaa", "bbb", "ccc"), accent="#D787FF")

    assert strip.plain == "TRAIL  aaa › bbb › ccc"


def test_plain_trail_strip_keeps_width_based_elision() -> None:
    strip = build_trail_strip(
        ("alpha", "bravo", "charlie", "delta"),
        accent="#D787FF",
        max_width=10,
    )

    assert strip.plain == "TRAIL  alpha › … › charlie › delta"


def test_typed_trail_entries_render_kind_glyphs_and_accents() -> None:
    strip = build_trail_strip(
        (
            TrailStripEntry("sase-uk.6", kind="bead"),
            TrailStripEntry("link_traversing_pager.md", kind="plan"),
            TrailStripEntry("app.py", kind="file"),
        ),
        accent="#D787FF",
    )

    assert "◈ sase-uk.6" in strip.plain
    assert "✎ link_traversing_pager.md" in strip.plain
    assert "▤ app.py" in strip.plain


def test_typed_trail_entries_elide_by_depth() -> None:
    depth_four = build_trail_strip(
        tuple(TrailStripEntry(f"crumb-{index}", kind="file") for index in range(4)),
        accent="#FFAF5F",
    )
    depth_ten = build_trail_strip(
        tuple(TrailStripEntry(f"crumb-{index}", kind="file") for index in range(10)),
        accent="#FFAF5F",
    )

    assert depth_four.plain == "TRAIL  ⟨ …3 › ▤ crumb-3 ⟩"
    assert depth_ten.plain == "TRAIL  ⟨ …9 › ▤ crumb-9 ⟩"


def test_append_trail_entry_keeps_untyped_labels_plain() -> None:
    text = Text()
    append_trail_entry(text, TrailStripEntry("plain"))

    assert text.plain == "plain"
