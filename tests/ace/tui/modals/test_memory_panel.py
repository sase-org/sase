"""Load, scope-cycling, picking, and empty-state behavior for the Memory panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals import memory_panel as memory_panel_module
from sase.ace.tui.modals.memory_panel import MemoryPanel
from sase.ace.tui.modals.memory_panel_load import (
    MemoryPanelInitialLoad,
    MemoryScopeChoice,
)
from sase.ace.tui.modals.memory_panel_scope_picker import MemoryScopePicker
from tests.ace.tui.modals.memory_panel_test_helpers import (
    MemoryPanelTestApp,
    install_fixed_load,
    install_fixed_scope_choices,
    memory_note,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


async def test_panel_mounts_and_selects_first_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("zebra", note_type="short", description="Always loaded."),
        memory_note("agent_hood", description="Hub note."),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        # Tier 1 (short) notes sort before Tier 2 regardless of stem, so the
        # short "zebra" note is selected first even though "agent_hood" is
        # alphabetically earlier.
        assert panel._current_note == "sase/memory/zebra.md"
        assert "zebra" in panel_static_text(panel, "memory-panel-card-title")


async def test_tree_ordering_nests_children_under_their_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note("always", note_type="short", description="Always loaded."),
        memory_note("hub", description="Hub."),
        memory_note("child", parent="sase/memory/hub.md", description="Child."),
        memory_note("zeta", description="Later root."),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        rows = [(row.note.path.stem, row.depth) for row in panel._all_rows]
        assert rows == [
            ("always", 0),
            ("hub", 0),
            ("child", 1),
            ("zeta", 0),
        ]


async def test_seed_filters_setting_reaches_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_scope_key: str | None = None,
        seed_from_current_project: bool = True,
    ) -> MemoryPanelInitialLoad:
        captured.append(seed_from_current_project)
        return MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None)

    monkeypatch.setattr(
        memory_panel_module, "load_memory_panel_initial_state", fake_initial_load
    )

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    app._current_project_settings = CurrentProjectSettings(seed_filters=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

    assert captured == [False]


async def test_scope_cycling_orders_by_display_name_and_scopes_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._scope_index == 0
        assert [row.note.path.stem for row in panel._rows] == ["only_in_alpha"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_beta"]

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 0)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_alpha"]


async def test_scope_selection_is_remembered_per_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("aaa"), memory_note("bbb"))),
        "proj-b": scope_snapshot(ref_b, (memory_note("ccc"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_note == "sase/memory/bbb.md")

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 0)
        assert panel._current_note == "sase/memory/bbb.md"


async def test_scope_picker_switches_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("only_in_alpha"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("only_in_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    install_fixed_scope_choices(
        monkeypatch,
        (
            MemoryScopeChoice(key="proj-a", display_name="Alpha", note_count=1),
            MemoryScopeChoice(key="proj-b", display_name="Beta", note_count=1),
        ),
    )

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("ctrl+p")
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryScopePicker))
        await pilot.press("down")
        await pilot.press("enter")

        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)
        assert [row.note.path.stem for row in panel._rows] == ["only_in_beta"]


async def test_no_memory_root_shows_creation_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase", has_memory=False, memory_read_root=None)
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, ())})

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "No memory root for" in meta
        assert "sase" in meta
        assert "will be created" in meta


async def test_empty_scope_with_root_shows_add_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, ())})

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "No memory notes in" in meta
        assert "sase" in meta
        assert "add the first note" in meta


async def test_diagnostics_scope_shows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    snapshot = scope_snapshot(ref, (), diagnostics=("sase/memory: bad layout",))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert "bad layout" in panel_static_text(panel, "memory-panel-card-meta")


async def test_initial_and_scope_switch_loads_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = scope_ref("proj-a", "Alpha")
    ref_b = scope_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": scope_snapshot(ref_a, (memory_note("a"),)),
        "proj-b": scope_snapshot(ref_b, (memory_note("b"),)),
    }
    off_main_thread = install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._scope_index == 1)

    assert off_main_thread == [True, True]


async def test_refresh_invalidates_and_reloads_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPanel()
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        # Swap in a new snapshot object so we can prove refresh reloaded it.
        snapshots["sase"] = scope_snapshot(
            ref, (memory_note("alpha"), memory_note("beta"))
        )
        await pilot.press("r")
        await wait_for(pilot, lambda: not panel._loading and len(panel._rows) == 2)
        assert [row.note.path.stem for row in panel._rows] == ["alpha", "beta"]
