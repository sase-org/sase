"""Theme-aware history chrome styles for the pager.

``HistoryStyles`` is the only source of history colours for the state
pill, the time band, the gutter rail and change marks, the diff body,
the timeline picker, and the trail version suffix. It is resolved once
per host theme (cached on the theme values) and invalidated on theme
change by the cached key including every theme colour.
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
from typing import Any


@dataclass(frozen=True, slots=True)
class HistoryStyles:
    """Every history colour role, resolved for one host theme."""

    # Surface colours the roles were derived against.
    foreground: str
    background: str
    # Identity roles.
    past: str
    insert: str
    delete: str
    modified: str
    uncommitted: str
    tombstone: str
    # Gutter change marks.
    gutter_add: str
    gutter_change: str
    gutter_remove: str
    # Full-height body rails for pinned sections.
    rail_past: str
    rail_deleted: str
    # Faint time-band background while pinned in the past.
    band_past_tint: str
    # State-pill capsules: background plus black-or-white text at >= 4.5:1.
    now_pill_bg: str
    now_pill_fg: str
    past_pill_bg: str
    past_pill_fg: str
    uncommitted_pill_bg: str
    uncommitted_pill_fg: str
    deleted_pill_bg: str
    deleted_pill_fg: str
    # Cache key: every theme colour plus every derived role.
    signature: str


def _theme_values(theme: Any | None) -> tuple[Any, ...]:
    if theme is None:
        return (None,) * 8
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


def history_styles_for_theme(theme: Any | None) -> HistoryStyles:
    """Return the cached :class:`HistoryStyles` for *theme*."""
    return _history_styles_for_values(*_theme_values(theme))


@functools.cache
def _history_styles_for_values(
    foreground: Any,
    background: Any,
    primary: Any,
    secondary: Any,
    accent: Any,
    success: Any,
    warning: Any,
    error: Any,
) -> HistoryStyles:
    from sase.pager.syntax_theme import history_palette_from_theme

    class _Theme:
        pass

    probe = _Theme()
    probe.foreground = foreground  # type: ignore[attr-defined]
    probe.background = background  # type: ignore[attr-defined]
    probe.primary = primary  # type: ignore[attr-defined]
    probe.secondary = secondary  # type: ignore[attr-defined]
    probe.accent = accent  # type: ignore[attr-defined]
    probe.success = success  # type: ignore[attr-defined]
    probe.warning = warning  # type: ignore[attr-defined]
    probe.error = error  # type: ignore[attr-defined]
    palette = history_palette_from_theme(probe)
    return _history_styles_from_palette(palette)


def _history_styles_from_palette(palette: dict[str, str]) -> HistoryStyles:
    """Build :class:`HistoryStyles` from an extended history palette."""
    from sase.pager.syntax_theme import contrast_text, readable_color

    background = readable_color(palette.get("background"), fallback="#000000")
    foreground = readable_color(
        palette.get("foreground"), fallback=contrast_text(background)
    )

    def get(key: str, fallback: str) -> str:
        return str(palette.get(key, fallback))

    past = get("past", "#9d7cd8")
    insert = get("insert", "#3FB950")
    delete = get("delete", "#F85149")
    modified = get("modified", "#58A6FF")
    uncommitted = get("uncommitted", "#FFB000")
    tombstone = get("tombstone", delete)
    now_bg, now_fg = _pill_pair(get("now_pill_bg", ""), background, foreground)
    past_bg, past_fg = _pill_pair(get("past_pill_bg", past), background, foreground)
    unc_bg, unc_fg = _pill_pair(
        get("uncommitted_pill_bg", uncommitted), background, foreground
    )
    del_bg, del_fg = _pill_pair(
        get("deleted_pill_bg", tombstone), background, foreground
    )
    signature = "|".join(
        (
            foreground,
            background,
            past,
            insert,
            delete,
            modified,
            uncommitted,
            tombstone,
            get("gutter_add", insert),
            get("gutter_change", modified),
            get("gutter_remove", delete),
            get("rail_past", past),
            get("rail_deleted", tombstone),
            get("band_past_tint", background),
            now_bg,
            now_fg,
            past_bg,
            past_fg,
            unc_bg,
            unc_fg,
            del_bg,
            del_fg,
        )
    )
    return HistoryStyles(
        foreground=foreground,
        background=background,
        past=past,
        insert=insert,
        delete=delete,
        modified=modified,
        uncommitted=uncommitted,
        tombstone=tombstone,
        gutter_add=get("gutter_add", insert),
        gutter_change=get("gutter_change", modified),
        gutter_remove=get("gutter_remove", delete),
        rail_past=get("rail_past", past),
        rail_deleted=get("rail_deleted", tombstone),
        band_past_tint=get("band_past_tint", background),
        now_pill_bg=now_bg,
        now_pill_fg=now_fg,
        past_pill_bg=past_bg,
        past_pill_fg=past_fg,
        uncommitted_pill_bg=unc_bg,
        uncommitted_pill_fg=unc_fg,
        deleted_pill_bg=del_bg,
        deleted_pill_fg=del_fg,
        signature=signature,
    )


def default_history_styles() -> HistoryStyles:
    """Return the styles for a missing theme (dark fallback)."""
    return history_styles_for_theme(None)


def extra_history_palette_roles(
    theme: Any | None, legacy: dict[str, str]
) -> dict[str, str]:
    """Return the badge-phase palette roles beyond the legacy set."""
    from sase.pager.syntax_theme import (
        contrast_ratio,
        contrast_text,
        ensure_contrast,
        parse_color,
        readable_color,
    )

    background = readable_color(getattr(theme, "background", None), fallback="#000000")
    foreground = readable_color(
        getattr(theme, "foreground", None), fallback=contrast_text(background)
    )
    if foreground == background:
        # Degenerate themes (e.g. textual-ansi's terminal-default pair)
        # resolve both roles to the same colour, which makes contrast
        # math meaningless. Fall back to the theme's declared luminance.
        dark = bool(getattr(theme, "dark", True))
        background = "#000000" if dark else "#ffffff"
        foreground = contrast_text(background)
    warning = getattr(theme, "warning", None) or "#FFB000"
    past = str(legacy.get("past", "#9d7cd8"))
    delete = str(legacy.get("delete", "#F85149"))
    uncommitted = str(legacy.get("uncommitted", warning))
    tombstone = str(legacy.get("tombstone", delete))

    modified = ensure_contrast("#58A6FF", background, foreground)
    modified = _keep_hue_distance_from(
        modified, past, 30.0, background, foreground, fallback="#58A6FF"
    )
    # Marks need >= 3.0:1; nudge toward the neutral when the blue misses.
    if contrast_ratio(modified, background) < 3.0:
        modified = ensure_contrast(modified, background, foreground)

    rail_past = _ensure_marks_contrast(past, background, foreground)
    rail_deleted = _ensure_marks_contrast(tombstone, background, foreground)

    # About 14% past accent over the surface, faded back toward the
    # surface until body text keeps >= 4.5:1 against it.
    band_past_tint = background
    for step in range(8):
        candidate = _blend_hex(past, background, 0.14 + step * 0.12)
        if parse_color(candidate) is None:
            break
        band_past_tint = candidate
        if contrast_ratio(foreground, candidate) >= 4.5:
            break

    now_bg = _blend_hex(foreground, background, 0.18)
    past_bg, _ = _pill_pair(past, background, foreground)
    unc_bg, _ = _pill_pair(uncommitted, background, foreground)
    del_bg, _ = _pill_pair(tombstone, background, foreground)

    return {
        "foreground": foreground,
        "background": background,
        "modified": modified,
        "rail_past": rail_past,
        "rail_deleted": rail_deleted,
        "band_past_tint": band_past_tint,
        "now_pill_bg": now_bg,
        "past_pill_bg": past_bg,
        "uncommitted_pill_bg": unc_bg,
        "deleted_pill_bg": del_bg,
    }


def _pill_pair(candidate_bg: str, background: str, foreground: str) -> tuple[str, str]:
    """Return a pill ``(background, text)`` pair with text at >= 4.5:1.

    The text is black or white, whichever passes 4.5:1 against the
    background. When neither does, the background is nudged toward the
    nearer extreme until one passes.
    """
    from sase.pager.syntax_theme import contrast_ratio, parse_color
    from textual.color import Color

    base = parse_color(candidate_bg) or Color.parse(foreground)
    surface = parse_color(background) or Color.parse("#000000")
    black = Color.parse("#000000")
    white = Color.parse("#ffffff")
    bg = base.hex
    picked = _pick_pill_text(bg)
    if picked is not None:
        return (bg, picked)
    # Nudge the background toward whichever extreme is nearer until a
    # black-or-white text passes 4.5:1 (at most ten steps each way).
    near_black = contrast_ratio(black.hex, bg) >= contrast_ratio(white.hex, bg)
    targets = (black, white) if near_black else (white, black)
    for target in targets:
        for step in range(1, 11):
            nudged = base.blend(target, step / 10).hex
            picked = _pick_pill_text(nudged)
            if picked is not None:
                return (nudged, picked)
    # Last resort: solid text on the surface itself (always passes).
    if contrast_ratio(black.hex, surface.hex) >= contrast_ratio(white.hex, surface.hex):
        return (surface.hex, "#000000")
    return (surface.hex, "#ffffff")


def _pick_pill_text(background: str) -> str | None:
    """Return ``#000000`` or ``#ffffff`` at >= 4.5:1, preferring contrast."""
    from sase.pager.syntax_theme import contrast_ratio

    black_ratio = contrast_ratio("#000000", background)
    white_ratio = contrast_ratio("#ffffff", background)
    best = (
        ("#000000", black_ratio)
        if black_ratio >= white_ratio
        else ("#ffffff", white_ratio)
    )
    if best[1] >= 4.5:
        return best[0]
    return None


