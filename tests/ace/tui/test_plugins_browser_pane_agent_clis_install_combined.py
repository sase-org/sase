"""Combined plugin + CLI install and install-history tests for the Updates tab."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_agent_clis_history import (
    build_agent_cli_history_panel,
)
from sase.agent_clis.history import build_agent_cli_update_run
from sase.agent_clis.install import AgentCliInstallsPlanned
from sase.agent_clis.models import (
    AgentCliOperation,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)
from sase.plugins.operations import InstallManyOutcome
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._agent_cli_install_helpers import (
    _by_name,
    _completion,
    _FakeReporter,
    _install_result,
    _npm_entry,
    _skip_entry,
    _stub_install_plan,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _highlight,
    _highlight_row,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _ready_many_plan,
    _render,
    _spy_notify,
    _uv_tool,
)
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)

_NOW = 1_800_000_000.0


# -- combined plugin + CLI installs ------------------------------------------


def _many_outcome(plan: Any, *, changed: bool = True) -> InstallManyOutcome:
    changes = (
        (UvPackageChange(name="sase-nvim", kind=ChangeKind.ADDED, new_version="2.0.0"),)
        if changed
        else ()
    )
    return InstallManyOutcome(
        plan=plan,
        change_set=UvChangeSet(changes=changes),
        groups=(),
        elapsed=2.0,
    )


async def _mark_plugin_and_cli(pane: Any) -> None:
    _highlight(pane, "nvim")
    pane.action_toggle_install_mark()
    _highlight_row(pane, "cli:qwen")
    pane.action_toggle_mark()
    assert pane._marked == {"plugin:nvim", "cli:qwen"}


async def test_combined_install_previews_plugins_section_and_runs_clis_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    monkeypatch.setattr(
        update_receipt, "_PENDING_UPDATE_TOAST_FILE", tmp_path / "toast.json"
    )
    statuses = _by_name()
    cli_plan = AgentCliInstallsPlanned(entries=(_npm_entry(statuses["qwen"]),))
    _stub_install_plan(monkeypatch, cli_plan)
    plugin_plan = _ready_many_plan(("nvim",))
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: pbp._InstallManyPreview(plan=plugin_plan),
    )
    order: list[str] = []
    cli_results = (
        _install_result("qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True),
    )
    monkeypatch.setattr(
        pbp,
        "_execute_agent_cli_installs",
        lambda *a, **k: order.append("clis") or cli_results,
    )
    monkeypatch.setattr(
        pbp,
        "execute_install_many",
        lambda plan, **k: order.append("plugins") or _many_outcome(plan),
    )
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[str] = []
        monkeypatch.setattr(
            page.app, "_restart_tui", lambda *, restart_axe: restart_calls.append("y")
        )
        reloads: list[bool] = []
        monkeypatch.setattr(pane, "_start_load", lambda *, force: reloads.append(force))
        await _mark_plugin_and_cli(pane)
        assert "Marked: 1 plugin install · 1 CLI install" in pane._hints()

        def submit(*args: Any, **kwargs: Any) -> object:
            assert_session_worker_submit_signature(args, kwargs)
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert str(modal._title) == "Install 1 plugin and 1 agent CLI"
        variant = modal._variants[0]
        assert variant.sections[0].title == "Qwen Code"
        plugins_section = variant.sections[-1]
        assert plugins_section.title == "Plugins"
        assert any("uv tool install" in command for command in plugins_section.commands)
        assert any("nvim" in component.name for component in plugins_section.components)
        assert "sase's TUI restarts after the plugins install." in variant.details

        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        assert submitted["args"][0] == "agent-cli-plugin-install"
        outcome = submitted["args"][1](_FakeReporter())
        assert order == ["clis", "plugins"]
        assert outcome.success is True
        submitted["on_complete"](
            _completion(outcome.payload, message=outcome.message, success=True)
        )
        assert pane._agent_cli_results["qwen"] == cli_results[0]
        assert pane._marked == set()
        assert restart_calls == ["y"]
        assert reloads == []
        assert messages and "Installed Qwen Code 0.8.0" in messages[0][0]


async def test_combined_install_without_plugin_changes_reloads_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    cli_plan = AgentCliInstallsPlanned(entries=(_npm_entry(statuses["qwen"]),))
    _stub_install_plan(monkeypatch, cli_plan)
    plugin_plan = _ready_many_plan(("nvim",))
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: pbp._InstallManyPreview(plan=plugin_plan),
    )
    cli_results = (
        _install_result("qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True),
    )
    monkeypatch.setattr(pbp, "_execute_agent_cli_installs", lambda *a, **k: cli_results)
    monkeypatch.setattr(
        pbp,
        "execute_install_many",
        lambda plan, **k: _many_outcome(plan, changed=False),
    )
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        reloads: list[bool] = []
        monkeypatch.setattr(pane, "_start_load", lambda *, force: reloads.append(force))
        await _mark_plugin_and_cli(pane)

        def submit(*args: Any, **kwargs: Any) -> object:
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        outcome = submitted["args"][1](_FakeReporter())
        submitted["on_complete"](
            _completion(outcome.payload, message=outcome.message, success=True)
        )
        assert restart_calls == []
        assert reloads == [False]
        assert messages and "Installed Qwen Code 0.8.0" in messages[0][0]


async def test_combined_install_runs_clis_when_plugins_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.plugins.operations import NotUvTool
    from sase.uv_tool.errors import NotAUvToolInstallError
    from tests.ace.tui._plugins_browser_pane_helpers import _not_uv_tool

    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    cli_plan = AgentCliInstallsPlanned(entries=(_npm_entry(statuses["qwen"]),))
    _stub_install_plan(monkeypatch, cli_plan)
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: pbp._InstallManyPreview(
            plan=NotUvTool(error=NotAUvToolInstallError(_not_uv_tool()))
        ),
    )
    executed_plugins: list[Any] = []
    cli_results = (
        _install_result("qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True),
    )
    monkeypatch.setattr(pbp, "_execute_agent_cli_installs", lambda *a, **k: cli_results)
    monkeypatch.setattr(
        pbp,
        "execute_install_many",
        lambda plan, **k: executed_plugins.append(plan),
    )
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        reloads: list[bool] = []
        monkeypatch.setattr(pane, "_start_load", lambda *, force: reloads.append(force))
        await _mark_plugin_and_cli(pane)

        def submit(*args: Any, **kwargs: Any) -> object:
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        variant = modal._variants[0]
        assert [section.title for section in variant.sections] == ["Qwen Code"]
        assert any("uv tool" in line for line in variant.skipped)
        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        outcome = submitted["args"][1](_FakeReporter())
        assert executed_plugins == []
        submitted["on_complete"](
            _completion(outcome.payload, message=outcome.message, success=True)
        )
        assert pane._agent_cli_results["qwen"] == cli_results[0]
        assert restart_calls == []
        assert reloads == [False]
        assert messages and "Installed Qwen Code 0.8.0" in messages[0][0]


async def test_combined_install_with_nothing_runnable_toasts_every_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.plugins.operations import NotUvTool
    from sase.uv_tool.errors import NotAUvToolInstallError
    from tests.ace.tui._plugins_browser_pane_helpers import _not_uv_tool

    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    cli_plan = AgentCliInstallsPlanned(
        entries=(_skip_entry(statuses["qwen"], "npm is not on PATH"),)
    )
    _stub_install_plan(monkeypatch, cli_plan)
    not_uv_tool = NotAUvToolInstallError(_not_uv_tool())
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: pbp._InstallManyPreview(
            plan=NotUvTool(error=not_uv_tool)
        ),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        await _mark_plugin_and_cli(pane)
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert severity == "warning"
        assert message.startswith("Nothing marked can be installed: ")
        assert "npm is not on PATH" in message
        assert str(not_uv_tool) in message
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


# -- history and result lines ------------------------------------------------


def _render_install_history_panel(run: Any) -> str:
    statuses = _by_name()
    panel = build_agent_cli_history_panel(
        statuses["qwen"],
        (run,),
        enabled=True,
        error=None,
        all_clis=True,
        now=_NOW,
        max_rows=0,
        colors={},
    )
    return _render(panel)


def test_install_history_shows_down_glyph_installed_text_and_i_badge() -> None:
    from datetime import UTC, datetime

    run = build_agent_cli_update_run(
        (
            AgentCliUpdateResult(
                name="qwen",
                display_name="Qwen Code",
                status=UpdateResultStatus.UPDATED,
                old_version=None,
                new_version="0.8.0",
                command=("npm", "install", "-g", "@qwen-code/qwen-code"),
                docs_url=None,
                operation=AgentCliOperation.INSTALL,
            ),
        ),
        trigger=UpdateTrigger.ADMIN_CENTER,
        elapsed=3.0,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        run_id="install123456",
    )
    rendered = _render_install_history_panel(run)
    assert "↓" in rendered
    assert "installed 0.8.0" in rendered
    assert "· i ·" in rendered
    assert "History · all agent CLIs" in rendered


def test_update_history_keeps_arrow_glyph_and_update_badge() -> None:
    from datetime import UTC, datetime

    run = build_agent_cli_update_run(
        (
            AgentCliUpdateResult(
                name="claude",
                display_name="Claude Code",
                status=UpdateResultStatus.UPDATED,
                old_version="1.0.0",
                new_version="1.1.0",
                command=("claude", "update"),
                docs_url=None,
                operation=AgentCliOperation.UPDATE,
            ),
        ),
        trigger=UpdateTrigger.ADMIN_CENTER,
        elapsed=3.0,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        run_id="update123456",
    )
    statuses = _by_name()
    panel = build_agent_cli_history_panel(
        statuses["claude"],
        (run,),
        enabled=True,
        error=None,
        all_clis=True,
        now=_NOW,
        max_rows=0,
        colors={},
    )
    rendered = _render(panel)
    assert "▲" in rendered
    assert "· A ·" in rendered


def test_agent_cli_install_result_lines() -> None:
    from sase.ace.tui.modals.plugins_browser_agent_clis_actions import (
        agent_cli_install_summary,
        agent_cli_result_line,
    )

    success = _install_result(
        "qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True
    )
    assert agent_cli_result_line(success) == "Qwen Code: installed 0.8.0"
    noted = _install_result(
        "qwen",
        "Qwen Code",
        UpdateResultStatus.UPDATED,
        reason="note here",
        on_path=True,
    )
    assert agent_cli_result_line(noted) == "Qwen Code: installed 0.8.0 — note here"
    failure = _install_result(
        "qwen", "Qwen Code", UpdateResultStatus.FAILED, reason="boom"
    )
    assert agent_cli_result_line(failure) == "Qwen Code: install failed — boom"
    skipped = _install_result(
        "qwen", "Qwen Code", UpdateResultStatus.SKIPPED, reason="no npm"
    )
    assert agent_cli_result_line(skipped) == "Qwen Code: skipped — no npm"

    message, severity = agent_cli_install_summary((success,))
    assert (message, severity) == ("Installed Qwen Code 0.8.0", "information")
    message, severity = agent_cli_install_summary((success, failure))
    assert severity == "error"
    assert "install failed" in message
    off_path = _install_result(
        "qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=False
    )
    message, severity = agent_cli_install_summary((off_path,))
    assert severity == "warning"
    assert "export PATH=" in message
