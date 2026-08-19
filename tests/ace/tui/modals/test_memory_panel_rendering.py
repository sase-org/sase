"""Rendering helper tests for the Memory panel shell."""

from __future__ import annotations

from rich.console import Console

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.memory_panel_catalog import MemoryRailNode
from sase.ace.tui.modals.memory_panel_help_modal import MemoryPanelHelpModal
from sase.ace.tui.modals.memory_panel_rendering import (
    build_empty_scope_message,
    build_empty_scope_no_root_message,
    _build_note_badge_row,
    _build_note_property_grid,
    build_note_card_meta,
    build_note_row_text,
    build_panel_footer,
    note_rail_width,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)


def _row(note, *, depth: int = 0) -> MemoryRailNode:
    return MemoryRailNode(note=note, depth=depth)


def test_empty_scope_message_names_display_name() -> None:
    text = build_empty_scope_message("Research", accent="#87D7FF")

    assert text.plain == (
        "No memory notes in Research yet.\n\nPress a to add the first note."
    )
    assert "gh_" not in text.plain


def test_empty_scope_no_root_message_names_display_name() -> None:
    text = build_empty_scope_no_root_message("Research", accent="#87D7FF")

    assert "No memory root for Research yet." in text.plain
    assert "will be created" in text.plain


def test_panel_footer_lists_only_conditional_keys() -> None:
    keymaps = MemoryPanelKeymaps()

    assert (
        build_panel_footer(keymaps, has_notes=False, has_source_path=False, ring_size=1)
        == ""
    )

    footer = build_panel_footer(
        keymaps, has_notes=True, has_source_path=True, ring_size=2
    )
    assert "p/P scope" in footer
    assert "y copy" in footer
    assert "o edit" in footer
    assert "Z view" in footer
    assert "a add" not in footer
    assert "filter" not in footer
    assert "help" not in footer
    assert "esc" not in footer
    assert "j/" not in footer
    assert "refresh" not in footer


def test_panel_footer_lists_link_and_back_when_present() -> None:
    keymaps = MemoryPanelKeymaps()
    footer = build_panel_footer(
        keymaps,
        has_notes=True,
        has_source_path=True,
        ring_size=2,
        has_links=True,
        has_trail=True,
        focused_link_stem="child",
    )
    assert "Tab link" in footer
    assert "Enter / l follow" in footer
    assert "→ child" in footer
    assert "backspace / h back" in footer
    assert "p/P scope" in footer


def test_note_card_meta_renders_parent_and_children_chips() -> None:
    ref = scope_ref("sase", "sase")
    hub = memory_note("hub", description="Hub.")
    child = memory_note("child", parent="sase/memory/hub.md", description="Child.")
    snapshot = scope_snapshot(ref, (hub, child))

    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(build_note_card_meta(snapshot, child, accent="#87D7FF"))
    text = capture.get()

    assert "PARENT" in text
    assert "1 hub" in text
    assert "CHILDREN" not in text


def test_memory_panel_help_documents_enter_does_not_follow() -> None:
    modal = MemoryPanelHelpModal(keymaps=MemoryPanelKeymaps())
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(modal._content())
    text = capture.get()

    assert "only l currently follows a chip" in text
    assert "Enter does nothing in this panel" in text


def test_note_row_text_marks_tier_and_child_indent() -> None:
    short_row = _row(memory_note("always", note_type="short"))
    long_row = _row(memory_note("hub"))
    child_row = _row(memory_note("child", parent="sase/memory/hub.md"), depth=1)

    assert build_note_row_text(short_row, generated_paths=frozenset()).plain.startswith(
        "● "
    )
    assert build_note_row_text(long_row, generated_paths=frozenset()).plain.startswith(
        "○ "
    )
    child_text = build_note_row_text(child_row, generated_paths=frozenset()).plain
    assert child_text.startswith("└ ○ ")
    assert "child" in child_text


