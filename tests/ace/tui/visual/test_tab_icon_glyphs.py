"""Mechanical tofu audit for the notification tab icons.

The PNG goldens render through a pinned, system-font-free stack, so a glyph the
bundled fonts do not carry rasterizes as a ``.notdef`` box in every snapshot
while looking correct in a real terminal. A reviewer cannot tell those apart by
eye, and the tab strip identifies narrow tabs by icon alone, so the audit is
performed here instead: every icon ACE can pick without configuration must be
covered by a bundled font and must rasterize to actual ink.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from fontTools.ttLib import TTFont
import pytest

from sase.ace.tui.widgets.notification_tab_style import (
    _BUILTIN_TAB_ICONS,
    _KIND_TAB_ICONS,
    _LAST_RESORT_TAB_ICON,
)
from sase.config.loading import load_default_config
from tests.ace.tui.visual.png_diff import render_svg_to_png

pytestmark = pytest.mark.visual

_FONTS_DIR = Path(__file__).with_name("fonts")


def _shipped_config_tab_icons() -> tuple[str, ...]:
    """Return the ``ace.notification_tabs`` icons ``default_config.yml`` ships.

    These are what a user with no overrides actually sees, and the config read
    outranks the in-module built-ins, so auditing only the Python tables would
    miss a glyph added to the shipped defaults alone.
    """
    tabs = load_default_config(files).get("ace", {}).get("notification_tabs", {})
    return tuple(
        raw["icon"]
        for raw in tabs.values()
        if isinstance(raw, dict) and isinstance(raw.get("icon"), str)
    )


# Every glyph ACE can put on the top bar with nothing configured: the shipped
# config defaults, the in-module built-ins behind them, the per-kind defaults
# for a tab ACE has never heard of, and the last-resort mark. A user-configured
# or sender-declared icon is out of scope by construction — this suite cannot
# know it, and the resolver already bounds its width.
_AUDITED_ICONS = tuple(
    dict.fromkeys(
        (
            *_shipped_config_tab_icons(),
            *_BUILTIN_TAB_ICONS.values(),
            *_KIND_TAB_ICONS.values(),
            _LAST_RESORT_TAB_ICON,
        )
    )
)

# A plane-16 private-use codepoint no bundled font has any reason to carry.
# It keeps the coverage assertion honest: a fallback font claiming every
# codepoint would satisfy it vacuously. Fira Code does map the start of the
# basic private-use area, so this deliberately sits far outside it.
_UNCOVERED_CODEPOINT = 0x10FFFD

_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
    '<rect width="64" height="64" fill="#000000"/>'
    '<text x="8" y="48" font-family="Fira Code,monospace" font-size="40" '
    'fill="#ffffff">{glyph}</text>'
    "</svg>"
)


@lru_cache(maxsize=1)
def _bundled_codepoints() -> frozenset[int]:
    """Return every codepoint the bundled font files can render."""
    covered: set[int] = set()
    for path in sorted(_FONTS_DIR.iterdir()):
        if path.suffix.lower() not in {".otf", ".ttf"}:
            continue
        covered.update(TTFont(path).getBestCmap() or {})
    return frozenset(covered)


def _render_ink(glyph: str) -> bytes:
    """Rasterize one glyph through the pinned snapshot renderer."""
    return render_svg_to_png(_ICON_SVG.format(glyph=glyph))


@pytest.mark.parametrize("icon", _AUDITED_ICONS)
def test_builtin_tab_icon_is_covered_by_a_bundled_font(icon: str) -> None:
    missing = [char for char in icon if ord(char) not in _bundled_codepoints()]
    assert not missing, (
        f"Tab icon {icon!r} uses codepoints no bundled font covers: "
        + ", ".join(f"U+{ord(char):04X}" for char in missing)
        + ". It would rasterize as a missing-glyph box in every PNG golden. "
        "Add a font that carries it to tests/ace/tui/visual/fonts (and to "
        "renderer_env.json), or choose a covered glyph."
    )


@pytest.mark.parametrize("icon", _AUDITED_ICONS)
def test_builtin_tab_icon_rasterizes_to_ink(icon: str) -> None:
    blank = _render_ink(" ")
    assert _render_ink(icon) != blank, (
        f"Tab icon {icon!r} rasterized to an empty cell, so the goldens show "
        "nothing where the top bar shows a mark."
    )


def test_coverage_audit_is_not_vacuous() -> None:
    assert _UNCOVERED_CODEPOINT not in _bundled_codepoints()
