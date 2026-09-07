"""Tests for pager syntax theme derivation."""

from __future__ import annotations

from textual.theme import BUILTIN_THEMES

from sase.pager.syntax import SyntaxRole
from sase.pager.syntax_theme import (
    MIN_SYNTAX_CONTRAST,
    syntax_palette_from_theme,
    _contrast_ratio,
)


def test_palette_covers_every_syntax_role_with_rich_styles() -> None:
    palette = syntax_palette_from_theme(BUILTIN_THEMES["flexoki"])

    assert set(palette.styles) == set(SyntaxRole)
    assert set(palette.rich_styles) == set(SyntaxRole)
    assert palette.styles[SyntaxRole.COMMENT].italic is True
    assert palette.styles[SyntaxRole.COMMENT].dim is False
    assert palette.styles[SyntaxRole.MARKDOWN_STRONG].bold is True
    assert palette.styles[SyntaxRole.MARKDOWN_STRONG].italic is False
    assert palette.styles[SyntaxRole.MARKDOWN_EMPHASIS].italic is True
    assert palette.styles[SyntaxRole.MARKDOWN_EMPHASIS].bold is False
    assert palette.styles[SyntaxRole.ERROR].underline is True
    assert all(style.bgcolor is None for style in palette.rich_styles.values())


def test_palette_is_readable_against_builtin_dark_and_light_backgrounds() -> None:
    for theme_name in ("textual-dark", "textual-light", "flexoki"):
        palette = syntax_palette_from_theme(BUILTIN_THEMES[theme_name])
        assert palette.signature
        for style in palette.styles.values():
            assert (
                _contrast_ratio(style.color, palette.background) >= MIN_SYNTAX_CONTRAST
            )


def test_palette_falls_back_to_neutral_colors_for_invalid_custom_theme_values() -> None:
    palette = syntax_palette_from_theme(_BrokenTheme())

    assert palette.background == "#777777"
    for style in palette.styles.values():
        assert _contrast_ratio(style.color, palette.background) >= MIN_SYNTAX_CONTRAST


class _BrokenTheme:
    foreground = "definitely-not-a-color"
    background = "#777777"
    primary = "bad"
    secondary = "bad"
    accent = "bad"
    success = "bad"
    warning = "bad"
    error = "bad"
