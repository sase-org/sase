"""Mention-relation (SEE ALSO / REFERENCED BY) chips for strand rows."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.memory.notes import MemoryNote
from tests.ace.tui.modals.memory_panel_test_helpers import (
    MemoryPanelTestApp,
    install_fake_strand_read,
    install_fixed_load,
    memory_note,
    memory_web_with_mentioning_strands,
    panel_static_text,
    scope_ref,
    scope_snapshot,
)


def _descriptor_note() -> MemoryNote:
    return memory_note(
        "glossary", note_type="core", description="Glossary.", body="Glossary body."
    )


async def test_strand_that_mentions_another_shows_see_also(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    web = memory_web_with_mentioning_strands()
    snapshot = scope_snapshot(ref, (_descriptor_note(),), webs=(web,))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})
    install_fake_strand_read(monkeypatch)

    panel = MemoryPane(initial_note="glossary:alpha")
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "glossary:alpha"

        assert [note.path.stem for note in panel._chip_notes] == ["glossary:beta"]
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "SEE ALSO" in meta
        assert "PARENT" not in meta
        assert "CHILDREN" not in meta
        assert "REFERENCED BY" not in meta
        assert ".1 Beta Term" in meta


async def test_strand_referenced_by_another_shows_referenced_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    web = memory_web_with_mentioning_strands()
    snapshot = scope_snapshot(ref, (_descriptor_note(),), webs=(web,))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})
    install_fake_strand_read(monkeypatch)

    panel = MemoryPane(initial_note="glossary:beta")
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "glossary:beta"

        assert [note.path.stem for note in panel._chip_notes] == ["glossary:alpha"]
        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "REFERENCED BY" in meta
        assert "SEE ALSO" not in meta
        assert ".1 Alpha Term" in meta


async def test_following_see_also_chip_lands_on_the_mentioned_strand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    web = memory_web_with_mentioning_strands()
    snapshot = scope_snapshot(ref, (_descriptor_note(),), webs=(web,))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})
    install_fake_strand_read(monkeypatch)

    panel = MemoryPane(initial_note="glossary:alpha")
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "glossary:alpha"

        await pilot.press("tab")
        await pilot.press("l")
        await wait_for(pilot, lambda: panel._current_note == "glossary:beta")
        assert panel._trail == ["glossary:alpha"]


async def test_closure_none_web_strand_keeps_parent_child_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    non_mentions_web = replace(memory_web_with_mentioning_strands(), closure="none")
    snapshot = scope_snapshot(ref, (_descriptor_note(),), webs=(non_mentions_web,))
    install_fixed_load(monkeypatch, (ref,), {"sase": snapshot})
    install_fake_strand_read(monkeypatch)

    panel = MemoryPane(initial_note="glossary:alpha")
    app = MemoryPanelTestApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        assert panel._current_note == "glossary:alpha"

        meta = panel_static_text(panel, "memory-panel-card-meta")
        assert "SEE ALSO" not in meta
        assert "REFERENCED BY" not in meta
        assert "PARENT" in meta
