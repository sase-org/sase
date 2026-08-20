"""Relation chips, digit shortcuts, and following them in the Snippets panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.snippets_panel import SnippetsPanel
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    SnippetsPanelTestApp,
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
    snippet_call,
    snippet_entry,
)


async def test_relation_chip_numbering_is_continuous_across_both_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("alpha", outbound=("beta", "gamma"), inbound=("delta",)),
        snippet_entry("beta"),
        snippet_entry("gamma"),
        snippet_entry("delta"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "alpha"
        assert [entry.trigger for entry in panel._chip_entries] == [
            "beta",
            "gamma",
            "delta",
        ]
        assert panel._chip_outbound_count == 2

        meta = panel_static_text(panel, "snippets-panel-card-meta")
        assert "CALLS" in meta
        assert "CALLED BY" in meta
        assert "1 beta" in meta
        assert "2 gamma" in meta
        assert "3 delta" in meta


async def test_digit_follows_called_by_chip_when_calls_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("aaa_leaf", inbound=("bbb_ref", "ccc_ref")),
        snippet_entry("bbb_ref"),
        snippet_entry("ccc_ref"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "aaa_leaf"
        assert panel._chip_outbound_count == 0
        assert [entry.trigger for entry in panel._chip_entries] == [
            "bbb_ref",
            "ccc_ref",
        ]

        await pilot.press("2")
        await wait_for(pilot, lambda: panel._current_trigger == "ccc_ref")
        assert panel._trail == ["aaa_leaf"]


async def test_tab_moves_chip_cursor_and_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("leaf", inbound=("x", "y")),
        snippet_entry("x"),
        snippet_entry("y"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._chip_cursor is None

        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("tab")
        assert panel._chip_cursor == 1
        await pilot.press("tab")
        assert panel._chip_cursor == 0


async def test_follow_moves_trigger_cursor_and_pushes_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("leaf", inbound=("x", "y")),
        snippet_entry("x"),
        snippet_entry("y"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_trigger == "x")
        assert panel._trail == ["leaf"]
        assert panel._chip_cursor is None


async def test_follow_through_active_filter_clears_it_and_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("leaf", inbound=("x",)),
        snippet_entry("x"),
        snippet_entry("y"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "leaf":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.trigger for e in panel._entries] == ["leaf"])

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)

        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_trigger == "x")
        assert panel._filter_text == ""
        assert [e.trigger for e in panel._entries] == ["leaf", "x", "y"]


async def test_alias_call_follows_canonical_explicit_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("helper", aliases=("Helper",)),
        snippet_entry(
            "wrap",
            raw="#[Helper]$0",
            outbound=("helper",),
            calls=(
                snippet_call(
                    "Helper",
                    status="resolved",
                    canonical="helper",
                    start=0,
                    end=9,
                ),
            ),
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel(initial_trigger="wrap")
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_trigger == "wrap"
        assert [entry.trigger for entry in panel._chip_entries] == ["helper"]
        await pilot.press("1")
        await wait_for(pilot, lambda: panel._current_trigger == "helper")


async def test_unresolved_and_cyclic_calls_are_visible_but_not_followable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry(
            "outer",
            raw="#[gone] #[selfish] #[helper]",
            outbound=("helper",),
            calls=(
                snippet_call("gone", status="missing", start=0, end=7),
                snippet_call("selfish", status="cycle", start=8, end=18),
                snippet_call("helper", status="resolved", start=19, end=28),
            ),
        ),
        snippet_entry("helper"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel(initial_trigger="outer")
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert [entry.trigger for entry in panel._chip_entries] == ["helper"]
        meta = panel_static_text(panel, "snippets-panel-card-meta")
        assert "UNRESOLVED" in meta
        assert "missing: gone" in meta
        assert "cycle: selfish" in meta
        await pilot.press("2")
        await pilot.pause()
        assert panel._current_trigger == "outer"
        await pilot.press("1")
        await wait_for(pilot, lambda: panel._current_trigger == "helper")
