"""Rendering helpers for the Config Center Updates tab."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import restore_selection_by_identity
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.render import build_community_warning_panel, build_detail_panel
from sase.plugins.render_common import (
    _AVAILABLE_GLYPH,
    _COMMUNITY_STYLE,
    _INSTALLED_GLYPH,
    _UPDATE_GLYPH,
    build_incoming_commits_renderable,
)
from sase.updates.incoming_commits import IncomingCommits
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.versions import CorePackageVersion, CoreVersions

from .plugins_browser_constants import (
    _BUILTIN_GROUP,
    _COMMUNITY_GROUP,
    _DETAIL_PLACEHOLDER,
    _HEADER_PREFIX,
    _ITEM_PREFIX,
)


class PluginsBrowserRenderingMixin:
    """Rendering and selection helpers for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _catalog: PluginCatalog | None
        _core_incoming_commits: dict[str, IncomingCommits]
        _core_versions: CoreVersions
        _detail_debouncer: DetailPanelDebouncer | None
        _detail_name: str | None
        _error: str | None
        _filter_text: str
        _grouped: list[tuple[str, str, list[PluginCatalogEntry]]]
        _incoming_commits_enabled: bool
        _install_mode: str | None
        _loading: bool
        _marked_install: set[str]
        _now: float
        _offline: bool
        _restore_name: str | None
        _session_state: Any
        _syncing_plugin_options: bool
        _uv_tool: object | None
        _verbose: bool
        _dev_root: str | None

        def _detail_widget(self) -> Static | None: ...

        def _ensure_plugin_incoming_commits(
            self, entry: PluginCatalogEntry
        ) -> None: ...

        def _plugin_incoming_commits_state(
            self, entry: PluginCatalogEntry
        ) -> tuple[IncomingCommits | None, bool]: ...

        def _is_item(self, option_list: OptionList, index: int) -> bool: ...

        def _option_list(self) -> OptionList | None: ...

        def _hints(self) -> str: ...

        def _status_message(self) -> str: ...

        def _summary_text(self) -> Text: ...

        def _can_update_sase(self) -> bool: ...

        def _can_switch_mode(self) -> bool: ...

        def _sync_current_banner(self) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def _render_agent_clis(self) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

    def _render_all(self) -> None:
        self._rebuild_groups()
        self._prune_stale_marked_install()
        self._update_static("#sase-core-versions", self._core_versions_panel())
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        self._sync_current_banner()
        self._rebuild_options()
        self._sync_state_visibility()
        self._render_agent_clis()
        # A fresh load may have changed the highlighted plugin's data (e.g. a
        # new latest version), so force the detail to repaint immediately.
        self._render_detail_now(force=True)

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
        preferred = self._restore_name or self._session_state.plugins.identity
        self._restore_name = None
        entries = self._flat_plugin_entries()
        selected_name: str | None = None
        self._syncing_plugin_options = True
        try:
            option_list.clear_options()
            for opt in self._create_options():
                option_list.add_option(opt)
            if entries:
                row = restore_selection_by_identity(
                    entries,
                    prior_identity=preferred,
                    prior_visual_row=self._session_state.plugins.row,
                    identity_fn=lambda entry: entry.name,
                )
                selected_name = entries[row].name
                option_index = self._option_index_for_plugin(option_list, selected_name)
                if option_index is not None:
                    option_list.highlighted = option_index
                else:
                    self._skip_to_first_item(option_list)
                    selected_name = self._highlighted_name()
            else:
                option_list.highlighted = None
        finally:
            self._syncing_plugin_options = False
        self._record_plugin_bookmark(selected_name)

    def _flat_plugin_entries(self) -> list[PluginCatalogEntry]:
        return [entry for _, _, entries in self._grouped for entry in entries]

    @staticmethod
    def _option_index_for_plugin(option_list: OptionList, name: str) -> int | None:
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            opt = option_list.get_option_at_index(index)
            if opt.id == target:
                return index
        return None

    def _logical_row_for_plugin(self, name: str) -> int | None:
        for row, entry in enumerate(self._flat_plugin_entries()):
            if entry.name == name:
                return row
        return None

    def _record_plugin_bookmark(self, name: str | None) -> None:
        if name is None:
            if self._catalog is not None and not self._filter_text.strip():
                self._session_state.plugins.record(None, None)
            return
        self._session_state.plugins.record(name, self._logical_row_for_plugin(name))

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
        """A single list row: mark + status glyph + name + version + update."""
        text = Text()
        if entry.name in self._marked_install:
            text.append("[✓] ", style="bold #00D700")
        else:
            text.append("    ")
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
        if self._verbose:
            text.append("  ")
            text.append(f"★{entry.stars}", style="dim")
            if entry.updated_at:
                text.append("  ")
                text.append(entry.updated_at, style="dim")
        return text

    @staticmethod
    def _version_label(entry: PluginCatalogEntry) -> str:
        info = entry.installed
        if info.installed:
            if entry.latest.source == "editable":
                return PluginsBrowserRenderingMixin._dev_version_label(entry)
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

    @staticmethod
    def _dev_version_label(entry: PluginCatalogEntry) -> str:
        latest = entry.latest
        current = latest.current_version or entry.installed.version
        current_label = f"v{current}" if current else "editable"
        if entry.update_available and latest.version:
            return f"{current_label} → v{latest.version}  dev"
        state = PluginsBrowserRenderingMixin._dev_state_label(latest.state)
        if state:
            return f"{current_label}  dev · {state}"
        return f"{current_label}  dev"

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Highlight the first non-header option, if any."""
        for index in range(option_list.option_count):
            if self._is_item(option_list, index):
                option_list.highlighted = index
                return

    def _highlight_named(self, option_list: OptionList, name: str) -> bool:
        """Highlight the row for *name* if it is present; return success."""
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            opt = option_list.get_option_at_index(index)
            if opt.id == target:
                option_list.highlighted = index
                return True
        return False

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Repaint the detail panel for the newly highlighted row (debounced).

        The cursor highlight is already instant (the ``OptionList`` paints it
        itself); only the comparatively expensive detail rebuild is funneled
        through the debouncer so a held j/k collapses to one final paint. The
        hints line (which gates ``i install`` on the highlighted row) is cheap,
        so it refreshes immediately.
        """
        if event.option_list.id == "agent-clis-list":
            self._on_agent_cli_highlighted()  # type: ignore[attr-defined]
            return
        if event.option_list.id == "plugins-list":
            if self._syncing_plugin_options:
                return
            self._record_plugin_bookmark(self._highlighted_name())
            self._update_static("#plugins-hints", self._hints())
            self._schedule_detail()

    def _schedule_detail(self) -> None:
        debouncer = self._detail_debouncer
        if debouncer is None:
            self._render_detail_now()
            return
        debouncer.schedule(self._render_detail_now)

    def _render_detail_now(self, *, force: bool = False) -> None:
        """Paint the detail panel for the currently highlighted plugin.

        Re-reads the live highlight (so the latest selection wins after a
        debounced burst) and skips redundant work when the same plugin is
        already shown, unless *force* is set (used after a reload whose data
        may have changed under an unchanged selection).
        """
        entry = self._current_entry()
        name = entry.name if entry is not None else None
        if not force and name == self._detail_name:
            return
        self._detail_name = name
        self._update_detail(entry)

    def _update_detail(self, entry: PluginCatalogEntry | None) -> None:
        detail = self._detail_widget()
        if detail is None:
            return
        if entry is None:
            detail.update(_DETAIL_PLACEHOLDER)
            return
        self._ensure_plugin_incoming_commits(entry)
        detail.update(self._detail_renderable(entry))

    def _detail_renderable(self, entry: PluginCatalogEntry) -> RenderableType:
        """The ``show``-equivalent detail: community warning (if any) + panel."""
        parts: list[RenderableType] = []
        if entry.is_community:
            parts.append(build_community_warning_panel(entry))
        incoming, loading = self._plugin_incoming_commits_state(entry)
        parts.append(
            build_detail_panel(
                entry,
                incoming_commits=incoming,
                incoming_commits_loading=loading,
            )
        )
        return Group(*parts)

    def _core_versions_panel(self) -> Panel:
        """Compact installed/latest display for SASE's own packages."""
        body: list[RenderableType] = [self._core_versions_table()]
        mode_line = self._mode_line()
        if mode_line is not None:
            body.append(Text(""))
            body.append(mode_line)
        incoming_sections = self._core_incoming_sections()
        if incoming_sections:
            body.append(Text(""))
            body.extend(incoming_sections)
        body.append(Text(""))
        if isinstance(self._uv_tool, NotUvToolInstall):
            warning = Text()
            warning.append("! ", style="yellow")
            warning.append(
                "`sase update` unavailable — sase is not a `uv tool` install.",
                style="yellow",
            )
            body.append(warning)
        else:
            cta = Text()
            if self._can_update_sase():
                cta.append("u", style="bold #AF87FF")
                cta.append("  run `sase update`", style="cyan")
                cta.append("  ·  upgrades sase core + all plugins", style="dim")
            if cta.plain:
                body.append(cta)
        return Panel(Group(*body), title="SASE Core", border_style="#AF87FF")

    def _mode_line(self) -> Text | None:
        if isinstance(self._uv_tool, NotUvToolInstall):
            return None
        mode = self._install_mode
        if mode is None:
            return None
        labels = {
            "managed": "PyPI (managed)",
            "dev": "Dev (editable)",
            "mixed": "Mixed",
        }
        line = Text()
        line.append("Mode  ", style="dim")
        line.append(labels.get(mode, mode), style="bold #AF87FF")
        if mode == "dev" and self._dev_root:
            line.append(f" · {self._dev_root}", style="dim")
        return line

    def _core_incoming_sections(self) -> list[RenderableType]:
        if not self._incoming_commits_enabled:
            return []
        sections: list[RenderableType] = []
        for package in self._core_versions.packages:
            if not package.update_available:
                continue
            incoming = self._core_incoming_commits.get(package.name)
            loading = self._loading and incoming is None
            if incoming is None and not loading:
                continue
            label = Text(package.name, style="bold")
            sections.append(
                Group(
                    label,
                    build_incoming_commits_renderable(incoming, loading=loading),
                )
            )
        return sections

    def _core_versions_table(self) -> Table:
        table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
        table.add_column(no_wrap=True)  # glyph
        table.add_column(style="bold", no_wrap=True)  # name
        table.add_column(no_wrap=True)  # installed/latest
        table.add_column()  # note
        for package in self._core_versions.packages:
            table.add_row(
                self._core_glyph(package),
                Text(package.name),
                self._core_version_cell(package),
                self._core_note_cell(package),
            )
        return table

    @staticmethod
    def _core_glyph(package: CorePackageVersion) -> Text:
        if package.update_available:
            return Text(_UPDATE_GLYPH, style="bold cyan")
        return Text("·", style="dim")

    @staticmethod
    def _core_version_cell(package: CorePackageVersion) -> Text:
        installed = package.installed_version
        latest = package.latest_version
        if installed is None:
            return Text("not installed", style="dim")
        if package.update_available and latest:
            cell = Text()
            cell.append(f"v{installed}", style="dim")
            cell.append(" → ", style="dim")
            cell.append(f"v{latest}", style="cyan")
            if package.install_type == "editable":
                cell.append("   dev", style="dim")
            return cell
        cell = Text(f"v{installed}", style="dim")
        if package.install_type == "editable":
            cell.append("   dev", style="dim")
        return cell

    @staticmethod
    def _core_note_cell(package: CorePackageVersion) -> Text:
        if package.installed_version is None:
            return Text("not installed", style="dim")
        if not package.latest_checked:
            return Text("checking latest…", style="dim")
        if package.update_available:
            return Text("update available", style="cyan")
        if package.install_type == "editable":
            label = PluginsBrowserRenderingMixin._dev_state_label(package.latest_state)
            if label:
                return Text(label, style="dim")
            return Text("up to date", style="dim")
        if package.latest_version:
            return Text("up to date", style="dim")
        return Text("latest unknown", style="dim")

    @staticmethod
    def _dev_state_label(state: str | None) -> str:
        labels = {
            "current": "",
            "update_available": "update available",
            "dirty": "local changes",
            "diverged": "diverged",
            "detached": "detached HEAD",
            "no_upstream": "no upstream",
            "offline": "offline",
            "fetch_failed": "fetch failed",
            "unavailable": "unavailable",
        }
        return labels.get(state or "", state or "")

    def _current_entry(self) -> PluginCatalogEntry | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        if not opt.id or str(opt.id).startswith(_HEADER_PREFIX):
            return None
        return self._entry_by_name(str(opt.id).removeprefix(_ITEM_PREFIX))

    def _entry_by_name(self, name: str) -> PluginCatalogEntry | None:
        for _, _, entries in self._grouped:
            for entry in entries:
                if entry.name == name:
                    return entry
        return None

    def _highlighted_name(self) -> str | None:
        entry = self._current_entry()
        return entry.name if entry is not None else None

    def _can_install_entry(self, entry: PluginCatalogEntry | None) -> bool:
        """Whether *entry* can be installed or marked for install now."""
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        return entry is not None and not entry.installed.installed

    def _refresh_install_mark_row(self, name: str) -> bool:
        """Patch one plugin row after its mark bit changes."""
        option_list = self._option_list()
        entry = self._entry_by_name(name)
        if option_list is None or entry is None:
            return False
        target = f"{_ITEM_PREFIX}{name}"
        for index in range(option_list.option_count):
            option = option_list.get_option_at_index(index)
            if option.id == target:
                option_list.replace_option_prompt_at_index(index, self._row_text(entry))
                return True
        return False

    def _advance_install_mark_selection(self) -> None:
        """Move the cursor to the next installable row after a mark toggle."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return
        start = option_list.highlighted
        for offset in range(1, option_list.option_count + 1):
            index = (start + offset) % option_list.option_count
            if not self._is_item(option_list, index):
                continue
            option = option_list.get_option_at_index(index)
            entry = self._entry_by_name(str(option.id).removeprefix(_ITEM_PREFIX))
            if self._can_install_entry(entry):
                option_list.highlighted = index
                return

    def _clear_install_marks(self) -> None:
        """Clear all install marks and patch visible rows in place."""
        if not self._marked_install:
            return
        names = tuple(self._marked_install)
        self._marked_install.clear()
        for name in names:
            self._refresh_install_mark_row(name)
        self._update_static("#plugins-hints", self._hints())

    def _prune_stale_marked_install(self) -> None:
        """Drop marks for missing, installed, or currently un-installable rows."""
        if not self._marked_install:
            return
        live = {
            entry.name
            for _, _, entries in self._grouped
            for entry in entries
            if self._can_install_entry(entry)
        }
        self._marked_install &= live
