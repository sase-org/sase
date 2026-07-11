"""Catalog loading helpers for the Config Center Updates tab."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sase.config import load_merged_config
from sase.main.update_routing import update_mode
from sase.mode_switch.repos import config_dev_root
from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogError,
    load_plugin_catalog,
)
from sase.plugins.latest import enrich_with_latest, is_newer
from sase.plugins.pypi_source import fetch_latest_version
from sase.uv_tool.detect import (
    NotUvToolInstall,
    UvToolInstall,
    probe_uv_tool_install,
)
from sase.uv_tool.receipt import load_receipt
from sase.uv_tool.versions import (
    CoreVersions,
    collect_installed_core_versions,
    enrich_core_versions_latest,
)
from sase.updates.incoming_commits import (
    IncomingCommits,
    core_package_commit_spec,
    fetch_incoming_commits,
)
from sase.version._git import git_probe_cache_key


_FRESH_EDITABLE_STATES = frozenset({"current", "update_available", "dirty", "diverged"})


@dataclass(frozen=True)
class PluginsLoadResult:
    """Outcome of a (possibly cache-first) plugin catalog load.

    *uv_tool* is the one-shot ``probe_uv_tool_install`` result carried alongside
    the catalog so the pane learns, off-thread, whether install/update mutations
    are even possible (a managed ``uv tool install sase``). ``None`` means the
    probe was not run (e.g. a stubbed loader in tests); the pane keeps whatever
    it already detected.
    """

    catalog: PluginCatalog | None
    error: str | None
    now: float
    uv_tool: UvToolInstall | NotUvToolInstall | None = None
    core_versions: CoreVersions | None = None
    core_incoming_commits: dict[str, IncomingCommits] = field(default_factory=dict)
    install_mode: str | None = None
    dev_root: str | None = None
    fresh_editable_roots: frozenset[str] = frozenset()


def probe_uv_tool() -> UvToolInstall | NotUvToolInstall | None:
    """Best-effort uv-tool probe; never raises (mutations gate on it only)."""
    try:
        return probe_uv_tool_install()
    except Exception:  # noqa: BLE001 - a probe failure must not break browsing.
        return None


def _collect_core_versions_for_pane(*, offline: bool = False) -> CoreVersions:
    """Best-effort SASE core version collection for the Updates tab."""
    versions = collect_installed_core_versions()
    return enrich_core_versions_latest(
        versions,
        offline=offline,
        fetch_fn=fetch_latest_version,
        is_newer=is_newer,
    )


def load_plugins_catalog_for_pane(
    *,
    refresh: bool = False,
    offline: bool = False,
    incoming_commits_enabled: bool = True,
    incoming_commits_limit: int = 7,
    now: float | None = None,
) -> PluginsLoadResult:
    """Load the plugin catalog (merged with installed + latest). Off-thread safe.

    Mirrors ``sase plugin list``: cache-first by default, then a best-effort
    latest-version enrichment so the update markers/counts match the ChangeSpecI. A
    hard catalog failure (e.g. a missing ``gh``) becomes the pane's error
    state; an enrichment failure degrades to the un-enriched catalog. The
    uv-tool probe runs here too so the mutation-availability check stays off the
    event loop.
    """
    load_now = time.time() if now is None else now
    uv_tool = probe_uv_tool()
    install_mode = _detect_install_mode(uv_tool)
    dev_root = str(config_dev_root(load_merged_config()))
    core_versions = _collect_core_versions_for_pane(offline=offline)
    core_incoming_commits = _fetch_core_incoming_commits_for_pane(
        core_versions,
        enabled=incoming_commits_enabled,
        limit=incoming_commits_limit,
        offline=offline,
    )
    try:
        catalog = load_plugin_catalog(refresh=refresh, offline=offline, now=load_now)
    except PluginCatalogError as exc:
        return PluginsLoadResult(
            catalog=None,
            error=str(exc),
            now=load_now,
            uv_tool=uv_tool,
            core_versions=core_versions,
            core_incoming_commits=core_incoming_commits,
            install_mode=install_mode,
            dev_root=dev_root,
        )
    try:
        catalog = enrich_with_latest(catalog, offline=offline, refresh=refresh)
    except Exception:  # noqa: BLE001 - list stays read-only; markers degrade only.
        pass
    return PluginsLoadResult(
        catalog=catalog,
        error=None,
        now=load_now,
        uv_tool=uv_tool,
        core_versions=core_versions,
        core_incoming_commits=core_incoming_commits,
        install_mode=install_mode,
        dev_root=dev_root,
        fresh_editable_roots=_fresh_editable_roots(core_versions, catalog),
    )


def _fresh_editable_roots(
    core_versions: CoreVersions,
    catalog: PluginCatalog,
) -> frozenset[str]:
    """Return roots proven refreshed by this online latest-version load."""
    roots = {
        _canonical_root(package.git_root)
        for package in core_versions.packages
        if package.install_type == "editable"
        and package.latest_state in _FRESH_EDITABLE_STATES
        and package.git_root
    }
    roots.update(
        _canonical_root(entry.latest.git_root)
        for entry in catalog.entries
        if entry.latest.source == "editable"
        and entry.latest.state in _FRESH_EDITABLE_STATES
        and entry.latest.git_root
    )
    return frozenset(roots)


def _canonical_root(root: str) -> str:
    return str(git_probe_cache_key(Path(root)))


def _detect_install_mode(install: object | None) -> str | None:
    """Classify the uv receipt as managed/dev/mixed for display."""
    if not isinstance(install, UvToolInstall):
        return None
    try:
        receipt = load_receipt(install.receipt_path)
    except Exception:
        return None
    requirements = (receipt.primary, *receipt.deduped_injected_plugins())
    has_dev = any(req.editable for req in requirements)
    has_managed = any(not req.editable for req in requirements)
    return update_mode(has_dev=has_dev, has_managed=has_managed)


def _fetch_core_incoming_commits_for_pane(
    core_versions: CoreVersions,
    *,
    enabled: bool,
    limit: int,
    offline: bool,
) -> dict[str, IncomingCommits]:
    if not enabled:
        return {}
    results: dict[str, IncomingCommits] = {}
    for package in core_versions.packages:
        spec = core_package_commit_spec(package)
        if spec is None:
            continue
        results[package.name] = fetch_incoming_commits(
            spec,
            limit=limit,
            offline=offline,
        )
    return results


_PluginsLoadResult = PluginsLoadResult
_collect_core_versions = _collect_core_versions_for_pane
_probe_uv_tool = probe_uv_tool
_load_plugins_catalog = load_plugins_catalog_for_pane
