"""Session injection, visibility, and teardown for the Glossary content pane."""

from __future__ import annotations

import threading

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals import glossary_pane as glossary_pane_module
from sase.ace.tui.modals.catalog_pane_contract import CatalogPaneSession
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    GlossaryPanelTestApp,
    glossary_entry,
    install_fixed_load,
    project_ref,
    project_snapshot,
)


async def test_session_records_project_and_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Agent Hood"), glossary_entry(1, "Zebra"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})
    session = CatalogPaneSession()
    pane = GlossaryPane(session=session)
    app = GlossaryPanelTestApp(pane)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not pane._loading)
        assert session.scope_key == "sase"
        assert session.entry_id == "Agent Hood"
        await pilot.press("j")
        await wait_for(pilot, lambda: pane._current_term == "Zebra")
        assert session.entry_id == "Zebra"


async def test_explicit_term_and_project_win_over_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(
            ref_a, (glossary_entry(0, "Only In Alpha"), glossary_entry(1, "Shared"))
        ),
        "proj-b": project_snapshot(ref_b, (glossary_entry(0, "Only In Beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    session = CatalogPaneSession(scope_key="proj-b", entry_id="Only In Beta")
    pane = GlossaryPane(
        initial_project_key="proj-a",
        initial_term="Shared",
        session=session,
    )
    app = GlossaryPanelTestApp(pane)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not pane._loading)
        assert pane._ring[pane._project_index].key == "proj-a"
        assert pane._current_term == "Shared"
        assert session.scope_key == "proj-a"
        assert session.entry_id == "Shared"


async def test_session_seeds_project_and_term_without_explicit_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (glossary_entry(0, "Only In Alpha"),)),
        "proj-b": project_snapshot(
            ref_b, (glossary_entry(0, "First"), glossary_entry(1, "Remembered"))
        ),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)
    session = CatalogPaneSession(scope_key="proj-b", entry_id="Remembered")
    pane = GlossaryPane(session=session)
    app = GlossaryPanelTestApp(pane)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not pane._loading)
        assert pane._ring[pane._project_index].key == "proj-b"
        assert pane._current_term == "Remembered"


async def test_hidden_pane_focus_default_does_not_steal_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": project_snapshot(ref, (glossary_entry(0, "Alpha"),))},
    )
    pane = GlossaryPane()
    app = GlossaryPanelTestApp(pane)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not pane._loading)
        pane.on_center_tab_visibility_changed(False)
        app.set_focus(None)
        pane.focus_default()
        assert app.focused is None


async def test_unmount_cancels_in_flight_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    ref = project_ref("sase", "sase")
    snapshot = project_snapshot(ref, (glossary_entry(0, "Alpha"),))

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
        session_project_key: str | None = None,
    ) -> GlossaryPanelInitialLoad:
        del launch_workspace, initial_project_key, seed_from_current_project
        del session_project_key
        started.set()
        release.wait(timeout=5)
        return GlossaryPanelInitialLoad(ring=(ref,), project_index=0, snapshot=snapshot)

    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_panel_initial_state", fake_initial_load
    )
    pane = GlossaryPane()
    app = GlossaryPanelTestApp(pane)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: started.is_set())
        worker = pane._load_worker
        assert worker is not None
        await pane.remove()
        assert worker.is_cancelled or worker.is_finished
        if pane._debouncer is not None:
            assert pane._debouncer.is_pending is False
        release.set()
