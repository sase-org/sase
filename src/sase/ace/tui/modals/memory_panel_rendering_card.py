"""Note-card title, badges, and property grid for the Memory panel shell.

Split of :mod:`sase.ace.tui.modals.memory_panel_rendering`: this module
owns the note/web/strand card chrome and the aligned metadata grid.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.ace.tui.memory_panel_catalog import (
    MemoryNoteDigest,
    MemoryRailNode,
    MemoryScopeRef,
    MemoryScopeSnapshot,
    memory_note_relations,
)
from sase.memory.inventory import MemoryStats
from sase.memory.notes import AGENTS_PARENT, MemoryNote
from sase.memory.read_log import MemoryReadPathSummary
from sase.notifications.models import format_relative_time

from ._memory_panel_rendering_shared import note_is_invalid
from .glossary_preview_render import build_numbered_chip_rows
from .numbered_link_keys import NUMBERED_LINK_CHIP_PREFIX

_COLOR_LABEL = "dim"
_BADGE_FOREGROUND = "#1a1a1a"


def _note_is_orphaned(note: MemoryNote, notes_by_path: dict[str, MemoryNote]) -> bool:
    if note.type != "reference":
        return False
    if note.parent == AGENTS_PARENT:
        return False
    return note.parent not in notes_by_path


def memory_note_source_path(scope: MemoryScopeRef, note: MemoryNote) -> str:
    """Return the on-disk path *note* was read from within *scope*."""
    return str(Path(scope.content_root) / note.source_relative_path)


def _build_note_card_title(
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


def build_rail_node_card_title(
    node: MemoryRailNode,
    *,
    scope_display_name: str,
    accent: str,
) -> RenderableType:
    """Build the card title for a note, web, or strand row."""
    if node.strand is None and node.web is None:
        return _build_note_card_title(
            node.note,
            scope_display_name=scope_display_name,
            accent=accent,
        )

    identity = Text()
    if node.strand is not None:
        identity.append("S", style=f"bold {accent}")
        identity.append(" ")
        identity.append("STRAND", style=f"bold {accent}")
        identity.append("  ")
        identity.append(node.strand.keyword, style="bold")
        path_label = node.identity
    else:
        assert node.web is not None
        identity.append("W", style=f"bold {accent}")
        identity.append(" ")
        identity.append("MEMORY WEB", style=f"bold {accent}")
        identity.append("  ")
        identity.append(node.web.slug, style="bold")
        path_label = node.note.relative_path

    if scope_display_name:
        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(scope_display_name, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]
    lines.append(Text(path_label, style="dim"))
    return Group(*lines)


def _build_note_description(note: MemoryNote) -> RenderableType:
    """Build the note card's description line, or ``""`` when absent."""
    if not note.description:
        return ""
    return Text(note.description, style="italic")


def build_rail_node_description(node: MemoryRailNode) -> RenderableType:
    """Build the card description for a note, web, or strand row."""
    if node.strand is not None:
        return Text(node.strand.summary, style="italic") if node.strand.summary else ""
    if node.web is not None:
        return (
            Text(node.web.description, style="italic") if node.web.description else ""
        )
    return _build_note_description(node.note)


def append_badge(text: Text, label: str, *, accent: str) -> None:
    if text.plain:
        text.append(" ")
    text.append(f" {label} ", style=f"bold {_BADGE_FOREGROUND} on {accent}")


def build_note_badge_row(
    snapshot: MemoryScopeSnapshot,
    note: MemoryNote,
    *,
    accent: str,
    include_type: bool = True,
) -> Text | None:
    """Build the type/generated/shadow/orphan/invalid badge row."""
    badges: list[str] = []
    if include_type:
        badges.append(
            "CORE · always loaded"
            if note.type == "core"
            else "REFERENCE · read on demand"
        )
    if note.relative_path in snapshot.generated_paths:
        badges.append("GENERATED")
    if note.path.stem in snapshot.shadowed_stems:
        badges.append("SHADOWS HOME")
    notes_by_path = {item.relative_path: item for item in snapshot.notes}
    if _note_is_orphaned(note, notes_by_path):
        badges.append("ORPHANED")
    if note_is_invalid(note):
        badges.append("INVALID")
    if not badges:
        return None
    text = Text()
    for badge in badges:
        append_badge(text, badge, accent=accent)
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


def iso_from_mtime_ns(mtime_ns: int) -> str:
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
    rows: list[tuple[str, str | RenderableType]] = [
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
            ("Last modified", format_relative_time(iso_from_mtime_ns(digest.mtime_ns)))
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

    return build_property_grid(rows, accent=accent)


def build_property_grid(
    rows: list[tuple[str, str | RenderableType]], *, accent: str
) -> RenderableType:
    """Build an aligned two-column metadata grid."""
    grid = Table.grid(expand=True, padding=(0, 2, 0, 0))
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        if isinstance(value, Text):
            rendered: RenderableType = value
        elif isinstance(value, str):
            rendered = Text(value, style=accent)
        else:
            rendered = value
        grid.add_row(Text(label, style=_COLOR_LABEL), rendered)
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
    badges = build_note_badge_row(snapshot, note, accent=accent)
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


__all__ = [
    "append_badge",
    "build_note_badge_row",
    "build_note_card_meta",
    "build_property_grid",
    "build_rail_node_card_title",
    "build_rail_node_description",
    "iso_from_mtime_ns",
    "memory_note_source_path",
]
