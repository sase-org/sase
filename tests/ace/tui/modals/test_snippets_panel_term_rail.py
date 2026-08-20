"""Trigger-rail filtering and width behavior for the Snippets panel."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.snippets_panel import SnippetsPanel
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    SnippetsPanelTestApp,
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
    snippet_entry,
)


async def test_filter_matches_triggers_aliases_and_source_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("agent", aliases=("Agent",)),
        snippet_entry(
            "other",
            kind="xprompt",
            path="xprompts/other.md",
            xprompt_name="other",
            writable=False,
        ),
        snippet_entry("zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "Agent":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.trigger for e in panel._entries] == ["agent"])

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)
        panel._apply_filter("", bodies=False)
        await wait_for(pilot, lambda: len(panel._entries) == 3)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "xprompt":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.trigger for e in panel._entries] == ["other"])


async def test_body_filter_toggle_matches_raw_and_composed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("agent"),
        snippet_entry("other", raw="mentions hood in the body$0"),
        snippet_entry("zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "hood":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._entries)

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)
        await pilot.press("full_stop")
        await wait_for(
            pilot,
            lambda: [e.trigger for e in panel._entries] == ["other"],
        )
        assert "bodies" in panel_static_text(panel, "snippets-panel-header")


async def test_empty_filter_shows_no_match_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "nomatch":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._entries)
        assert "no snippets matched: nomatch" in panel_static_text(
            panel, "snippets-panel-card-meta"
        )


async def test_filtering_to_short_triggers_does_not_jitter_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        snippet_entry("very_long_trigger_name", aliases=("VeryLongTriggerName",)),
        snippet_entry("z"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width_before = panel._trigger_list().styles.width.value

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        await pilot.press("z")
        await wait_for(pilot, lambda: [e.trigger for e in panel._entries] == ["z"])

        assert panel._trigger_list().styles.width.value == width_before


async def test_cycling_to_a_project_with_short_triggers_shrinks_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(
            ref_a,
            (
                snippet_entry(
                    "very_long_trigger_name", aliases=("VeryLongTriggerName",)
                ),
            ),
        ),
        "proj-b": project_snapshot(ref_b, (snippet_entry("ab"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width_before = panel._trigger_list().styles.width.value
        assert width_before > 32

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        await pilot.pause()
        assert panel._trigger_list().styles.width.value == 32


async def test_trigger_list_option_list_widget_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (snippet_entry("helper"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = SnippetsPanel()
    app = SnippetsPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        option_list = panel.query_one("#snippets-panel-triggers", OptionList)
        assert option_list.option_count == 1
