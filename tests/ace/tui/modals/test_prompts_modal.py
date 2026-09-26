"""Tests for the tabbed Prompts overlay shell (stash + history panes)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals._prompt_history_models import PromptHistoryAction
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsResult,
    PromptsTab,
)
from sase.ace.tui.modals.stash_pane import StashRestoreResult
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from tests.ace.tui.modals.prompt_history_modal_test_helpers import _item
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import make_entry


class PromptsHost(App[None]):
    """Push the Prompts overlay and capture its dismiss result."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        entries: list | None = None,
        *,
        initial_tab: PromptsTab = PromptsTab.STASH,
        origin: PromptsOrigin | None = None,
    ) -> None:
        super().__init__()
        self._entries = entries if entries is not None else []
        self._initial_tab = initial_tab
        self._origin = origin
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            PromptsModal(
                self._entries,
                origin=self._origin,
                initial_tab=self._initial_tab,
            ),
            lambda result: setattr(self, "result", result),
        )


def _entries() -> list:
    return [
        make_entry("a", text="first draft", created_at="2026-06-16T12:00:00"),
        make_entry("b", text="second draft", created_at="2026-06-16T11:00:00"),
    ]


def _refuse_history_io(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail any history disk read; return the call log for assertions."""
    calls: list[str] = []

    def _refuse_catalog() -> object:
        calls.append("catalog")
        raise AssertionError("history catalog must not load before activation")

    def _refuse_page(**kwargs: object) -> object:
        calls.append("page")
        raise AssertionError("history pages must not load before activation")

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(_refuse_catalog),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        _refuse_page,
    )
    return calls


async def test_opens_on_stash_without_history_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _refuse_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        strip = modal.query_one("#prompts-modal-tabs", PanelTabStrip)
        labels = [tab.label for tab in strip._tabs]
        assert labels == ["Stash 2", "History"]
        assert modal.query_one("#stashed-prompts-list", OptionList)
        assert modal._active_tab is PromptsTab.STASH
        # History pane is not mounted, so no catalog/page read could have run.
        assert calls == []
        with pytest.raises(NoMatches):
            modal.query_one("#history-pane-body")
        footer = modal.query_one("#prompts-modal-footer", Static)
        assert "pin" in str(footer.content)


def _record_history_io(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record history disk reads while serving empty results."""
    from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog

    calls: list[str] = []

    def _empty_catalog() -> object:
        calls.append("catalog")
        return PromptHistoryProjectCatalog(entries=())

    def _empty_page(**kwargs: object) -> object:
        calls.append("page")
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(_empty_catalog),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        _empty_page,
    )
    return calls


async def test_brackets_cycle_tabs_with_wraparound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH


async def test_click_selects_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        strip = modal.query_one("#prompts-modal-tabs", PanelTabStrip)

        async def _click_tab(tab_id: str) -> None:
            pad = max(0, (strip.size.width - strip._line_width) // 2)
            start, end = strip._tab_ranges[tab_id]
            await pilot.click(
                "#prompts-modal-tabs", offset=(pad + (start + end) // 2, 0)
            )
            await pilot.pause()

        await _click_tab("history")
        assert modal._active_tab is PromptsTab.HISTORY
        await _click_tab("stash")
        assert modal._active_tab is PromptsTab.STASH


async def test_escape_and_q_close_from_stash() -> None:
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None

    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert app.result is None


async def test_q_types_in_history_filter_instead_of_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("]")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        assert filter_input.has_focus
        await pilot.press("q")
        await pilot.pause()
        assert filter_input.value == "q"
        assert app.result == "UNSET"
        assert modal.is_mounted
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_brackets_in_filter_cycle_without_typing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("]")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        assert filter_input.value == ""
        # Ordinary typing still lands in the filter after returning.
        await pilot.press("]")
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("b")
        await pilot.pause()
        assert modal.query_one("#prompt-history-filter-input", Input).value == "ab"


async def test_stash_marks_and_history_filter_survive_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # mark "a" for restore
        await pilot.press("]")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        filter_input.value = "hello"
        await pilot.pause()
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("]")
        await pilot.pause()
        assert modal.query_one("#prompt-history-filter-input", Input).value == "hello"
        await pilot.press("[")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.STASH
    assert isinstance(app.result.stash, StashRestoreResult)
    assert set(app.result.stash.pop_ids) == {"a"}
    assert app.result.history is None


async def test_history_submit_carries_tab_and_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        PromptHistoryPage(
            records=[record_from_entry(_item(text="recall me").entry)],
            next_cursor=None,
            exhausted=True,
        )
    ]

    def fake_load(**kwargs: object) -> PromptHistoryPage:
        if pages:
            return pages.pop(0)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        fake_load,
    )
    origin = PromptsOrigin(kind="home_mru")
    app = PromptsHost(_entries(), origin=origin)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("]")
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await wait_for(
            pilot,
            lambda: len(modal._ensure_history_pane()._all_items) == 1,
        )
        await pilot.pause()
        # Enter in the filter submits the highlighted row.
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.HISTORY
    assert app.result.origin == origin
    assert app.result.stash is None
    assert app.result.history is not None
    assert app.result.history.action is PromptHistoryAction.SUBMIT
    assert app.result.history.prompt_text == "recall me"


async def test_stash_result_carries_origin() -> None:
    origin = PromptsOrigin(kind="live_bar")
    app = PromptsHost(_entries(), origin=origin)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.STASH
    assert app.result.origin == origin
    assert app.result.stash is not None
    assert app.result.stash.pop_ids == ["a"]


async def test_initial_tab_history_mounts_history_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    app = PromptsHost(_entries(), initial_tab=PromptsTab.HISTORY)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        assert modal._active_tab is PromptsTab.HISTORY
        assert modal.query_one("#history-pane-body")
        # Stash list mounts only on first stash activation.
        with pytest.raises(NoMatches):
            modal.query_one("#stashed-prompts-list")
        await pilot.press("[")
        await pilot.pause()
        assert modal.query_one("#stashed-prompts-list", OptionList)


async def test_narrow_width_marks_shell_container() -> None:
    app = PromptsHost(_entries())
    async with app.run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        container = modal.query_one("#prompts-modal-container")
        assert container.has_class("-narrow")
