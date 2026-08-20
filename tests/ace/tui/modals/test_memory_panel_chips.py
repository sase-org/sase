"""Parent/child chips, digit shortcuts, and following them in the Memory panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.memory.notes import MemoryNote
from tests.ace.tui.modals.memory_panel_test_helpers import (
    MemoryPanelTestApp,
    install_fixed_load,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


def _linked_notes() -> tuple[MemoryNote, ...]:
    """A short root, a hub with two children, and a grandchild under `both`."""
    return (
        memory_note("always", note_type="short", description="Always loaded."),
        memory_note("hub", description="Hub."),
        memory_note("both", parent="sase/memory/hub.md", description="Has a child."),
        memory_note("grand", parent="sase/memory/both.md", description="Grandchild."),
        memory_note("child", parent="sase/memory/hub.md", description="Leaf child."),
        memory_note("zeta", description="Root with no children."),
    )


async def test_root_note_chips_are_children_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")

        assert panel._chip_parent_count == 0
        assert [note.path.stem for note in panel._chip_notes] == ["both", "child"]

        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "PARENT" not in meta
        assert "CHILDREN" in meta
        assert "1 both" in meta
        assert "2 child" in meta


async def test_child_note_chips_are_parent_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/child.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/child.md")

        assert panel._chip_parent_count == 1
        assert [note.path.stem for note in panel._chip_notes] == ["hub"]

        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "PARENT" in meta
        assert "CHILDREN" not in meta
        assert "1 hub" in meta


async def test_note_with_both_edges_numbers_continuously(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/both.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/both.md")

        assert panel._chip_parent_count == 1
        assert [note.path.stem for note in panel._chip_notes] == ["hub", "grand"]

        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "PARENT" in meta
        assert "CHILDREN" in meta
        assert "1 hub" in meta
        assert "2 grand" in meta


async def test_agents_parent_root_without_children_has_no_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/zeta.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/zeta.md")

        assert panel._chip_notes == ()
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "PARENT" not in meta
        assert "CHILDREN" not in meta


async def test_tab_moves_chip_cursor_and_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")
        assert panel._chip_cursor is None

        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("tab")
        assert panel._chip_cursor == 1
        await pilot.press("tab")
        assert panel._chip_cursor == 0


async def test_follow_moves_note_cursor_and_pushes_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")

        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/both.md")
        assert panel._trail == ["sase/memory/hub.md"]
        assert panel._chip_cursor is None


async def test_digit_follows_child_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")

        await pilot.press("2")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/child.md")
        assert panel._trail == ["sase/memory/hub.md"]


async def test_follow_through_active_filter_clears_it_and_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "hub":
            await pilot.press(char)
        await wait_for(
            pilot,
            lambda: [row.note.path.stem for row in panel._rows] == ["hub"],
        )

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)

        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/both.md")
        assert panel._filter_text == ""
        assert "both" in [row.note.path.stem for row in panel._rows]


async def test_scope_switch_clears_chips_and_does_not_leave_stale_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, _linked_notes()),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._land_on_note("sase/memory/hub.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/hub.md")
        assert panel._chip_notes
        panel._travel_forward("sase/memory/both.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/both.md")
        assert panel._trail == ["sase/memory/hub.md"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert panel._trail == []
        assert [note.path.stem for note in panel._chip_notes] == []
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "PARENT" not in meta
        assert "CHILDREN" not in meta
