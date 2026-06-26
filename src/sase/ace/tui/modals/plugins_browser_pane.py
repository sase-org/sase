"""Read-only Plugins browser pane for the Config Center modal.

This widget hosts the **Plugins** tab of :class:`ConfigCenterModal`: a
master/detail layout (mirroring the XPrompts tab) that brings the
``sase plugin list`` experience into the TUI. Phase 2 builds the read-only
list browse — a header summary line, a filter input, a grouped
``OptionList`` split into Built-in / Community sections with CLI-matching
status glyphs, and a placeholder detail panel. The catalog loads
cache-first off the event loop (``run_worker(thread=True)``) so a slow
``gh`` / network call never blocks the UI; loading, empty, and error states
are surfaced in place.

The ``show``-equivalent detail panel and the refresh / offline / verbose
affordances arrive in later phases. This pane intentionally reuses the same
single source of truth as the CLI
(:func:`sase.plugins.catalog.load_plugin_catalog` plus
:func:`sase.plugins.latest.enrich_with_latest`) so the TUI list and
``sase plugin list`` never drift.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
    load_plugin_catalog,
)
from sase.plugins.latest import enrich_with_latest
from sase.plugins.render_common import (
    _AVAILABLE_GLYPH,
    _COMMUNITY_STYLE,
    _INSTALLED_GLYPH,
    _UPDATE_GLYPH,
    humanize_age,
)

#: Right-panel placeholder until the detail view lands (Phase 3).
_DETAIL_PLACEHOLDER = "Select a plugin to view its details."

_BUILTIN_GROUP = "Built-in"
_COMMUNITY_GROUP = "Community"

_HEADER_PREFIX = "__header__"
_ITEM_PREFIX = "plugin__"


@dataclass(frozen=True)
class _PluginsLoadResult:
    """Outcome of a (possibly cache-first) plugin catalog load."""

    catalog: PluginCatalog | None
    error: str | None
    now: float


def _load_plugins_catalog(
    *,
    refresh: bool = False,
    offline: bool = False,
    now: float | None = None,
) -> _PluginsLoadResult:
    """Load the plugin catalog (merged with installed + latest). Off-thread safe.

    Mirrors ``sase plugin list``: cache-first by default, then a best-effort
    latest-version enrichment so the update markers/counts match the CLI. A
    hard catalog failure (e.g. a missing ``gh``) becomes the pane's error
    state; an enrichment failure degrades to the un-enriched catalog.
    """
    load_now = time.time() if now is None else now
    try:
        catalog = load_plugin_catalog(refresh=refresh, offline=offline, now=load_now)
    except PluginCatalogError as exc:
        return _PluginsLoadResult(catalog=None, error=str(exc), now=load_now)
    try:
        catalog = enrich_with_latest(catalog, offline=offline, refresh=refresh)
    except Exception:  # noqa: BLE001 - list stays read-only; markers degrade only.
        pass
    return _PluginsLoadResult(catalog=catalog, error=None, now=load_now)


class _PluginsFilterInput(Input):
    """Filter input that yields ``[`` / ``]`` to the host tab strip.

    Like the other Config Center panes, ``[`` / ``]`` must reach the host
    modal so tab switching works while typing; ``escape`` returns focus to
    the list without leaving a stale filter applied.
    """

    def on_key(self, event: events.Key) -> None:
        if event.key in ("left_square_bracket", "right_square_bracket"):
            host = self.screen
            prev_tab = getattr(host, "action_prev_center_tab", None)
            next_tab = getattr(host, "action_next_center_tab", None)
            if callable(prev_tab) and callable(next_tab):
                event.stop()
                event.prevent_default()
                (prev_tab if event.key == "left_square_bracket" else next_tab)()
        elif event.key == "escape":
            pane = self._pane()
            if pane is not None:
                event.stop()
                event.prevent_default()
                pane.cancel_input()

    def _pane(self) -> PluginsBrowserPane | None:
        node: object | None = self.parent
        while node is not None:
            if isinstance(node, PluginsBrowserPane):
                return node
            node = getattr(node, "parent", None)
        return None


class PluginsBrowserPane(Vertical):
    """Read-only browser for the SASE plugin catalog (Config Center → Plugins)."""

    can_focus = False

    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("slash", "focus_filter", "Filter"),
    ]

    def __init__(self, *, auto_load: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._auto_load = auto_load
        self._catalog: PluginCatalog | None = None
        self._error: str | None = None
        self._loading = auto_load
        self._now = time.time()
        self._filter_text = ""
        self._grouped: list[tuple[str, str, list[PluginCatalogEntry]]] = []
        self._worker: Worker[Any] | None = None

    # -- composition --

    def compose(self) -> ComposeResult:
        yield Static(self._summary_text(), id="plugins-summary", markup=False)
        yield _PluginsFilterInput(
            placeholder="/ filter plugins…", id="plugins-filter-input"
        )
        with Horizontal(id="plugins-panels"):
            with Vertical(id="plugins-list-panel"):
                yield Static(self._status_message(), id="plugins-status", markup=False)
                yield OptionList(*self._create_options(), id="plugins-list")
            with Vertical(id="plugins-detail-panel"):
                with VerticalScroll(id="plugins-detail-scroll"):
                    yield Static(_DETAIL_PLACEHOLDER, id="plugins-detail", markup=False)
        yield Static(self._hints(), id="plugins-hints", markup=False)

    def on_mount(self) -> None:
        self._sync_state_visibility()
        if self._auto_load:
            self._start_load(force=False)

    def focus_default(self) -> None:
        """Focus the list (browse-first) when the Plugins tab activates."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    # -- loading --

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        self._sync_state_visibility()
        self._update_static("#plugins-summary", self._summary_text())
        refresh = force

        def task() -> _PluginsLoadResult:
            return _load_plugins_catalog(refresh=refresh)

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._catalog = getattr(result, "catalog", None)
            self._error = getattr(result, "error", None)
            self._now = getattr(result, "now", self._now)
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._render_all()

    # -- rendering --

    def _render_all(self) -> None:
        self._rebuild_groups()
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        self._rebuild_options()
        self._sync_state_visibility()

    def _rebuild_groups(self) -> None:
        self._grouped = []
        catalog = self._catalog
        if catalog is None:
            return
        builtin = [e for e in catalog.builtin_entries if self._matches(e)]
        community = [e for e in catalog.community_entries if self._matches(e)]
        if builtin:
            self._grouped.append((_BUILTIN_GROUP, "bold dim", builtin))
        if community:
            self._grouped.append(
                (_COMMUNITY_GROUP, f"bold {_COMMUNITY_STYLE}", community)
            )

    def _matches(self, entry: PluginCatalogEntry) -> bool:
        needle = self._filter_text.strip().casefold()
        if not needle:
            return True
        haystack = "\n".join(
            part
            for part in (entry.name, entry.repo, entry.description, *entry.topics)
            if part
        ).casefold()
        return needle in haystack

    def _rebuild_options(self) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)
        self._skip_to_first_item(option_list)

    def _create_options(self) -> list[Option]:
        """Build OptionList items: disabled section headers + plugin rows."""
        options: list[Option] = []
        for group, style, entries in self._grouped:
            header = Text(f"── {group} ──", style=style)
            options.append(Option(header, id=f"{_HEADER_PREFIX}{group}", disabled=True))
            for entry in entries:
                options.append(
                    Option(self._row_text(entry), id=f"{_ITEM_PREFIX}{entry.name}")
                )
        return options

    def _row_text(self, entry: PluginCatalogEntry) -> Text:
        """A single list row: status glyph + name + version + update marker."""
        text = Text()
        text.append("  ")
        if entry.installed.installed:
            text.append(_INSTALLED_GLYPH, style="green")
        else:
            text.append(_AVAILABLE_GLYPH, style="dim")
        text.append(" ")
        text.append(entry.name, style="bold")
        version = self._version_label(entry)
        if version:
            text.append("  ")
            text.append(version, style="dim")
        if entry.update_available:
            text.append("  ")
            text.append(_UPDATE_GLYPH, style="bold cyan")
        return text

    @staticmethod
    def _version_label(entry: PluginCatalogEntry) -> str:
        info = entry.installed
        if info.installed:
            if entry.latest.source == "editable":
                return "editable"
            if entry.latest.source == "git":
                return "git"
            if entry.update_available and info.version and entry.latest.version:
                return f"v{info.version} → v{entry.latest.version}"
            if info.version:
                return f"v{info.version}"
            return "installed"
        if entry.latest.version:
            return f"latest v{entry.latest.version}"
        return ""

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Highlight the first non-header option, if any."""
        for index in range(option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    # -- state visibility --

    def _sync_state_visibility(self) -> None:
        """Show the list when populated, else the status placeholder."""
        has_rows = any(entries for _, _, entries in self._grouped)
        try:
            status = self.query_one("#plugins-status", Static)
            option_list = self.query_one("#plugins-list", OptionList)
        except Exception:
            return
        status.update(self._status_message())
        show_status = self._loading or self._error is not None or not has_rows
        status.display = show_status
        option_list.display = not show_status

    # -- dynamic text --

    def _summary_text(self) -> str:
        if self._loading:
            return "SASE Plugins · loading…"
        catalog = self._catalog
        if catalog is None:
            return "SASE Plugins · unavailable"
        total = len(catalog.entries)
        installed = catalog.installed_count
        updates = catalog.updates_available
        age = humanize_age(catalog.age_seconds(self._now))
        return (
            f"{total} plugins · {installed} installed · "
            f"{updates} updates available · cached {age}"
        )

    def _status_message(self) -> str:
        if self._loading:
            return "Loading plugins…"
        if self._error is not None:
            return f"Could not load plugins:\n{self._error}"
        if self._catalog is None:
            return "Plugin catalog unavailable."
        if not self._catalog.entries:
            return "No SASE plugins found."
        if not any(entries for _, _, entries in self._grouped):
            return "No plugins match the current filter."
        return ""

    def _hints(self) -> str:
        return "j/k: navigate   /: filter   [ / ]: switch tab   Esc: close"

    # -- navigation --

    def action_next_option(self) -> None:
        """Move to the next non-header option."""
        option_list = self._option_list()
        if option_list is None:
            return
        current = option_list.highlighted
        start = 0 if current is None else current + 1
        for index in range(start, option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_prev_option(self) -> None:
        """Move to the previous non-header option."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return
        for index in range(option_list.highlighted - 1, -1, -1):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def action_focus_filter(self) -> None:
        try:
            self.query_one("#plugins-filter-input", _PluginsFilterInput).focus()
        except Exception:
            pass

    # -- input events --

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "plugins-filter-input":
            return
        self._filter_text = event.value
        self._rebuild_groups()
        self._rebuild_options()
        self._sync_state_visibility()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "plugins-filter-input":
            # Keep the filter applied; hand control back to the list.
            self.focus_default()

    def cancel_input(self) -> None:
        """Drop any in-progress filter and return focus to the list."""
        if self._filter_text:
            self._filter_text = ""
            self._set_filter_value("")
            self._rebuild_groups()
            self._rebuild_options()
            self._sync_state_visibility()
        self.focus_default()

    # -- helpers --

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plugins-list", OptionList)
        except Exception:
            return None

    @staticmethod
    def _is_item(option_list: OptionList, index: int) -> bool:
        try:
            opt = option_list.get_option_at_index(index)
        except Exception:
            return False
        return bool(opt.id) and not str(opt.id).startswith(_HEADER_PREFIX)

    def _set_filter_value(self, value: str) -> None:
        try:
            self.query_one("#plugins-filter-input", _PluginsFilterInput).value = value
        except Exception:
            pass

    def _update_static(self, selector: str, content: Text | str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass
