"""Perceptual spacing, contrast, and stability of the provider accent palette."""

from __future__ import annotations

import math
import re

from sase.ace.tui._artifact_tab_descriptors import (
    _PROVIDER_ACCENTS,
    _provider_accent_for_kind,
)
from sase.ace.tui.artifact_tabs import ARTIFACTS_ACCENTS, EXTERNAL_ACCENT

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")

# The app's stock Textual theme surfaces (see ``docs/artifacts_pane_visual_grammar.md``).
_DARK_SURFACES = ("#121212", "#1E1E1E")
_LIGHT_SURFACES = ("#E0E0E0", "#D8D8D8")
_CHIP_TEXT = "#1A1A1A"

_MIN_PROVIDER_COUNT = 8
_MIN_PAIRWISE_DISTANCE = 0.085
_MIN_DARK_CONTRAST = 3.3
_MIN_LIGHT_CONTRAST = 2.9
_MIN_CHIP_CONTRAST = 3.3


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


def _min_contrast_against(value: str, surfaces: tuple[str, ...]) -> float:
    return min(_contrast_ratio(value, surface) for surface in surfaces)


def _srgb_to_oklab(value: str) -> tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(value))
    long = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    mid = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    long_, mid_, short_ = long ** (1 / 3), mid ** (1 / 3), short ** (1 / 3)
    lightness = 0.2104542553 * long_ + 0.7936177850 * mid_ - 0.0040720468 * short_
    a = 1.9779984951 * long_ - 2.4285922050 * mid_ + 0.4505937099 * short_
    b_axis = 0.0259040371 * long_ + 0.7827717662 * mid_ - 0.8086757660 * short_
    return (lightness, a, b_axis)


def _oklab_distance(a: str, b: str) -> float:
    l1, a1, b1 = _srgb_to_oklab(a)
    l2, a2, b2 = _srgb_to_oklab(b)
    return math.sqrt((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)


def test_palette_has_enough_colors_for_eight_or_more_providers() -> None:
    assert len(_PROVIDER_ACCENTS) >= _MIN_PROVIDER_COUNT
    assert len(set(_PROVIDER_ACCENTS)) == len(_PROVIDER_ACCENTS)


def test_palette_values_are_pinned_uppercase_hex() -> None:
    for color in _PROVIDER_ACCENTS:
        assert _HEX_RE.match(color), color


def test_palette_excludes_reserved_builtin_and_error_colors() -> None:
    reserved = frozenset(ARTIFACTS_ACCENTS.values()) | {EXTERNAL_ACCENT}
    for color in _PROVIDER_ACCENTS:
        assert color not in reserved


def test_palette_is_pairwise_perceptually_spaced() -> None:
    for i, a in enumerate(_PROVIDER_ACCENTS):
        for b in _PROVIDER_ACCENTS[i + 1 :]:
            assert _oklab_distance(a, b) >= _MIN_PAIRWISE_DISTANCE, (a, b)


def test_palette_is_spaced_from_reserved_colors() -> None:
    reserved = frozenset(ARTIFACTS_ACCENTS.values()) | {EXTERNAL_ACCENT}
    for color in _PROVIDER_ACCENTS:
        for other in reserved:
            assert _oklab_distance(color, other) >= _MIN_PAIRWISE_DISTANCE, (
                color,
                other,
            )


def test_palette_is_legible_on_dark_and_light_shell_surfaces() -> None:
    for color in _PROVIDER_ACCENTS:
        assert _min_contrast_against(color, _DARK_SURFACES) >= _MIN_DARK_CONTRAST, color
        assert _min_contrast_against(color, _LIGHT_SURFACES) >= _MIN_LIGHT_CONTRAST, (
            color
        )
        assert _min_contrast_against(color, (_CHIP_TEXT,)) >= _MIN_CHIP_CONTRAST, color


def test_provider_accent_for_kind_is_a_pure_function_of_kind() -> None:
    before = dict(ARTIFACTS_ACCENTS)
    first = _provider_accent_for_kind("research")
    second = _provider_accent_for_kind("research")
    assert first == second
    assert dict(ARTIFACTS_ACCENTS) == before


def test_provider_discovery_never_mutates_artifacts_accents() -> None:
    before = dict(ARTIFACTS_ACCENTS)
    for kind in ("research", "wiki", "notes", "adr", "unrelated_kind"):
        _provider_accent_for_kind(kind)
    assert dict(ARTIFACTS_ACCENTS) == before


def test_plan_keeps_its_pinned_accent_through_the_hash_helper() -> None:
    assert _provider_accent_for_kind("plan") == ARTIFACTS_ACCENTS["ref:plan"]
    assert _provider_accent_for_kind("plan") == "#AF87FF"


def test_installing_an_unrelated_kind_does_not_repaint_existing_kinds() -> None:
    """Every kind's accent depends only on its own name, not on the set of

    currently installed kinds, so registering or removing an unrelated
    provider can never repaint an existing tab.
    """
    fixed_kind = "research"
    before = _provider_accent_for_kind(fixed_kind)
    for other_kind in ("brand_new_kind", "another_new_kind", "zzz_last_kind"):
        _provider_accent_for_kind(other_kind)
    assert _provider_accent_for_kind(fixed_kind) == before
