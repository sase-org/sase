"""Header, footer, empty/error states, and accent for the Memory panel.

Split of :mod:`sase.ace.tui.modals.memory_panel_rendering`: this module
owns the panel chrome strips and the empty/error invitation copy.
"""

from __future__ import annotations

from typing import Any

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.display import key_display_name
from sase.macro.highlight_theme import derive_argument_color

_FALLBACK_ACCENT = "#87D7FF"


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
    deleted_count: int = 0,
) -> RenderableType:
    """Build the ``MEMORY · scope · N notes · scope i/N`` header line.

    *unpublished* renders a right-aligned ``⚠ UNPUBLISHED`` badge after a
    panel write that has not yet been published with ``sase memory init``.
    *deleted_count* appends the ``· N deleted`` chip while the DELETED
    group is shown.
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
    if deleted_count > 0:
        left.append(f"  ·  {deleted_count} deleted", style="dim")
    if not unpublished:
        return left
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="ellipsis")
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(left, Text("⚠ UNPUBLISHED", style="bold yellow"))
    return grid


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
    web_action: str | None = None,
    has_strand_navigation: bool = False,
    can_mutate: bool = False,
    unpublished: bool = False,
    time_verbs: tuple[str, ...] = (),
    edit_now: bool = False,
    deleted_verb: str = "",
) -> str:
    """Build the footer strip, showing only currently-conditional keymaps.

    Link and back keys appear when chips or a trail are present.
    Edit/delete appear when a writable note is selected; publish appears
    when this scope is unpublished. History and changes appear whenever
    notes are listed. Step destinations from ``time_verbs_for_moment``
    follow the lens keys; while pinned in the past, refusing verbs are
    hidden and ``o`` reads ``edit now``.
    """
    parts: list[str] = []
    if has_notes:
        parts.append(f"{key_display_name(keymaps.open_history)} history")
        parts.append(f"{key_display_name(keymaps.open_changes)} changes")
    if deleted_verb:
        parts.append(deleted_verb)
    for verb in time_verbs:
        if verb:
            parts.append(str(verb))
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
    if web_action:
        parts.append(f"{key_display_name(keymaps.toggle_web)} {web_action}")
    if has_strand_navigation:
        parts.append(
            f"{key_display_name(keymaps.next_strand)}/"
            f"{key_display_name(keymaps.prev_strand)} strand"
        )
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
        if edit_now:
            parts.append(f"{key_display_name(keymaps.open_source)} edit now")
        else:
            parts.append(f"{key_display_name(keymaps.open_source)} source")
        parts.append(f"{key_display_name(keymaps.open_viewer)} view")
    return "  ·  ".join(parts)


__all__ = [
    "build_diagnostics_message",
    "build_empty_scope_message",
    "build_empty_scope_no_root_message",
    "build_no_match_message",
    "build_panel_footer",
    "build_panel_header",
    "memory_card_accent",
]