def test_note_row_text_marks_generated_and_invalid() -> None:
    generated = memory_note("sase")
    row = _row(generated)
    text = build_note_row_text(
        row, generated_paths=frozenset({"sase/memory/sase.md"})
    ).plain
    assert "⚙" in text

    invalid = memory_note("broken", type_source="invalid")
    text = build_note_row_text(_row(invalid), generated_paths=frozenset()).plain
    assert "⚠" in text


def test_note_row_text_includes_description_snippet() -> None:
    note = memory_note("hub", description="Line one.\nLine two.")
    text = build_note_row_text(_row(note), generated_paths=frozenset()).plain
    assert "Line one. Line two." in text


def test_note_badge_row_marks_tier_generated_shadowed_orphaned_invalid() -> None:
    ref = scope_ref("sase", "sase")

    short_note = memory_note("always", note_type="short")
    assert (
        _build_note_badge_row(
            scope_snapshot(ref, (short_note,)), short_note, accent="#fff"
        ).plain
    ) == " TIER 1 · always loaded "

    long_note = memory_note("hub")
    assert (
        _build_note_badge_row(
            scope_snapshot(ref, (long_note,)), long_note, accent="#fff"
        ).plain
    ) == " TIER 2 "

    generated_note = memory_note("sase")
    snapshot = scope_snapshot(
        ref, (generated_note,), generated_paths=frozenset({"sase/memory/sase.md"})
    )
    assert (
        "GENERATED"
        in _build_note_badge_row(snapshot, generated_note, accent="#fff").plain
    )

    shadowed_note = memory_note("shared")
    snapshot = scope_snapshot(
        ref, (shadowed_note,), shadowed_stems=frozenset({"shared"})
    )
    assert (
        "SHADOWS HOME"
        in _build_note_badge_row(snapshot, shadowed_note, accent="#fff").plain
    )

    orphan_note = memory_note("orphan", parent="sase/memory/missing.md")
    snapshot = scope_snapshot(ref, (orphan_note,))
    assert (
        "ORPHANED" in _build_note_badge_row(snapshot, orphan_note, accent="#fff").plain
    )

    invalid_note = memory_note("broken", parent_source="invalid")
    snapshot = scope_snapshot(ref, (invalid_note,))
    assert (
        "INVALID" in _build_note_badge_row(snapshot, invalid_note, accent="#fff").plain
    )


def test_note_property_grid_includes_type_parent_children_and_source() -> None:
    note = memory_note("hub", description="Hub note.")
    grid = _build_note_property_grid(
        note,
        child_count=2,
        stats=None,
        digest=None,
        read_summary=None,
        source_path="/tmp/demo/sase/memory/hub.md",
        accent="#fff",
    )
    # Type, Parent, Children, Source -- no Size/Last modified/Last audited
    # read rows since stats/digest/read_summary are all None.
    assert grid.row_count == 4


def test_note_rail_width_is_driven_by_the_widest_row() -> None:
    nodes = (
        _row(memory_note("agent_instruction_file", description="Long stem note.")),
        _row(memory_note("z")),
    )
    assert (
        note_rail_width(nodes, generated_paths=frozenset(), available_width=1000) == 47
    )


def test_note_rail_width_clamps_below_the_historical_minimum() -> None:
    assert note_rail_width((), generated_paths=frozenset(), available_width=1000) == 32
    assert (
        note_rail_width(
            (_row(memory_note("a")),), generated_paths=frozenset(), available_width=1000
        )
        == 32
    )


def test_note_rail_width_clamps_above_the_maximum() -> None:
    node = _row(memory_note("a" * 80))
    assert (
        note_rail_width((node,), generated_paths=frozenset(), available_width=1000)
        == 52
    )


def test_note_rail_width_is_constrained_by_available_room() -> None:
    nodes = (
        _row(memory_note("agent_instruction_file", description="Long stem note.")),
    )
    assert note_rail_width(nodes, generated_paths=frozenset(), available_width=84) == 32


def test_note_rail_width_ignores_room_clamp_before_layout_settles() -> None:
    nodes = (
        _row(memory_note("agent_instruction_file", description="Long stem note.")),
    )
    assert note_rail_width(nodes, generated_paths=frozenset(), available_width=0) == 47
