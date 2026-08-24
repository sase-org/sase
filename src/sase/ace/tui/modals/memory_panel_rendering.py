"""Pure render helpers for the Memory panel shell.

Note-rail rows, the header/footer strips, the note card, and empty/error
states are built here. Nothing in this module touches the filesystem or a
mounted widget -- callers apply these renderables to widgets from
:mod:`sase.ace.tui.modals.memory_panel_view`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.memory_panel_catalog import (
    MemoryNoteDigest,
    MemoryRailNode,
    MemoryScopeRef,
    MemoryScopeSnapshot,
    memory_note_relations,
)
from sase.memory.inventory import MemoryStats
from sase.memory.notes import AGENTS_PARENT, MemoryNote, collapse_description
from sase.memory.read_log import MemoryReadPathSummary
from sase.notifications.models import format_relative_time
from sase.xprompt.highlight_theme import derive_argument_color

from .glossary_preview_render import build_numbered_chip_rows
from .numbered_link_keys import NUMBERED_LINK_CHIP_PREFIX

_COLOR_LABEL = "dim"
_BADGE_FOREGROUND = "#1a1a1a"
_FALLBACK_ACCENT = "#87D7FF"

_TIER1_MARK = "●"  # ●
_TIER2_MARK = "○"  # ○
_CHILD_INDENT = "└ "  # └
_GENERATED_MARK = "⚙"  # ⚙
_INVALID_MARK = "⚠"  # ⚠

# The note rail is sized to fit its widest row. Chrome is everything in
# ``#memory-panel-notes`` that is not text: the 1-cell ``solid`` border on
# each side, ``OptionList``'s default ``padding: 0 1``, and the 2-cell
# vertical scrollbar held open by ``scrollbar-gutter: stable``.
_NOTE_RAIL_CHROME = 6
# Never narrower than the historical fixed width, and never wide enough to
# crowd the note card. Mirrored by the ``min-width`` / ``max-width``
# backstops on ``#memory-panel-notes`` in ``styles.tcss``.
_NOTE_RAIL_MIN_WIDTH = 32
_NOTE_RAIL_MAX_WIDTH = 52
# Cells the note card keeps for itself, chrome included; 56 leaves it ~50
# columns of prose, the narrowest comfortable measure for a note.
_NOTE_RAIL_DETAIL_RESERVED = 56


def memory_card_accent(theme: Any) -> str:
    """Return the theme-derived accent used by the Memory panel."""
    background = getattr(theme, "background", None) or "#000000"
    accent = derive_argument_color(
        getattr(theme, "primary", None),
        foreground=getattr(theme, "foreground", None),
        background=background,
    )
    return accent or _FALLBACK_ACCENT


def build_panel_header(
    *,
    scope_display_name: str,
    note_count: int,
    scope_index: int,
    scope_count: int,
    accent: str,
    unpublished: bool = False,
) -> RenderableType:
    """Build the ``MEMORY · scope · N notes · scope i/N`` header line.

    *unpublished* renders a right-aligned ``⚠ UNPUBLISHED`` badge after a
    panel write that has not yet been published with ``sase memory init``.
    """
    left = Text()
    left.append("MEMORY", style=f"bold {accent}")
    if scope_display_name:
        left.append("  ·  ")
        left.append(scope_display_name, style="bold")
    note_word = "note" if note_count == 1 else "notes"
    left.append(f"  ·  {note_count} {note_word}", style="dim")
    if scope_count > 0:
        left.append(f"  ·  scope {scope_index + 1}/{scope_count}", style="dim")
    if not unpublished:
        return left
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(left, Text("⚠ UNPUBLISHED", style="bold yellow"))
    return grid


def _note_is_invalid(note: MemoryNote) -> bool:
    return note.type_source == "invalid" or note.parent_source == "invalid"


def _note_is_orphaned(note: MemoryNote, notes_by_path: dict[str, MemoryNote]) -> bool:
    if note.type != "reference":
        return False
    if note.parent == AGENTS_PARENT:
        return False
    return note.parent not in notes_by_path


def build_note_row_text(
    node: MemoryRailNode, *, generated_paths: frozenset[str]
) -> Text:
    """Build one note-rail row: tree indent, glyphs, stem, and description."""
    note = node.note
    text = Text()
    if node.depth > 0:
        text.append(_CHILD_INDENT, style="dim")
    marker = _TIER1_MARK if note.type == "core" else _TIER2_MARK
    text.append(f"{marker} ")
    if note.relative_path in generated_paths:
        text.append(f"{_GENERATED_MARK} ")
    if _note_is_invalid(note):
        text.append(f"{_INVALID_MARK} ", style="bold")
    text.append(note.path.stem)
    snippet = collapse_description(note.description)
    if snippet:
        text.append("  ")
        text.append(snippet, style="dim")
    return text


def note_rail_width(
    nodes: tuple[MemoryRailNode, ...],
    *,
    generated_paths: frozenset[str],
    available_width: int,
) -> int:
    """Return the width ``#memory-panel-notes`` should take.

    Wide enough for the widest row of *nodes* to render on one line, clamped
    so the rail is never narrower than its historical fixed width and never
    takes the note card's share of *available_width* -- the panel body's
    content width, or ``0`` before the first layout has settled.
    """
    if not nodes:
        return _NOTE_RAIL_MIN_WIDTH
    widest = max(
        build_note_row_text(node, generated_paths=generated_paths).cell_len
        for node in nodes
    )
    desired = widest + _NOTE_RAIL_CHROME
    cap = _NOTE_RAIL_MAX_WIDTH
    if available_width > 0:
        # The ``- 1`` is ``#memory-panel-detail``'s ``margin-left``.
        room = available_width - _NOTE_RAIL_DETAIL_RESERVED - 1
        cap = min(cap, max(_NOTE_RAIL_MIN_WIDTH, room))
    return max(_NOTE_RAIL_MIN_WIDTH, min(cap, desired))


def memory_note_source_path(scope: MemoryScopeRef, note: MemoryNote) -> str:
    """Return the on-disk path *note* was read from within *scope*."""
    return str(Path(scope.content_root) / note.source_relative_path)


def build_note_card_title(
    note: MemoryNote,
    *,
    scope_display_name: str,
    accent: str,
) -> RenderableType:
    """Build the note card's title: stem plus root-relative path."""
    identity = Text()
    identity.append("M", style=f"bold {accent}")
    identity.append(" ")
    identity.append("MEMORY", style=f"bold {accent}")
    identity.append("  ")
    identity.append(note.path.stem, style="bold")

    if scope_display_name:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(scope_display_name, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]
    lines.append(Text(note.relative_path, style="dim"))
    return Group(*lines)


