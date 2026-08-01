"""Updates-pane sub-tab and Agent CLIs browser tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.agent_clis.models import (
    AgentCliUpdateResult,
    AgentCliUpdatesReady,
    UpdateResultStatus,
)

from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
)


async def test_updates_subtabs_cycle_and_gate_plugin_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        agent_cli_colors={"claude": "#D97757", "codex": "#10A37F"},
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        switcher = pane.query_one("#updates-subtab-switcher", ContentSwitcher)
        assert pane._active_subtab == "plugins"

        pane.action_cycle_subtab()
        assert pane._active_subtab == "agent-clis"
        assert switcher.current == "updates-subtab-agent-clis"
        assert pane.check_action("install", ()) is False
        assert pane.check_action("update_agent_clis", ()) is True

        pane.action_cycle_subtab()
        assert pane._active_subtab == "core"
        assert switcher.current == "updates-subtab-core"
        assert pane.check_action("next_option", ()) is False

        pane.action_cycle_subtab_reverse()
        assert pane._active_subtab == "agent-clis"


async def test_agent_cli_session_restores_subtab_and_row_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )
    state = AdminCenterSessionState()
    state.updates.active_subtab = "agent-clis"
    state.updates.agent_clis.record("codex", 0)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="updates", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#updates")))
        pane = modal.query_one("#updates", PluginsBrowserPane)
        await page.wait_for(lambda _s: not pane._loading)

        option_list = pane.query_one("#agent-clis-list", OptionList)
        assert pane._active_subtab == "agent-clis"
        assert option_list.highlighted == 1
        assert state.updates.agent_clis.identity == "codex"


async def test_updates_subtabs_handle_brackets_from_core_and_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="updates")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#updates")))
        pane = modal.query_one("#updates", PluginsBrowserPane)
        await page.wait_for(lambda _s: not pane._loading)
        plugins_list = pane.query_one("#plugins-list", OptionList)
        agent_clis_list = pane.query_one("#agent-clis-list", OptionList)

        assert pane._active_subtab == "core"
        assert page.app.focused is pane

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "plugins")
        assert page.app.focused is plugins_list

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "agent-clis")
        assert page.app.focused is agent_clis_list

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "core")
        assert page.app.focused is pane

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "agent-clis")
        assert page.app.focused is agent_clis_list

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "plugins")
        assert page.app.focused is plugins_list

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "core")
        assert page.app.focused is pane


async def test_updates_subtab_hints_share_projects_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        hints = (pane._core_hints(), pane._hints(), pane._agent_cli_hints())

        assert all("[ / ] sub-tab" in hint for hint in hints)
        assert all("]/[ sub-tab" not in hint for hint in hints)
        assert all("a sync agents" in hint for hint in hints)


async def test_agent_cli_marks_patch_rows_and_escape_clears_first(
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
        option_list = pane.query_one("#agent-clis-list", OptionList)
        assert option_list.highlighted == 0

        pane.action_toggle_mark()
        assert pane._marked_agent_clis == {"claude"}
        claude_row = option_list.get_option_at_index(0).prompt
        row_text = claude_row.plain if hasattr(claude_row, "plain") else str(claude_row)
        assert "[✓]" in row_text

        pane.action_clear_marks_or_close()
        assert pane._marked_agent_clis == set()
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


async def test_agent_cli_update_plan_confirm_and_tracked_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    statuses = _agent_cli_statuses()
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=statuses,
    )
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._switch_to_subtab("agent-clis")

        def submit(*args: Any, **kwargs: Any) -> object:
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)
        pane.action_update_agent_clis()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        variant = modal._variants[0]
        assert variant.items_label == "Commands"
        assert any("claude update" in item for item in variant.items)
        assert any(
            "Homebrew installs require a manual upgrade" in item
            and "developers.openai.com" in item
            for item in variant.skipped
        )

        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        assert submitted["dedup_key"] == "agent-cli-update"
        assert submitted["exclusive_scopes"] == ("agent-cli-update",)
        assert submitted["reload_on_complete"] is False

        plan = pane._make_agent_cli_update_plan(None, all_clis=True)
        assert isinstance(plan, AgentCliUpdatesReady)
        result = AgentCliUpdateResult(
            name="claude",
            display_name="Claude Code",
            status=UpdateResultStatus.UPDATED,
            old_version="1.0.0",
            new_version="1.1.0",
            command=("/home/dev/.local/bin/claude", "update"),
            docs_url="https://code.claude.com/docs/en/setup",
        )
        monkeypatch.setattr(
            pbp,
            "_execute_agent_cli_updates",
            lambda *_args, **_kwargs: (result,),
        )
        task_result = submitted["args"][3](_Reporter())
        assert task_result.success is True
        assert task_result.payload == (result,)

        reloads: list[bool] = []
        monkeypatch.setattr(
            pane,
            "_start_load",
            lambda *, force: reloads.append(force),
        )
        submitted["on_complete"](
            SimpleNamespace(
                payload=(result,),
                message="Claude Code: updated 1.0.0 → 1.1.0",
                success=True,
            )
        )
        assert pane._agent_cli_results["claude"] == result
        assert reloads == [False]


async def test_update_sase_action_remains_pane_wide(
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
        calls: list[str] = []
        monkeypatch.setattr(
            pane,
            "_start_sase_update_preview",
            lambda **_kwargs: calls.append(pane._active_subtab),
        )
        for subtab in ("core", "plugins", "agent-clis"):
            pane._switch_to_subtab(subtab)
            pane.action_update_sase()
        assert calls == ["core", "plugins", "agent-clis"]


class _Reporter:
    def phase(self, _label: str) -> None:
        pass

    def section(self, _title: str) -> None:
        pass

    def log(self, _text: str, *, stream: str = "stdout") -> None:
        del stream

    def subprocess_run_fn(self) -> Any:
        raise AssertionError("executor was stubbed; no subprocess should run")
