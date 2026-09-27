"""Tests for History pane paging (ctrl+j / ctrl+k)."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from sase.ace.testing import wait_for
import sase.ace.tui.modals.history_pane as history_pane
from sase.ace.tui.modals.history_pane import HistoryPane
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsTab,
)
from sase.history.prompt import PromptHistoryPageCursor
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from tests.ace.tui.modals.prompt_history_modal_test_helpers import (
    _PromptHistoryTestApp,
    _item,
)


def _open_history_overlay(
    monkeypatch: pytest.MonkeyPatch,
    loader: object,
    *,
    initial_filter: str = "",
) -> PromptsModal:
    monkeypatch.setattr(
        history_pane,
        "load_prompt_record_page",
        loader,
    )
    return PromptsModal(
        [],
        initial_tab=PromptsTab.HISTORY,
        origin=PromptsOrigin(initial_filter=initial_filter),
    )


def _history_pane(overlay: PromptsModal) -> HistoryPane:
    pane = overlay._history_pane
    assert pane is not None
    return pane


def test_prompt_history_paging_bound_to_ctrl_j_and_ctrl_k() -> None:
    key_action_pairs = [
        (binding[0], binding[1])
        if isinstance(binding, tuple)
        else (binding.key, binding.action)
        for binding in HistoryPane.BINDINGS
    ]

    assert ("ctrl+j", "load_more") in key_action_pairs
    assert ("ctrl+k", "unload") in key_action_pairs
    assert all(key != "ctrl+d" for key, _ in key_action_pairs)


async def test_ctrl_j_loads_more_without_deleting_filter_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = PromptHistoryPageCursor(offset=1)
    pages = [
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    ]
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        if pages:
            return pages.pop(0)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    overlay = _open_history_overlay(
        monkeypatch, fake_load_prompt_record_page, initial_filter="alpha"
    )
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(overlay)
        await wait_for(
            pilot,
            lambda: (
                overlay._history_pane is not None
                and len(overlay._history_pane._all_items) == 1
                and not overlay._history_pane._history_loading
            ),
        )
        pane = _history_pane(overlay)

        filter_input = overlay.query_one("#prompt-history-filter-input", Input)
        assert filter_input.has_focus
        assert filter_input.value == "alpha"

        filter_input.cursor_position = 0
        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(pane._all_items) == 2 and not pane._history_loading
        )

        assert filter_input.value == "alpha"
        assert [item.entry.text for item in pane._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]
        assert calls[1]["cursor"] == first_cursor
        assert calls[0]["page_size"] == pane._page_size


async def test_ctrl_k_unloads_last_page_and_next_load_refetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = PromptHistoryPageCursor(offset=1)
    pages_by_cursor = {
        None: PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        first_cursor: PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    }
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        cursor = kwargs.get("cursor")
        return pages_by_cursor.get(
            cursor,  # type: ignore[arg-type]
            PromptHistoryPage(records=[], next_cursor=None, exhausted=True),
        )

    overlay = _open_history_overlay(
        monkeypatch, fake_load_prompt_record_page, initial_filter="alpha"
    )
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(overlay)
        await wait_for(
            pilot,
            lambda: (
                overlay._history_pane is not None
                and len(overlay._history_pane._all_items) == 1
                and not overlay._history_pane._history_loading
            ),
        )
        pane = _history_pane(overlay)

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert len(pane._all_items) == 1
        assert len(calls) == 1

        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(pane._all_items) == 2 and not pane._history_loading
        )
        assert [item.entry.text for item in pane._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]

        await pilot.press("ctrl+k")
        await wait_for(pilot, lambda: len(pane._all_items) == 1)
        assert [item.entry.text for item in pane._all_items] == [
            "alpha first loaded prompt",
        ]
        assert pane._history_exhausted is False
        assert pane._next_cursor == first_cursor

        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(pane._all_items) == 2 and not pane._history_loading
        )
        assert calls[2]["cursor"] == first_cursor
        assert [item.entry.text for item in pane._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]


async def test_prompt_history_uses_configured_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(history_pane, "get_ace_page_size", lambda: 25)
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    overlay = _open_history_overlay(monkeypatch, fake_load_prompt_record_page)
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(overlay)
        await wait_for(
            pilot,
            lambda: (
                overlay._history_pane is not None
                and overlay._history_pane._history_loaded_once
            ),
        )
        pane = _history_pane(overlay)

    assert pane._page_size == 25
    assert calls[0]["page_size"] == 25
    assert "^j/+25" in pane._hints_text()
    assert "^k/-25" in pane._hints_text()


async def test_ctrl_d_no_longer_loads_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = PromptHistoryPageCursor(offset=1)
    pages = [
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    ]
    page_loads = 0

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        nonlocal page_loads
        page_loads += 1
        if pages:
            return pages.pop(0)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    overlay = _open_history_overlay(
        monkeypatch, fake_load_prompt_record_page, initial_filter="alpha"
    )
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(overlay)
        await wait_for(
            pilot,
            lambda: (
                overlay._history_pane is not None
                and len(overlay._history_pane._all_items) == 1
                and not overlay._history_pane._history_loading
            ),
        )
        pane = _history_pane(overlay)

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert page_loads == 1
        assert not pane._history_loading
        assert [item.entry.text for item in pane._all_items] == [
            "alpha first loaded prompt",
        ]
