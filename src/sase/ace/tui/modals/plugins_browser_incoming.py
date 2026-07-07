"""Incoming-commit support for the Config Center Updates plugin browser."""

from __future__ import annotations

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

if TYPE_CHECKING:
    from textual.worker import Worker


@dataclass(frozen=True)
class IncomingCommitsConfig:
    """Config for Updates-tab incoming commit previews."""

    enabled: bool = True
    max_per_repo: int = 7
    confirm_max_per_repo: int = 250


ConfirmIncomingCommitsLoader = Callable[[], tuple[RepoIncomingCommits, ...]]


class PluginsBrowserIncomingCommitsMixin:
    """Lazy plugin incoming-commit fetches for the detail panel."""

    if TYPE_CHECKING:
        _incoming_commit_cache: dict[IncomingCommitsCacheKey, IncomingCommits]
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
                self._incoming_commit_cache[key] = result
        elif event.state == WorkerState.ERROR:
            error = self._worker_error_text(event.worker, kind="incoming commits")
            self._incoming_commit_cache[key] = IncomingCommits(
                total=0,
                commits=(),
                source="unavailable",
                error=error,
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
