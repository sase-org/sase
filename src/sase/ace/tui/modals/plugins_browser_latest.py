"""Lazy per-row latest-version fetches for the Config Center Updates plugin browser."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from textual.worker import WorkerState

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.latest import LatestInfo, latest_cache_key
from sase.uv_tool.detect import NotUvToolInstall

from .plugins_browser_rows import build_plugin_row

if TYPE_CHECKING:
    from textual.worker import Worker

    from .plugins_browser_rows import UpdateRow


class PluginsBrowserLatestMixin:
    """Lazy plugin latest-version fetches for the highlighted detail row."""

    if TYPE_CHECKING:
        _catalog: PluginCatalog | None
        _grouped: list[tuple[str, str, list[PluginCatalogEntry]]]
        _offline: bool
        _plugin_entry_by_name: dict[str, PluginCatalogEntry]
        _plugin_latest_loading: set[str]
        _plugin_latest_workers: dict[int, str]
        _rows: tuple[UpdateRow, ...]
        _rows_by_key: dict[str, UpdateRow]
        _uv_tool: object | None

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _refresh_install_mark_row(self, name: str) -> bool: ...

        def _render_detail_now(self, *, force: bool = False) -> None: ...

        def _worker_error_text(
            self, worker: Worker[Any], *, kind: str = "install"
        ) -> str: ...

    def _ensure_plugin_latest(self, entry: PluginCatalogEntry) -> None:
        if self._offline or entry.latest.checked:
            return
        key = latest_cache_key(entry)
        if not key or key in self._plugin_latest_loading:
            return
        self._plugin_latest_loading.add(key)
        snapshot = entry
        offline = self._offline

        def task() -> PluginCatalogEntry:
            from . import plugins_browser_pane as pane_module

            return pane_module._enrich_entry_latest(snapshot, offline=offline)

        worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=False,
            group="updates-plugin-latest",
        )
        self._plugin_latest_workers[id(worker)] = key

    def _on_plugin_latest_worker_state(
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
        self._plugin_latest_workers.pop(id(event.worker), None)
        self._plugin_latest_loading.discard(key)
        latest: LatestInfo | None = None
        name: str | None = None
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, PluginCatalogEntry):
                name = result.name
                latest = result.latest
        elif event.state == WorkerState.ERROR:
            error = self._worker_error_text(event.worker, kind="latest version")
            latest = LatestInfo(
                checked=True,
                source="unknown",
                error=error or "unavailable",
            )
            name = self._entry_name_for_latest_key(key)
        if latest is None or name is None:
            return
        self._apply_plugin_latest(name, latest)
        current = self._current_entry()
        if current is not None and current.name == name:
            self._render_detail_now(force=True)

    def _apply_plugin_latest(self, name: str, latest: LatestInfo) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        updated: PluginCatalogEntry | None = None
        entries: list[PluginCatalogEntry] = []
        for entry in catalog.entries:
            if entry.name == name:
                updated = dataclasses.replace(entry, latest=latest)
                entries.append(updated)
            else:
                entries.append(entry)
        if updated is None:
            return
        self._catalog = dataclasses.replace(catalog, entries=tuple(entries))
        self._plugin_entry_by_name[name] = updated
        self._grouped = [
            (
                group,
                style,
                [updated if entry.name == name else entry for entry in group_entries],
            )
            for group, style, group_entries in self._grouped
        ]
        self._refresh_install_mark_row(name)
        blocked = isinstance(self._uv_tool, NotUvToolInstall)
        new_row = build_plugin_row(updated, blocked=blocked)
        self._rows = tuple(
            new_row if row.key == new_row.key else row for row in self._rows
        )
        self._rows_by_key[new_row.key] = new_row

    def _entry_name_for_latest_key(self, key: str) -> str | None:
        catalog = self._catalog
        if catalog is None:
            return None
        for entry in catalog.entries:
            if latest_cache_key(entry) == key:
                return entry.name
        return None
