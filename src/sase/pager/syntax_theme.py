"""Theme-adaptive syntax palette for pager source roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
from types import MappingProxyType
from typing import Any

from rich.style import Style
from textual.color import Color

from sase.pager.syntax import SyntaxRole
from sase.xprompt.highlight_theme import HighlightStyle, derive_argument_color

MIN_SYNTAX_CONTRAST = 4.5


@dataclass(frozen=True, slots=True)
class SyntaxPalette:
    """Pager syntax styles derived from a concrete host theme."""

    styles: Mapping[SyntaxRole, HighlightStyle]
    rich_styles: Mapping[SyntaxRole, Style]
    foreground: str
    background: str
    signature: str


def syntax_palette_from_theme(theme: Any | None) -> SyntaxPalette:
    """Return a deterministic, readable syntax palette for *theme*."""

    values = _theme_values(theme)
    return _syntax_palette_from_values(*values)


def _contrast_ratio(foreground: str | None, background: str | None) -> float:
    """Return WCAG contrast ratio for two CSS colors."""

    fg = _parse_color(foreground) or Color.parse("#ffffff")
    bg = _parse_color(background) or Color.parse("#000000")
    fg_lum = _relative_luminance(fg)
    bg_lum = _relative_luminance(bg)
    lighter = max(fg_lum, bg_lum)
    darker = min(fg_lum, bg_lum)
    return (lighter + 0.05) / (darker + 0.05)


def _theme_values(
    theme: Any | None,
) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    if theme is None:
        return (None, None, None, None, None, None, None, None)
    return (
        getattr(theme, "foreground", None),
        getattr(theme, "background", None),
        getattr(theme, "primary", None),
        getattr(theme, "secondary", None),
        getattr(theme, "accent", None),
        getattr(theme, "success", None),
        getattr(theme, "warning", None),
        getattr(theme, "error", None),
    )


@functools.cache
def _syntax_palette_from_values(
    foreground: str | None,
    background: str | None,
    primary: str | None,
    secondary: str | None,
    accent: str | None,
    success: str | None,
    warning: str | None,
    error: str | None,
) -> SyntaxPalette:
    bg = _readable_color(background, fallback="#000000")
    fg = _readable_color(foreground, fallback=_contrast_text(bg))
    muted = _muted_foreground(fg, bg)
    secondary_arg = _derive_argument_color(secondary, foreground=fg, background=bg)
    accent_arg = _derive_argument_color(accent, foreground=fg, background=bg)

    styles: dict[SyntaxRole, HighlightStyle] = {
        SyntaxRole.KEYWORD: HighlightStyle(_ensure_contrast(accent, bg, fg), bold=True),
        SyntaxRole.TYPE: HighlightStyle(_ensure_contrast(primary, bg, fg)),
        SyntaxRole.FUNCTION: HighlightStyle(_ensure_contrast(secondary, bg, fg)),
        SyntaxRole.DECORATOR: HighlightStyle(_ensure_contrast(accent_arg, bg, fg)),
        SyntaxRole.CONSTANT: HighlightStyle(_ensure_contrast(warning, bg, fg)),
        SyntaxRole.NUMBER: HighlightStyle(_ensure_contrast(warning, bg, fg)),
        SyntaxRole.STRING: HighlightStyle(_ensure_contrast(success, bg, fg)),
        SyntaxRole.COMMENT: HighlightStyle(muted, italic=True),
        SyntaxRole.ERROR: HighlightStyle(
            _ensure_contrast(error, bg, fg), underline=True
        ),
        SyntaxRole.MARKDOWN_HEADING: HighlightStyle(
            _ensure_contrast(primary, bg, fg), bold=True
        ),
        SyntaxRole.MARKDOWN_STRONG: HighlightStyle(fg, bold=True),
        SyntaxRole.MARKDOWN_EMPHASIS: HighlightStyle(fg, italic=True),
        SyntaxRole.MARKDOWN_CODE: HighlightStyle(
            _ensure_contrast(secondary_arg, bg, fg)
        ),
        SyntaxRole.PROJECT_TAG: HighlightStyle(
            _ensure_contrast(accent, bg, fg), bold=True
        ),
        SyntaxRole.DIFF_ADDED: HighlightStyle(_ensure_contrast(success, bg, fg)),
        SyntaxRole.DIFF_DELETED: HighlightStyle(_ensure_contrast(error, bg, fg)),
        SyntaxRole.DIFF_HEADER: HighlightStyle(
            _ensure_contrast(secondary, bg, fg), bold=True
        ),
        SyntaxRole.DIFF_HUNK: HighlightStyle(_ensure_contrast(secondary_arg, bg, fg)),
    }
    rich_styles = {
        role: Style.parse(style.rich_style) if style.rich_style else Style()
        for role, style in styles.items()
    }
    signature = "|".join(
        (
            fg,
            bg,
            *(f"{role.value}:{style.rich_style}" for role, style in styles.items()),
        )
    )
    return SyntaxPalette(
        styles=MappingProxyType(styles),
        rich_styles=MappingProxyType(rich_styles),
        foreground=fg,
        background=bg,
        signature=signature,
    )


def _readable_color(value: str | None, *, fallback: str) -> str:
    color = _parse_color(value)
    if color is None:
        color = Color.parse(fallback)
    return color.hex


def _muted_foreground(foreground: str, background: str) -> str:
    muted = Color.parse(foreground).blend(Color.parse(background), 0.35).hex
    return _ensure_contrast(muted, background, foreground)


def _ensure_contrast(
    value: str | None,
    background: str,
    neutral: str,
) -> str:
    color = _parse_color(value)
    if color is None:
        color = Color.parse(neutral)
    if _contrast_ratio(color.hex, background) >= MIN_SYNTAX_CONTRAST:
        return color.hex

    target = Color.parse(neutral)
    if _contrast_ratio(target.hex, background) < MIN_SYNTAX_CONTRAST:
        target = Color.parse(_contrast_text(background))
    for step in range(1, 11):
        candidate = color.blend(target, step / 10).hex
        if _contrast_ratio(candidate, background) >= MIN_SYNTAX_CONTRAST:
            return candidate
    return target.hex


def _derive_argument_color(
    base: str | None,
    *,
    foreground: str,
    background: str,
) -> str | None:
    if _parse_color(base) is None:
        return None
    return derive_argument_color(base, foreground=foreground, background=background)


def _contrast_text(background: str) -> str:
    black = "#000000"
    white = "#ffffff"
    return (
        black
        if _contrast_ratio(black, background) >= _contrast_ratio(white, background)
        else white
    )


def _parse_color(value: str | None) -> Color | None:
    if not value:
        return None
    try:
        return Color.parse(value)
    except Exception:
        return None


def _relative_luminance(color: Color) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        if normalized <= 0.04045:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.r)
        + 0.7152 * channel(color.g)
        + 0.0722 * channel(color.b)
    )


def contrast_ratio(foreground: str | None, background: str | None) -> float:
    """Return the public WCAG contrast ratio for two CSS colors."""
    return _contrast_ratio(foreground, background)


def history_palette_from_theme(theme: Any | None) -> dict[str, str]:
    """Return history chrome roles seeded around the violet past accent.

    Past stays violet (``#9d7cd8`` corrected for contrast); text contrast
    is >=4.5 and mark contrast >=3.0, and the past hue stays >=60 degrees
    from the theme warning hue. Callers invalidate on host theme change.
    """
    values = _theme_values(theme)
    background = _readable_color(values[1], fallback="#000000")
    foreground = _readable_color(values[0], fallback=_contrast_text(background))
    warning = values[6] or "#FFB000"
    past = _ensure_contrast("#9d7cd8", background, foreground)
    past = _keep_hue_distance(past, warning, background, foreground)
    insert = _ensure_contrast("#3FB950", background, foreground)
    delete = _ensure_contrast("#F85149", background, foreground)
    return {
        "past": past,
        "insert": insert,
        "delete": delete,
        "gutter_add": insert,
        "gutter_change": past,
        "gutter_remove": delete,
        "tombstone": delete,
        "uncommitted": _ensure_contrast(warning, background, foreground),
    }


def _keep_hue_distance(
    past: str, warning: str | None, background: str, foreground: str
) -> str:
    """Nudge *past* away from the warning hue when they sit too close."""
    try:
        from textual.color import Color as _Color

        past_hue = _hue_of(_Color.parse(past))
        warning_hue = _hue_of(_Color.parse(warning or "#FFB000"))
        if past_hue is None or warning_hue is None:
            return past
        distance = abs(past_hue - warning_hue)
        distance = min(distance, 360 - distance)
        if distance >= 60:
            return past
        # Rotate toward blue/violet to preserve the past hue family.
        candidate = _Color.parse("#9d7cd8").hex
        if _contrast_ratio(candidate, background) >= 3.0:
            return candidate
        return _ensure_contrast(candidate, background, foreground)
    except Exception:
        return past


def _hue_of(color: Any) -> float | None:
    try:
        _, _, _, hue = color.hsv if hasattr(color, "hsv") else (None, None, None, None)
        return float(hue) if hue is not None else None
    except Exception:
        try:
            red, green, blue = color.r / 255, color.g / 255, color.b / 255
            mx, mn = max(red, green, blue), min(red, green, blue)
            if mx == mn:
                return 0.0
            if mx == red:
                hue = (60 * ((green - blue) / (mx - mn)) + 360) % 360
            elif mx == green:
                hue = (60 * ((blue - red) / (mx - mn)) + 120) % 360
            else:
                hue = (60 * ((red - green) / (mx - mn)) + 240) % 360
            return hue
        except Exception:
            return None


__all__ = [
    "MIN_SYNTAX_CONTRAST",
    "SyntaxPalette",
    "contrast_ratio",
    "history_palette_from_theme",
    "syntax_palette_from_theme",
]
