"""Snapshot-gated comprehensive Updates-pane flow tests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_comprehensive_update import (
    ComprehensiveUpdateActionsMixin,
    ComprehensiveUpdateRequest,
    _ComprehensiveUpdatePreview,
    _plan_captured_providers,
    _provider_preview_section,
    _sase_preview_section,
)
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliUpdatesReady,
    UpdateStrategy,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)


def test_provider_plan_intersects_capture_without_broadening() -> None:
    statuses = _agent_cli_statuses()

    plan, dropped, error = _plan_captured_providers(
        ("claude", "removed"),
        statuses,
        offline=False,
    )

    assert error is None
    assert isinstance(plan, AgentCliUpdatesReady)
    assert [entry.name for entry in plan.entries] == ["claude"]
    assert plan.entries[0].argv == ("/home/dev/.local/bin/claude", "update")
    assert plan.entries[0].status.docs_url == ("https://code.claude.com/docs/en/setup")
    assert [item.name for item in dropped] == ["removed"]
    assert "codex" not in {entry.name for entry in plan.entries}


def test_provider_revalidation_keeps_current_and_manual_outcomes() -> None:
    claude, codex, _qwen = _agent_cli_statuses()
    current_claude = replace(
        claude,
        latest_version=claude.installed_version,
        update_available=False,
    )

    plan, dropped, error = _plan_captured_providers(
        ("claude", "codex"),
        (current_claude, codex),
        offline=False,
    )

    assert error is None
    assert dropped == ()
    assert isinstance(plan, AgentCliNothingToUpdate)
    current, manual = plan.entries
    assert current.skip_reason and "already up to date" in current.skip_reason
    assert manual.strategy is UpdateStrategy.MANUAL
    assert manual.manual_argv == ("brew", "upgrade", "codex")
    assert manual.skip_reason and "developers.openai.com" in manual.skip_reason


def test_provider_inventory_failure_does_not_claim_candidates_were_removed() -> None:
    plan, dropped, error = _plan_captured_providers(
        ("claude",),
        (),
        offline=False,
        source_error="registry unavailable",
    )

    assert isinstance(plan, AgentCliNothingToUpdate)
    assert dropped == ()
    assert error == "provider inventory unavailable: registry unavailable"


def test_comprehensive_preview_has_separate_exact_sections() -> None:
    statuses = _agent_cli_statuses()
    provider_plan, dropped, error = _plan_captured_providers(
        ("claude", "removed"),
        statuses,
        offline=False,
    )
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude", "removed")),
        sase_preview=pbp._DevUpdatePreview(plan=None, subject="sase"),
        provider_plan=provider_plan,
        provider_dropped=dropped,
        provider_error=error,
    )

    sase = _sase_preview_section(preview)
    providers = _provider_preview_section(preview)

    assert sase.title == "SASE, core & plugins"
    assert sase.commands == ("uv tool upgrade --color never sase",)
    assert providers.title == "Agent CLIs"
    assert providers.commands == ("Claude Code: /home/dev/.local/bin/claude update",)
    assert any("Claude Code documentation" in item for item in providers.details)
    assert any("removed: no longer present" in item for item in providers.skipped)


def test_sase_blocker_does_not_suppress_runnable_provider_plan() -> None:
    provider_plan, dropped, error = _plan_captured_providers(
        ("claude",),
        _agent_cli_statuses(),
        offline=False,
    )
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=None,
        sase_blocker="SASE install is blocked",
        provider_plan=provider_plan,
        provider_dropped=dropped,
        provider_error=error,
    )

    assert preview.sase_runnable is False
    assert preview.provider_runnable is True
    assert preview.runnable is True


class _Reporter:
    def phase(self, _label: str) -> None:
        pass

    def section(self, _title: str) -> None:
        pass

    def log(self, _text: str, *, stream: str = "stdout") -> None:
        del stream


class _SubmitApp:
    def __init__(self) -> None:
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None

    def _submit_tracked_task(self, *args: Any, **kwargs: Any) -> object:
        self.submitted = (args, kwargs)
        return object()


class _ExecutionHarness(ComprehensiveUpdateActionsMixin):
    def __init__(self) -> None:
        self.app = _SubmitApp()
        self.order: list[str] = []

    def _execute_provider_leg(
        self, _preview: Any, _reporter: Any
    ) -> tuple[tuple[Any, ...], str | None]:
        self.order.append("providers")
        return (), "provider failed"

    def _execute_comprehensive_sase_leg(
        self, _preview: Any, _reporter: Any
    ) -> ComprehensiveSaseUpdateResult:
        self.order.append("sase")
        return ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        )

    def _on_comprehensive_update_complete(self, _completion: Any) -> None:
        pass


def test_comprehensive_task_claims_both_scopes_and_continues_after_provider_failure() -> (
    None
):
    harness = _ExecutionHarness()
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=pbp._DevUpdatePreview(plan=None, subject="sase"),
    )

    assert harness._submit_comprehensive_update_task(preview) is True
    assert harness.app.submitted is not None
    args, kwargs = harness.app.submitted
    assert kwargs["exclusive_scopes"] == ("sase-update", "agent-cli-update")
    assert kwargs["dedup_key"] == "comprehensive-update"

    task_result = args[3](_Reporter())
    assert harness.order == ["providers", "sase"]
    assert task_result.success is False
    assert task_result.payload is not None
    assert task_result.payload.provider_error == "provider failed"


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
        sections = confirm._variants[0].sections
        assert [section.title for section in sections] == [
            "SASE, core & plugins",
            "Agent CLIs",
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
