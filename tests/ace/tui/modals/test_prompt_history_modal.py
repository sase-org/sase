"""Tests for History pane mounting, loading, and text filtering."""

from __future__ import annotations

import asyncio
import inspect
from threading import Event

import pytest
from textual.widgets import Input

from sase.ace.testing import wait_for
import sase.ace.tui.modals.history_pane as history_pane
from sase.ace.tui.modals.history_pane import HistoryPane
from sase.ace.tui.modals.prompts_modal import PromptsModal, PromptsTab
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from tests.ace.tui.modals.prompt_history_modal_test_helpers import (
    _PromptHistoryTestApp,
    _item,
)


def test_prompt_history_mount_handler_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(HistoryPane.on_mount)


async def test_prompt_history_opens_while_initial_disk_load_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def slow_load_prompt_record_page(**_kwargs: object) -> PromptHistoryPage:
        started.set()
        release.wait()
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        history_pane,
        "load_prompt_record_page",
        slow_load_prompt_record_page,
    )
    overlay = PromptsModal([], initial_tab=PromptsTab.HISTORY)

    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(overlay)
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            pane = overlay._history_pane
            assert pane is not None
            filter_input = overlay.query_one("#prompt-history-filter-input", Input)
            assert filter_input.has_focus
            await pilot.press("a")
            assert filter_input.value == "a"
            assert not pane._history_loaded_once
        finally:
            release.set()
            await wait_for(pilot, lambda: pane._history_loaded_once)
            assert pane._history_loaded_once


def test_prompt_history_filter_matches_prompt_text_only() -> None:
    matching_item = _item(text="fix the tests", context="main")
    context_only_item = _item(text="ship the change", context="feature/tests")
    pane = object.__new__(HistoryPane)
    pane._all_items = [matching_item, context_only_item]
    pane._show_cancelled = False

    assert pane._get_filtered_items("tests") == [matching_item]


def test_prompt_history_filter_matches_display_and_canonical_text() -> None:
    item = _item(text="#gh:gh_acme__widgets Fix parser")
    item.display_text = "#gh:widgets Fix parser"
    pane = object.__new__(HistoryPane)
    pane._all_items = [item]
    pane._show_cancelled = False

    assert pane._get_filtered_items("widgets") == [item]
    assert pane._get_filtered_items("gh_acme__widgets") == [item]


def test_prompt_history_selected_prompt_uses_display_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOptionList:
        highlighted = 0

    item = _item(text="#gh:gh_acme__widgets Fix parser")
    item.display_text = "#gh:widgets Fix parser"
    pane = object.__new__(HistoryPane)
    pane._filtered_items = [item]
    monkeypatch.setattr(
        pane,
        "query_one",
        lambda _selector, _widget_type: FakeOptionList(),
    )

    assert pane._get_selected_prompt_text() == "#gh:widgets Fix parser"


def test_prompt_history_initial_filter_prefilters_items(monkeypatch) -> None:
    entries = [
        _item(text="fix auth login").entry,
        _item(text="update docs").entry,
    ]

    pane = HistoryPane(initial_filter="auth")
    pane._append_page(
        PromptHistoryPage(
            records=[record_from_entry(entry) for entry in entries],
            next_cursor=None,
            exhausted=True,
        )
    )
    pane._filtered_items = pane._get_filtered_items(pane._initial_filter)

    assert pane._initial_filter == "auth"
    assert [item.entry.text for item in pane._filtered_items] == ["fix auth login"]


def test_prompt_history_append_page_keeps_canonical_entry_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "#gh:gh_acme__widgets Fix parser"
    monkeypatch.setattr(
        history_pane,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )
    pane = HistoryPane()

    pane._append_page(
        PromptHistoryPage(
            records=[record_from_entry(_item(text=raw).entry)],
            next_cursor=None,
            exhausted=True,
        )
    )

    assert pane._all_items[0].entry.text == raw
    assert pane._all_items[0].display_text == "#gh:widgets Fix parser"


def test_prompt_history_count_label_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLabel:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    label = FakeLabel()
    pane = object.__new__(HistoryPane)
    pane._all_items = [
        _item(text="fix auth"),
        _item(text="update docs"),
        _item(text="cancelled", cancelled=True),
    ]
    pane._filtered_items = [pane._all_items[0]]
    pane._history_loaded_once = True
    pane._history_loading = False
    pane._history_exhausted = True

    monkeypatch.setattr(
        pane,
        "query_one",
        lambda _selector, _widget_type: label,
    )

    pane._update_history_count_label()

    assert label.value == "History · 1 / 3 total"

    pane._history_exhausted = False
    pane._update_history_count_label()

    assert label.value == "History · 1 / 3 loaded · ^j +100 older"
