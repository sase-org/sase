"""Term-rail filtering and width behavior for the Glossary panel."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.glossary_panel import GlossaryPanel
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    GlossaryPanelTestApp,
    glossary_entry,
    install_fixed_load,
    panel_static_text,
    project_ref,
    project_snapshot,
)


async def test_filter_matches_terms_aliases_and_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Agent Hood", aliases=("hood",)),
        glossary_entry(1, "Sase Agent", definition="Mentions hood in passing."),
        glossary_entry(2, "Zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "hood":
            await pilot.press(char)
        await wait_for(
            pilot, lambda: [e.term for e in panel._entries] == ["Agent Hood"]
        )

        # Toggling definition matching (from the term list, not the filter box)
        # widens the same pattern to also match "Sase Agent"'s definition.
        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)
        await pilot.press("full_stop")
        await wait_for(
            pilot,
            lambda: (
                sorted(e.term for e in panel._entries) == ["Agent Hood", "Sase Agent"]
            ),
        )


async def test_empty_filter_shows_no_match_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Agent Hood"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "nomatch":
            await pilot.press(char)
        await wait_for(pilot, lambda: not panel._entries)
        assert "no terms matched: nomatch" in panel_static_text(
            panel, "glossary-panel-card-meta"
        )


async def test_term_rail_width_matches_widest_row_after_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Agent Hood", aliases=("hood", "agent neighborhood")),
        glossary_entry(1, "Zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width = panel._term_list().styles.width
        assert width is not None
        assert width.value == 43


async def test_filtering_to_short_terms_does_not_jitter_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Agent Hood", aliases=("hood", "agent neighborhood")),
        glossary_entry(1, "Zebra"),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        width_before = panel._term_list().styles.width.value

        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "zebra":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.term for e in panel._entries] == ["Zebra"])

        assert panel._term_list().styles.width.value == width_before


async def test_cycling_to_a_project_with_short_terms_shrinks_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    snapshots = {
        "proj-a": project_snapshot(
            ref_a,
            (glossary_entry(0, "Agent Hood", aliases=("hood", "agent neighborhood")),),
        ),
        "proj-b": project_snapshot(ref_b, (glossary_entry(0, "AB"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.pause()
        assert panel._term_list().styles.width.value == 43

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        await pilot.pause()
        assert panel._term_list().styles.width.value == 32


async def test_term_list_option_list_widget_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Agent Hood"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        option_list = panel.query_one("#glossary-panel-terms", OptionList)
        assert option_list.option_count == 1
