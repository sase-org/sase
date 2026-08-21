"""Note-rail filtering and width behavior for the Memory panel."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.memory_pane import MemoryPane
from tests.ace.tui.modals.memory_panel_test_helpers import (
    MemoryPanelTestApp,
    install_fixed_load,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


async def test_filter_matches_stem_and_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        # Matches on stem.
        memory_note("agent_hood", description="Covers a different term."),
        # Matches on description, not stem.
        memory_note("sase_agent", description="Mentions hood in passing."),
        memory_note("zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "hood":
            await pilot.press(char)
        await wait_for(
            pilot,
            lambda: (
                sorted(row.note.path.stem for row in panel._rows)
                == ["agent_hood", "sase_agent"]
            ),
        )


async def test_filter_extends_into_bodies_only_when_toggled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("hub", body="Mentions dragonfruit deep in the body."),
        memory_note("other"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        await pilot.press(".", "1")
        assert panel._filter_input().value == ".1"
        assert panel._pending_numbered_link is False
        for _ in range(2):
            await pilot.press("backspace")
        for char in "dragonfruit":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._rows)

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)
        await pilot.press("greater_than_sign")
        await wait_for(
            pilot, lambda: [row.note.path.stem for row in panel._rows] == ["hub"]
        )


async def test_empty_filter_shows_no_match_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (memory_note("agent_hood"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "nomatch":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._rows)
        assert "no notes matched: nomatch" in panel_static_text(
            panel, "memory-panel-card-meta"
        )


async def test_note_rail_width_matches_widest_row_after_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("agent_hood", description="Agent hood alias hood."),
        memory_note("zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width = panel._note_list().styles.width
        assert width is not None
        assert width.value >= 32


async def test_filtering_to_short_notes_does_not_jitter_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("agent_hood", description="Agent hood alias hood."),
        memory_note("zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width_before = panel._note_list().styles.width.value

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "zebra":
            await pilot.press(char)
        await wait_for(
            pilot, lambda: [row.note.path.stem for row in panel._rows] == ["zebra"]
        )

        assert panel._note_list().styles.width.value == width_before


async def test_cycling_to_a_scope_with_short_notes_shrinks_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(
            ref_a, (memory_note("agent_hood", description="Agent hood alias hood."),)
        ),
        "proj-b": scope_snapshot(ref_b, (memory_note("ab"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width_a = panel._note_list().styles.width.value

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        await pilot.pause()
        assert panel._note_list().styles.width.value == 32
        assert panel._note_list().styles.width.value <= width_a


async def test_note_list_option_list_widget_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (memory_note("agent_hood"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        option_list = panel.query_one("#memory-panel-notes", OptionList)
        assert option_list.option_count == 1
