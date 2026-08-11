"""Tests for shared VCS-log origin presentation."""

from __future__ import annotations

from rich.cells import cell_len

from sase.vcs_log._origin_style import (
    ORIGIN_ORDER,
    build_origin_detail,
    build_origin_legend,
    origin_glyph,
)


def test_origin_legend_lists_observed_origins_in_canonical_order() -> None:
    legend = build_origin_legend(("manual", "stitch", "stitch"))

    assert legend.plain == "✦ stitch  ✎ manual"
    assert "auto" not in legend.plain


def test_origin_detail_uses_type_value_for_auto() -> None:
    assert build_origin_detail("auto", automation_type="sase init").plain == (
        "↻ auto · sase init"
    )
    assert build_origin_detail("stitch").plain == "✦ stitch · sase stitch create"
    assert build_origin_detail("manual").plain == "✎ manual · no SASE provenance"


def test_origin_glyphs_are_single_cell() -> None:
    assert {origin: cell_len(origin_glyph(origin)) for origin in ORIGIN_ORDER} == {
        "stitch": 1,
        "auto": 1,
        "manual": 1,
    }
