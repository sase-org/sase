"""Content-aware geometry for the prompt preview panel.

Pure helpers with no Textual imports so sizing stays unit-testable.

Mirrors ``PreviewPanelModal > Container`` in ``styles.tcss``:
``width: 96%``, ``height: 85%``, ``max-width: 150``, ``max-height: 42``.
That TCSS block is the pre-mount fallback; the constants below must agree
with it (covered by a test that parses the TCSS).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rich.cells import cell_len

# Baseline mirrors PreviewPanelModal > Container in styles.tcss.
BASELINE_WIDTH_FRACTION = 0.96
BASELINE_HEIGHT_FRACTION = 0.85
BASELINE_MAX_WIDTH = 150
BASELINE_MAX_HEIGHT = 42

# Maximum leaves a thin dimmed backdrop so the panel still reads as floating:
# two backdrop columns on each side, one backdrop row top and bottom.
# Terminal cells are about twice as tall as wide, so this looks like an even
# gutter.
_MAX_MARGIN_COLS = 2
_MAX_MARGIN_ROWS = 1

_P95_QUANTILE = 0.95
_TAB_SIZE = 4


@dataclass(frozen=True)
class PanelGeometry:
    """Outer container size in terminal cells."""

    width: int
    height: int


def baseline_geometry(screen_w: int, screen_h: int) -> PanelGeometry:
    """Return today's fixed TCSS size, clamped to the screen."""
    width = min(
        int(screen_w * BASELINE_WIDTH_FRACTION),
        BASELINE_MAX_WIDTH,
        max(1, screen_w),
    )
    height = min(
        int(screen_h * BASELINE_HEIGHT_FRACTION),
        BASELINE_MAX_HEIGHT,
        max(1, screen_h),
    )
    return PanelGeometry(width=max(1, width), height=max(1, height))


def max_geometry(screen_w: int, screen_h: int) -> PanelGeometry:
    """Return the largest panel size, leaving a thin backdrop gutter."""
    baseline = baseline_geometry(screen_w, screen_h)
    width = max(
        screen_w - 2 * _MAX_MARGIN_COLS,
        baseline.width,
    )
    height = max(
        screen_h - 2 * _MAX_MARGIN_ROWS,
        baseline.height,
    )
    width = min(width, max(1, screen_w))
    height = min(height, max(1, screen_h))
    return PanelGeometry(width=max(1, width), height=max(1, height))


def compute_panel_geometry(
    *,
    screen_w: int,
    screen_h: int,
    content_rows: int,
    content_cols: int,
    chrome_rows: int,
    chrome_cols: int,
) -> PanelGeometry:
    """Clamp ``chrome + content`` between the baseline and the maximum."""
    baseline = baseline_geometry(screen_w, screen_h)
    maximum = max_geometry(screen_w, screen_h)
    width = max(
        baseline.width,
        min(chrome_cols + max(0, content_cols), maximum.width),
    )
    height = max(
        baseline.height,
        min(chrome_rows + max(0, content_rows), maximum.height),
    )
    return PanelGeometry(width=width, height=height)


def p95_line_width(content: str, *, tab_size: int = _TAB_SIZE) -> int:
    """Return the 95th-percentile display width of source lines.

    Lines are expanded with ``tab_size`` and measured with
    :func:`rich.cells.cell_len`, so one pathological long line (a URL, a
    minified JSON blob) cannot blow the panel out to full width.
    """
    if not content:
        return 0
    lines = content.expandtabs(tab_size).split("\n")
    if content.endswith("\n"):
        lines = lines[:-1]
    if not lines:
        return 0
    widths = sorted(cell_len(line) for line in lines)
    if not widths:
        return 0
    index = min(
        len(widths) - 1,
        max(0, math.ceil(_P95_QUANTILE * len(widths)) - 1),
    )
    return widths[index]


def gutter_width(line_count: int, *, line_numbers: bool = True) -> int:
    """Return the Syntax line-number gutter for ``line_count`` lines."""
    if not line_numbers:
        return 0
    return len(str(max(1, line_count))) + 3


__all__ = [
    "BASELINE_HEIGHT_FRACTION",
    "BASELINE_MAX_HEIGHT",
    "BASELINE_MAX_WIDTH",
    "BASELINE_WIDTH_FRACTION",
    "PanelGeometry",
    "baseline_geometry",
    "compute_panel_geometry",
    "gutter_width",
    "max_geometry",
    "p95_line_width",
]