def build_note_description(note: MemoryNote) -> RenderableType:
    """Build the note card's description line, or ``""`` when absent."""
    if not note.description:
        return ""
    return Text(note.description, style="italic")


def _append_badge(text: Text, label: str, *, accent: str) -> None:
    if text.plain:
        text.append(" ")
    text.append(f" {label} ", style=f"bold {_BADGE_FOREGROUND} on {accent}")


def _build_note_badge_row(
    snapshot: MemoryScopeSnapshot, note: MemoryNote, *, accent: str
) -> Text | None:
    """Build the tier/generated/shadow/orphan/invalid badge row."""
    badges: list[str] = []
    badges.append("TIER 1 · always loaded" if note.type == "core" else "TIER 2")
    if note.relative_path in snapshot.generated_paths:
        badges.append("GENERATED")
    if note.path.stem in snapshot.shadowed_stems:
        badges.append("SHADOWS HOME")
    notes_by_path = {item.relative_path: item for item in snapshot.notes}
    if _note_is_orphaned(note, notes_by_path):
        badges.append("ORPHANED")
    if _note_is_invalid(note):
        badges.append("INVALID")
    if not badges:
        return None
    text = Text()
    for badge in badges:
        _append_badge(text, badge, accent=accent)
    return text


def _type_label(note: MemoryNote) -> str:
    if note.type_source == "invalid":
        return "invalid"
    if note.type_source == "missing":
        return "missing"
    return note.type or "missing"


def _parent_label(note: MemoryNote) -> str:
    if note.parent_source == "invalid":
        return f"{note.parent} (invalid)"
    return note.parent


def _iso_from_mtime_ns(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, tz=UTC).isoformat()


def _build_note_property_grid(
    note: MemoryNote,
    *,
    child_count: int,
    stats: MemoryStats | None,
    digest: MemoryNoteDigest | None,
    read_summary: MemoryReadPathSummary | None,
    source_path: str,
    accent: str,
) -> RenderableType:
    """Build the aligned type/parent/size/read/source metadata grid."""
    rows: list[tuple[str, str]] = [
        ("Type", _type_label(note)),
        ("Parent", _parent_label(note)),
        ("Children", str(child_count)),
    ]
    if stats is not None:
        line_word = "line" if stats.line_count == 1 else "lines"
        rows.append(
            (
                "Size",
                f"{stats.line_count} {line_word}, ~{stats.approx_token_count} tokens",
            )
        )
    if digest is not None:
        rows.append(
            ("Last modified", format_relative_time(_iso_from_mtime_ns(digest.mtime_ns)))
        )
    if read_summary is not None:
        rows.append(
            (
                "Last audited read",
                f"{read_summary.last_agent} · {read_summary.last_reason} · "
                f"{format_relative_time(read_summary.last_read_at)}",
            )
        )
    rows.append(("Source", source_path))

    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        grid.add_row(Text(label, style=_COLOR_LABEL), Text(value, style=accent))
    return grid


