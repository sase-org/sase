"""Shared helpers for the ACE mechanical glyph-coverage audits.

The tab-icon and emoji audits both check the same thing against different
glyph sets: is a codepoint ACE can render covered by a bundled font, and does
it rasterize to actual ink through the pinned snapshot renderer, instead of a
``.notdef`` box no reviewer could tell apart from a real glyph by eye.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from tests.ace.tui.visual.png_diff import render_svg_to_png

FONTS_DIR = Path(__file__).with_name("fonts")

GLYPH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    '<rect width="64" height="64" fill="#000000"/>'
    '<text x="8" y="48" font-family="Fira Code,monospace" font-size="40" '
    'fill="#ffffff">{glyph}</text>'
    "</svg>"
)


@lru_cache(maxsize=1)
def bundled_codepoints() -> frozenset[int]:
    """Return every codepoint the bundled font files can render."""
    covered: set[int] = set()
    for path in sorted(FONTS_DIR.iterdir()):
        if path.suffix.lower() not in {".otf", ".ttf"}:
            continue
        covered.update(TTFont(path).getBestCmap() or {})
    return frozenset(covered)


def render_ink(glyph: str) -> bytes:
    """Rasterize one glyph through the pinned snapshot renderer."""
    return render_svg_to_png(GLYPH_SVG.format(glyph=glyph))
