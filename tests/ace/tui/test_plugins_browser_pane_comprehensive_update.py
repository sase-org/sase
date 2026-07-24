"""Snapshot-gated comprehensive Updates-pane flow tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugins_browser_comprehensive_update import (
    ComprehensiveUpdateActionsMixin,
    ComprehensiveUpdateRequest,
    _agents_preview_section,
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
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
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
    _catalog,
    _core_versions,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import _dev_plan


def _incoming_core_versions() -> Any:
    return _core_versions(
        sase_installed="0.5.0",
        sase_latest="0.6.0",
        core_installed="0.4.0",
        core_latest="0.5.0",
    )


def _captured(
    project_key: str,
    project: str,
    hood: str,
    *,
    username: str = "alice",
    machine: str = "zeus",
    runs: int = 2,
    families: int = 1,
) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key=project_key,
        project=project,
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id=f"{project_key}-{hood}",
        format_version=2,
        source_owner_kind="exact",
        source_username=username,
        source_machine=machine,
        top_hood=hood,
        hood_digest="b" * 64,
        run_count=runs,
        family_count=families,
        cache_created_at=1.0,
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


def test_comprehensive_agents_preview_captures_exact_projects_and_hoods() -> None:
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=None,
        sase_current=True,
        agents_updates=(
            _captured("alpha", "Alpha", "foo"),
            _captured(
                "alpha",
                "Alpha",
                "bar",
                username="bob",
                machine="hera",
                runs=1,
                families=0,
            ),
            _captured("beta", "Beta", "baz", runs=3, families=2),
        ),
    )

    section = _agents_preview_section(preview)

    assert preview.agents_runnable is True
    assert preview.runnable is True
    assert section.title == "Agents repos"
    assert section.counts == ("2 projects", "3 hoods")
    assert section.summary == (
        "Imports 3 captured foreign hoods across 2 projects without network access."
    )
    assert [
        (component.name, component.detail, component.state)
        for component in section.components
    ] == [
        ("Alpha", "alice.zeus.foo · 2 runs · 1 family", "update"),
        ("Alpha", "bob.hera.bar · 1 run · 0 families", "update"),
        ("Beta", "alice.zeus.baz · 3 runs · 2 families", "update"),
    ]


def test_comprehensive_agents_preview_without_cache_items_is_noop() -> None:
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=None,
        sase_current=True,
    )

    assert preview.agents_runnable is False
    assert preview.runnable is False
    assert _agents_preview_section(preview).summary == (
        "No cached foreign agent hood updates were captured."
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


def test_comprehensive_preview_captures_no_network_agents_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    captured = _captured("alpha", "Alpha", "foo")
    snapshot = SyncStatusSnapshot(
        100.0,
        (
            ProjectSyncStatus(
                "alpha",
                "Alpha",
                "ready",
                pending_updates=(captured,),
            ),
        ),
    )

    def get_status(**kwargs: object) -> SyncStatusSnapshot:
        calls.append(dict(kwargs))
        return snapshot

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update.get_agents_sync_status",
        get_status,
    )

    class _PreviewHarness(ComprehensiveUpdateActionsMixin):
        def __init__(self) -> None:
            self._loading = False
            self._comprehensive_update_plan_worker = None
            self._agent_cli_statuses = ()
            self._agent_cli_error = None
            self._offline = False
            self._uv_tool = None
            self.worker: Any = None

        def _sase_up_to_date(self) -> bool:
            return True

        def run_worker(self, callback: Any, **_kwargs: object) -> object:
            self.worker = callback
            return object()

    harness = _PreviewHarness()
    harness._start_comprehensive_update_preview(ComprehensiveUpdateRequest(()))
    preview = harness.worker()

    assert calls == [{"revalidate_only": True}]
    assert preview.agents_updates == (captured,)
    assert preview.agents_runnable is True
