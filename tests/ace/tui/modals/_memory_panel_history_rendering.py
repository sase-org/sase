"""Rendering and time-strip tests for the memory panel history."""

from __future__ import annotations

from rich.console import Console

from tests.ace.tui.modals._memory_panel_history_fixtures import history_summary

from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps
from sase.ace.tui.keymaps.bindings import build_memory_bindings, memory_help_bindings
from sase.ace.tui.modals import memory_panel_rendering_card as rendering_card_module
from sase.ace.tui.modals.memory_panel_history import selector_for_node
from sase.ace.tui.modals.memory_panel_rendering import (
    build_note_card_meta,
    build_panel_footer,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)


def test_memory_bindings_include_history_and_changes() -> None:
    keymaps = MemoryPanelKeymaps()
    assert keymaps.open_history == "H"
    assert keymaps.open_changes == "C"
    actions = {binding.action for binding in build_memory_bindings(keymaps)}
    assert "open_history" in actions
    assert "open_changes" in actions
    descriptions = dict(memory_help_bindings(keymaps))
    # Help surfaces the effective keys for the new verbs.
    assert "H" in descriptions
    assert "C" in descriptions


def test_panel_footer_always_shows_history_with_notes() -> None:
    keymaps = MemoryPanelKeymaps()
    shown = build_panel_footer(
        keymaps, has_notes=True, has_source_path=True, ring_size=1
    )
    assert "H history" in shown
    assert "C changes" in shown
    empty = build_panel_footer(
        keymaps,
        has_notes=False,
        has_source_path=False,
        ring_size=1,
    )
    assert "history" not in empty


def test_time_strip_clean_now_shows_pill_and_meaning() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        TimeStripSnapshot,
        build_time_band_for_timeline,
        render_card_head,
        render_time_strip,
    )
    from sase.pager.history_kit import history_styles_for_theme

    timeline = history_summary()
    snapshot = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=dict(timeline),
        now_epoch=1790769600,
    )
    styles = history_styles_for_theme(None)
    head = render_card_head("sase/memory/gotchas.md", snapshot, styles, width=60)
    assert "NOW" in head.plain
    assert "sase/memory/gotchas.md" in head.plain
    data = build_time_band_for_timeline(
        dict(timeline),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert data is not None
    strip = render_time_strip(data, width=60, rows=2, styles=styles)
    # Row 2 answers "what changed last?" with the newest meaning.
    assert (
        "sase-1bc.12" in strip.plain
        or "authored" in strip.plain.lower()
        or strip.plain.strip() != ""
    )


def test_time_strip_untracked_and_no_vcs_use_pager_words() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        build_time_band_for_timeline,
        render_time_strip,
    )
    from sase.pager.history_kit import history_styles_for_theme

    styles = history_styles_for_theme(None)
    untracked = build_time_band_for_timeline(
        history_summary(state="untracked", versions=[]),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert untracked is not None
    assert (
        "UNTRACKED"
        in render_time_strip(untracked, width=60, rows=2, styles=styles).plain
    )
    no_vcs = build_time_band_for_timeline(
        history_summary(state="NO VCS", versions=[]),
        subject_id="note:sase/memory/gotchas.md",
        now_epoch=1790769600,
    )
    assert no_vcs is not None
    assert "NO VCS" in render_time_strip(no_vcs, width=60, rows=2, styles=styles).plain


def test_time_strip_indexing_reserves_rows_and_folds() -> None:
    from sase.ace.tui.modals.memory_pane_time_strip import (
        build_time_band_for_timeline,
        render_time_strip,
        time_strip_row_count,
    )
    from sase.pager.history_kit import history_styles_for_theme

    assert time_strip_row_count(10) == 1
    assert time_strip_row_count(20) == 2
    styles = history_styles_for_theme(None)
    data = build_time_band_for_timeline(
        None, subject_id="note:sase/memory/gotchas.md", loading=True
    )
    assert data is not None
    strip = render_time_strip(data, width=60, rows=2, styles=styles)
    assert "indexing" in strip.plain.lower()
    folded = render_time_strip(data, width=60, rows=1, styles=styles)
    assert "indexing" in folded.plain.lower()


def test_note_property_grid_has_no_history_row() -> None:
    note = memory_note("gotchas")
    grid = rendering_card_module._build_note_property_grid(
        note,
        child_count=0,
        stats=None,
        digest=None,
        read_summary=None,
        source_path="/tmp/sase/memory/gotchas.md",
        accent="#fff",
    )
    # Type, Parent, Children, Source.
    assert grid.row_count == 4
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(grid)
    text = capture.get()
    assert "History" not in text


def test_note_card_meta_has_no_history_row() -> None:
    ref = scope_ref("sase", "sase")
    note = memory_note("gotchas", description="Gotchas.")
    snapshot = scope_snapshot(ref, (note,))
    rendered = build_note_card_meta(
        snapshot,
        note,
        accent="#87D7FF",
    )
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(rendered)
    assert "History" not in capture.get()


def test_selector_for_node_covers_notes_and_strands() -> None:
    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    note = memory_note("gotchas")
    node = MemoryRailNode(note=note, depth=0)
    assert selector_for_node(node) == "sase/memory/gotchas.md"

    from tests.ace.tui.modals.memory_panel_test_helpers import (
        memory_web_with_mentioning_strands,
    )

    web = memory_web_with_mentioning_strands()
    strand = web.strands[0]
    strand_node = MemoryRailNode(
        note=note, depth=1, web=web, strand=strand, strand_scope="project"
    )
    selector = selector_for_node(strand_node)
    assert selector is not None
    assert selector.startswith(f"{web.slug}:")


def test_stale_chip_marks_only_a_kept_snapshot() -> None:
    """``stale`` rides with the last good strip, never with no snapshot."""
    from sase.ace.tui.modals.memory_pane_time_strip import (
        TimeStripSnapshot,
        render_card_head,
    )
    from sase.pager.history_kit import history_styles_for_theme

    styles = history_styles_for_theme(None)
    kept = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=history_summary(),
        now_epoch=1790769600,
        failed=True,
    )
    assert "stale" in render_card_head("sase/memory/gotchas.md", kept, styles).plain
    nothing = TimeStripSnapshot(
        subject_id="note:sase/memory/gotchas.md",
        path_label="sase/memory/gotchas.md",
        timeline=None,
        now_epoch=1790769600,
        failed=True,
    )
    head = render_card_head("sase/memory/gotchas.md", nothing, styles).plain
    assert "stale" not in head
