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
from sase.ace.tui.modals.plugins_browser_incoming import (
    _loaded_incoming_commit_seed,
    _sase_update_incoming_commit_sources,
)
from sase.agent_clis.models import (
    AgentCliNothingToUpdate,
    AgentCliUpdatesReady,
    UpdateStrategy,
)
from sase.uv_tool.render import PlannedPackage
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    core_package_commit_spec,
    plugin_entry_commit_spec,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _all_current_catalog,
    _catalog,
    _core_versions,
    _patch_catalog,
    _patch_other_panes,
    _render,
    _uv_tool,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import _dev_plan


def _incoming_core_versions() -> Any:
    return _core_versions(
        sase_installed="0.5.0",
        sase_latest="0.6.0",
        core_installed="0.4.0",
        core_latest="0.5.0",
    )


def test_comprehensive_managed_sources_use_loaded_updatable_set() -> None:
    preview = pbp._DevUpdatePreview(plan=None, subject="sase")

    sources = _sase_update_incoming_commit_sources(
        preview,
        core_versions=_incoming_core_versions(),
        catalog=_catalog(),
    )

    assert [label for label, _spec in sources] == ["sase", "sase-core", "github"]
    assert [(spec.base_ref, spec.head_ref) for _label, spec in sources] == [
        ("v0.5.0", "v0.6.0"),
        ("v0.4.0", "v0.5.0"),
        ("v1.2.0", "v1.3.0"),
    ]


def test_comprehensive_editable_sources_exclude_skipped_roots() -> None:
    actionable = _sase_update_incoming_commit_sources(
        pbp._DevUpdatePreview(plan=_dev_plan(), subject="sase"),
        core_versions=_incoming_core_versions(),
        catalog=_catalog(),
    )
    skipped = _sase_update_incoming_commit_sources(
        pbp._DevUpdatePreview(plan=_dev_plan(status="skipped"), subject="sase"),
        core_versions=_incoming_core_versions(),
        catalog=_catalog(),
    )

    assert [label for label, _spec in actionable] == ["github"]
    assert actionable[0][1].git_root == "/repo/sase-github"
    assert actionable[0][1].current_ref == "HEAD"
    assert actionable[0][1].upstream_ref == "origin/main"
    assert skipped == ()


def test_comprehensive_mixed_sources_are_exact_ordered_and_deduplicated() -> None:
    plan = _dev_plan()
    preview = pbp._DevUpdatePreview(
        plan=replace(plan, roots=(plan.roots[0], plan.roots[0])),
        subject="sase",
        managed_argv=("uv", "tool", "install", "--upgrade-package", "sase-core-rs"),
        managed_packages=(
            PlannedPackage(
                name="sase-core-rs",
                role="dependency",
                current_version="0.4.0",
            ),
        ),
    )

    sources = _sase_update_incoming_commit_sources(
        preview,
        core_versions=_incoming_core_versions(),
        catalog=_catalog(),
    )

    assert [label for label, _spec in sources] == ["github", "sase-core"]
    assert len({spec.cache_key for _label, spec in sources}) == 2


def test_comprehensive_sources_seed_loaded_core_and_plugin_snapshots() -> None:
    core_versions = _incoming_core_versions()
    catalog = _catalog()
    core_spec = core_package_commit_spec(core_versions.packages[0])
    plugin_spec = plugin_entry_commit_spec(catalog.entries[0])
    assert core_spec is not None
    assert plugin_spec is not None
    core_cached = IncomingCommits(
        total=1,
        commits=(CommitSummary("abc1234", "cached core"),),
        source="github",
    )
    plugin_cached = IncomingCommits(
        total=2,
        commits=(CommitSummary("def5678", "cached plugin"),),
        source="github",
    )

    seed = _loaded_incoming_commit_seed(
        core_versions=core_versions,
        core_incoming={"sase": core_cached},
        catalog=catalog,
        plugin_incoming={plugin_spec.cache_key: plugin_cached},
    )

    assert seed[core_spec.cache_key] is core_cached
    assert seed[plugin_spec.cache_key] is plugin_cached


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
    assert [
        (component.name, component.detail, component.state)
        for component in providers.components
    ] == [
        ("Claude Code", "1.0.0 → 1.1.0", "update"),
        (
            "removed",
            "no longer present in the live provider inventory",
            "skipped",
        ),
    ]


def test_comprehensive_sase_preview_leads_with_dev_components() -> None:
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=pbp._DevUpdatePreview(plan=_dev_plan(), subject="sase"),
    )

    section = _sase_preview_section(preview)

    assert [
        (component.name, component.detail, component.state)
        for component in section.components
    ] == [
        ("sase-github", "origin/main · 1 incoming commit", "update"),
        (
            "sase-github",
            "0.1.0+1.gabc123def → 0.1.0+2.gdef456abc",
            "update",
        ),
        ("Reinstall uv-tool editable Python packages", "reconcile step", "update"),
    ]
    assert section.counts == ("1 checkout", "1 step")


def test_comprehensive_provider_preview_marks_current_and_manual_rows() -> None:
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
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude", "codex")),
        sase_preview=pbp._DevUpdatePreview(plan=None, subject="sase"),
        provider_plan=plan,
        provider_dropped=dropped,
        provider_error=error,
    )

    section = _provider_preview_section(preview)
    states = {component.name: component.state for component in section.components}

    assert states == {"Claude Code": "current", "Codex CLI": "skipped"}
    assert any(
        component.name == "Claude Code" and "already up to date" in component.detail
        for component in section.components
    )
    assert any(
        component.name == "Codex CLI" and "developers.openai.com" in component.detail
        for component in section.components
    )


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
        assert confirm._incoming_commits_loader is not None
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
