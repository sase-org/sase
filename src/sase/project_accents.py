"""Deterministic, collision-free accent colors for enabled projects.

Shared backend for every project-tag surface (D6): the top-right chip, the
Projects pane, ``sase project current``, and every tag renderer use one
canonical ``among`` set — enabled, non-system project keys — so the TUI and
the CLI cannot drift.

This module owns ``PROJECT_ACCENTS``, :func:`project_accent`, and the map
helpers. :mod:`sase.ace.tui.project_styles` keeps re-exports for existing
importers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import functools
from collections.abc import Mapping

from sase.palette_hash import hash_palette_index as _hash_index

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


def project_accent_index(
    project_key: str, *, among: Iterable[str] | None = None
) -> int:
    """Return the palette index of ``project_key``'s accent.

    Mirrors :func:`project_accent`: hash-only without ``among``, unique
    within ``among`` otherwise. The index points into :data:`PROJECT_ACCENTS`
    (the LSP catalog's ``accent_palette``).
    """

    accent = project_accent(project_key, among=among)
    try:
        return PROJECT_ACCENTS.index(accent)
    except ValueError:
        return _hash_index(project_key, len(PROJECT_ACCENTS))


def _record_state(record: Any) -> str | None:
    state = getattr(record, "state", None)
    if state is None and isinstance(record, dict):
        state = record.get("state")
    return str(state) if state is not None else None


def _record_name(record: Any) -> str | None:
    for attr in ("project_name", "key", "name"):
        value = getattr(record, attr, None)
        if value:
            return str(value)
    if isinstance(record, dict):
        for key in ("project_name", "key", "name"):
            value = record.get(key)
            if value:
                return str(value)
    if isinstance(record, str):
        return record
    return None


def accent_among_keys(records: Iterable[Any]) -> tuple[str, ...]:
    """Return the D6 canonical accent set for *records*.

    The canonical set is the enabled, non-system project keys: records whose
    state is ``enabled``, that are not system-managed, that are true projects
    (not siblings), and that are not the system ``home`` project. The result
    is sorted for determinism.
    """

    keys: list[str] = []
    for record in records:
        name = _record_name(record)
        if not name or name.casefold() == "home":
            continue
        state = _record_state(record)
        if state is not None and state != "enabled":
            continue
        system_managed = getattr(record, "system_managed", None)
        if system_managed is None and isinstance(record, dict):
            system_managed = record.get("system_managed")
        if system_managed:
            continue
        is_project = getattr(record, "is_project", None)
        if is_project is None and isinstance(record, dict):
            is_project = record.get("is_project", True)
        if is_project is False:
            continue
        keys.append(name)
    return tuple(sorted(set(keys)))


__all__ = [
    "PROJECT_ACCENTS",
    "accent_among_keys",
    "project_accent",
    "project_accent_index",
]
