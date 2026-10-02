"""Tests for pager syntax theme derivation."""

from __future__ import annotations

from textual.theme import BUILTIN_THEMES

from sase.pager.syntax import SyntaxRole
from sase.pager.syntax_theme import (
    MIN_MARKDOWN_CONTRAST,
    MIN_SYNTAX_CONTRAST,
    contrast_ratio,
    is_terminal_color,
    parse_color,
    syntax_palette_from_theme,
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
                contrast_ratio(style.color, palette.background) >= MIN_SYNTAX_CONTRAST
            )


def test_palette_falls_back_to_neutral_colors_for_invalid_custom_theme_values() -> None:
    palette = syntax_palette_from_theme(_BrokenTheme())

    assert palette.background == "#777777"
    for style in palette.styles.values():
        assert contrast_ratio(style.color, palette.background) >= MIN_SYNTAX_CONTRAST


def test_dark_background_resolves_to_the_painted_surface_not_black() -> None:
    palette = syntax_palette_from_theme(BUILTIN_THEMES["textual-dark"])

    assert palette.background == "#121212"
    assert contrast_ratio(palette.foreground, palette.background) >= (
        MIN_MARKDOWN_CONTRAST
    )


def test_markdown_hierarchy_hits_reading_contrast_on_dark_light_and_flexoki() -> None:
    for theme_name in ("textual-dark", "textual-light", "flexoki"):
        palette = syntax_palette_from_theme(BUILTIN_THEMES[theme_name])
        heading = palette.styles[SyntaxRole.MARKDOWN_HEADING]
        code = palette.styles[SyntaxRole.MARKDOWN_CODE]
        assert heading.bold is True
        assert code.bold is False
        assert (
            contrast_ratio(heading.color, palette.background) >= MIN_MARKDOWN_CONTRAST
        ), theme_name
        assert (
            contrast_ratio(code.color, palette.background) >= MIN_MARKDOWN_CONTRAST
        ), theme_name
        for role in (
            SyntaxRole.MARKDOWN_META,
            SyntaxRole.MARKDOWN_STRUCTURE,
        ):
            assert (
                contrast_ratio(palette.styles[role].color, palette.background)
                >= MIN_SYNTAX_CONTRAST
            ), (theme_name, role)


def test_terminal_native_colors_degrade_to_neutral_without_invalid_rich() -> None:
    palette = syntax_palette_from_theme(BUILTIN_THEMES["textual-ansi"])

    assert not is_terminal_color(palette.background)
    assert parse_color(palette.background) is not None
    assert palette.signature
    for style in palette.styles.values():
        assert not is_terminal_color(style.color)
        assert contrast_ratio(style.color, palette.background) >= (MIN_SYNTAX_CONTRAST)


class _BrokenTheme:
    foreground = "definitely-not-a-color"
    background = "#777777"
    primary = "bad"
    secondary = "bad"
    accent = "bad"
    success = "bad"
    warning = "bad"
    error = "bad"
