"""Confirmation-modal tests for comprehensive Updates-pane flows."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_comprehensive_update import (
    _ComprehensiveUpdatePreview,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _all_current_catalog,
    _catalog,
    _patch_catalog,
    _patch_other_panes,
    _render,
    _uv_tool,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import _dev_plan


async def test_config_center_handoff_confirms_only_captured_live_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: pbp._DevUpdatePreview(
            plan=None,
            subject="sase",
        ),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(
            initial_tab="updates",
            auto_update=True,
            comprehensive_provider_names=("claude",),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")

        confirm = page.app.screen
        assert isinstance(confirm, PluginActionConfirmModal)
        assert confirm._incoming_commits_loader is not None
        sections = confirm._variants[0].sections
        assert [section.title for section in sections] == [
            "SASE, core & plugins",
            "Agent CLIs",
            "Cached agent hoods",
        ]
        assert sections[1].commands == (
            "Claude Code: /home/dev/.local/bin/claude update",
        )
        assert "Codex CLI" not in " ".join(sections[1].commands)

        confirm.action_cancel()
        await page.expect_modal("ConfigCenterModal")
        pane = modal.query_one("#updates")
        assert pane._comprehensive_update_request is None
        assert pane._starting_comprehensive_request is None


async def test_comprehensive_confirmation_submits_same_captured_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )
    sase_preview = pbp._DevUpdatePreview(plan=_dev_plan(), subject="sase")
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: sase_preview,
    )

    async with AcePage() as page:
        admin = ConfigCenterModal(
            initial_tab="updates",
            auto_update=True,
            comprehensive_provider_names=("claude",),
        )
        page.app.push_screen(admin)
        await page.expect_modal("PluginActionConfirmModal")
        confirm = page.app.screen
        assert isinstance(confirm, PluginActionConfirmModal)
        pane = admin.query_one("#updates")
        submitted: list[_ComprehensiveUpdatePreview] = []
        monkeypatch.setattr(
            pane,
            "_submit_comprehensive_update_task",
            lambda preview: submitted.append(preview) or True,
        )
        monkeypatch.setattr(
            pane,
            "_close_admin_center_after_sase_update",
            lambda: None,
        )

        confirm.action_confirm()
        await page.wait_for(lambda _s: bool(submitted))
        assert submitted[0].sase_preview is sase_preview
        assert submitted[0].request.provider_names == ("claude",)


async def test_provider_only_comprehensive_confirmation_explains_no_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        admin = ConfigCenterModal(
            initial_tab="updates",
            auto_update=True,
            comprehensive_provider_names=("claude",),
        )
        page.app.push_screen(admin)
        await page.expect_modal("PluginActionConfirmModal")

        confirm = page.app.screen
        assert isinstance(confirm, PluginActionConfirmModal)
        assert confirm._incoming_commits_loader is None
        assert confirm._incoming_commits_empty_message is not None
        await page.wait_for(
            lambda _s: len(confirm.query("#plugin-action-commits-body")) > 0
        )
        body = confirm.query_one("#plugin-action-commits-body")
        assert "Agent CLI installers" in _render(body.content)


async def test_comprehensive_confirmation_honors_disabled_commit_previews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )
    monkeypatch.setattr(
        pbp,
        "_load_incoming_commits_config",
        lambda: pbp._IncomingCommitsConfig(enabled=False),
    )
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: pbp._DevUpdatePreview(
            plan=None,
            subject="sase",
        ),
    )

    async with AcePage() as page:
        admin = ConfigCenterModal(
            initial_tab="updates",
            auto_update=True,
            comprehensive_provider_names=("claude",),
        )
        page.app.push_screen(admin)
        await page.expect_modal("PluginActionConfirmModal")

        confirm = page.app.screen
        assert isinstance(confirm, PluginActionConfirmModal)
        assert confirm._incoming_commits_loader is None
        assert confirm._incoming_commits_empty_message is None
        assert len(confirm.query("#plugin-action-commits")) == 0
