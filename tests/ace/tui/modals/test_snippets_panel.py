"""Load, project-cycling, and empty-state behavior for the Snippets panel."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.worker import WorkerState

from sase.ace.testing import wait_for
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals import snippets_panel as snippets_panel_module
from sase.ace.tui.modals.snippets_panel import SnippetsPanel
from sase.ace.tui.modals.snippets_panel_load import SnippetsPanelInitialLoad
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    SnippetsPanelTestApp,
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
    snippet_entry,
)


async def test_panel_mounts_and_selects_first_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("zebra"),
        snippet_entry("agent"),
        snippet_entry("middle"),
    )
    off_main_thread = install_fixed_load(
        monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)}
    )

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "agent"
        assert [entry.trigger for entry in panel._entries] == [
            "agent",
            "middle",
            "zebra",
        ]
        assert off_main_thread == [True]
        assert "agent" in panel_static_text(panel, "snippets-panel-card-title")
        assert "RAW" in panel_static_text(panel, "snippets-panel-card-raw")
        assert "COMPOSED" in panel_static_text(panel, "snippets-panel-card-composed")


async def test_generated_aliases_are_metadata_not_rail_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper", aliases=("Helper",)),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert [entry.trigger for entry in panel._entries] == ["helper"]
        meta = panel_static_text(panel, "snippets-panel-card-meta")
        assert "Helper" in meta
        assert "ALIASES" in meta


async def test_seed_filters_setting_reaches_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[bool] = []

    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
    ) -> SnippetsPanelInitialLoad:
        captured.append(seed_from_current_project)
        return SnippetsPanelInitialLoad(ring=(), project_index=0, snapshot=None)

    monkeypatch.setattr(
        snippets_panel_module,
        "load_snippets_panel_initial_state",
        fake_initial_load,
    )

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    app._current_project_settings = CurrentProjectSettings(seed_filters=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

    assert captured == [False]


async def test_next_snippet_updates_card_after_debounce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("agent"), snippet_entry("zebra"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_trigger == "zebra")

        def _title_shows_zebra() -> bool:
            return "zebra" in panel_static_text(panel, "snippets-panel-card-title")

        await wait_for(pilot, _title_shows_zebra, timeout=2.0)


async def test_project_cycling_orders_by_display_name_and_scopes_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (snippet_entry("only_alpha"),)),
        "proj-b": project_snapshot(ref_b, (snippet_entry("only_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._project_index == 0
        assert [e.trigger for e in panel._entries] == ["only_alpha"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert [e.trigger for e in panel._entries] == ["only_beta"]

        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 0)
        assert [e.trigger for e in panel._entries] == ["only_alpha"]


async def test_project_cycling_restores_per_project_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (snippet_entry("aa"), snippet_entry("ab"))),
        "proj-b": project_snapshot(ref_b, (snippet_entry("ba"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_trigger == "ab")

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        await pilot.press("P")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 0)
        assert panel._current_trigger == "ab"


async def test_empty_project_shows_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, ())})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "snippets-panel-card-meta")
        assert "No snippets in" in meta
        assert "sase" in meta


async def test_empty_invitation_uses_display_name_not_spec_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("gh_org__research", "Research")
    install_fixed_load(
        monkeypatch, (ref,), {"gh_org__research": project_snapshot(ref, ())}
    )

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        meta = panel_static_text(panel, "snippets-panel-card-meta")
        assert "Research" in meta
        assert "gh_org__research" not in meta


async def test_diagnostics_project_shows_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    snapshot = project_snapshot(ref, (), diagnostics=("sase.yml: bad snippets shape",))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert "bad snippets shape" in panel_static_text(
            panel, "snippets-panel-card-meta"
        )


async def test_initial_and_project_switch_loads_run_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (snippet_entry("a"),)),
        "proj-b": project_snapshot(ref_b, (snippet_entry("b"),)),
    }
    off_main_thread = install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)

    assert off_main_thread == [True, True]


async def test_stale_project_worker_result_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(ref_a, (snippet_entry("only_alpha"),)),
        "proj-b": project_snapshot(ref_b, (snippet_entry("only_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "only_alpha"
        event = SimpleNamespace(
            state=WorkerState.SUCCESS,
            worker=SimpleNamespace(result=snapshots["proj-b"]),
        )
        panel._on_project_load_state_changed(event)
        assert panel._current_trigger == "only_alpha"


async def test_programmatic_highlight_echo_does_not_move_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("agent"), snippet_entry("zebra"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        option_list = panel._trigger_list()
        event = SimpleNamespace(option_list=option_list, option_index=0)
        panel.on_option_list_option_highlighted(event)
        assert panel._current_trigger == "agent"


async def test_copy_template_uses_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper", raw="TODO($1)$0"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})
    captured: list[str] = []

    def fake_copy(_owner: object, text: str, **_kwargs: object) -> None:
        captured.append(text)

    monkeypatch.setattr(snippets_panel_module, "schedule_copy_delivery", fake_copy)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel.action_copy_template()

    assert captured == ["TODO($1)$0"]


async def test_source_action_path_uses_origin_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper", path="/tmp/workspace/sase/sase.yml"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._source_action_path() == "/tmp/workspace/sase/sase.yml"


async def test_initial_trigger_alias_selects_canonical_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("helper", aliases=("Helper",)),
        snippet_entry("other"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel(initial_trigger="Helper")
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "helper"


async def test_jk_navigation_does_not_stat_or_parse_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = tuple(snippet_entry(f"item_{index:03d}") for index in range(80))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        def fail_io(*_a: object, **_k: object) -> object:
            raise AssertionError("snippet j/k must not touch disk")

        monkeypatch.setattr("pathlib.Path.stat", fail_io)
        monkeypatch.setattr("pathlib.Path.read_text", fail_io)
        monkeypatch.setattr("pathlib.Path.read_bytes", fail_io)
        monkeypatch.setattr("pathlib.Path.glob", fail_io)
        first = panel._current_trigger
        await pilot.press("j")
        await wait_for(pilot, lambda: panel._current_trigger != first)
        await pilot.press("k")
        await wait_for(pilot, lambda: panel._current_trigger == first)
