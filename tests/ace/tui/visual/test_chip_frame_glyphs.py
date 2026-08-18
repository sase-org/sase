"""Mechanical tofu audit for the current-project chip's frame glyphs.

Mirrors ``test_tab_icon_glyphs.py``: the PNG goldens render through a pinned,
system-font-free stack, so a glyph the bundled fonts do not carry rasterizes
as a ``.notdef`` box in every snapshot while looking correct in a real
terminal. The two frame rails (``▏``/``▕``) are drawn on every resolved chip,
so a future glyph swap that silently drops font coverage would otherwise ship
unnoticed.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.current_project_indicator import (
    _FRAME_LEFT,
    _FRAME_RIGHT,
)
from tests.ace.tui.visual._glyph_audit import bundled_codepoints, render_ink

pytestmark = pytest.mark.visual

_FRAME_GLYPHS: tuple[str, ...] = (_FRAME_LEFT, _FRAME_RIGHT)


@pytest.mark.parametrize("glyph", _FRAME_GLYPHS)
def test_frame_glyph_is_covered_by_a_bundled_font(glyph: str) -> None:
    missing = [char for char in glyph if ord(char) not in bundled_codepoints()]
    assert not missing, (
        f"Chip frame glyph {glyph!r} uses codepoints no bundled font covers: "
        + ", ".join(f"U+{ord(char):04X}" for char in missing)
        + ". It would rasterize as a missing-glyph box in every PNG golden. "
        "Add a font that carries it to tests/ace/tui/visual/fonts (and to "
        "renderer_env.json), or choose a covered glyph."
    )


@pytest.mark.parametrize("glyph", _FRAME_GLYPHS)
def test_frame_glyph_rasterizes_to_ink(glyph: str) -> None:
    blank = render_ink(" ")
    assert render_ink(glyph) != blank, (
        f"Chip frame glyph {glyph!r} rasterized to an empty cell, so the "
        "goldens show nothing where the chip's rail should be."
    )
