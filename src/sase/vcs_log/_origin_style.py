"""Shared presentation for VCS-log commit origins."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

from sase.core.vcs_log_wire import CommitOrigin

ORIGIN_ORDER: tuple[CommitOrigin, ...] = ("stitch", "auto", "manual")

_ORIGIN_GLYPHS: dict[CommitOrigin, str] = {
    "stitch": "✦",
    "auto": "↻",
    "manual": "✎",
}
_ORIGIN_STYLES: dict[CommitOrigin, str] = {
    "stitch": "#FFD700",
    "auto": "dim #8A8A8A",
    "manual": "bold #FFAF5F",
}
_ORIGIN_LABELS: dict[CommitOrigin, str] = {
    "stitch": "stitch",
    "auto": "auto",
    "manual": "manual",
}
_ORIGIN_DETAIL_SUFFIXES: dict[CommitOrigin, str] = {
    "stitch": "sase stitch create",
    "auto": "SASE automation",
    "manual": "no SASE provenance",
}


def origin_glyph(origin: CommitOrigin) -> str:
    """Return the single-cell glyph for *origin*."""
    return _ORIGIN_GLYPHS.get(origin, _ORIGIN_GLYPHS["manual"])


def origin_style(origin: CommitOrigin) -> str:
    """Return the Rich style for *origin*."""
    return _ORIGIN_STYLES.get(origin, _ORIGIN_STYLES["manual"])


def _origin_label(origin: CommitOrigin) -> str:
    """Return the short human label for *origin*."""
    return _ORIGIN_LABELS.get(origin, _ORIGIN_LABELS["manual"])


def build_commit_origin(origin: CommitOrigin) -> Text:
    """Build the shared glyph and short label for one origin."""
    text = Text()
    text.append(
        f"{origin_glyph(origin)} {_origin_label(origin)}",
        style=origin_style(origin),
    )
    return text


def build_origin_legend(origins: Iterable[CommitOrigin]) -> Text:
    """Build the adaptive origin legend cluster for observed origins only."""
    observed = frozenset(origins)
    text = Text()
    for origin in ORIGIN_ORDER:
        if origin not in observed:
            continue
        if text.plain:
            text.append("  ", style="dim")
        text.append_text(build_commit_origin(origin))
    return text


def build_origin_detail(
    origin: CommitOrigin,
    *,
    automation_type: str | None = None,
) -> Text:
    """Build the selected-commit detail text for *origin*."""
    text = build_commit_origin(origin)
    suffix = _origin_detail_suffix(origin, automation_type=automation_type)
    if suffix:
        text.append(" · ", style="dim")
        text.append(suffix, style="dim")
    return text


def _origin_detail_suffix(
    origin: CommitOrigin,
    *,
    automation_type: str | None,
) -> str:
    if origin == "auto" and automation_type is not None:
        cleaned = automation_type.strip()
        if cleaned:
            return cleaned
    return _ORIGIN_DETAIL_SUFFIXES.get(origin, _ORIGIN_DETAIL_SUFFIXES["manual"])


__all__ = [
    "ORIGIN_ORDER",
    "build_commit_origin",
    "build_origin_detail",
    "build_origin_legend",
    "origin_glyph",
    "origin_style",
]
