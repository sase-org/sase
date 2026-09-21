"""Pure unit tests for preview panel content-aware sizing."""

from __future__ import annotations

import re
from pathlib import Path

from sase.ace.tui.modals.preview_panel_sizing import (
    BASELINE_HEIGHT_FRACTION,
    BASELINE_MAX_HEIGHT,
    BASELINE_MAX_WIDTH,
    BASELINE_WIDTH_FRACTION,
    baseline_geometry,
    compute_panel_geometry,
    max_geometry,
    p95_line_width,
)


def test_baseline_matches_historical_tcss_sizes() -> None:
    assert baseline_geometry(120, 40).width == 115
    assert baseline_geometry(120, 40).height == 34
    assert baseline_geometry(200, 60).width == 150
    assert baseline_geometry(200, 60).height == 42


def test_moderate_overflow_grows_to_chrome_plus_rows() -> None:
    geometry = compute_panel_geometry(
        screen_w=120,
        screen_h=40,
        content_rows=30,
        content_cols=10,
        chrome_rows=10,
        chrome_cols=12,
    )
    # Baseline is 115x34; chrome(10) + rows(30) = 40 would exceed it,
    # but max height is 38, so it clamps to max.
    assert geometry.height == 38
    # Width stays at baseline because 12 + 10 < 115.
    assert geometry.width == 115


def test_exact_height_growth_without_clamping() -> None:
    geometry = compute_panel_geometry(
        screen_w=200,
        screen_h=60,
        content_rows=20,
        content_cols=10,
        chrome_rows=12,
        chrome_cols=12,
    )
    # Baseline is 150x42; 12 + 20 = 32 < 42 so height stays baseline.
    assert geometry == baseline_geometry(200, 60)

    geometry = compute_panel_geometry(
        screen_w=200,
        screen_h=100,
        content_rows=40,
        content_cols=10,
        chrome_rows=10,
        chrome_cols=12,
    )
    # Baseline height for 100 rows is 42; 10 + 40 = 50 grows past it,
    # max height is 98 so no clamping.
    assert geometry.height == 50
    assert geometry.width == 150


def test_huge_content_clamps_to_screen_margins() -> None:
    geometry = compute_panel_geometry(
        screen_w=160,
        screen_h=60,
        content_rows=500,
        content_cols=500,
        chrome_rows=14,
        chrome_cols=12,
    )
    assert geometry.width == 156
    assert geometry.height == 58


def test_tiny_screens_never_exceed_screen() -> None:
    baseline = baseline_geometry(40, 12)
    maximum = max_geometry(40, 12)
    assert baseline.width <= 40
    assert baseline.height <= 12
    assert maximum.width >= baseline.width
    assert maximum.height >= baseline.height
    assert maximum.width <= 40
    assert maximum.height <= 12

    geometry = compute_panel_geometry(
        screen_w=40,
        screen_h=12,
        content_rows=100,
        content_cols=100,
        chrome_rows=10,
        chrome_cols=12,
    )
    assert geometry.width <= 40
    assert geometry.height <= 12
    assert geometry.width >= baseline.width
    assert geometry.height >= baseline.height


def test_p95_ignores_single_outlier() -> None:
    short_lines = ["x" * 10 for _ in range(19)]
    content = "\n".join([*short_lines, "y" * 1000])
    assert p95_line_width(content) == 10


def test_p95_widens_for_consistently_wide_content() -> None:
    content = "\n".join("z" * 100 for _ in range(20))
    assert p95_line_width(content) == 100


def test_tcss_constants_agree_with_stylesheet() -> None:
    tcss_path = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "sase"
        / "ace"
        / "tui"
        / "styles.tcss"
    )
    text = tcss_path.read_text(encoding="utf-8")
    block = re.search(
        r"PreviewPanelModal\s*>\s*Container\s*\{(.*?)\}",
        text,
        re.DOTALL,
    )
    assert block is not None
    body = block.group(1)
    width_pct = re.search(r"width:\s*([\d.]+)%", body)
    height_pct = re.search(r"height:\s*([\d.]+)%", body)
    max_width = re.search(r"max-width:\s*(\d+)", body)
    max_height = re.search(r"max-height:\s*(\d+)", body)
    assert width_pct is not None
    assert height_pct is not None
    assert max_width is not None
    assert max_height is not None
    assert float(width_pct.group(1)) / 100 == BASELINE_WIDTH_FRACTION
    assert float(height_pct.group(1)) / 100 == BASELINE_HEIGHT_FRACTION
    assert int(max_width.group(1)) == BASELINE_MAX_WIDTH
    assert int(max_height.group(1)) == BASELINE_MAX_HEIGHT
