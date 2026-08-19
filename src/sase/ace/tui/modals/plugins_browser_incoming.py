"""Incoming-commit support for the Config Center Updates plugin browser."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.worker import WorkerState

from sase.config.core import load_merged_config
from sase.dev_update.models import DevUpdatePlan
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry, find_plugin
from sase.plugins.operations import UpdateReady
from sase.updates.incoming_commits import (
    CommitSourceSpec,
    IncomingCommits,
    IncomingCommitsCacheKey,
    RepoIncomingCommits,
    core_package_commit_spec,
    dev_update_root_commit_spec,
    fetch_incoming_commit_groups,
    fetch_incoming_commits,
    plugin_entry_commit_spec,
)
from sase.uv_tool.versions import CoreVersions
from sase.version._utils import normalize_distribution_name

from .plugins_browser_dev_update import DevUpdatePreview

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class IncomingCommitsConfig:
    """Config for Updates-tab incoming commit previews."""

    enabled: bool = True
    max_per_repo: int = 7
    confirm_max_per_repo: int = 250


ConfirmIncomingCommitsLoader = Callable[[], tuple[RepoIncomingCommits, ...]]

#: Cap on `_incoming_commit_cache`. Already bounded in practice by
#: installed-and-updatable count rather than catalog size, so this is a leak
#: fix for a long session, not a scale fix.
_INCOMING_COMMIT_CACHE_MAX = 128


def _put_incoming_commit_cache(
    cache: OrderedDict[IncomingCommitsCacheKey, IncomingCommits],
    key: IncomingCommitsCacheKey,
    value: IncomingCommits,
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _INCOMING_COMMIT_CACHE_MAX:
        cache.popitem(last=False)


class PluginsBrowserIncomingCommitsMixin:
    """Lazy plugin incoming-commit fetches for the detail panel."""

    if TYPE_CHECKING:
        _incoming_commit_cache: OrderedDict[IncomingCommitsCacheKey, IncomingCommits]
        _incoming_commit_loading: set[IncomingCommitsCacheKey]
        _incoming_commit_workers: dict[int, IncomingCommitsCacheKey]
        _incoming_commits_enabled: bool
        _incoming_commits_limit: int
        _incoming_commits_confirm_limit: int
        _offline: bool
        _catalog: PluginCatalog | None
        _core_versions: CoreVersions
        _core_incoming_commits: dict[str, IncomingCommits]

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _worker_error_text(
            self, worker: Worker[Any], *, kind: str = "install"
        ) -> str: ...

    def _ensure_plugin_incoming_commits(self, entry: PluginCatalogEntry) -> None:
        spec = self._plugin_incoming_commit_spec(entry)
        if spec is None:
            return
        key = spec.cache_key
        if key in self._incoming_commit_cache or key in self._incoming_commit_loading:
            return
        self._incoming_commit_loading.add(key)
        offline = self._offline
        limit = self._incoming_commits_limit

        def task() -> IncomingCommits:
            from . import plugins_browser_pane as pane_module

            return pane_module._fetch_incoming_commits(
                spec, limit=limit, offline=offline
            )

        worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=False,
            group="updates-incoming-commits",
        )
        self._incoming_commit_workers[id(worker)] = key

    def _plugin_incoming_commit_spec(
        self, entry: PluginCatalogEntry
    ) -> CommitSourceSpec | None:
        if not self._incoming_commits_enabled or self._offline:
            return None
        return plugin_entry_commit_spec(entry)

    def _plugin_incoming_commits_state(
        self, entry: PluginCatalogEntry
    ) -> tuple[IncomingCommits | None, bool]:
        spec = self._plugin_incoming_commit_spec(entry)
        if spec is None:
            return None, False
        key = spec.cache_key
        return (
            self._incoming_commit_cache.get(key),
            key in self._incoming_commit_loading,
        )

    def _on_incoming_commits_worker_state(
        self,
        event: Worker.StateChanged,
        key: IncomingCommitsCacheKey,
    ) -> None:
        terminal_states = {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        if event.state not in terminal_states:
            return
        self._incoming_commit_workers.pop(id(event.worker), None)
        self._incoming_commit_loading.discard(key)
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, IncomingCommits):
                _put_incoming_commit_cache(self._incoming_commit_cache, key, result)
        elif event.state == WorkerState.ERROR:
            error = self._worker_error_text(event.worker, kind="incoming commits")
            _put_incoming_commit_cache(
                self._incoming_commit_cache,
                key,
                IncomingCommits(
                    total=0,
                    commits=(),
                    source="unavailable",
                    error=error,
                ),
            )
        entry = self._current_entry()
        if entry is None:
            return
        spec = self._plugin_incoming_commit_spec(entry)
        if spec is not None and spec.cache_key == key:
            self._render_detail_now(force=True)

    def _dev_update_incoming_commits_loader(
        self,
        plan: DevUpdatePlan,
    ) -> ConfirmIncomingCommitsLoader | None:
        if not self._incoming_commits_enabled:
            return None
        specs: list[tuple[str, CommitSourceSpec]] = []
        for root in plan.actionable_roots:
            spec = dev_update_root_commit_spec(root)
            if spec is None:
                continue
            specs.append((_short_root(root.git_root), spec))
        return self._incoming_commits_loader_from_specs(specs, seed={})

    def _managed_sase_update_incoming_commits_loader(
        self,
    ) -> ConfirmIncomingCommitsLoader | None:
        if not self._incoming_commits_enabled:
            return None
        specs: list[tuple[str, CommitSourceSpec]] = []
        seed: dict[IncomingCommitsCacheKey, IncomingCommits] = {}
        core_incoming = dict(self._core_incoming_commits)
        for package in self._core_versions.packages:
            spec = core_package_commit_spec(package)
            if spec is None:
                continue
            specs.append((package.name, spec))
            cached = core_incoming.get(package.name)
            if cached is not None:
                seed[spec.cache_key] = cached

        catalog = self._catalog
        if catalog is not None:
            for entry in sorted(
                (entry for entry in catalog.entries if entry.update_available),
                key=lambda entry: entry.name.casefold(),
            ):
                spec = plugin_entry_commit_spec(entry)
                if spec is None:
                    continue
                specs.append((entry.name, spec))
                cached = self._incoming_commit_cache.get(spec.cache_key)
                if cached is not None:
                    seed[spec.cache_key] = cached
        return self._incoming_commits_loader_from_specs(specs, seed=seed)

    def _sase_update_incoming_commits_loader(
        self,
        preview: DevUpdatePreview,
    ) -> ConfirmIncomingCommitsLoader | None:
        """Build a loader from the exact editable/managed work in *preview*."""
        if not self._incoming_commits_enabled:
            return None
        specs = _sase_update_incoming_commit_sources(
            preview,
            core_versions=self._core_versions,
            catalog=self._catalog,
        )
        return self._incoming_commits_loader_from_specs(
            list(specs),
            seed=_loaded_incoming_commit_seed(
                core_versions=self._core_versions,
                core_incoming=self._core_incoming_commits,
                catalog=self._catalog,
                plugin_incoming=self._incoming_commit_cache,
            ),
        )

    def _plugin_update_incoming_commits_loader(
        self,
        plan: UpdateReady,
    ) -> ConfirmIncomingCommitsLoader | None:
        if not self._incoming_commits_enabled:
            return None
        catalog = self._catalog
        if catalog is None:
            return None
        specs: list[tuple[str, CommitSourceSpec]] = []
        seed: dict[IncomingCommitsCacheKey, IncomingCommits] = {}
        for target in plan.targets:
            entry = find_plugin(catalog, target)
            if entry is None:
                continue
            spec = plugin_entry_commit_spec(entry)
            if spec is None:
                continue
            specs.append((entry.name, spec))
            cached = self._incoming_commit_cache.get(spec.cache_key)
            if cached is not None:
                seed[spec.cache_key] = cached
        return self._incoming_commits_loader_from_specs(specs, seed=seed)

    def _incoming_commits_loader_from_specs(
        self,
        specs: list[tuple[str, CommitSourceSpec]],
        *,
        seed: dict[IncomingCommitsCacheKey, IncomingCommits],
    ) -> ConfirmIncomingCommitsLoader | None:
        if not specs:
            return None
        spec_snapshot = tuple(specs)
        seed_snapshot = dict(seed)
        limit = self._incoming_commits_confirm_limit
        offline = self._offline

        def loader() -> tuple[RepoIncomingCommits, ...]:
            from . import plugins_browser_pane as pane_module

            return pane_module._fetch_incoming_commit_groups(
                spec_snapshot,
                limit=limit,
                offline=offline,
                seed=seed_snapshot,
            )

        return loader


def _load_incoming_commits_config(
    load_fn: Callable[[], dict[str, Any]] = load_merged_config,
) -> IncomingCommitsConfig:
    try:
        data = load_fn()
    except Exception:  # noqa: BLE001 - config failures should not break the pane.
        return IncomingCommitsConfig()
    ace = data.get("ace") if isinstance(data, dict) else None
    updates = ace.get("updates") if isinstance(ace, dict) else None
    incoming = updates.get("incoming_commits") if isinstance(updates, dict) else None
    if not isinstance(incoming, dict):
        return IncomingCommitsConfig()
    return IncomingCommitsConfig(
        enabled=_coerce_bool(incoming.get("enabled"), default=True),
        max_per_repo=_coerce_nonnegative_int(
            incoming.get("max_per_repo"),
            default=7,
        ),
        confirm_max_per_repo=_coerce_nonnegative_int(
            incoming.get("confirm_max_per_repo"),
            default=250,
        ),
    )


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", "none", "disabled"}:
            return False
    return default


def _coerce_nonnegative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


_fetch_incoming_commits = fetch_incoming_commits
_fetch_incoming_commit_groups = fetch_incoming_commit_groups
load_incoming_commits_config = _load_incoming_commits_config


def _short_root(root: str) -> str:
    name = Path(root).name
    return name or root


def _sase_update_incoming_commit_sources(
    preview: DevUpdatePreview,
    *,
    core_versions: CoreVersions,
    catalog: PluginCatalog | None,
) -> tuple[tuple[str, CommitSourceSpec], ...]:
    """Select frozen repository ranges represented by one SASE update preview."""
    if preview.plan is None:
        return _dedupe_commit_sources(
            _all_managed_commit_sources(core_versions=core_versions, catalog=catalog)
        )

    known_labels = _known_source_labels(
        core_versions=core_versions,
        catalog=catalog,
    )
    sources: list[tuple[str, CommitSourceSpec]] = []
    for root in preview.plan.actionable_roots:
        spec = dev_update_root_commit_spec(root)
        if spec is None:
            continue
        label = known_labels.get(spec.cache_key) or _human_repo_label(
            _short_root(root.git_root)
        )
        sources.append((label, spec))

    if preview.managed_argv:
        for package in preview.managed_packages:
            source = _managed_package_commit_source(
                package.name,
                core_versions=core_versions,
                catalog=catalog,
            )
            if source is not None:
                sources.append(source)
    return _dedupe_commit_sources(sources)


def _all_managed_commit_sources(
    *,
    core_versions: CoreVersions,
    catalog: PluginCatalog | None,
) -> list[tuple[str, CommitSourceSpec]]:
    sources: list[tuple[str, CommitSourceSpec]] = []
    for package in core_versions.packages:
        spec = core_package_commit_spec(package)
        if spec is not None:
            sources.append((package.name, spec))
    if catalog is not None:
        for entry in sorted(
            (entry for entry in catalog.entries if entry.update_available),
            key=lambda entry: entry.name.casefold(),
        ):
            spec = plugin_entry_commit_spec(entry)
            if spec is not None:
                sources.append((entry.name, spec))
    return sources


def _managed_package_commit_source(
    package_name: str,
    *,
    core_versions: CoreVersions,
    catalog: PluginCatalog | None,
) -> tuple[str, CommitSourceSpec] | None:
    target = normalize_distribution_name(package_name)
    for package in core_versions.packages:
        keys = {
            normalize_distribution_name(package.name),
            normalize_distribution_name(package.distribution_name),
        }
        if target not in keys:
            continue
        spec = core_package_commit_spec(package)
        return (package.name, spec) if spec is not None else None
    if catalog is None:
        return None
    for entry in catalog.entries:
        keys = {
            normalize_distribution_name(entry.name),
            normalize_distribution_name(entry.repo),
            normalize_distribution_name(entry.full_name.rsplit("/", 1)[-1]),
            normalize_distribution_name(f"sase-{entry.name}"),
        }
        if target not in keys:
            continue
        spec = plugin_entry_commit_spec(entry)
        return (entry.name, spec) if spec is not None else None
    return None


def _known_source_labels(
    *,
    core_versions: CoreVersions,
    catalog: PluginCatalog | None,
) -> dict[IncomingCommitsCacheKey, str]:
    labels: dict[IncomingCommitsCacheKey, str] = {}
    for label, spec in _all_managed_commit_sources(
        core_versions=core_versions,
        catalog=catalog,
    ):
        labels.setdefault(spec.cache_key, label)
    return labels


def _loaded_incoming_commit_seed(
    *,
    core_versions: CoreVersions,
    core_incoming: dict[str, IncomingCommits],
    catalog: PluginCatalog | None,
    plugin_incoming: dict[IncomingCommitsCacheKey, IncomingCommits],
) -> dict[IncomingCommitsCacheKey, IncomingCommits]:
    seed = dict(plugin_incoming)
    for package in core_versions.packages:
        spec = core_package_commit_spec(package)
        cached = core_incoming.get(package.name)
        if spec is not None and cached is not None:
            seed[spec.cache_key] = cached
    if catalog is not None:
        for entry in catalog.entries:
            spec = plugin_entry_commit_spec(entry)
            if spec is None:
                continue
            cached = plugin_incoming.get(spec.cache_key)
            if cached is not None:
                seed[spec.cache_key] = cached
    return seed


def _dedupe_commit_sources(
    sources: list[tuple[str, CommitSourceSpec]],
) -> tuple[tuple[str, CommitSourceSpec], ...]:
    result: list[tuple[str, CommitSourceSpec]] = []
    seen: set[IncomingCommitsCacheKey] = set()
    for label, spec in sources:
        if spec.cache_key in seen:
            continue
        seen.add(spec.cache_key)
        result.append((label, spec))
    return tuple(result)


def _human_repo_label(label: str) -> str:
    if normalize_distribution_name(label) in {"sase-core", "sase-core-rs"}:
        return "sase-core"
    if label.startswith("sase-"):
        return label.removeprefix("sase-")
    return label