def _ensure_marks_contrast(value: str, background: str, foreground: str) -> str:
    """Return *value* corrected to >= 3.0:1 mark contrast."""
    from sase.pager.syntax_theme import (
        contrast_ratio,
        contrast_text,
        parse_color,
    )
    from textual.color import Color

    color = parse_color(value)
    if color is None:
        color = Color.parse(foreground)
    if contrast_ratio(color.hex, background) >= 3.0:
        return color.hex
    target = Color.parse(foreground)
    if contrast_ratio(target.hex, background) < 3.0:
        target = Color.parse(contrast_text(background))
    for step in range(1, 11):
        candidate = color.blend(target, step / 10).hex
        if contrast_ratio(candidate, background) >= 3.0:
            return candidate
    return target.hex


#: Blue candidates for the changed-mark role, tried in order until one
#: keeps >= 3.0:1 mark contrast and sits clear of the past hue. The two
#: vivid violets are last resorts for themes whose corrected past is
#: itself a muted blue (e.g. solarized-light), where every true blue
#: crowds it; they only ever win when all six blues fail.
_BLUE_CANDIDATES = (
    "#58A6FF",
    "#3B9EFF",
    "#1E90FF",
    "#4D7CFE",
    "#0062FF",
    "#00BFFF",
    "#7C3AED",
    "#6D28D9",
)


