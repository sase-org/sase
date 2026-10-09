"""Lazy per-row command-preview fetches for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import WorkerState

from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.declared_commands import (
    DeclaredCommands,
    declared_cache_key,
    get_declared_commands_for_entry,
)

if TYPE_CHECKING:
    from textual.worker import Worker


class PluginsBrowserDeclaredMixin:
    """Lazy upstream command previews for the highlighted detail row.

    Mirrors :class:`PluginsBrowserLatestMixin`: the row chip never fetches —
    :meth:`_row_text` only consults :attr:`_plugin_declared_previews` — while
    the detail view fetches the preview lazily in a worker in its own group.
    Installed entries never fetch: their authoritative installed commands win.
    """

    if TYPE_CHECKING:
        _offline: bool
        _plugin_declared_loading: set[str]
        _plugin_declared_previews: dict[str, DeclaredCommands]
        _plugin_declared_workers: dict[int, str]

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _refresh_row(self, key: str) -> bool: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _worker_error_text(
            self, worker: Worker[Any], *, kind: str = "install"
        ) -> str: ...

    def _declared_preview_for_entry(
        self, entry: PluginCatalogEntry
    ) -> DeclaredCommands | None:
        """Return the cached upstream preview for *entry*, if one landed."""
        return self._plugin_declared_previews.get(declared_cache_key(entry.full_name))

    def _ensure_plugin_declared_preview(self, entry: PluginCatalogEntry) -> None:
        """Fetch the upstream command preview for *entry* off-thread, once."""
        if self._offline or entry.installed.installed:
            return
        key = declared_cache_key(entry.full_name)
        if not key or not entry.full_name:
            return
        if key in self._plugin_declared_loading:
            return
        # Any stored preview settles the row for this load — including
        # ``unknown``, which renders nothing. Without this, each detail
        # repaint would spawn another fetch and the worker would never drain.
        if key in self._plugin_declared_previews:
            return
        self._plugin_declared_loading.add(key)
        snapshot = entry
        offline = self._offline

        def task() -> tuple[str, DeclaredCommands]:
            return key, get_declared_commands_for_entry(snapshot, offline=offline)

        worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=False,
            group="updates-plugin-declared",
        )
        self._plugin_declared_workers[id(worker)] = key

    def _on_plugin_declared_worker_state(
        self,
        event: Worker.StateChanged,
        key: str,
    ) -> None:
        terminal_states = {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }
        if event.state not in terminal_states:
            return
        self._plugin_declared_workers.pop(id(event.worker), None)
        self._plugin_declared_loading.discard(key)
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 2:
            return
        result_key, declared = result
        if result_key != key or not isinstance(declared, DeclaredCommands):
            return
        self._plugin_declared_previews[key] = declared
        name = self._entry_name_for_declared_key(key)
        if name is not None:
            self._refresh_row(f"plugin:{name}")
        current = self._current_entry()
        if current is not None and declared_cache_key(current.full_name) == key:
            self._render_detail_now(force=True)

    def _entry_name_for_declared_key(self, key: str) -> str | None:
        catalog = self._catalog  # type: ignore[attr-defined]
        if catalog is None:
            return None
        for entry in catalog.entries:
            if declared_cache_key(entry.full_name) == key:
                return entry.name
        return None
