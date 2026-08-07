"""Apostrophe entry-jump tests for the Admin Center Updates pane."""

from __future__ import annotations

import pytest
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


def _agent_cli_labels(pane: PluginsBrowserPane) -> list[str]:
    option_list = pane.query_one("#agent-clis-list", OptionList)
    labels: list[str] = []
    for index in range(option_list.option_count):
        prompt = option_list.get_option_at_index(index).prompt
        labels.append(prompt.plain if hasattr(prompt, "plain") else str(prompt))
    return labels


def _hint_text(pane: PluginsBrowserPane, selector: str) -> str:
    return pane.query_one(selector, Static).render().plain


def _item_indices(pane: PluginsBrowserPane, selector: str) -> list[int]:
    option_list = pane.query_one(selector, OptionList)
    return [
        index
        for index in range(option_list.option_count)
        if pane._is_item(option_list, index)
    ]


async def test_updates_plugins_apostrophe_paints_hints_skipping_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is True
        labels = _option_labels(pane)
        hinted = [label for label in labels if label.startswith("[")]
        assert len(hinted) == pane._jump_target_count() == 4
        assert [label[:3] for label in hinted] == ["[0]", "[1]", "[2]", "[3]"]
        # Disabled group headers never receive a hint.
        headers = [label for label in labels if "──" in label]
        assert headers and all(not header.startswith("[") for header in headers)
        assert "JUMP ' first" in _hint_text(pane, "#plugins-hints")


async def test_updates_plugins_hint_selects_row_and_renders_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#plugins-list", OptionList)
        item_indices = _item_indices(pane, "#plugins-list")

        await page.press("apostrophe")
        await page.press("2")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [0]
        assert option_list.highlighted == item_indices[2]
        jumped_name = pane._flat_plugin_entries()[2].name
        await page.wait_for(lambda _s: pane._detail_name == jumped_name)
        assert not any(label.startswith("[") for label in _option_labels(pane))
        assert "' jump" in _hint_text(pane, "#plugins-hints")


async def test_updates_plugins_second_apostrophe_returns_to_previous_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#plugins-list", OptionList)
        item_indices = _item_indices(pane, "#plugins-list")

        await page.press("apostrophe")
        await page.press("3")
        await page.pause()
        assert option_list.highlighted == item_indices[3]

        await page.press("apostrophe")
        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []
        assert option_list.highlighted == item_indices[0]


async def test_updates_plugins_escape_cancels_jump_without_moving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        option_list = pane.query_one("#plugins-list", OptionList)
        before = option_list.highlighted

        await page.press("apostrophe")
        await page.press("escape")
        await page.pause()

        assert pane.jump_mode_active is False
        assert option_list.highlighted == before
        assert not any(label.startswith("[") for label in _option_labels(pane))
        assert page.state["modal"] == "ConfigCenterModal"


async def test_updates_agent_clis_hint_selects_row_and_renders_detail(
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
        pane._switch_to_subtab("agent-clis")
        await page.pause()
        option_list = pane.query_one("#agent-clis-list", OptionList)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True
        assert [label[:3] for label in _agent_cli_labels(pane)] == [
            "[0]",
            "[1]",
            "[2]",
        ]
        assert "JUMP ' first" in _hint_text(pane, "#agent-clis-hints")

        await page.press("2")
        await page.pause()

        assert pane.jump_mode_active is False
        assert option_list.highlighted == 2
        await page.wait_for(lambda _s: pane._agent_cli_detail_name == "qwen")
        assert not any(label.startswith("[") for label in _agent_cli_labels(pane))


async def test_updates_core_subtab_apostrophe_is_an_inert_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._switch_to_subtab("core")
        await page.pause()

        assert pane.check_action("jump_to_entry", ()) is False

        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane._jump_target_count() == 0
        assert pane._active_subtab == "core"


async def test_updates_subtab_switch_clears_jump_hints(
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
        await page.press("1")
        await page.pause()
        assert pane.jump_back_stack == [0]

        pane._switch_to_subtab("agent-clis")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []
        assert not any(label.startswith("[") for label in _option_labels(pane))


async def test_updates_plugins_filter_change_clears_jump_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True

        pane.query_one("#plugins-filter-input").value = "github"
        await page.pause()

        assert pane.jump_mode_active is False
        assert not any(label.startswith("[") for label in _option_labels(pane))
