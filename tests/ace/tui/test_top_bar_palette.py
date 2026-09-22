"""Contrast guard keeping the updates badge distinct from top-bar neighbors.

Covers WCAG 2.1 SC 1.4.11 (non-text contrast): the badge surface must stay
at least 3:1 against every neighboring chip background. Luminance contrast
is what keeps the chip distinct under red-green color-vision deficiency,
where hue alone collapses.
"""

from __future__ import annotations

from rich.style import Style
from rich.text import Text

from sase.ace.tui.proc_gear_chips import MONITOR_GEAR_HUE, PROC_GEAR_HUE, gear_chip
from sase.ace.tui.widgets._override_pill import (
    ALIAS_LANE_PALETTE,
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
)
from sase.ace.tui.widgets.stashed_prompts_indicator import StashedPromptsIndicator
from sase.ace.tui.widgets.update_accents import UPDATES_SURFACE
from sase.ace.tui.widgets.updates_indicator import UpdatesAvailableIndicator

_MIN_SURFACE_CONTRAST = 3.0
_MIN_TEXT_CONTRAST = 4.5


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    stripped = value.lstrip("#")
    return tuple(int(stripped[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(value: str) -> float:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: str, b: str) -> float:
    la = _relative_luminance(a) + 0.05
    lb = _relative_luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def _as_style(value: object) -> Style | None:
    if value is None:
        return None
    if isinstance(value, Style):
        return value
    text = str(value)
    if not text.strip():
        return None
    try:
        return Style.parse(text)
    except Exception:
        return None


def _color_hex(color: object) -> str | None:
    triplet = getattr(color, "triplet", None)
    if triplet is None:
        return None
    return f"#{triplet.red:02X}{triplet.green:02X}{triplet.blue:02X}"


def _backgrounds(text: Text) -> set[str]:
    found: set[str] = set()
    for raw in [text.style, *[span.style for span in text.spans]]:
        style = _as_style(raw)
        if style is None or style.bgcolor is None:
            continue
        hex_value = _color_hex(style.bgcolor)
        if hex_value is not None:
            found.add(hex_value)
    return found


def _foreground_background_pairs(text: Text) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    candidates: list[object] = []
    if text.spans:
        candidates.extend(span.style for span in text.spans)
    elif text.style:
        candidates.append(text.style)
    for raw in candidates:
        style = _as_style(raw)
        if style is None or style.color is None or style.bgcolor is None:
            continue
        fg = _color_hex(style.color)
        bg = _color_hex(style.bgcolor)
        if fg is not None and bg is not None:
            pairs.append((fg, bg))
    return pairs


def _neighbors() -> dict[str, Text]:
    return {
        "proc gear chip": gear_chip(1, PROC_GEAR_HUE),
        "monitor gear chip": gear_chip(1, MONITOR_GEAR_HUE),
        "stashed prompts": StashedPromptsIndicator._build_content(1),
        "alias override pill": build_override_pill(
            subject="@medium",
            effort="max",
            trailing="∞",
            palette=ALIAS_LANE_PALETTE,
        ),
        "provider hard-disable pill": build_override_pill(
            subject="CLAUDE",
            effort=None,
            trailing="off ∞",
            palette=PROVIDER_DISABLE_PALETTE,
        ),
        "provider soft-disable pill": build_override_pill(
            subject="CLAUDE",
            effort=None,
            trailing="soft ∞",
            palette=PROVIDER_SOFT_DISABLE_PALETTE,
        ),
        "provider priority pill": build_override_pill(
            subject="CLAUDE ★",
            effort=None,
            trailing="priority ∞",
            palette=PROVIDER_PRIORITY_PALETTE,
        ),
    }


def test_updates_surface_stays_distinct_from_every_neighbor() -> None:
    badge = UpdatesAvailableIndicator._build_content(3, core=True, agent_cli_count=2)
    badge_backgrounds = _backgrounds(badge)
    assert UPDATES_SURFACE in badge_backgrounds, (
        f"badge does not render on {UPDATES_SURFACE}: {sorted(badge_backgrounds)}"
    )
    for name, neighbor in _neighbors().items():
        for neighbor_bg in _backgrounds(neighbor):
            ratio = _contrast_ratio(UPDATES_SURFACE, neighbor_bg)
            assert ratio >= _MIN_SURFACE_CONTRAST, (
                f"updates surface {UPDATES_SURFACE} too close to {name} "
                f"background {neighbor_bg}: {ratio:.2f}:1 "
                f"(need >= {_MIN_SURFACE_CONTRAST}:1)"
            )


def test_updates_badge_text_meets_aa_contrast() -> None:
    badge = UpdatesAvailableIndicator._build_content(3, core=True, agent_cli_count=2)
    pairs = _foreground_background_pairs(badge)
    assert pairs, "badge has no foreground/background pairs to check"
    for fg, bg in pairs:
        ratio = _contrast_ratio(fg, bg)
        assert ratio >= _MIN_TEXT_CONTRAST, (
            f"badge text {fg} on {bg} is {ratio:.2f}:1 (need >= {_MIN_TEXT_CONTRAST}:1)"
        )
