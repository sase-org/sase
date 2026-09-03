"""Apostrophe entry-jump tests for the Admin Center Updates pane."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane

from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_other_panes,
)


def _hint_text(pane: PluginsBrowserPane, selector: str) -> str:
    return pane.query_one(selector, Static).render().plain


def _item_indices(pane: PluginsBrowserPane, selector: str) -> list[int]:
    option_list = pane.query_one(selector, OptionList)
    return [
        index
        for index in range(option_list.option_count)
        if pane._is_item(option_list, index)
    ]


async def test_updates_apostrophe_paints_hints_across_all_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is True
        labels = _option_labels(pane)
        hinted = [label for label in labels if label.startswith("[")]
        assert len(hinted) == pane._jump_target_count()
        assert pane._jump_target_count() == 2 + 4 + 3
        kinds = {row.kind for row in pane._flat_rows()}
        assert kinds == {"core", "plugin", "agent-cli"}
        headers = [label for label in labels if "──" in label]
        assert headers and all(not header.startswith("[") for header in headers)
        assert "JUMP ' first" in _hint_text(pane, "#updates-hints")


async def test_updates_hint_selects_row_and_renders_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#updates-list", OptionList)
        item_indices = _item_indices(pane, "#updates-list")
        origin = pane._jump_current_index()
        assert origin is not None
        target = 0 if origin != 0 else 1

        await page.press("apostrophe")
        await page.press(str(target))
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [origin]
        assert option_list.highlighted == item_indices[target]
        jumped = pane._flat_rows()[target]
        await page.wait_for(lambda _s: pane._detail_key == jumped.key)
        assert not any(label.startswith("[") for label in _option_labels(pane))
        assert "' jump" in _hint_text(pane, "#updates-hints")


async def test_updates_second_apostrophe_returns_to_previous_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#updates-list", OptionList)
        item_indices = _item_indices(pane, "#updates-list")
        origin = pane._jump_current_index()
        assert origin is not None
        target = 0 if origin != 0 else 1

        await page.press("apostrophe")
        await page.press(str(target))
        await page.pause()
        assert option_list.highlighted == item_indices[target]

        await page.press("apostrophe")
        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []
        assert option_list.highlighted == item_indices[origin]


async def test_updates_escape_cancels_jump_without_moving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#updates-list", OptionList)
        before = option_list.highlighted

        await page.press("apostrophe")
        await page.press("escape")
        await page.pause()

        assert pane.jump_mode_active is False
        assert option_list.highlighted == before
        assert not any(label.startswith("[") for label in _option_labels(pane))
        assert page.state["modal"] == "ConfigCenterModal"


async def test_updates_jump_mode_takes_g_and_shift_g_from_the_scroller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        scroll = pane.query_one("#updates-detail-scroll", VerticalScroll)

        for hint_key in ("G", "g"):
            await page.press("apostrophe")
            await page.pause()
            assert pane.jump_mode_active is True

            await page.press(hint_key)
            await page.pause()

            # These rows allocate single-digit hints, so g / G are invalid
            # hints that exit jump mode -- but they must reach the pane's
            # jump handler instead of being swallowed by the detail scroller.
            assert pane.jump_mode_active is False
            assert scroll.scroll_y == 0


async def test_updates_scope_switch_clears_jump_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        origin = pane._jump_current_index()
        assert origin is not None
        target = 0 if origin != 0 else 1
        await page.press("apostrophe")
        await page.press(str(target))
        await page.pause()
        assert pane.jump_back_stack == [origin]

        pane._set_scope("installed")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []
        assert not any(label.startswith("[") for label in _option_labels(pane))


async def test_updates_filter_change_clears_jump_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True

        pane.query_one("#updates-filter-input").value = "github"
        await page.pause()

        assert pane.jump_mode_active is False
        # The row rebuild that clears painted hint prefixes is debounced.
        await page.wait_for(
            lambda _s: not any(label.startswith("[") for label in _option_labels(pane))
        )
