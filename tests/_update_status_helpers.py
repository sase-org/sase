"""Shared factories for update-status tests."""

from __future__ import annotations

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from sase.version._git import GitUpstreamStatus


def core_versions(*, update: bool = True) -> CoreVersions:
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


def plugin_entry(
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


def plugin_catalog(*, plugin_update: bool = True) -> PluginCatalog:
    github = plugin_entry(
        "github",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(
            checked=True,
            version="0.6.0" if plugin_update else "0.5.0",
            source="index",
        ),
    )
    nvim = plugin_entry(
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


def git_status(
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


def agent_cli_status(
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