def build_note_card_meta(
    snapshot: MemoryScopeSnapshot,
    note: MemoryNote,
    *,
    accent: str,
    parent: tuple[MemoryNote, ...] | None = None,
    children: tuple[MemoryNote, ...] | None = None,
    focused_link_number: int | None = None,
) -> RenderableType:
    """Build the badge row, link chips, divider, and property grid.

    When *parent* or *children* is omitted, both are recomputed from
    ``memory_note_relations`` so callers that only need the static card
    (tests, empty-cursor paint) still get the numbered PARENT / CHILDREN
    rows.
    """
    if parent is None or children is None:
        parent, children = memory_note_relations(snapshot, note)
    sections: list[RenderableType] = []
    badges = _build_note_badge_row(snapshot, note, accent=accent)
    if badges is not None:
        sections.append(badges)
    chip_rows = build_numbered_chip_rows(
        (
            ("PARENT", tuple(item.path.stem for item in parent)),
            ("CHILDREN", tuple(item.path.stem for item in children)),
        ),
        focused_number=focused_link_number,
        accent=accent,
        shortcut_prefix=NUMBERED_LINK_CHIP_PREFIX,
    )
    if chip_rows is not None:
        sections.append(chip_rows)
    sections.append(Text("-" * 44, style="dim"))
    sections.append(
        _build_note_property_grid(
            note,
            child_count=len(children),
            stats=snapshot.stats.get(note.relative_path),
            digest=snapshot.digests.get(note.relative_path),
            read_summary=snapshot.read_summaries.get(note.relative_path),
            source_path=memory_note_source_path(snapshot.scope, note),
            accent=accent,
        )
    )
    return Group(*sections)


def build_empty_scope_message(scope_display_name: str, *, accent: str) -> Text:
    """Build the centered invitation shown for a scope with no notes yet."""
    text = Text(justify="center")
    text.append("No memory notes in ", style="dim")
    text.append(scope_display_name, style="bold")
    text.append(" yet.\n\n", style="dim")
    text.append("Press ", style="dim")
    text.append("a", style=f"bold {accent}")
    text.append(" to add the first note.", style="dim")
    return text


def build_empty_scope_no_root_message(scope_display_name: str, *, accent: str) -> Text:
    """Build the message shown for a scope with no memory root yet."""
    text = Text(justify="center")
    text.append("No memory root for ", style="dim")
    text.append(scope_display_name, style="bold")
    text.append(" yet.\n\n", style="dim")
    text.append(
        "sase/memory/ will be created when you add the first note.", style="dim"
    )
    return text


def build_diagnostics_message(
    diagnostics: tuple[str, ...], *, accent: str
) -> RenderableType:
    """Build the error state shown for a scope whose notes failed to load."""
    text = Text(justify="left")
    text.append("Memory failed to load:\n\n", style=f"bold {accent}")
    for index, diagnostic in enumerate(diagnostics):
        if index:
            text.append("\n")
        text.append(diagnostic, style="dim")
    return text


def build_no_match_message(pattern: str) -> Text:
    """Build the message shown when a filter pattern matches no notes."""
    return Text(f"no notes matched: {pattern}", style="dim")


def build_panel_footer(
    keymaps: MemoryPanelKeymaps,
    *,
    has_notes: bool,
    has_source_path: bool,
    ring_size: int,
    has_links: bool = False,
    has_trail: bool = False,
    focused_link_stem: str | None = None,
    can_mutate: bool = False,
    unpublished: bool = False,
) -> str:
    """Build the footer strip, showing only currently-conditional keymaps.

    Link and back keys appear when chips or a trail are present.
    Edit/delete appear when a writable note is selected; publish appears
    when this scope is unpublished.
    """
    parts: list[str] = []
    if ring_size > 1:
        parts.append(
            f"{key_display_name(keymaps.next_scope)}/"
            f"{key_display_name(keymaps.prev_scope)} scope"
        )
    if has_links:
        parts.append(f"{key_display_name(keymaps.next_link)} link")
        parts.append(f"{key_display_name(keymaps.follow_link)} follow")
        if focused_link_stem:
            parts.append(f"→ {focused_link_stem}")
    if has_trail:
        parts.append(f"{key_display_name(keymaps.travel_back)} back")
    if can_mutate:
        parts.append(f"{key_display_name(keymaps.edit_note)} edit")
        parts.append(f"{key_display_name(keymaps.delete_note)} delete")
    if unpublished:
        parts.append(f"{key_display_name(keymaps.publish)} publish")
    if has_notes:
        parts.append(f"{key_display_name(keymaps.copy_body)} copy")
    if has_source_path:
        parts.append(f"{key_display_name(keymaps.open_source)} source")
        parts.append(f"{key_display_name(keymaps.open_viewer)} view")
    return "  ·  ".join(parts)


__all__ = [
    "build_diagnostics_message",
    "build_empty_scope_message",
    "build_empty_scope_no_root_message",
    "build_no_match_message",
    "build_note_card_meta",
    "build_note_card_title",
    "build_note_description",
    "build_note_row_text",
    "build_panel_footer",
    "build_panel_header",
    "memory_card_accent",
    "memory_note_source_path",
    "note_rail_width",
]
