"""Back-trail behavior for the Snippets panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.snippets_panel import SnippetsPanel
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    SnippetsPanelTestApp,
    install_fixed_load,
    project_ref,
    project_snapshot,
    snippet_entry,
)


async def test_back_restores_previous_trigger_and_pops_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    snapshot = project_snapshot(
        ref,
        (
            snippet_entry("a", inbound=("b",)),
            snippet_entry("b", inbound=("c",)),
            snippet_entry("c"),
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "a"

        panel._travel_forward("b")
        await wait_for(pilot, lambda: panel._current_trigger == "b")
        panel._travel_forward("c")
        await wait_for(pilot, lambda: panel._current_trigger == "c")
        assert panel._trail == ["a", "b"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_trigger == "b")
        assert panel._trail == ["a"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_trigger == "a")
        assert panel._trail == []


async def test_back_on_empty_trail_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("h")
        await pilot.pause()
        assert panel._current_trigger == "helper"
        assert panel._trail == []


async def test_trail_is_bounded_at_32(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("sase", "sase")
    triggers = [f"term{index:02d}" for index in range(41)]
    entries = tuple(snippet_entry(trigger) for trigger in triggers)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == triggers[0]

        for trigger in triggers[1:]:
            panel._travel_forward(trigger)
        await pilot.pause()

        assert panel._current_trigger == triggers[-1]
        assert len(panel._trail) == 32
        assert panel._trail[0] == triggers[8]
        assert panel._trail[-1] == triggers[39]


async def test_project_cycling_clears_the_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(
            ref_a,
            (snippet_entry("a", inbound=("b",)), snippet_entry("b")),
        ),
        "proj-b": project_snapshot(ref_b, (snippet_entry("only_beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._travel_forward("b")
        await wait_for(pilot, lambda: panel._current_trigger == "b")
        assert panel._trail == ["a"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert panel._trail == []


async def test_back_skips_a_deleted_trail_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("real"), snippet_entry("other"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._trail = ["real", "ghost"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_trigger == "real")
        assert panel._trail == []
