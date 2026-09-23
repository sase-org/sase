"""Install-flow tests for missing agent CLIs in the Updates tab."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.agent_clis.install import AgentCliInstallsPlanned
from sase.agent_clis.models import (
    AgentCliUnknownName,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)
from tests.ace.tui._agent_cli_install_helpers import (
    _DIGEST,
    _by_name,
    _FakeReporter,
    _install_result,
    _make_script,
    _npm_entry,
    _script_entry,
    _skip_entry,
    _stub_install_plan,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _highlight_row,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _render,
    _spy_notify,
    _uv_tool,
)
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)


async def test_install_detail_panel_per_route(
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
        statuses = _by_name()

        npm_text = _render(pane._agent_cli_detail_panel(statuses["qwen"]))
        assert "Qwen Code · not installed" in npm_text
        assert "not installed" in npm_text
        assert "npm · @qwen-code/qwen-code" in npm_text
        assert "npm install -g @qwen-code/qwen-code" in npm_text
        assert "↓ i install now · Space mark · * mark all missing" in npm_text

        script_text = _render(pane._agent_cli_detail_panel(statuses["muse"]))
        assert "Muse Code · not installed" in script_text
        assert "install script" in script_text
        assert "https://dev.meta.ai/install.sh" in script_text
        assert "SHA-256 shown before it runs" in script_text
        assert "~/.local/bin (MUSE_INSTALL_DIR overrides)" in script_text

        manual_text = _render(pane._agent_cli_detail_panel(statuses["antigravity"]))
        assert "How to install" in manual_text
        assert "SASE can't run this installer" in manual_text

        installed_text = _render(pane._agent_cli_detail_panel(statuses["claude"]))
        assert "· not installed" not in installed_text


async def test_install_detail_panel_off_path_call_to_action(
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
        statuses = _by_name()
        pane._agent_cli_results["qwen"] = _install_result(
            "qwen",
            "Qwen Code",
            UpdateResultStatus.UPDATED,
            new_version="0.8.0",
            on_path=False,
        )
        text = _render(pane._agent_cli_detail_panel(statuses["qwen"]))
        assert "which is not on PATH" in text
        assert 'export PATH="/home/dev/.npm-global/bin:$PATH"' in text


# -- i routing ---------------------------------------------------------------


async def test_i_on_installable_cli_opens_modal_with_digest_and_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    script = _make_script(tmp_path)
    plan = AgentCliInstallsPlanned(
        entries=(
            _npm_entry(statuses["qwen"], on_path=True),
            _script_entry(statuses["muse"], script, on_path=False),
            _skip_entry(statuses["antigravity"], "no SASE-runnable installer"),
        )
    )
    requested = _stub_install_plan(monkeypatch, plan)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:qwen")
        assert pane.check_action("install", ()) is True
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        assert requested == [("qwen",)]
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert str(modal._title) == "Install 2 agent CLIs"
        variant = modal._variants[0]
        assert variant.summary == "Installs 2 agent CLIs, one at a time"
        assert variant.argv == ()
        assert "Runs without a shell" in variant.details[0]
        npm_section, script_section = variant.sections
        assert npm_section.title == "Qwen Code"
        assert npm_section.counts == ("npm", "latest v0.8.0")
        assert npm_section.details == ("target /home/dev/.npm-global/bin · on PATH",)
        assert npm_section.commands == ("npm install -g @qwen-code/qwen-code",)
        assert script_section.title == "Muse Code"
        assert script_section.counts == ("install script", "latest v1.3.0-R3401.1")
        assert script_section.details == (
            f"script https://dev.meta.ai/install.sh · {script.size_bytes} bytes",
            f"sha256 {_DIGEST}",
            "target ~/.local/bin · not on PATH (SASE prints the export line)",
        )
        assert script_section.commands[0].startswith("bash ")
        assert any("Antigravity CLI" in line for line in variant.skipped)


async def test_i_on_manual_cli_toasts_reason_without_modal(
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
        assert pane.check_action("install", ()) is True
        await page.press("i")
        await page.pause()
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"
        assert messages and messages[0][1] == "warning"
        assert "antigravity.dev" in messages[0][0]


async def test_i_on_installed_cli_toasts_already_installed(
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
        assert pane.check_action("install", ()) is True
        pane.action_install()
        await page.pause()
        assert messages == [("Claude Code is already installed.", "information")]
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


async def test_i_while_install_plan_worker_runs_is_ignored(
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
    plan = AgentCliInstallsPlanned(entries=(_npm_entry(statuses["qwen"]),))
    _stub_install_plan(monkeypatch, plan)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._agent_cli_install_plan_worker = object()  # type: ignore[assignment]
        assert "↓ preparing install preview…" in pane._hints()
        _highlight_row(pane, "cli:qwen")
        pane.action_install()
        await page.pause()
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


# -- preview routing, cleanup, and execution ---------------------------------


async def test_install_unknown_name_toasts_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    _stub_install_plan(
        monkeypatch,
        AgentCliUnknownName(query="nope", known_names=("qwen",), suggestions=()),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight_row(pane, "cli:qwen")
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        assert messages == [("Unknown agent CLI: nope", "error")]
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


async def test_install_all_skipped_toasts_reasons_and_cleans_up(
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
    cleaned: list[bool] = []
    plan = AgentCliInstallsPlanned(
        entries=(_skip_entry(statuses["qwen"], "npm is not on PATH"),)
    )
    original_cleanup = AgentCliInstallsPlanned.cleanup

    def _spy_cleanup(self: AgentCliInstallsPlanned) -> None:
        cleaned.append(True)
        original_cleanup(self)

    monkeypatch.setattr(AgentCliInstallsPlanned, "cleanup", _spy_cleanup)
    _stub_install_plan(monkeypatch, plan)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight_row(pane, "cli:qwen")
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        assert cleaned == [True]
        assert messages[0][1] == "warning"
        assert "npm is not on PATH" in messages[0][0]
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"
        hints = pane.query_one("#updates-hints", Static).render()
        assert "preparing install preview" not in str(hints)


async def test_install_cancel_cleans_up_fetched_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    script = _make_script(tmp_path)
    plan = AgentCliInstallsPlanned(entries=(_script_entry(statuses["muse"], script),))
    _stub_install_plan(monkeypatch, plan)
    submitted: list[Any] = []
    monkeypatch.setattr(
        pbp, "_execute_agent_cli_installs", lambda *a, **k: submitted.append(1)
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:muse")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        assert script.path.exists()
        await page.press("n")
        await page.expect_modal("ConfigCenterModal")
        assert not script.path.exists()
        assert submitted == []


async def test_install_dedup_rejection_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    script = _make_script(tmp_path)
    plan = AgentCliInstallsPlanned(entries=(_script_entry(statuses["muse"], script),))
    _stub_install_plan(monkeypatch, plan)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:muse")
        monkeypatch.setattr(page.app, "_submit_session_worker", lambda *a, **k: None)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        assert not script.path.exists()


async def test_install_task_uses_admin_center_trigger_and_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    script = _make_script(tmp_path)
    plan = AgentCliInstallsPlanned(
        entries=(
            _npm_entry(statuses["qwen"]),
            _script_entry(statuses["muse"], script),
        )
    )
    _stub_install_plan(monkeypatch, plan)
    calls: dict[str, Any] = {}

    def _execute(
        executed_plan: AgentCliInstallsPlanned, **kwargs: Any
    ) -> tuple[AgentCliUpdateResult, ...]:
        calls["plan"] = executed_plan
        calls.update(kwargs)
        kwargs["progress_fn"](1, 2, executed_plan.entries[0])
        kwargs["progress_fn"](2, 2, executed_plan.entries[1])
        return (
            _install_result(
                "qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True
            ),
            _install_result(
                "muse",
                "Muse Code",
                UpdateResultStatus.UPDATED,
                new_version="1.3.0-R3401.1",
                on_path=True,
            ),
        )

    monkeypatch.setattr(pbp, "_execute_agent_cli_installs", _execute)
    submitted: dict[str, Any] = {}

    def submit(*args: Any, **kwargs: Any) -> object:
        assert_session_worker_submit_signature(args, kwargs)
        submitted["args"] = args
        submitted.update(kwargs)
        return object()

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:qwen")
        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        assert submitted["args"][0] == "agent-cli-install"
        assert submitted["dedup_key"] == "agent-cli-install"
        assert submitted["exclusive_scopes"] == ("agent-cli-update",)
        assert (
            submitted["duplicate_message"]
            == "An agent CLI install or update is already running."
        )

        reporter = _FakeReporter()
        outcome = submitted["args"][1](reporter)
        assert outcome.success is True
        assert calls["plan"] is plan
        assert calls["trigger"] is UpdateTrigger.ADMIN_CENTER
        assert reporter.phases == [
            "Installing agent CLIs",
            "Installing Qwen Code (1/2)",
            "Installing Muse Code (2/2)",
        ]
        assert reporter.sections == ["Results"]
        assert [stream for stream, _text in reporter.logs] == ["result", "result"]
        assert "installed 0.8.0" in reporter.logs[0][1]
        assert not script.path.exists()


async def test_install_task_failure_reports_unsuccessful(
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
    plan = AgentCliInstallsPlanned(entries=(_npm_entry(statuses["qwen"]),))
    _stub_install_plan(monkeypatch, plan)
    failure = _install_result(
        "qwen", "Qwen Code", UpdateResultStatus.FAILED, reason="boom"
    )
    monkeypatch.setattr(pbp, "_execute_agent_cli_installs", lambda *a, **k: (failure,))
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "cli:qwen")

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
        assert outcome.success is False
        assert outcome.payload == (failure,)
        assert outcome.error is not None


async def test_install_complete_clears_marks_toasts_and_reloads(
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
        pane._marked.update({"cli:qwen", "cli:muse"})
        reloads: list[bool] = []
        monkeypatch.setattr(pane, "_start_load", lambda *, force: reloads.append(force))
        results = (
            _install_result(
                "qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True
            ),
            _install_result(
                "muse",
                "Muse Code",
                UpdateResultStatus.UPDATED,
                new_version="1.3.0-R3401.1",
                on_path=True,
            ),
        )
        pane._on_agent_cli_install_complete(
            SimpleNamespace(payload=results, message="done", success=True)
        )
        assert pane._agent_cli_results["qwen"] == results[0]
        assert pane._marked == set()
        assert messages == [
            ("Installed Qwen Code 0.8.0 · Muse Code 1.3.0-R3401.1", "information")
        ]
        assert reloads == [False]


async def test_install_complete_off_path_warns_with_export_line(
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
        monkeypatch.setattr(pane, "_start_load", lambda *, force: None)
        pane._on_agent_cli_install_complete(
            SimpleNamespace(
                payload=(
                    _install_result(
                        "qwen",
                        "Qwen Code",
                        UpdateResultStatus.UPDATED,
                        on_path=False,
                    ),
                ),
                message="done",
                success=True,
            )
        )
        assert messages and messages[0][1] == "warning"
        assert 'export PATH="/home/dev/.npm-global/bin:$PATH"' in messages[0][0]
        assert "not on PATH" in pane._row_text(pane._rows_by_key["cli:qwen"]).plain


# -- bulk marks --------------------------------------------------------------


async def test_bulk_mark_then_i_installs_marked_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    statuses = _by_name()
    script = _make_script(tmp_path)
    plan = AgentCliInstallsPlanned(
        entries=(
            _npm_entry(statuses["qwen"]),
            _script_entry(statuses["muse"], script),
        )
    )
    requested = _stub_install_plan(monkeypatch, plan)
    results = (
        _install_result("qwen", "Qwen Code", UpdateResultStatus.UPDATED, on_path=True),
        _install_result(
            "muse",
            "Muse Code",
            UpdateResultStatus.UPDATED,
            new_version="1.3.0-R3401.1",
            on_path=True,
        ),
    )
    monkeypatch.setattr(pbp, "_execute_agent_cli_installs", lambda *a, **k: results)
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight_row(pane, "cli:qwen")
        pane.action_toggle_mark()
        _highlight_row(pane, "cli:muse")
        pane.action_toggle_mark()
        assert pane._marked == {"cli:qwen", "cli:muse"}
        assert "Marked: 2 CLI installs" in pane._hints()

        def submit(*args: Any, **kwargs: Any) -> object:
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        assert requested == [("muse", "qwen")] or requested == [("qwen", "muse")]
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert str(modal._title) == "Install 2 agent CLIs"
        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        submitted["on_complete"](
            SimpleNamespace(payload=results, message="done", success=True)
        )
        assert pane._marked == set()
        assert messages and "Installed Qwen Code" in messages[0][0]
