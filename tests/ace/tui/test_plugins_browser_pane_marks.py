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
        assert pane._marked == {"plugin:nvim", "cli:claude", "cli:qwen"}


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


async def test_cli_install_mark_stays_inside_agent_cli_section(
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
        _highlight_row(pane, "cli:qwen")
        pane.action_toggle_mark()
        assert pane._marked == {"cli:qwen"}
        assert pane._marked_cli_install_names() == ("qwen",)
        assert pane._marked_plugin_names() == ()
        assert "Marked: 1 CLI install" in pane._hints()
        # The cursor advances to the next installable CLI, never into plugins.
        highlighted = pane._highlighted_row()
        assert highlighted is not None
        assert highlighted.kind == "agent-cli"
        assert highlighted.key != "cli:qwen"
        assert "install" in highlighted.capabilities


async def test_manual_cli_mark_warns_with_vendor_reason(
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
        _highlight_row(pane, "cli:antigravity")
        assert pane.check_action("toggle_install_mark", ()) is False
        pane.action_toggle_mark()
        await page.pause()
        assert pane._marked == set()
        assert messages and messages[0][1] == "warning"
        assert "Antigravity CLI can't be installed by SASE" in messages[0][0]


async def test_mark_all_installable_clis_then_unmarks(
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
        _highlight_row(pane, "cli:qwen")
        assert pane.check_action("toggle_mark_all", ()) is True
        pane.action_toggle_mark_all()
        assert pane._marked == {"cli:qwen", "cli:muse"}
        assert messages and messages[0] == (
            "Marked 2 agent CLIs to install",
            "information",
        )
        assert "Marked: 2 CLI installs" in pane._hints()

        pane.action_toggle_mark_all()
        assert pane._marked == set()
        assert messages[-1] == ("Unmarked 2 agent CLIs", "information")


async def test_mark_all_updatable_clis_share_one_verb(
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
        _highlight_row(pane, "cli:claude")
        pane.action_toggle_mark_all()
        # codex is manual-only, so claude is the only updatable CLI row.
        assert pane._marked == {"cli:claude"}
        assert messages and messages[0] == (
            "Marked 1 agent CLI to update",
            "information",
        )


async def test_mark_all_respects_scope_and_filter(
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
        pane._set_scope("installed")
        _highlight_row(pane, "cli:claude")
        pane.action_toggle_mark_all()
        # qwen/muse are hidden by the Installed scope, so only updates mark.
        assert pane._marked == {"cli:claude"}

        pane._set_scope("all")
        _highlight_row(pane, "cli:qwen")
        _apply_updates_filter(pane, "qwen")
        pane.action_toggle_mark_all()
        assert pane._marked == {"cli:claude", "cli:qwen"}


async def test_mark_all_keeps_builtin_and_community_plugins_apart(
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
        _highlight(pane, "nvim")
        pane.action_toggle_mark_all()
        assert pane._marked == {"plugin:nvim"}
        assert messages and messages[0] == (
            "Marked 1 plugin to install",
            "information",
        )

        _highlight_row(pane, "plugin:acme")
        pane.action_toggle_mark_all()
        assert pane._marked == {"plugin:nvim", "plugin:acme"}


async def test_mark_all_unmarkable_row_warns_like_space(
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
        _highlight_row(pane, "cli:antigravity")
        assert pane.check_action("toggle_mark_all", ()) is False
        pane.action_toggle_mark_all()
        await page.pause()
        assert pane._marked == set()
        assert messages and messages[0][1] == "warning"
        assert "Antigravity CLI can't be installed by SASE" in messages[0][0]


async def test_pane_bindings_have_no_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_uv_tool())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        keys = [key for key, _action, _description in pane.BINDINGS]
        assert len(keys) == len(set(keys))
        assert ("asterisk", "toggle_mark_all", "Mark all") in pane.BINDINGS


async def test_asterisk_press_marks_all_without_saved_query_picker(
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
        _highlight_row(pane, "cli:qwen")
        await page.press("asterisk")
        await page.wait_for(lambda _s: pane._marked == {"cli:qwen", "cli:muse"})
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


async def test_asterisk_in_filter_input_inserts_text(
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
        pane.action_focus_filter()
        await page.wait_for(
            lambda _s: getattr(page.app.focused, "id", None) == "updates-filter-input"
        )
        await page.press("asterisk")
        await page.wait_for(
            lambda _s: pane.query_one("#updates-filter-input").value == "*"
        )
        assert pane._marked == set()
