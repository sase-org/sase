"""Back-trail behavior for the Memory panel."""

from __future__ import annotations

import pytest

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


async def test_back_restores_previous_note_and_pops_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("aaa"),
        memory_note("bbb"),
        memory_note("ccc"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "sase/memory/aaa.md"

        panel._travel_forward("sase/memory/bbb.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")
        panel._travel_forward("sase/memory/ccc.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/ccc.md")
        assert panel._trail == ["sase/memory/aaa.md", "sase/memory/bbb.md"]
        assert "TRAIL" in panel_static_text(panel, "memory-panel-trail")
        assert "aaa" in panel_static_text(panel, "memory-panel-trail")

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")
        assert panel._trail == ["sase/memory/aaa.md"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/aaa.md")
        assert panel._trail == []


async def test_back_on_empty_trail_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (memory_note("hub"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("h")
        await pilot.pause()
        assert panel._current_note == "sase/memory/hub.md"
        assert panel._trail == []


async def test_trail_is_bounded_at_32(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    stems = [f"note{index:02d}" for index in range(41)]
    notes = tuple(memory_note(stem) for stem in stems)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == f"sase/memory/{stems[0]}.md"

        for stem in stems[1:]:
            panel._travel_forward(f"sase/memory/{stem}.md")
        await pilot.pause()

        assert panel._current_note == f"sase/memory/{stems[-1]}.md"
        assert len(panel._trail) == 32
        assert panel._trail[0] == f"sase/memory/{stems[8]}.md"
        assert panel._trail[-1] == f"sase/memory/{stems[39]}.md"


async def test_scope_cycling_clears_the_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("aaa"), memory_note("bbb"))),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._travel_forward("sase/memory/bbb.md")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")
        assert panel._trail == ["sase/memory/aaa.md"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert panel._trail == []


async def test_back_skips_a_missing_trail_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (memory_note("real"), memory_note("other"))
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._trail = ["sase/memory/real.md", "sase/memory/ghost.md"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/real.md")
        assert panel._trail == []
