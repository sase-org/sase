"""Tests for shared SASE update-status aggregation and caching."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import subprocess
from pathlib import Path

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.latest_cache import CachedLatest
from sase.updates import (
    DEFAULT_UPDATE_STATUS_TTL_SECONDS,
    OutdatedComponent,
    ProviderUpdateCandidate,
    SCHEMA_VERSION,
    UpdateSourceStatus,
    UpdateStatus,
    build_update_status,
    compute_update_status,
    get_cached_update_status,
    merge_update_status,
    provider_update_candidates,
    read_update_status_snapshot,
    revalidate_provider_candidates,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
    write_update_status_snapshot,
)
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from sase.version._git import GitUpstreamStatus


def _core_versions(*, update: bool = True) -> CoreVersions:
    return CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="1.0.0",
                latest_version="1.1.0" if update else "1.0.0",
                latest_checked=True,
                update_available=update,
            ),
            CorePackageVersion(
                name="sase-core",
                distribution_name="sase-core-rs",
                installed_version="2.0.0",
                latest_version="2.0.0",
                latest_checked=True,
                update_available=False,
            ),
        )
    )


def _entry(
    name: str,
    *,
    installed: InstalledInfo,
    latest: LatestInfo,
) -> PluginCatalogEntry:
    repo = f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"sase-org/{repo}",
        owner="sase-org",
        description="",
        url=f"https://github.com/sase-org/{repo}",
        homepage="",
        topics=(),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="2026-06-01",
        installed=installed,
        latest=latest,
    )


def _catalog(*, plugin_update: bool = True) -> PluginCatalog:
    github = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(
            checked=True,
            version="0.6.0" if plugin_update else "0.5.0",
            source="index",
        ),
    )
    nvim = _entry(
        "nvim",
        installed=InstalledInfo.not_installed(),
        latest=LatestInfo(checked=True, version="1.0.0", source="index"),
    )
    return PluginCatalog(
        fetched_at=1_700_000_000.0,
        entries=(github, nvim),
        from_cache=True,
        stale=False,
    )


def _git_status(
    *,
    ahead: int | None,
    behind: int | None,
    dirty: bool = False,
    detached: bool = False,
    upstream: str | None = "origin/main",
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root="/repo",
        upstream=upstream,
        remote="origin" if upstream else None,
        remote_branch="main" if upstream else None,
        detached=detached,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def _agent_cli_status(
    name: str,
    *,
    installed_version: str | None = "1.0.0",
    latest_version: str | None = "1.1.0",
    installed: bool = True,
    update_available: bool = True,
    version_error: str | None = None,
    install_method: InstallMethod | None = None,
    npm_root_writable: bool | None = None,
) -> AgentCliStatus:
    return AgentCliStatus(
        name=name,
        display_name=f"{name.title()} CLI",
        binary=name,
        executable=f"/bin/{name}" if installed else None,
        installed_version=installed_version,
        latest_version=latest_version,
        install_method=install_method
        or (InstallMethod.NPM if installed else InstallMethod.NOT_INSTALLED),
        update_available=update_available,
        docs_url=None,
        install_hint=f"install {name}",
        package=f"@example/{name}",
        npm_root_writable=npm_root_writable,
        version_error=version_error,
    )


def test_compute_update_status_reports_core_and_installed_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_collect_installed_core_versions",
        lambda: _core_versions(update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: _core_versions(update=True),
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: _catalog(plugin_update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: _catalog(plugin_update=True),
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
    core_versions = CoreVersions(
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

    result = build_update_status(core_versions, _catalog(plugin_update=True), now=123.0)

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

    core_versions = CoreVersions(
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
    plugin_catalog = PluginCatalog(
        fetched_at=1_700_000_000.0,
        entries=(
            _entry(
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
        lambda: core_versions,
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: versions,
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: plugin_catalog,
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
        lambda **_kwargs: _catalog(plugin_update=True),
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
        lambda: _core_versions(update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: versions,
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: _catalog(plugin_update=False),
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
            _agent_cli_status("claude"),
            _agent_cli_status("codex", update_available=False),
            _agent_cli_status("qwen", installed=False, update_available=False),
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


def test_update_status_snapshot_round_trip_and_freshness(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
        ),
        provider_candidates=(
            ProviderUpdateCandidate(
                provider="claude",
                display_name="Claude Code",
                installed_version="1.0.0",
                latest_version="1.1.0",
                manual_only=True,
            ),
        ),
        core_source=UpdateSourceStatus.success(90.0),
        plugin_source=UpdateSourceStatus(checked_at=80.0, error="registry down"),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )

    write_update_status_snapshot(status, path=path)

    assert read_update_status_snapshot(path=path) == status
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 4
    assert envelope["provider_candidates"][0]["manual_only"] is True
    assert update_status_snapshot_is_fresh(status, now=110.0, ttl_seconds=20)
    assert not update_status_snapshot_is_fresh(status, now=130.0, ttl_seconds=20)


def test_previous_update_status_schema_is_treated_as_cache_miss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION - 1,
                "checked_at": 100.0,
                "components": [
                    {
                        "display_name": "sase",
                        "role": "host",
                        "installed_version": "1.0.0",
                        "latest_version": "1.1.0",
                        "distribution_name": "sase",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert read_update_status_snapshot(path=path) is None


def test_provider_candidate_projection_marks_only_manual_plans() -> None:
    candidates = provider_update_candidates(
        (
            _agent_cli_status("claude"),
            _agent_cli_status("codex", install_method=InstallMethod.HOMEBREW),
            _agent_cli_status("qwen", npm_root_writable=False),
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


def test_update_status_snapshot_rejects_partially_invalid_rows(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        core_source=UpdateSourceStatus.success(100.0),
        plugin_source=UpdateSourceStatus.success(100.0),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )
    write_update_status_snapshot(status, path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["components"] = [{"display_name": "partial"}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_update_status_snapshot(path=path) is None


def test_merge_update_status_replaces_success_and_preserves_failed_sources() -> None:
    old_core = OutdatedComponent("sase", "host", "1", "2", "sase")
    old_plugin = OutdatedComponent("github", "plugin", "1", "2", "sase-github")
    old_provider = ProviderUpdateCandidate("claude", "Claude", "1", "2")
    previous = UpdateStatus(
        checked_at=100.0,
        components=(old_core, old_plugin),
        provider_candidates=(old_provider,),
        core_source=UpdateSourceStatus.success(100.0),
        plugin_source=UpdateSourceStatus.success(90.0),
        agent_cli_source=UpdateSourceStatus.success(80.0),
    )
    current_provider = ProviderUpdateCandidate("codex", "Codex", "3", "4")
    current = UpdateStatus(
        checked_at=200.0,
        components=(),
        provider_candidates=(current_provider,),
        core_source=UpdateSourceStatus.success(200.0),
        plugin_source=UpdateSourceStatus.failure("github unavailable"),
        agent_cli_source=UpdateSourceStatus.failure("npm unavailable"),
    )

    merged = merge_update_status(previous, current)

    assert merged.components == (old_plugin,)
    assert merged.provider_candidates == (old_provider,)
    assert merged.core_source == UpdateSourceStatus.success(200.0)
    assert merged.plugin_source == UpdateSourceStatus(
        checked_at=90.0,
        error="github unavailable",
    )
    assert merged.agent_cli_source == UpdateSourceStatus(
        checked_at=80.0,
        error="npm unavailable",
    )


def test_merge_update_status_successful_empty_is_not_unknown() -> None:
    previous = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(ProviderUpdateCandidate("claude", "Claude", "1", "2"),),
        agent_cli_source=UpdateSourceStatus.success(100.0),
    )
    successful_empty = UpdateStatus(
        checked_at=200.0,
        components=(),
        agent_cli_source=UpdateSourceStatus.success(200.0),
    )

    merged = merge_update_status(previous, successful_empty)

    assert merged.provider_candidates == ()
    assert merged.agent_cli_source == UpdateSourceStatus.success(200.0)


def test_revalidate_update_status_drops_components_updated_locally() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )

    def _version(dist_name: str) -> str:
        if dist_name == "sase":
            return "1.1.0"
        if dist_name == "sase-github":
            return "0.5.0"
        raise importlib_metadata.PackageNotFoundError(dist_name)

    result = revalidate_update_status(status, version_fn=_version)

    assert [component.display_name for component in result.components] == ["github"]


def test_revalidate_provider_candidates_zero_candidates_does_no_work() -> None:
    def _status_fn(_names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        raise AssertionError("zero candidates must not inspect provider metadata")

    assert revalidate_provider_candidates((), status_fn=_status_fn) == ()


def test_revalidate_provider_candidates_is_named_drop_only_and_conservative() -> None:
    candidates = (
        ProviderUpdateCandidate("claude", "Claude", "1.0.0", "2.0.0"),
        ProviderUpdateCandidate("codex", "Codex", "1.0.0", "2.0.0"),
        ProviderUpdateCandidate("qwen", "Qwen", "1.0.0", "2.0.0"),
    )
    calls: list[tuple[str, ...]] = []

    def _status_fn(names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        calls.append(names)
        return (
            _agent_cli_status(
                "claude",
                installed_version=None,
                version_error="timed out",
            ),
            _agent_cli_status("codex", installed_version="2.0.0"),
            _agent_cli_status("new-provider"),
        )

    result = revalidate_provider_candidates(candidates, status_fn=_status_fn)

    assert calls == [("claude", "codex", "qwen")]
    assert result == (candidates[0],)


def test_revalidate_provider_candidates_refreshes_manual_projection() -> None:
    candidate = ProviderUpdateCandidate("codex", "Codex", "1.0.0", "2.0.0")

    result = revalidate_provider_candidates(
        (candidate,),
        status_fn=lambda _names: (
            _agent_cli_status(
                "codex",
                installed_version="1.1.0",
                install_method=InstallMethod.HOMEBREW,
            ),
        ),
    )

    assert result == (
        ProviderUpdateCandidate(
            "codex",
            "Codex",
            "1.1.0",
            "2.0.0",
            manual_only=True,
        ),
    )


@pytest.mark.parametrize(
    ("git_status", "expected_names"),
    [
        (_git_status(ahead=0, behind=2), ["sase", "github"]),
        (_git_status(ahead=0, behind=0), ["github"]),
        (_git_status(ahead=2, behind=0), ["github"]),
        (_git_status(ahead=1, behind=2), ["github"]),
        (_git_status(ahead=0, behind=2, dirty=True), ["github"]),
    ],
)
def test_revalidate_update_status_uses_git_for_editable_components(
    git_status: GitUpstreamStatus,
    expected_names: list[str],
) -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0+local",
                latest_version="1.0.0+abc123",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
                install_type="wheel",
            ),
        ),
    )

    def _version(dist_name: str) -> str:
        if dist_name == "sase":
            raise AssertionError("editable revalidation must not compare versions")
        if dist_name == "sase-github":
            return "0.5.0"
        raise importlib_metadata.PackageNotFoundError(dist_name)

    result = revalidate_update_status(
        status,
        version_fn=_version,
        git_classifier_fn=lambda _path: git_status,
    )

    assert [component.display_name for component in result.components] == expected_names


def test_revalidate_update_status_keeps_editable_component_on_git_error() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0+local",
                latest_version="1.0.0+abc123",
                distribution_name="sase",
                install_type="editable",
                source_root="/src/sase",
                upstream_ref="origin/main",
            ),
        ),
    )

    def _raise(_path: Path) -> GitUpstreamStatus:
        raise subprocess.TimeoutExpired(["git"], timeout=1.0)

    result = revalidate_update_status(
        status,
        version_fn=lambda _dist: "1.0.0",
        git_classifier_fn=_raise,
    )

    assert result == status


def test_revalidate_update_status_keeps_component_on_transient_metadata_error() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )

    result = revalidate_update_status(
        status,
        version_fn=lambda _dist: (_ for _ in ()).throw(OSError("metadata busy")),
    )

    assert result == status


def test_get_cached_update_status_uses_fresh_snapshot_without_compute(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("fresh cache should not compute")

    result = get_cached_update_status(
        path=path,
        now=110.0,
        ttl_seconds=20,
        compute_fn=_compute,
        version_fn=lambda _dist_name: "0.5.0",
    )

    assert result == status


def test_get_cached_update_status_revalidate_only_uses_stale_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(checked_at=100.0, components=())
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("revalidate-only mode must never compute")

    result = get_cached_update_status(
        path=path,
        now=10_000.0,
        ttl_seconds=20.0,
        revalidate_only=True,
        compute_fn=_compute,
    )

    assert result == status


def test_ordinary_tick_revalidates_named_candidates_without_full_inventory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    candidate = ProviderUpdateCandidate("claude", "Claude Code", "1.0.0", "2.0.0")
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(candidate,),
    )
    write_update_status_snapshot(status, path=path)
    named_calls: list[tuple[str, ...]] = []

    def local_status(names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        named_calls.append(names)
        return (_agent_cli_status("claude", installed_version="1.1.0"),)

    result = get_cached_update_status(
        path=path,
        now=10_000.0,
        revalidate_only=True,
        compute_fn=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary ticks must not run full/network discovery")
        ),
        provider_status_fn=local_status,
    )

    assert result is not None
    assert result.provider_candidates == (
        ProviderUpdateCandidate(
            "claude",
            "Claude Code",
            "1.1.0",
            "2.0.0",
        ),
    )
    assert named_calls == [("claude",)]


def test_get_cached_update_status_revalidate_only_does_not_compute_on_miss(
    tmp_path: Path,
) -> None:
    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("revalidate-only mode must never compute")

    result = get_cached_update_status(
        path=tmp_path / "missing.json",
        revalidate_only=True,
        compute_fn=_compute,
    )

    assert result is None


def test_get_cached_update_status_falls_back_to_snapshot_on_compute_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(checked_at=100.0, components=())
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise RuntimeError("offline")

    result = get_cached_update_status(
        path=path,
        now=200.0,
        ttl_seconds=20,
        compute_fn=_compute,
    )

    assert result == status


def test_get_cached_update_status_full_compute_does_not_redetect_providers(
    tmp_path: Path,
) -> None:
    status = UpdateStatus(
        checked_at=200.0,
        components=(),
        provider_candidates=(
            ProviderUpdateCandidate("claude", "Claude", "1.0.0", "2.0.0"),
        ),
        core_source=UpdateSourceStatus.success(200.0),
        plugin_source=UpdateSourceStatus.success(200.0),
        agent_cli_source=UpdateSourceStatus.success(200.0),
    )

    result = get_cached_update_status(
        path=tmp_path / "status.json",
        now=200.0,
        compute_fn=lambda **_kwargs: status,
        provider_status_fn=lambda _names: (_ for _ in ()).throw(
            AssertionError("a full inventory is already locally validated")
        ),
    )

    assert result == status


def test_default_update_status_ttl_is_ten_minutes() -> None:
    assert DEFAULT_UPDATE_STATUS_TTL_SECONDS == 600


def test_update_status_snapshot_freshness_uses_default_ttl() -> None:
    status = UpdateStatus(checked_at=0.0, components=())
    future_status = UpdateStatus(checked_at=601.0, components=())

    assert update_status_snapshot_is_fresh(status, now=599.0)
    assert not update_status_snapshot_is_fresh(status, now=600.0)
    assert not update_status_snapshot_is_fresh(status, now=601.0)
    assert not update_status_snapshot_is_fresh(future_status, now=600.0)


def test_cached_core_fetch_uses_fresh_latest_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_read_latest_cache",
        lambda: {"sase": CachedLatest(version="1.1.0", fetched_at=100.0)},
    )

    def _no_fetch(_dist_name: str) -> str | None:
        raise AssertionError("a fresh latest-version cache must not hit PyPI")

    monkeypatch.setattr(status_module, "_fetch_latest_version", _no_fetch)

    fetch = status_module._make_cached_core_fetch_fn(now=120.0)

    assert fetch("sase") == "1.1.0"


def test_cached_core_fetch_writes_through_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(status_module, "_read_latest_cache", dict)
    monkeypatch.setattr(status_module, "_fetch_latest_version", lambda _d: "2.0.0")
    written: dict[str, CachedLatest] = {}
    monkeypatch.setattr(
        status_module, "_write_latest_cache", lambda cache: written.update(cache)
    )

    fetch = status_module._make_cached_core_fetch_fn(now=500.0)

    assert fetch("sase-core-rs") == "2.0.0"
    assert written == {"sase-core-rs": CachedLatest(version="2.0.0", fetched_at=500.0)}
