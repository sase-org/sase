"""Unified mark-set tests for the Config Center Updates pane."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _highlight,
    _highlight_row,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _ready_many_plan,
    _spy_notify,
    _uv_tool,
)


def _apply_updates_filter(pane: PluginsBrowserPane, needle: str) -> None:
    pane._filter_text = needle
    if pane._detail_debouncer is not None:
        pane._detail_debouncer.cancel()
    pane._apply_filter()


def _visible_keys(pane: PluginsBrowserPane) -> set[str]:
    return {row.key for row in pane._flat_rows()}


async def test_plugin_mark_survives_scope_switch_and_is_consumed_by_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_uv_tool())
    batch_plans: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: (
            batch_plans.append(names)
            or pbp._InstallManyPreview(plan=_ready_many_plan(names))
        ),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        pane.action_toggle_install_mark()
        assert pane._marked == {"plugin:nvim"}

        pane._set_scope("installed")
        assert "plugin:nvim" not in _visible_keys(pane)
        assert pane._marked == {"plugin:nvim"}

        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        assert batch_plans == [("nvim",)]


async def test_cli_mark_consumed_by_update_when_cli_rows_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    recorded: list[tuple[tuple[str, ...] | None, bool]] = []

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:claude")
        pane.action_toggle_mark()
        assert pane._marked == {"cli:claude"}

        _apply_updates_filter(pane, "nvim")
        assert "cli:claude" not in _visible_keys(pane)
        assert pane._marked == {"cli:claude"}

        original = pane._make_agent_cli_update_plan

        def _record(names: tuple[str, ...] | None, *, all_clis: bool) -> Any:
            recorded.append((names, all_clis))
            return original(names, all_clis=all_clis)

        monkeypatch.setattr(pane, "_make_agent_cli_update_plan", _record)
        pane.action_update_agent_clis()
        await page.expect_modal("PluginActionConfirmModal")
        assert recorded == [(("claude",), False)]


async def test_plugin_marks_do_not_constrain_unmarked_cli_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    recorded: list[tuple[tuple[str, ...] | None, bool]] = []

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        pane.action_toggle_install_mark()
        assert pane._marked == {"plugin:nvim"}

        original = pane._make_agent_cli_update_plan

        def _record(names: tuple[str, ...] | None, *, all_clis: bool) -> Any:
            recorded.append((names, all_clis))
            return original(names, all_clis=all_clis)

        monkeypatch.setattr(pane, "_make_agent_cli_update_plan", _record)
        pane.action_update_agent_clis()
        await page.expect_modal("PluginActionConfirmModal")
        assert recorded == [(None, True)]


async def test_escape_clears_plugin_and_cli_marks_in_one_press(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane._marked.update({"plugin:nvim", "cli:claude"})
        pane._render_all()
        assert "Marked: 1 plugin install · 1 CLI update" in pane._hints()

        pane.action_clear_marks_or_close()
        assert pane._marked == set()
        assert messages and messages[0][0] == "Cleared 2 mark(s)."
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"
        assert "Marked:" not in pane._hints()


async def test_filter_hidden_marks_stay_in_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        pane.action_toggle_install_mark()
        _highlight_row(pane, "cli:claude")
        pane.action_toggle_mark()
        assert pane._marked == {"plugin:nvim", "cli:claude"}

        _apply_updates_filter(pane, "github")
        visible = _visible_keys(pane)
        assert "plugin:nvim" not in visible
        assert "cli:claude" not in visible
        hints = pane._hints()
        assert "Marked: 1 plugin install · 1 CLI update (2 hidden by filter)" in hints


async def test_prune_marks_drops_rows_that_lost_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._marked.update(
            {
                "plugin:nvim",
                "plugin:github",
                "plugin:missing",
                "cli:claude",
                "cli:qwen",
            }
        )
        pane._render_all()
        assert pane._marked == {"plugin:nvim", "cli:claude"}


async def test_i_marks_updatable_cli_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:claude")
        assert pane.check_action("toggle_install_mark", ()) is True
        pane.action_toggle_install_mark()
        assert pane._marked == {"cli:claude"}
        assert "Marked: 1 CLI update" in pane._hints()
        assert "I/space mark" in pane._hints()
