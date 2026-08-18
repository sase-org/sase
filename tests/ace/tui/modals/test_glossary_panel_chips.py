"""Relation chips, digit shortcuts, and following them in the Glossary panel."""

from __future__ import annotations

import pytest

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


async def test_relation_chip_numbering_is_continuous_across_both_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Alpha", definition="Alpha mentions Beta and Gamma."),
        glossary_entry(1, "Beta"),
        glossary_entry(2, "Gamma"),
        glossary_entry(3, "Delta"),
    )
    snapshot = project_snapshot(
        ref, entries, reverse_references={0: ("Delta",)}, scanning=True
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Alpha"
        assert [entry.term for entry in panel._chip_entries] == [
            "Beta",
            "Gamma",
            "Delta",
        ]
        assert panel._chip_outbound_count == 2

        meta = panel_static_text(panel, "glossary-panel-card-meta")
        assert "SEE ALSO" in meta
        assert "REFERENCED BY" in meta
        assert "1 Beta" in meta
        assert "2 Gamma" in meta
        assert "3 Delta" in meta


async def test_digit_follows_referenced_by_chip_when_see_also_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "AAA Leaf"),
        glossary_entry(1, "BBB Ref"),
        glossary_entry(2, "CCC Ref"),
    )
    snapshot = project_snapshot(
        ref, entries, reverse_references={0: ("BBB Ref", "CCC Ref")}
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "AAA Leaf"
        assert panel._chip_outbound_count == 0
        assert [entry.term for entry in panel._chip_entries] == [
            "BBB Ref",
            "CCC Ref",
        ]

        await pilot.press("2")
        await wait_for(pilot, lambda: panel._current_term == "CCC Ref")
        assert panel._trail == ["AAA Leaf"]


async def test_tab_moves_chip_cursor_and_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Leaf"),
        glossary_entry(1, "X"),
        glossary_entry(2, "Y"),
    )
    snapshot = project_snapshot(ref, entries, reverse_references={0: ("X", "Y")})
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._chip_cursor is None

        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("tab")
        assert panel._chip_cursor == 1
        await pilot.press("tab")
        assert panel._chip_cursor == 0


async def test_follow_moves_term_cursor_and_pushes_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Leaf"),
        glossary_entry(1, "X"),
        glossary_entry(2, "Y"),
    )
    snapshot = project_snapshot(ref, entries, reverse_references={0: ("X", "Y")})
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("tab")
        assert panel._chip_cursor == 0
        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_term == "X")
        assert panel._trail == ["Leaf"]
        assert panel._chip_cursor is None


async def test_follow_through_active_filter_clears_it_and_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Leaf"),
        glossary_entry(1, "X"),
        glossary_entry(2, "Y"),
    )
    snapshot = project_snapshot(ref, entries, reverse_references={0: ("X",)})
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("slash")
        await wait_for(pilot, lambda: panel._filter_input().display)
        for char in "leaf":
            await pilot.press(char)
        await wait_for(pilot, lambda: [e.term for e in panel._entries] == ["Leaf"])

        await pilot.press("escape")
        await wait_for(pilot, lambda: not panel._filter_input().display)

        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_term == "X")
        assert panel._filter_text == ""
        assert [e.term for e in panel._entries] == ["Leaf", "X", "Y"]


async def test_reverse_references_make_inbound_only_term_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Leaf"), glossary_entry(1, "Referencer"))
    snapshot = project_snapshot(ref, entries, reverse_references={0: ("Referencer",)})
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPanel()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "Leaf"
        assert panel._chip_outbound_count == 0
        assert [entry.term for entry in panel._chip_entries] == ["Referencer"]
