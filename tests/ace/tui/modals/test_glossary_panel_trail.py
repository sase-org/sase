"""Back-trail behavior for the Glossary panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    GlossaryPanelTestApp,
    glossary_entry,
    install_fixed_load,
    project_ref,
    project_snapshot,
)


async def test_back_restores_previous_term_and_pops_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "A"), glossary_entry(1, "B"), glossary_entry(2, "C"))
    snapshot = project_snapshot(ref, entries, reverse_references={0: ("B",), 1: ("C",)})
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == "A"

        panel._travel_forward("B")
        await wait_for(pilot, lambda: panel._current_term == "B")
        panel._travel_forward("C")
        await wait_for(pilot, lambda: panel._current_term == "C")
        assert panel._trail == ["A", "B"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "B")
        assert panel._trail == ["A"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "A")
        assert panel._trail == []


async def test_back_on_empty_trail_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Agent Hood"),)
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("h")
        await pilot.pause()
        assert panel._current_term == "Agent Hood"
        assert panel._trail == []


async def test_trail_is_bounded_at_32(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("sase", "sase")
    terms = [f"Term{index:02d}" for index in range(41)]
    entries = tuple(glossary_entry(index, term) for index, term in enumerate(terms))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_term == terms[0]

        for term in terms[1:]:
            panel._travel_forward(term)
        await pilot.pause()

        assert panel._current_term == terms[-1]
        assert len(panel._trail) == 32
        assert panel._trail[0] == terms[8]
        assert panel._trail[-1] == terms[39]


async def test_project_cycling_clears_the_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_a = project_ref("proj-a", "Alpha")
    ref_b = project_ref("proj-b", "Beta")
    entries_a = (glossary_entry(0, "A"), glossary_entry(1, "B"))
    snapshots = {
        "proj-a": project_snapshot(ref_a, entries_a, reverse_references={0: ("B",)}),
        "proj-b": project_snapshot(ref_b, (glossary_entry(0, "Only In Beta"),)),
    }
    install_fixed_load(monkeypatch, (ref_a, ref_b), snapshots)

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._travel_forward("B")
        await wait_for(pilot, lambda: panel._current_term == "B")
        assert panel._trail == ["A"]

        await pilot.press("p")
        await wait_for(pilot, lambda: not panel._loading and panel._project_index == 1)
        assert panel._trail == []


async def test_back_skips_a_deleted_trail_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    entries = (glossary_entry(0, "Real"), glossary_entry(1, "Other"))
    install_fixed_load(monkeypatch, (ref,), {"sase": project_snapshot(ref, entries)})

    panel = GlossaryPane()
    app = GlossaryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._trail = ["Real", "Ghost"]

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._current_term == "Real")
        assert panel._trail == []
