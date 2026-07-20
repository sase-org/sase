"""Aggregate installed/latest update status for every supported update source."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sase.agent_clis.models import AgentCliStatus, UpdateStrategy
from sase.agent_clis.operations import (
    collect_agent_cli_statuses,
    plan_agent_cli_status,
)
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry, load_plugin_catalog
from sase.plugins.latest import enrich_with_latest, is_newer
from sase.plugins.latest_cache import (
    CachedLatest,
    is_fresh,
    read_cache,
    write_cache,
)
from sase.plugins.pypi_source import fetch_latest_version
from sase.uv_tool.versions import (
    CorePackageVersion,
    CoreVersions,
    collect_installed_core_versions,
    enrich_core_versions_latest,
)
from sase.version._utils import normalize_distribution_name

ComponentRole = Literal["host", "core", "plugin"]


@dataclass(frozen=True)
class OutdatedComponent:
    """One installed SASE component that is behind its latest known version."""

    display_name: str
    role: ComponentRole
    installed_version: str | None
    latest_version: str | None
    distribution_name: str
    install_type: str | None = None
    source_root: str | None = None
    upstream_ref: str | None = None


@dataclass(frozen=True)
class ProviderUpdateCandidate:
    """One installed provider CLI with durable evidence of an update.

    Commands deliberately do not belong here.  A later update action must use
    the provider name to build a fresh plan from live metadata.
    """

    provider: str
    display_name: str
    installed_version: str
    latest_version: str
    manual_only: bool = False

    @property
    def name(self) -> str:
        """Return the stable provider registry name."""
        return self.provider


@dataclass(frozen=True)
class UpdateSourceStatus:
    """Last successful freshness plus the latest error for one source."""

    checked_at: float | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        """Return whether this source has ever completed successfully."""
        return self.checked_at is not None

    @property
    def successful(self) -> bool:
        """Return whether the latest source attempt completed successfully."""
        return self.known and self.error is None

    @classmethod
    def success(cls, checked_at: float) -> UpdateSourceStatus:
        return cls(checked_at=checked_at)

    @classmethod
    def failure(cls, error: str) -> UpdateSourceStatus:
        return cls(error=error)


@dataclass(frozen=True)
class UpdateStatus:
    """Composite update snapshot with independently truthful source state."""

    checked_at: float
    components: tuple[OutdatedComponent, ...]
    provider_candidates: tuple[ProviderUpdateCandidate, ...] = ()
    core_source: UpdateSourceStatus = field(default_factory=UpdateSourceStatus)
    plugin_source: UpdateSourceStatus = field(default_factory=UpdateSourceStatus)
    agent_cli_source: UpdateSourceStatus = field(default_factory=UpdateSourceStatus)

    @property
    def has_updates(self) -> bool:
        """Return whether any component or provider CLI is known outdated."""
        return bool(self.components or self.provider_candidates)

    @property
    def has_component_updates(self) -> bool:
        """Return whether SASE, core, or a plugin is known outdated."""
        return bool(self.components)

    @property
    def has_sase_updates(self) -> bool:
        """Alias for the SASE/core/plugin update domain."""
        return self.has_component_updates

    @property
    def has_agent_cli_updates(self) -> bool:
        """Return whether any supported provider CLI is known outdated."""
        return bool(self.provider_candidates)

    @property
    def has_core_update(self) -> bool:
        """Return whether a pending update requires a Rust core rebuild."""
        return any(component.role == "core" for component in self.components)

    @property
    def count(self) -> int:
        """Return the aggregate number of known updates."""
        return self.component_count + self.agent_cli_count

    @property
    def component_count(self) -> int:
        """Return the number of SASE/core/plugin updates."""
        return len(self.components)

    @property
    def sase_count(self) -> int:
        """Alias for the SASE/core/plugin count."""
        return self.component_count

    @property
    def agent_cli_count(self) -> int:
        """Return the number of provider CLI updates."""
        return len(self.provider_candidates)

    @property
    def manual_agent_cli_count(self) -> int:
        """Return the number of provider updates requiring manual action."""
        return sum(candidate.manual_only for candidate in self.provider_candidates)

    @property
    def provider_count(self) -> int:
        """Alias for the provider CLI count."""
        return self.agent_cli_count


def compute_update_status(
    *,
    offline: bool = False,
    refresh: bool = False,
    now: float | None = None,
) -> UpdateStatus:
    """Compute update status for SASE, plugins, and installed agent CLIs.

    Each source degrades independently. A PyPI, GitHub, npm, or dev-checkout
    failure can suppress that source's entries without hiding updates found by
    the other sources.
    """
    checked_at = time.time() if now is None else now
    core_components, core_source = _compute_core_source(
        offline=offline,
        now=checked_at,
    )
    plugin_components, plugin_source = _compute_plugin_source(
        offline=offline,
        refresh=refresh,
        now=checked_at,
    )
    provider_candidates, agent_cli_source = _compute_agent_cli_source(
        offline=offline,
        refresh=refresh,
        now=checked_at,
    )
    return _build_update_status(
        checked_at=checked_at,
        components=[*core_components, *plugin_components],
        provider_candidates=provider_candidates,
        core_source=core_source,
        plugin_source=plugin_source,
        agent_cli_source=agent_cli_source,
    )


def build_update_status(
    core_versions: CoreVersions,
    catalog: PluginCatalog | None,
    *,
    agent_cli_statuses: Sequence[AgentCliStatus] | None = None,
    core_error: str | None = None,
    plugin_error: str | None = None,
    agent_cli_error: str | None = None,
    now: float | None = None,
) -> UpdateStatus:
    """Build status from inventories an existing background load already owns."""
    checked_at = time.time() if now is None else now
    components = [
        _core_component(package)
        for package in core_versions.packages
        if package.update_available
    ]
    if catalog is not None:
        components.extend(
            _plugin_component(entry)
            for entry in catalog.entries
            if entry.installed.installed and entry.update_available
        )
    core_error = core_error or _core_versions_error(core_versions)
    plugin_error = plugin_error or (
        _plugin_catalog_error(catalog) if catalog is not None else "unavailable"
    )
    provider_candidates: tuple[ProviderUpdateCandidate, ...] = ()
    if agent_cli_statuses is not None:
        provider_candidates = provider_update_candidates(agent_cli_statuses)
        agent_cli_error = agent_cli_error or _agent_cli_statuses_error(
            agent_cli_statuses
        )
    return _build_update_status(
        checked_at=checked_at,
        components=components,
        provider_candidates=provider_candidates,
        core_source=_completed_source(checked_at, core_error),
        plugin_source=_completed_source(checked_at, plugin_error),
        agent_cli_source=(
            UpdateSourceStatus()
            if agent_cli_statuses is None and agent_cli_error is None
            else _completed_source(checked_at, agent_cli_error)
        ),
    )


def provider_update_candidates(
    statuses: Sequence[AgentCliStatus],
) -> tuple[ProviderUpdateCandidate, ...]:
    """Project installed, outdated provider statuses into durable evidence."""
    candidates = [
        ProviderUpdateCandidate(
            provider=status.provider,
            display_name=status.display_name,
            installed_version=status.installed_version,
            latest_version=status.latest_version,
            manual_only=(
                plan_agent_cli_status(status).strategy is UpdateStrategy.MANUAL
            ),
        )
        for status in statuses
        if status.installed
        and status.update_available
        and status.installed_version
        and status.latest_version
    ]
    return tuple(sorted(candidates, key=lambda item: item.provider.casefold()))


def _build_update_status(
    *,
    checked_at: float,
    components: list[OutdatedComponent],
    provider_candidates: Sequence[ProviderUpdateCandidate] = (),
    core_source: UpdateSourceStatus | None = None,
    plugin_source: UpdateSourceStatus | None = None,
    agent_cli_source: UpdateSourceStatus | None = None,
) -> UpdateStatus:
    return UpdateStatus(
        checked_at=checked_at,
        components=tuple(
            sorted(
                components,
                key=lambda item: (
                    _role_sort_key(item.role),
                    item.display_name.casefold(),
                ),
            )
        ),
        provider_candidates=tuple(
            sorted(provider_candidates, key=lambda item: item.provider.casefold())
        ),
        core_source=core_source or UpdateSourceStatus(),
        plugin_source=plugin_source or UpdateSourceStatus(),
        agent_cli_source=agent_cli_source or UpdateSourceStatus(),
    )


def _compute_core_source(
    *, offline: bool, now: float
) -> tuple[tuple[OutdatedComponent, ...], UpdateSourceStatus]:
    try:
        versions = _collect_installed_core_versions()
        versions = _enrich_core_versions_latest(
            versions,
            offline=offline,
            fetch_fn=_make_cached_core_fetch_fn(now),
            is_newer=_is_newer,
        )
    except Exception as exc:  # noqa: BLE001 - sources degrade independently.
        return (), UpdateSourceStatus.failure(_error_text(exc))
    return (
        tuple(
            _core_component(package)
            for package in versions.packages
            if package.update_available
        ),
        _completed_source(now, _core_versions_error(versions)),
    )


def _make_cached_core_fetch_fn(now: float) -> Callable[[str], str | None]:
    """Build a PyPI fetcher for core packages backed by the latest-version cache.

    The startup snapshot recompute is eligible every 10 minutes, but PyPI's
    answer for ``sase`` / ``sase-core-rs`` rarely changes that fast. Core
    lookups share the plugin latest-version cache (distinct distribution keys,
    so no collision) and only hit the network when their cached entry has
    lapsed the latest-version TTL. Misses are written through so the next
    recompute stays offline. The cache is read lazily so an offline recompute,
    which never calls ``fetch_fn``, touches no disk.
    """
    cache: dict[str, CachedLatest] | None = None

    def _fetch(dist_name: str) -> str | None:
        nonlocal cache
        if cache is None:
            cache = _safe_read_latest_cache()
        key = normalize_distribution_name(dist_name)
        cached = cache.get(key)
        if cached is not None and _latest_cache_is_fresh(cached, now):
            return cached.version
        version = _fetch_latest_version(dist_name)
        cache[key] = CachedLatest(version=version, fetched_at=now)
        _safe_write_latest_cache(cache)
        return version

    return _fetch


def _safe_read_latest_cache() -> dict[str, CachedLatest]:
    try:
        return _read_latest_cache()
    except Exception:  # noqa: BLE001 - cache reads must never break update hints.
        return {}


def _safe_write_latest_cache(cache: dict[str, CachedLatest]) -> None:
    try:
        _write_latest_cache(cache)
    except Exception:  # noqa: BLE001 - cache writes are best effort.
        return


def _core_component(package: CorePackageVersion) -> OutdatedComponent:
    name = package.name
    distribution_name = package.distribution_name
    role: ComponentRole = "host" if distribution_name == "sase" else "core"
    return OutdatedComponent(
        display_name=str(name),
        role=role,
        installed_version=package.installed_version,
        latest_version=package.latest_version,
        distribution_name=str(distribution_name),
        install_type=package.install_type,
        source_root=package.git_root,
        upstream_ref=package.upstream_ref,
    )


def _compute_plugin_source(
    *,
    offline: bool,
    refresh: bool,
    now: float,
) -> tuple[tuple[OutdatedComponent, ...], UpdateSourceStatus]:
    try:
        catalog = _load_plugin_catalog(refresh=refresh, offline=offline, now=now)
    except Exception as exc:  # noqa: BLE001 - sources degrade independently.
        return (), UpdateSourceStatus.failure(_error_text(exc))
    try:
        catalog = _enrich_with_latest(catalog, offline=offline, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - preserve last-known-good rows.
        return (), UpdateSourceStatus.failure(_error_text(exc))
    return (
        tuple(
            _plugin_component(entry)
            for entry in catalog.entries
            if entry.installed.installed and entry.update_available
        ),
        _completed_source(now, _plugin_catalog_error(catalog)),
    )


def _compute_agent_cli_source(
    *,
    offline: bool,
    refresh: bool,
    now: float,
) -> tuple[tuple[ProviderUpdateCandidate, ...], UpdateSourceStatus]:
    try:
        statuses = _collect_agent_cli_statuses(refresh=refresh, offline=offline)
    except Exception as exc:  # noqa: BLE001 - sources degrade independently.
        return (), UpdateSourceStatus.failure(_error_text(exc))
    return (
        provider_update_candidates(statuses),
        _completed_source(now, _agent_cli_statuses_error(statuses)),
    )


def _completed_source(checked_at: float, error: str | None) -> UpdateSourceStatus:
    if error is not None:
        return UpdateSourceStatus.failure(error)
    return UpdateSourceStatus.success(checked_at)


def _core_versions_error(versions: CoreVersions) -> str | None:
    errors = [
        f"{package.name}: {package.latest_error}"
        for package in versions.packages
        if package.latest_error
    ]
    return _join_errors(errors)


def _plugin_catalog_error(catalog: PluginCatalog) -> str | None:
    errors = list(catalog.warnings)
    errors.extend(
        f"{entry.name}: {entry.latest.error}"
        for entry in catalog.entries
        if entry.installed.installed and entry.latest.error
    )
    return _join_errors(errors)


def _agent_cli_statuses_error(statuses: Sequence[AgentCliStatus]) -> str | None:
    errors: list[str] = []
    for status in statuses:
        if status.version_error:
            errors.append(f"{status.provider}: {status.version_error}")
        if status.latest_error:
            errors.append(f"{status.provider}: {status.latest_error}")
    return _join_errors(errors)


def _join_errors(errors: Sequence[str]) -> str | None:
    values = tuple(dict.fromkeys(error.strip() for error in errors if error.strip()))
    return "; ".join(values) if values else None


def _error_text(error: Exception) -> str:
    message = str(error).strip()
    return message or type(error).__name__


def _plugin_component(entry: PluginCatalogEntry) -> OutdatedComponent:
    latest = entry.latest
    installed = entry.installed
    installed_version = latest.current_version or installed.version
    distribution_name = entry.repo or entry.name
    return OutdatedComponent(
        display_name=str(entry.name),
        role="plugin",
        installed_version=installed_version,
        latest_version=latest.version,
        distribution_name=str(distribution_name),
        install_type=latest.install_type,
        source_root=latest.git_root,
        upstream_ref=latest.upstream_ref,
    )


def _role_sort_key(role: ComponentRole) -> int:
    if role == "host":
        return 0
    if role == "core":
        return 1
    return 2


_collect_installed_core_versions = collect_installed_core_versions
_enrich_core_versions_latest = enrich_core_versions_latest
_load_plugin_catalog = load_plugin_catalog
_enrich_with_latest = enrich_with_latest
_fetch_latest_version = fetch_latest_version
_is_newer = is_newer
_read_latest_cache = read_cache
_write_latest_cache = write_cache
_latest_cache_is_fresh = is_fresh
_collect_agent_cli_statuses = collect_agent_cli_statuses

__all__ = [
    "ComponentRole",
    "OutdatedComponent",
    "ProviderUpdateCandidate",
    "UpdateSourceStatus",
    "UpdateStatus",
    "build_update_status",
    "compute_update_status",
    "provider_update_candidates",
]
