"""Mechanical tofu audit for the emoji ``src/sase`` actually uses.

The PNG goldens render through a pinned, system-font-free stack, so a glyph
the bundled fonts do not carry rasterizes as a ``.notdef`` box in every
snapshot while looking correct in a real terminal, and a reviewer cannot
tell the two apart by eye. ``test_tab_icon_glyphs.py`` performs that check
for the notification tab icons; this module performs the analogous check
for emoji, which have no single in-module registry to audit and so are
found instead by scanning the source tree for codepoints Unicode classifies
as emoji.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import pytest

from tests.ace.tui.visual._glyph_audit import bundled_codepoints, render_ink

pytestmark = pytest.mark.visual

emoji = pytest.importorskip("emoji")

_SRC_ROOT = Path(__file__).resolve().parents[4] / "src" / "sase"


@lru_cache(maxsize=1)
def _emoji_in_use() -> tuple[str, ...]:
    """Return every emoji character literally present under ``src/sase``.

    Membership in ``emoji.EMOJI_DATA`` is the same Unicode Emoji_Presentation
    classification used to size the original gap: it separates genuine emoji
    (U+2705 WHITE HEAVY CHECK MARK) from unrelated symbols in neighboring
    blocks, such as U+29D6 WHITE HOURGLASS, a math operator that is not an
    emoji and that this audit is not the right place to chase.
    """
    found: set[str] = set()
    for path in _SRC_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found.update(char for char in text if char in emoji.EMOJI_DATA)
    return tuple(sorted(found, key=ord))


_AUDITED_EMOJI = _emoji_in_use()


def _emoji_id(char: str) -> str:
    return f"U+{ord(char):04X}"


@pytest.mark.parametrize("char", _AUDITED_EMOJI, ids=_emoji_id)
def test_emoji_in_use_is_covered_by_a_bundled_font(char: str) -> None:
    assert ord(char) in bundled_codepoints(), (
        f"Emoji {char!r} ({_emoji_id(char)} "
        f"{unicodedata.name(char, '<unnamed>')}) is used under src/sase but no "
        "bundled font covers it. It would rasterize as a missing-glyph box in "
        "every PNG golden. Add a font that carries it to "
        "tests/ace/tui/visual/fonts (and to renderer_env.json), or remove the "
        "glyph."
    )


@pytest.mark.parametrize("char", _AUDITED_EMOJI, ids=_emoji_id)
def test_emoji_in_use_rasterizes_to_ink(char: str) -> None:
    blank = render_ink(" ")
    assert render_ink(char) != blank, (
        f"Emoji {char!r} ({_emoji_id(char)}) rasterized to an empty cell, so "
        "the goldens show nothing where ACE shows a mark."
    )


def test_audited_emoji_set_is_not_empty() -> None:
    """Guard the source scan itself, not just the coverage it feeds.

    An empty result would make both parametrized tests above vacuously pass
    with zero cases, silently disabling the audit instead of failing it.
    """
    assert _AUDITED_EMOJI
