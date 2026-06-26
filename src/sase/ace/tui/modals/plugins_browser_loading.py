"""Catalog loading helpers for the Config Center Updates tab."""

from __future__ import annotations

import time
from dataclasses import dataclass

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
from sase.uv_tool.versions import (
    CoreVersions,
    collect_installed_core_versions,
    enrich_core_versions_latest,
)


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
    now: float | None = None,
) -> PluginsLoadResult:
    """Load the plugin catalog (merged with installed + latest). Off-thread safe.

    Mirrors ``sase plugin list``: cache-first by default, then a best-effort
    latest-version enrichment so the update markers/counts match the CLI. A
    hard catalog failure (e.g. a missing ``gh``) becomes the pane's error
    state; an enrichment failure degrades to the un-enriched catalog. The
    uv-tool probe runs here too so the mutation-availability check stays off the
    event loop.
    """
    load_now = time.time() if now is None else now
    uv_tool = probe_uv_tool()
    core_versions = _collect_core_versions_for_pane(offline=offline)
    try:
        catalog = load_plugin_catalog(refresh=refresh, offline=offline, now=load_now)
    except PluginCatalogError as exc:
        return PluginsLoadResult(
            catalog=None,
            error=str(exc),
            now=load_now,
            uv_tool=uv_tool,
            core_versions=core_versions,
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
    )


_PluginsLoadResult = PluginsLoadResult
_collect_core_versions = _collect_core_versions_for_pane
_probe_uv_tool = probe_uv_tool
_load_plugins_catalog = load_plugins_catalog_for_pane
