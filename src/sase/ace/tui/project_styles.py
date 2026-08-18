"""Deterministic, collision-free accent colors for enabled projects.

Mirrors the "stable color for an identifier we cannot enumerate at
authoring time" pattern used by ``_provider_accent_for_kind``
(:mod:`sase.ace.tui._artifact_tab_descriptors`): hash the identifier, index
a frozen palette. Project accents add one requirement that pattern does not
need — colors must be *unique per project*, not merely stable — so
:func:`_project_accent_map` forward-probes past a hash collision to the next
free palette slot instead of accepting the collision.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import functools
import hashlib

from textual.color import Color

# 18 colors spaced evenly around the OKLCH hue wheel (20 degrees apart),
# each chroma-adjusted so every entry lands at approximately the same WCAG
# relative luminance (~0.196) as the existing ``_PROVIDER_ACCENTS`` band in
# ``_artifact_tab_descriptors.py``. That shared luminance is what gives the
# whole palette matching legibility on a dark terminal: every entry clears a
# contrast ratio of at least 3.3 against the app's dark shell surfaces
# (#121212/#1E1E1E), 2.9 against its light surfaces (#E0E0E0/#D8D8D8), and
# 3.3 against the identity chip's #1A1A1A text.
PROJECT_ACCENTS: tuple[str, ...] = (
    "#C5547D",
    "#CA545A",
    "#C75A31",
    "#B46817",
    "#A17204",
    "#8B7B02",
    "#6F8312",
    "#3F8B2C",
    "#1B8B5D",
    "#108A79",
    "#1E878C",
    "#1485A1",
    "#0982BE",
    "#4379D3",
    "#6E70D4",
    "#8E67CA",
    "#A65EB7",
    "#B9589C",
)


def _hash_index(key: str, modulo: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulo


@functools.lru_cache(maxsize=256)
def _project_accent_map_cached(project_keys: tuple[str, ...]) -> Mapping[str, str]:
    palette = PROJECT_ACCENTS
    if len(project_keys) > len(palette):
        return {key: palette[_hash_index(key, len(palette))] for key in project_keys}

    assigned: dict[str, str] = {}
    used: set[int] = set()
    for key in project_keys:
        idx = _hash_index(key, len(palette))
        while idx in used:
            idx = (idx + 1) % len(palette)
        used.add(idx)
        assigned[key] = palette[idx]
    return assigned


def _project_accent_map(project_keys: Iterable[str]) -> Mapping[str, str]:
    """Return a stable, distinct accent per key in ``project_keys``.

    Keys are assigned in sorted order so a key's color can only change when
    a key that sorts before it is added or removed *and* that change alters
    the forward-probe outcome. Assignment degrades to hash-only (repeats
    allowed) once there are more keys than palette colors.
    """

    return _project_accent_map_cached(tuple(sorted(set(project_keys))))


def project_accent(project_key: str, *, among: Iterable[str] | None = None) -> str:
    """Return ``project_key``'s accent, optionally unique within ``among``.

    Without ``among`` this degrades to a hash-only lookup (no collision
    avoidance). With ``among``, the accent is the one :func:`_project_accent_map`
    would assign that key within that key set.
    """

    if among is None:
        return PROJECT_ACCENTS[_hash_index(project_key, len(PROJECT_ACCENTS))]
    return _project_accent_map(set(among) | {project_key})[project_key]


# The chip plate is one surface step above the app background, tinted with the
# project's own accent. 0.12 puts plate-vs-background at contrast 1.11-1.12 for
# every palette entry -- the same step the pinned theme's $surface (#1C1B1A)
# takes over its $background (#100F0F) -- so the chip reads as raised material,
# not a highlight, while accent-on-plate keeps >= 87% of the accent's contrast
# against the bare background.
PROJECT_CHIP_PLATE_BLEND = 0.12


@functools.lru_cache(maxsize=256)
def project_chip_plate(accent: str, *, background: str) -> str:
    """Return the plate color behind a project chip drawn on ``background``."""

    return (
        Color.parse(background).blend(Color.parse(accent), PROJECT_CHIP_PLATE_BLEND).hex
    )
