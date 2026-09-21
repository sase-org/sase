"""Agents-tab ``r``/``R`` retry and refresh routing."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.commands import CommandContext, is_command_available
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import KeybindingFooter
from sase.feature_flags import override_flags
from tests._command_availability_helpers import catalog_by_id, make_agent


def test_agents_retry_excludes_proc_monitor_and_gate_rows() -> None:
    catalog = catalog_by_id()
    spec = catalog["app.agents_retry"]
    proc = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status="RUNNING",
        start_time=None,
        proc_id="abc123def456",
        proc_status="running",
        proc_label="Build docs",
    )
    monitor = make_agent(status="MONITORING")
    monitor.agent_family_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = "m1"
    monitor.monitor_state = "running"
    gate = make_agent(status="GATED")
    gate.agent_family_role = "gate"
    gate.role_suffix = "--gate"
    gate.gate_id = "g1"
    gate.gate_state = "pending"

    assert proc.is_proc_shell is True
    assert monitor.is_monitor is True
    assert gate.is_gate is True
    assert not is_command_available(spec, CommandContext(tab="agents", agent=proc))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=monitor))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=gate))
    assert is_command_available(
        spec, CommandContext(tab="agents", agent=make_agent(status="RUNNING"))
    )


def test_refresh_and_run_workflow_commands_are_unavailable_on_agents() -> None:
    catalog = catalog_by_id()
    ctx = CommandContext(tab="agents", agent=make_agent(status="RUNNING"))
    assert not is_command_available(catalog["app.refresh"], ctx)
    assert not is_command_available(catalog["app.run_workflow"], ctx)
    assert is_command_available(catalog["app.agents_refresh"], ctx)
    assert is_command_available(
        catalog["app.agents_refresh"], CommandContext(tab="agents", agent=None)
    )
    assert is_command_available(catalog["app.agents_retry"], ctx)


def test_agents_only_commands_are_unavailable_on_artifacts_and_axe() -> None:
    catalog = catalog_by_id()
    for tab in ("artifacts", "services"):
        ctx = CommandContext(tab=tab)
        assert not is_command_available(catalog["app.agents_refresh"], ctx)
        assert not is_command_available(catalog["app.agents_retry"], ctx)
        assert is_command_available(catalog["app.refresh"], ctx)


def test_r_and_R_actions_are_tab_gated() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    patches_app = AceApp(auto_start_axe=False, initial_tab="patches")
    axe_app = AceApp(auto_start_axe=False, initial_tab="services")
    patches_app.current_artifacts_subtab = "patches"

    assert agents_app.check_action("agents_refresh", ()) is not False
    assert agents_app.check_action("agents_retry", ()) is not False
    assert agents_app.check_action("refresh", ()) is False
    assert agents_app.check_action("run_workflow", ()) is False

    assert patches_app.check_action("refresh", ()) is not False
    assert patches_app.check_action("run_workflow", ()) is not False
    assert patches_app.check_action("agents_refresh", ()) is False
    assert patches_app.check_action("agents_retry", ()) is False

    assert axe_app.check_action("refresh", ()) is not False
    assert axe_app.check_action("run_workflow", ()) is not False
    assert axe_app.check_action("agents_refresh", ()) is False
    assert axe_app.check_action("agents_retry", ()) is False


def test_footer_and_help_follow_agents_retry_override() -> None:
    registry = load_keymap_registry({"keymaps": {"app": {"agents_retry": "f8"}}})
    footer = KeybindingFooter()
    footer.set_keymap_registry(registry)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
    )
    bindings = footer._compute_agent_bindings(agent)
    assert (footer._kd("agents_retry"), "retry") in bindings
    assert footer._kd("agents_retry") == "<f8>"

    help_pairs = {
        (key, label)
        for _section, rows in agents_bindings(registry)
        for key, label in rows
    }
    assert ("f8", "Retry local or remote agent") in help_pairs


def test_agents_help_refresh_label_follows_flag() -> None:
    registry = load_keymap_registry({})
    with override_flags(refresh_panel=False):
        labels = {
            (key, label)
            for _section, rows in agents_bindings(registry)
            for key, label in rows
        }
        assert ("r", "Refresh") in labels
        assert ("r", "Open Refresh panel") not in labels


async def test_agents_r_refreshes_and_R_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_calls: list[str] = []
    retry_calls: list[str] = []
    monkeypatch.setattr(
        AceApp,
        "action_agents_refresh",
        lambda self: refresh_calls.append(self.current_tab),
    )
    monkeypatch.setattr(
        AceApp,
        "action_agents_retry",
        lambda self: retry_calls.append(self.current_tab),
    )

    async with AcePage(initial_tab="agents") as page:
        await page.press("r")
        await page.pause()
        await page.press("R")
        await page.pause()

    assert refresh_calls == ["agents"]
    assert retry_calls == ["agents"]


async def test_artifacts_r_runs_and_R_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_calls: list[str] = []
    refresh_calls: list[str] = []
    monkeypatch.setattr(
        AceApp,
        "action_run_workflow",
        lambda self: run_calls.append(self.current_tab),
    )
    monkeypatch.setattr(
        AceApp,
        "action_refresh",
        lambda self: refresh_calls.append(self.current_tab),
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.press("r")
        await page.pause()
        await page.press("R")
        await page.pause()

    assert run_calls == ["artifacts"]
    assert refresh_calls == ["artifacts"]
    assert page.app.check_action("agents_refresh", ()) is False
    assert page.app.check_action("agents_retry", ()) is False


async def test_axe_r_runs_and_R_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    run_calls: list[str] = []
    refresh_calls: list[str] = []
    monkeypatch.setattr(
        AceApp,
        "action_run_workflow",
        lambda self: run_calls.append(self.current_tab),
    )
    monkeypatch.setattr(
        AceApp,
        "action_refresh",
        lambda self: refresh_calls.append(self.current_tab),
    )

    async with AcePage(initial_tab="services") as page:
        await page.press("r")
        await page.pause()
        await page.press("R")
        await page.pause()

    assert run_calls == ["services"]
    assert refresh_calls == ["services"]
    assert page.app.check_action("agents_refresh", ()) is False
    assert page.app.check_action("agents_retry", ()) is False
