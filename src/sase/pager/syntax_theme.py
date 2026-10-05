"""Theme-adaptive syntax palette for pager source roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from rich.style import Style
from textual.color import Color

from sase.pager.syntax import SyntaxRole

if TYPE_CHECKING:
    from sase.macro.highlight_theme import HighlightStyle

MIN_SYNTAX_CONTRAST = 4.5
MIN_MARKDOWN_CONTRAST = 7.0

#: Painted body surface when the raw theme leaves ``background`` empty.
#: ``textual-dark`` declares no background yet the mounted pager paints
#: this dark neutral, so contrast must be checked against it, not black.
DEFAULT_DARK_SURFACE = "#121212"
#: Painted body surface for light themes with no declared background.
DEFAULT_LIGHT_SURFACE = "#E0E0E0"
#: Conservative fallback when RGB is unavailable (terminal/ANSI colors):
#: pure extremes guarantee a computable contrast instead of claiming an
#: RGB guarantee against an unknown terminal palette.
TERMINAL_DARK_FALLBACK_BG = "#000000"
TERMINAL_LIGHT_FALLBACK_BG = "#FFFFFF"


@dataclass(frozen=True, slots=True)
class SyntaxPalette:
    """Pager syntax styles derived from a concrete host theme."""

    styles: Mapping[SyntaxRole, HighlightStyle]
    rich_styles: Mapping[SyntaxRole, Style]
    foreground: str
    background: str
    signature: str


@dataclass(frozen=True, slots=True)
class PagerPresentation:
    """Smallest immutable host-surface context for pager painting.

    Carries the resolved body foreground/background, the neutral chrome
    surface (history strip, trail, time band), and the raw theme accents
    they were derived with. Pure to construct and safe to cache: every
    field participates in the palette signature so a theme change
    invalidates styled results.
    """

    foreground: str
    background: str
    chrome: str
    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None
    success: str | None = None
    warning: str | None = None
    error: str | None = None
    dark: bool = True


def syntax_palette_from_theme(theme: Any | None) -> SyntaxPalette:
    """Return a deterministic, readable syntax palette for *theme*."""

    values = _theme_values(theme)
    return _syntax_palette_from_values(*values, _theme_is_dark(theme))


def pager_presentation_from_theme(
    theme: Any | None,
    *,
    body_background: str | None = None,
    chrome_background: str | None = None,
) -> PagerPresentation:
    """Resolve the painted pager surfaces for *theme*.

    *body_background* and *chrome_background* accept already-resolved
    computed styles read after mount (including alpha/inherited
    backgrounds); when absent or unparseable the theme values apply with
    the dark-aware painted fallbacks. Works for both the standalone
    ``SasePager`` app and a pager embedded in ACE since both expose the
    host theme as ``app.current_theme``. Never queries the terminal and
    never emits an invalid Rich color: terminal/ANSI inputs fall back to
    the conservative light/dark neutrals.
    """

    values = _theme_values(theme)
    dark = _theme_is_dark(theme)
    resolved_bg = _resolve_surface(body_background, values[1], dark=dark, kind="body")
    resolved_fg = _resolve_foreground(values[0], resolved_bg)
    chrome = _resolve_surface(
        chrome_background, None, dark=dark, kind="chrome", body_bg=resolved_bg
    )
    return PagerPresentation(
        foreground=resolved_fg,
        background=resolved_bg,
        chrome=chrome,
        primary=values[2],
        secondary=values[3],
        accent=values[4],
        success=values[5],
        warning=values[6],
        error=values[7],
        dark=dark,
    )


def resolve_pager_surfaces(host: Any) -> PagerPresentation:
    """Resolve painted surfaces from a mounted pager host, if possible.

    Reads ``host.app.current_theme`` plus any computed widget background
    without doing I/O or querying the terminal. Falls back to the pure
    theme resolution when widgets are unmounted or styles are unresolved.
    Supports standalone and ACE-embedded pagers alike.
    """

    theme: Any | None = None
    try:
        app = getattr(host, "app", None)
        theme = getattr(app, "current_theme", None)
    except Exception:
        theme = None
    body_bg: str | None = None
    try:
        styles = getattr(host, "styles", None)
        if styles is not None:
            background = getattr(styles, "background", None)
            if background is not None:
                text = str(background).strip()
                if text and text.lower() not in ("auto", "transparent"):
                    body_bg = text
    except Exception:
        body_bg = None
    try:
        return pager_presentation_from_theme(theme, body_background=body_bg)
    except Exception:
        return pager_presentation_from_theme(None)


def _contrast_ratio(foreground: str | None, background: str | None) -> float:
    """Return WCAG contrast ratio for two CSS colors."""

    fg = parse_color(foreground) or Color.parse("#ffffff")
    bg = parse_color(background) or Color.parse("#000000")
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
    dark: bool | None = None,
) -> SyntaxPalette:
    from sase.macro.highlight_theme import HighlightStyle

    presentation = _presentation_from_values(
        foreground,
        background,
        primary,
        secondary,
        accent,
        success,
        warning,
        error,
        dark=dark,
    )
    bg = presentation.background
    fg = presentation.foreground
    muted = _muted_foreground(fg, bg)
    secondary_arg = _derive_argument_color(secondary, foreground=fg, background=bg)
    accent_arg = _derive_argument_color(accent, foreground=fg, background=bg)

    heading = ensure_contrast_min(primary, bg, fg, MIN_MARKDOWN_CONTRAST)
    code_base = secondary_arg if secondary_arg is not None else secondary
    code = ensure_contrast_min(code_base, bg, fg, MIN_MARKDOWN_CONTRAST)
    meta = ensure_contrast(muted, bg, fg)
    structure = ensure_contrast(muted, bg, fg)

    styles: dict[SyntaxRole, HighlightStyle] = {
        SyntaxRole.KEYWORD: HighlightStyle(ensure_contrast(accent, bg, fg), bold=True),
        SyntaxRole.TYPE: HighlightStyle(ensure_contrast(primary, bg, fg)),
        SyntaxRole.FUNCTION: HighlightStyle(ensure_contrast(secondary, bg, fg)),
        SyntaxRole.DECORATOR: HighlightStyle(ensure_contrast(accent_arg, bg, fg)),
        SyntaxRole.CONSTANT: HighlightStyle(ensure_contrast(warning, bg, fg)),
        SyntaxRole.NUMBER: HighlightStyle(ensure_contrast(warning, bg, fg)),
        SyntaxRole.STRING: HighlightStyle(ensure_contrast(success, bg, fg)),
        SyntaxRole.COMMENT: HighlightStyle(muted, italic=True),
        SyntaxRole.ERROR: HighlightStyle(
            ensure_contrast(error, bg, fg), underline=True
        ),
        SyntaxRole.MARKDOWN_HEADING: HighlightStyle(heading, bold=True),
        SyntaxRole.MARKDOWN_STRONG: HighlightStyle(fg, bold=True),
        SyntaxRole.MARKDOWN_EMPHASIS: HighlightStyle(fg, italic=True),
        SyntaxRole.MARKDOWN_CODE: HighlightStyle(code),
        SyntaxRole.MARKDOWN_META: HighlightStyle(meta, bold=True),
        SyntaxRole.MARKDOWN_STRUCTURE: HighlightStyle(structure),
        SyntaxRole.PROJECT_TAG: HighlightStyle(
            ensure_contrast(accent, bg, fg), bold=True
        ),
        SyntaxRole.DIFF_ADDED: HighlightStyle(ensure_contrast(success, bg, fg)),
        SyntaxRole.DIFF_DELETED: HighlightStyle(ensure_contrast(error, bg, fg)),
        SyntaxRole.DIFF_HEADER: HighlightStyle(
            ensure_contrast(secondary, bg, fg), bold=True
        ),
        SyntaxRole.DIFF_HUNK: HighlightStyle(ensure_contrast(secondary_arg, bg, fg)),
    }
    rich_styles = {
        role: Style.parse(style.rich_style) if style.rich_style else Style()
        for role, style in styles.items()
    }
    signature = "|".join(
        (
            fg,
            bg,
            presentation.chrome,
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


def _presentation_from_values(
    foreground: str | None,
    background: str | None,
    primary: str | None,
    secondary: str | None,
    accent: str | None,
    success: str | None,
    warning: str | None,
    error: str | None,
    *,
    dark: bool | None = None,
) -> PagerPresentation:
    """Pure surface resolution shared by the palette and host glue."""

    is_dark = True if dark is None else bool(dark)
    # When the caller did not supply an explicit dark flag, infer it from
    # any parseable background luminance; missing/ANSI backgrounds keep
    # the conservative dark default.
    if dark is None:
        parsed_bg = parse_color(background)
        if parsed_bg is not None:
            is_dark = _relative_luminance(parsed_bg) < 0.25
    bg = _resolve_surface(None, background, dark=is_dark, kind="body")
    fg = _resolve_foreground(foreground, bg)
    chrome = _resolve_surface(None, None, dark=is_dark, kind="chrome", body_bg=bg)
    return PagerPresentation(
        foreground=fg,
        background=bg,
        chrome=chrome,
        primary=primary,
        secondary=secondary,
        accent=accent,
        success=success,
        warning=warning,
        error=error,
        dark=is_dark,
    )


def _theme_is_dark(theme: Any | None) -> bool:
    if theme is None:
        return True
    try:
        dark = getattr(theme, "dark", None)
    except Exception:
        return True
    if dark is None:
        return True
    return bool(dark)


def is_terminal_color(value: str | None) -> bool:
    """Return whether *value* is a terminal-native color without known RGB."""

    if not value or not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    return lowered.startswith("ansi_") or lowered in ("transparent", "auto")


def _is_terminal_color(value: str | None) -> bool:
    return is_terminal_color(value)


def _resolve_surface(
    explicit: str | None,
    theme_value: str | None,
    *,
    dark: bool,
    kind: str,
    body_bg: str | None = None,
) -> str:
    """Resolve one painted surface to a hex string without terminal I/O."""

    for candidate in (explicit, theme_value):
        if candidate is None:
            continue
        if _is_terminal_color(candidate):
            # Terminal-native colors have no known RGB: use the
            # conservative pure fallback for the theme luminance.
            return TERMINAL_DARK_FALLBACK_BG if dark else TERMINAL_LIGHT_FALLBACK_BG
        parsed = parse_color(candidate)
        if parsed is not None:
            return parsed.hex
        # Unparseable custom value: fall through to the painted fallback.
    if kind == "chrome" and body_bg is not None and parse_color(body_bg) is not None:
        return str(parse_color(body_bg).hex)  # type: ignore[union-attr]
    if dark:
        return DEFAULT_DARK_SURFACE
    return DEFAULT_LIGHT_SURFACE


def _resolve_foreground(foreground: str | None, background: str) -> str:
    if foreground is not None and not _is_terminal_color(foreground):
        parsed = parse_color(foreground)
        if parsed is not None:
            candidate = parsed.hex
            if _contrast_ratio(candidate, background) >= MIN_MARKDOWN_CONTRAST:
                return candidate
            # Theme foreground exists but misses the 7:1 reading bar:
            # correct it toward the stronger extreme.
            corrected = ensure_contrast_min(
                candidate, background, candidate, MIN_MARKDOWN_CONTRAST
            )
            if _contrast_ratio(corrected, background) >= MIN_SYNTAX_CONTRAST:
                return corrected
            return ensure_contrast(candidate, background, candidate)
    return (
        contrast_text(background)
        if _contrast_ratio(contrast_text(background), background)
        >= MIN_MARKDOWN_CONTRAST
        else contrast_text(background)
    )


def readable_color(value: str | None, *, fallback: str) -> str:
    if _is_terminal_color(value):
        return Color.parse(fallback).hex
    color = parse_color(value)
    if color is None:
        color = Color.parse(fallback)
    return color.hex


def _muted_foreground(foreground: str, background: str) -> str:
    muted = Color.parse(foreground).blend(Color.parse(background), 0.35).hex
    return ensure_contrast(muted, background, foreground)


def ensure_contrast(
    value: str | None,
    background: str,
    neutral: str,
) -> str:
    return ensure_contrast_min(value, background, neutral, MIN_SYNTAX_CONTRAST)


def ensure_contrast_min(
    value: str | None,
    background: str,
    neutral: str,
    minimum: float,
) -> str:
    color = parse_color(value)
    if color is None:
        try:
            color = Color.parse(neutral)
        except Exception:
            color = Color.parse(contrast_text(background))
        if parse_color(neutral) is None and _is_terminal_color(neutral):
            color = Color.parse(contrast_text(background))
    if _contrast_ratio(color.hex, background) >= minimum:
        return color.hex

    try:
        target = Color.parse(neutral)
    except Exception:
        target = Color.parse(contrast_text(background))
    if (
        parse_color(neutral) is None
        or _contrast_ratio(target.hex, background) < minimum
    ):
        target = Color.parse(contrast_text(background))
    for step in range(1, 21):
        candidate = color.blend(target, step / 20).hex
        if _contrast_ratio(candidate, background) >= minimum:
            return candidate
    return target.hex


def _derive_argument_color(
    base: str | None,
    *,
    foreground: str,
    background: str,
) -> str | None:
    if parse_color(base) is None:
        return None
    from sase.macro.highlight_theme import derive_argument_color

    return derive_argument_color(base, foreground=foreground, background=background)


def contrast_text(background: str) -> str:
    black = "#000000"
    white = "#ffffff"
    return (
        black
        if _contrast_ratio(black, background) >= _contrast_ratio(white, background)
        else white
    )


def parse_color(value: str | None) -> Color | None:
    if not value:
        return None
    if _is_terminal_color(value):
        # Terminal-native colors (textual-ansi on Textual 8.0.x, ansi-dark /
        # ansi-light on 8.2+) have no known RGB and Rich cannot parse them
        # either; degrade to the neutral fallback.
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
    dark = _theme_is_dark(theme)
    background = _resolve_surface(None, values[1], dark=dark, kind="body")
    foreground = _resolve_foreground(values[0], background)
    raw_warning = values[6]
    warning = (
        raw_warning
        if raw_warning is not None
        and not _is_terminal_color(raw_warning)
        and parse_color(raw_warning) is not None
        else "#FFB000"
    )
    past = ensure_contrast("#9d7cd8", background, foreground)
    past = _keep_hue_distance(past, warning, background, foreground)
    insert = ensure_contrast("#3FB950", background, foreground)
    delete = ensure_contrast("#F85149", background, foreground)
    palette = {
        "past": past,
        "insert": insert,
        "delete": delete,
        "gutter_add": insert,
        "gutter_change": past,
        "gutter_remove": delete,
        "tombstone": delete,
        "uncommitted": ensure_contrast(warning, background, foreground),
    }
    # Badge-phase roles: the changed-mark blue, the pill capsules, the
    # body rails, and the past band tint. Computed in pager core's style
    # set so every history surface reads one source.
    try:
        from sase.pager.history.styles import extra_history_palette_roles

        palette.update(extra_history_palette_roles(theme, palette))
        # Changed-line marks are the familiar VCS blue, distinct from the
        # violet past rail and the red removal tick.
        palette["gutter_change"] = palette["modified"]
    except Exception:
        pass
    return palette


def _keep_hue_distance(
    past: str, warning: str | None, background: str, foreground: str
) -> str:
    """Nudge *past* away from the warning hue when they sit too close."""
    try:
        from textual.color import Color as _Color

        past_hue = hue_of(_Color.parse(past))
        warning_hue = hue_of(_Color.parse(warning or "#FFB000"))
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
        return ensure_contrast(candidate, background, foreground)
    except Exception:
        return past


def hue_of(color: Any) -> float | None:
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
    "DEFAULT_DARK_SURFACE",
    "DEFAULT_LIGHT_SURFACE",
    "MIN_MARKDOWN_CONTRAST",
    "MIN_SYNTAX_CONTRAST",
    "PagerPresentation",
    "SyntaxPalette",
    "TERMINAL_DARK_FALLBACK_BG",
    "TERMINAL_LIGHT_FALLBACK_BG",
    "contrast_ratio",
    "contrast_text",
    "ensure_contrast",
    "ensure_contrast_min",
    "history_palette_from_theme",
    "hue_of",
    "is_terminal_color",
    "pager_presentation_from_theme",
    "parse_color",
    "readable_color",
    "resolve_pager_surfaces",
    "syntax_palette_from_theme",
]