def _keep_hue_distance_from(
    value: str,
    reference: str,
    minimum_degrees: float,
    background: str,
    foreground: str,
    *,
    fallback: str,
) -> str:
    """Keep *value* at least *minimum_degrees* of hue from *reference*."""
    from sase.pager.syntax_theme import (
        contrast_ratio,
        ensure_contrast,
        parse_color,
    )

    def _far_enough(candidate: str) -> bool:
        try:
            distance = _hue_distance(candidate, reference)
            if distance is None:
                return True
            return distance >= minimum_degrees
        except Exception:
            return True

    try:
        ordered = (value, fallback, *_BLUE_CANDIDATES)
        for raw in ordered:
            candidate = parse_color(raw)
            if candidate is None:
                continue
            if contrast_ratio(candidate.hex, background) < 3.0:
                continue
            if _far_enough(candidate.hex):
                return candidate.hex
        # Last resort: a contrast-safe colour even if the hue crowds past.
        return ensure_contrast(fallback, background, foreground)
    except Exception:
        return value


def _blend_hex(first: str, second: str, factor: float) -> str:
    """Return *first* blended toward *second* by *factor* as a hex string."""
    from textual.color import Color

    try:
        return Color.parse(first).blend(Color.parse(second), factor).hex
    except Exception:
        return second


def _hue_distance(first: str, second: str) -> float | None:
    """Return the circular hue distance in degrees between two colours."""
    from sase.pager.syntax_theme import hue_of
    from textual.color import Color

    try:
        first_hue = hue_of(Color.parse(first))
        second_hue = hue_of(Color.parse(second))
        if first_hue is None or second_hue is None:
            return None
        distance = abs(first_hue - second_hue)
        return min(distance, 360 - distance)
    except Exception:
        return None


__all__ = [
    "HistoryStyles",
    "default_history_styles",
    "extra_history_palette_roles",
    "history_styles_for_theme",
]
