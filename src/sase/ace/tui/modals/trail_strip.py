"""Shared breadcrumb-strip renderer used by Memory, Snippets, and the pager.

Pure and free of any glossary-specific data or imports, so panes that need a
``TRAIL  A › B › C`` strip do not have to depend on the glossary panel.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS

_KIND_TO_TAB = {
    "agent": "agents",
    "agents": "agents",
    "bead": "beads",
    "beads": "beads",
    "file": "files",
    "files": "files",
    "patch": "patches",
    "patches": "patches",
    "plan": "ref:plan",
    "ref:plan": "ref:plan",
    "stitch": "stitches",
    "stitches": "stitches",
}
_EXTRA_ICONS = {
    "ref:plan": "✎",
}
_DEFAULT_ENTRY_ICON = "◆"
_DEFAULT_ENTRY_ACCENT = "#AFAFAF"
_SEPARATOR = " › "


@dataclass(frozen=True, slots=True)
class TrailStripEntry:
    """One optional kind-aware breadcrumb label."""

    label: str
    kind: str | None = None


def build_trail_strip(
    path: Sequence[str | TrailStripEntry], *, accent: str, max_width: int = 70
) -> Text:
    """Build the ``TRAIL  A › B › C`` breadcrumb strip.

    String-only callers keep the original width-based elision: once the
    plain joined path exceeds *max_width*, the middle is elided while the
    first entry and the two most recent stay visible. Kind-aware pager
    entries collapse as soon as the depth passes three, because the full
    numbered trail is available in ``?``.
    """
    entries = tuple(_coerce_entry(item) for item in path)
    text = Text()
    text.append("TRAIL  ", style=f"bold {accent}")
    if _should_count_elide(entries):
        text.append("⟨ ", style="dim")
        text.append(f"…{len(entries) - 1}", style="dim")
        text.append(_SEPARATOR, style="dim")
        append_trail_entry(text, entries[-1])
        text.append(" ⟩", style="dim")
    elif _should_width_elide(entries, max_width=max_width):
        append_trail_entry(text, entries[0])
        text.append(_SEPARATOR, style="dim")
        text.append("…", style="dim")
        for entry in entries[-2:]:
            text.append(_SEPARATOR, style="dim")
            append_trail_entry(text, entry)
    else:
        _append_joined_entries(text, entries)
    return text


def append_trail_entry(text: Text, entry: TrailStripEntry) -> None:
    """Append one crumb to ``text`` with optional kind glyph/accent styling."""
    if entry.kind is None:
        text.append(entry.label)
        return
    icon, accent = _entry_marker(entry.kind)
    text.append(f"{icon} ", style=f"bold {accent}")
    text.append(entry.label, style=accent)


def _append_joined_entries(text: Text, entries: tuple[TrailStripEntry, ...]) -> None:
    for index, entry in enumerate(entries):
        if index > 0:
            text.append(_SEPARATOR, style="dim")
        append_trail_entry(text, entry)


def _should_count_elide(entries: tuple[TrailStripEntry, ...]) -> bool:
    return len(entries) > 3 and any(entry.kind is not None for entry in entries)


def _should_width_elide(
    entries: tuple[TrailStripEntry, ...],
    *,
    max_width: int,
) -> bool:
    if len(entries) <= 3:
        return False
    return cell_len(_plain_joined_entries(entries)) > max_width


def _plain_joined_entries(entries: tuple[TrailStripEntry, ...]) -> str:
    return _SEPARATOR.join(_plain_entry(entry) for entry in entries)


def _plain_entry(entry: TrailStripEntry) -> str:
    if entry.kind is None:
        return entry.label
    icon, _accent = _entry_marker(entry.kind)
    return f"{icon} {entry.label}"


def _coerce_entry(entry: str | TrailStripEntry) -> TrailStripEntry:
    if isinstance(entry, TrailStripEntry):
        return entry
    return TrailStripEntry(entry)


def _entry_marker(kind: str) -> tuple[str, str]:
    tab = _KIND_TO_TAB.get(kind)
    if tab is None:
        return (_DEFAULT_ENTRY_ICON, _DEFAULT_ENTRY_ACCENT)
    return (
        _EXTRA_ICONS.get(tab, ARTIFACTS_ICONS.get(tab, _DEFAULT_ENTRY_ICON)),
        ARTIFACTS_ACCENTS.get(tab, _DEFAULT_ENTRY_ACCENT),
    )


__all__ = ["TrailStripEntry", "append_trail_entry", "build_trail_strip"]
