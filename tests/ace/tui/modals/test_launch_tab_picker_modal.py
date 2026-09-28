"""Launch Tab picker (gb) modal and name coercion (sase-1bc.10)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Label

from sase.ace.tui.modals.launch_tab_picker_modal import (
    LaunchTabPickerModal,
    LaunchTabPickerResult,
    _coerce_new_tab_name,
    _filter_positions,
    _named_entries,
)
from sase.ace.tui.models.agent_tab_index import AgentTabCatalogEntry
from sase.core.agent_tab import AgentTabKey


def _entries() -> tuple[AgentTabCatalogEntry, ...]:
    return (
        AgentTabCatalogEntry(AgentTabKey.default(), "default", "main", 1),
        AgentTabCatalogEntry(AgentTabKey.named("blog"), "named", "blog", 2),
        AgentTabCatalogEntry(AgentTabKey.machine("iid"), "machine", "⌨ apollo", 3),
    )


def test_named_entries_skips_default_and_machine() -> None:
    named = _named_entries(_entries())
    assert [entry.label for entry in named] == ["blog"]


def test_filter_positions_matches_labels() -> None:
    labels = ("main (default)", "blog", "sase")
    assert _filter_positions(labels, "") == (0, 1, 2)
    assert _filter_positions(labels, "blo") == (1,)
    assert _filter_positions(labels, "MAIN") == (0,)
    assert _filter_positions(labels, "zzz") == ()


def test_coerce_new_tab_name() -> None:
    assert _coerce_new_tab_name("Blog") == "blog"
    with pytest.raises((ValueError, TypeError)):
        _coerce_new_tab_name("main")
    with pytest.raises((ValueError, TypeError)):
        _coerce_new_tab_name("all")
    with pytest.raises((ValueError, TypeError)):
        _coerce_new_tab_name("bad name!")


class _PickerHarness(App[None]):
    """Minimal app hosting the picker and recording its result."""

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self.results: list[LaunchTabPickerResult] = []
        self._current = current

    def compose(self) -> ComposeResult:
        yield Label("harness")

    async def on_mount(self) -> None:
        self.push_screen(
            LaunchTabPickerModal(_entries(), current=self._current),
            self.results.append,
        )


async def _submit_search(pilot, app: _PickerHarness, value: str) -> None:
    search = app.screen.query_one("#launch-tab-picker-search", Input)
    search.value = value
    await pilot.pause()
    search.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def test_picker_new_tab_name() -> None:
    app = _PickerHarness()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _submit_search(pilot, app, "sase")
        assert app.results == [LaunchTabPickerResult(action="tab", tab="sase")]


async def test_picker_default_choice() -> None:
    app = _PickerHarness()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _submit_search(pilot, app, "main")
        assert app.results == [LaunchTabPickerResult(action="default")]


async def test_picker_invalid_name_stays_open() -> None:
    app = _PickerHarness()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _submit_search(pilot, app, "bad name!")
        assert app.results == []
