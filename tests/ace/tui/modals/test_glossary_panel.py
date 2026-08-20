"""Load, project-cycling, and empty-state behavior for the Glossary panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals import glossary_pane as glossary_pane_module
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    GlossaryPanelTestApp,
    glossary_entry,
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
)


async def test_panel_mounts_and_selects_first_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Zebra"),
        glossary_entry(1, "Agent Hood"),
        glossary_entry(2, "Middle"),
    )
    off_main_thread = install_fixed_load(
        monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)}
    )

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Agent Hood"
        assert [entry.term for entry in panel._entries] == [
            "Agent Hood",
            "Middle",
            "Zebra",
        ]
        assert off_main_thread == [True]
        assert "Agent Hood" in panel_static_text(panel, "glossary-panel-card-title")


async def test_seed_filters_setting_reaches_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
        session_project_key: str | None = None,
    ) -> GlossaryPanelInitialLoad:
        del session_project_key
        captured.append(seed_from_current_project)
        return GlossaryPanelInitialLoad(ring=(), project_index=0, snapshot=None)

    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_panel_initial_state", fake_initial_load
    )

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    app._current_project_settings = CurrentProjectSettings(seed_filters=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

    assert captured == [False]


async def test_next_term_updates_card_after_debounce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Agent Hood"), glossary_entry(1, "Zebra"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_term == "Zebra")

        def _title_shows_zebra() -> bool:
            return "Zebra" in panel_static_text(panel, "glossary-panel-card-title")

        await wait_for(pilot, _title_shows_zebra, timeout=2.0)


async def test_project_cycling_orders_by_display_name_and_scopes_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (glossary_entry(0, "Only In Alpha"),)),
        "proj-b": project_snapshot(ref_b, (glossary_entry(0, "Only In Beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._project_index == 0
        assert [e.term for e in panel._entries] == ["Only In Alpha"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert [e.term for e in panel._entries] == ["Only In Beta"]

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 0)
        assert [e.term for e in panel._entries] == ["Only In Alpha"]


async def test_no_glossary_project_shows_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase", has_glossary=False)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, ())})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "glossary-panel-card-meta")
        assert "No glossary in" in meta
        assert "sase" in meta
        assert "add the first term" in meta


async def test_no_glossary_invitation_uses_display_name_not_spec_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("gh_org__research", "Research", has_glossary=False)
    install_fixed_load(
        monkeypatch, (ref,), {"gh_org__research": project_snapshot(ref, ())}
    )

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "glossary-panel-card-meta")
        assert "Research" in meta
        assert "gh_org__research" not in meta


async def test_diagnostics_project_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    snapshot = project_snapshot(ref, (), diagnostics=("sase.yml: bad glossary shape",))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert "bad glossary shape" in panel_static_text(
            panel, "glossary-panel-card-meta"
        )


async def test_initial_and_project_switch_loads_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (glossary_entry(0, "A"),)),
        "proj-b": project_snapshot(ref_b, (glossary_entry(0, "B"),)),
    }
    off_main_thread = install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)

    assert off_main_thread == [True, True]
