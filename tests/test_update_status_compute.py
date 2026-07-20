"""Tests for update-status aggregation and provider projection."""

from __future__ import annotations

from typing import Literal

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.updates import (
    OutdatedComponent,
    ProviderUpdateCandidate,
    UpdateSourceStatus,
    UpdateStatus,
    build_update_status,
    compute_update_status,
    provider_update_candidates,
)
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from tests._update_status_helpers import (
    agent_cli_status,
    core_versions,
    plugin_catalog,
    plugin_entry,
)

ComponentRole = Literal["host", "core", "plugin"]


def test_compute_update_status_reports_core_and_installed_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_collect_installed_core_versions",
        lambda: core_versions(update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: core_versions(update=True),
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: plugin_catalog(plugin_update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: plugin_catalog(plugin_update=True),
    )
    monkeypatch.setattr(
        status_module, "_collect_agent_cli_statuses", lambda **_kwargs: ()
    )

    result = compute_update_status(now=123.0)

    assert result.checked_at == 123.0
    assert [(c.display_name, c.role) for c in result.components] == [
        ("sase", "host"),
        ("github", "plugin"),
    ]
    assert result.count == 2
    assert result.component_count == 2
    assert result.agent_cli_count == 0
    assert result.core_source == UpdateSourceStatus.success(123.0)
    assert result.plugin_source == UpdateSourceStatus.success(123.0)
    assert result.agent_cli_source == UpdateSourceStatus.success(123.0)


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((), False),
        (("host",), False),
        (("plugin",), False),
        (("core",), True),
        (("host", "core", "plugin"), True),
    ],
)
def test_update_status_has_core_update(
    roles: tuple[ComponentRole, ...],
    expected: bool,
) -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=tuple(
            OutdatedComponent(
                display_name=f"component-{index}",
                role=role,
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name=f"component-{index}",
            )
            for index, role in enumerate(roles)
        ),
    )

    assert status.has_core_update is expected


def test_build_update_status_reuses_enriched_panel_inventory() -> None:
    versions = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="1.0.0",
                latest_version="1.1.0",
                latest_checked=True,
                update_available=True,
            ),
            CorePackageVersion(
                name="sase-core",
                distribution_name="sase-core-rs",
                installed_version="2.0.0",
                latest_version="2.1.0",
                latest_checked=True,
                update_available=True,
            ),
        )
    )

    result = build_update_status(
        versions, plugin_catalog(plugin_update=True), now=123.0
    )

    assert result.checked_at == 123.0
    assert [
        (component.display_name, component.role) for component in result.components
    ] == [
        ("sase", "host"),
        ("sase-core", "core"),
        ("github", "plugin"),
    ]
    assert result.has_core_update is True


def test_compute_update_status_carries_install_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    versions = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="1.0.0+local",
                latest_version="1.0.0+abc123",
                latest_checked=True,
                update_available=True,
                install_type="editable",
                git_root="/src/sase",
                upstream_ref="origin/main",
            ),
        )
    )
    catalog = PluginCatalog(
        fetched_at=1_700_000_000.0,
        entries=(
            plugin_entry(
                "github",
                installed=InstalledInfo(installed=True, version="0.5.0"),
                latest=LatestInfo(
                    checked=True,
                    version="0.5.0+abc123",
                    source="editable",
                    install_type="editable",
                    current_version="0.5.0+local",
                    update_available=True,
                    git_root="/src/sase-github",
                    upstream_ref="origin/main",
                ),
            ),
        ),
        from_cache=True,
        stale=False,
    )

    monkeypatch.setattr(
        status_module,
        "_collect_installed_core_versions",
        lambda: versions,
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: versions,
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: catalog,
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: catalog,
    )
    monkeypatch.setattr(
        status_module, "_collect_agent_cli_statuses", lambda **_kwargs: ()
    )

    result = compute_update_status(now=123.0)

    by_name = {component.display_name: component for component in result.components}
    assert by_name["sase"].install_type == "editable"
    assert by_name["sase"].source_root == "/src/sase"
    assert by_name["sase"].upstream_ref == "origin/main"
    assert by_name["github"].install_type == "editable"
    assert by_name["github"].source_root == "/src/sase-github"
    assert by_name["github"].upstream_ref == "origin/main"


def test_compute_update_status_sources_degrade_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    def _raise_core() -> CoreVersions:
        raise RuntimeError("core unavailable")

    monkeypatch.setattr(status_module, "_collect_installed_core_versions", _raise_core)
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: plugin_catalog(plugin_update=True),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: catalog,
    )
    monkeypatch.setattr(
        status_module, "_collect_agent_cli_statuses", lambda **_kwargs: ()
    )

    result = compute_update_status(now=123.0)

    assert [(c.display_name, c.role) for c in result.components] == [
        ("github", "plugin")
    ]
    assert result.core_source.error == "core unavailable"
    assert result.core_source.checked_at is None
    assert result.plugin_source == UpdateSourceStatus.success(123.0)


def test_compute_update_status_discovers_only_installed_outdated_provider_clis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_collect_installed_core_versions",
        lambda: core_versions(update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: versions,
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: plugin_catalog(plugin_update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: catalog,
    )
    calls: list[dict[str, object]] = []

    def _collect(**kwargs: object) -> tuple[AgentCliStatus, ...]:
        calls.append(kwargs)
        return (
            agent_cli_status("claude"),
            agent_cli_status("codex", update_available=False),
            agent_cli_status("qwen", installed=False, update_available=False),
        )

    monkeypatch.setattr(status_module, "_collect_agent_cli_statuses", _collect)

    result = compute_update_status(refresh=True, now=123.0)

    assert calls == [{"refresh": True, "offline": False}]
    assert result.provider_candidates == (
        ProviderUpdateCandidate("claude", "Claude CLI", "1.0.0", "1.1.0"),
    )
    assert result.component_count == 0
    assert result.agent_cli_count == 1
    assert result.manual_agent_cli_count == 0
    assert result.count == 1
    assert result.has_agent_cli_updates is True


def test_provider_candidate_projection_marks_only_manual_plans() -> None:
    candidates = provider_update_candidates(
        (
            agent_cli_status("claude"),
            agent_cli_status("codex", install_method=InstallMethod.HOMEBREW),
            agent_cli_status("qwen", npm_root_writable=False),
        )
    )

    assert [
        (candidate.provider, candidate.manual_only) for candidate in candidates
    ] == [
        ("claude", False),
        ("codex", True),
        ("qwen", True),
    ]
    assert (
        UpdateStatus(
            checked_at=1.0,
            components=(),
            provider_candidates=candidates,
        ).manual_agent_cli_count
        == 2
    )
