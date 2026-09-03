"""Rendering helpers for the Config Center Updates tab."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import (
    ProgrammaticSelectionGuard,
    restore_selection_by_identity,
)
from sase.agent_clis.models import AgentCliStatus
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.render import build_community_warning_panel, build_detail_panel
from sase.plugins.render_common import (
    _AVAILABLE_GLYPH,
    _INSTALLED_GLYPH,
    _UPDATE_GLYPH,
    build_incoming_commits_renderable,
)
from sase.updates.incoming_commits import IncomingCommits
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.versions import CorePackageVersion, CoreVersions

from .pane_entry_jump import apply_jump_hint_prefix
from .plugins_browser_constants import (
    _DETAIL_PLACEHOLDER,
    _HEADER_PREFIX,
    _ROW_PREFIX,
)
from .plugins_browser_rows import UpdateRow, UpdateScope, dev_state_label, select_rows


class PluginsBrowserRenderingMixin:
    """Rendering and selection helpers for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _catalog: PluginCatalog | None
        _core_incoming_commits: dict[str, IncomingCommits]
        _core_versions: CoreVersions
        _detail_debouncer: DetailPanelDebouncer | None
        _detail_key: str | None
        _filter_text: str
        _grouped: list[tuple[str, str, list[UpdateRow]]]
        _incoming_commits_enabled: bool
        _install_mode: str | None
        _loading: bool
        _marked: set[str]
        _now: float
        _offline: bool
        _restore_key: str | None
        _row_logical_row: dict[str, int]
        _row_option_index: dict[str, int]
        _rows: tuple[UpdateRow, ...]
        _rows_by_key: dict[str, UpdateRow]
        _scope: UpdateScope
        _session_state: Any
        _selection_guard: ProgrammaticSelectionGuard
        _uv_tool: object | None
        _verbose: bool
        _dev_root: str | None

        def _agent_cli_detail_panel(self, status: AgentCliStatus) -> Panel: ...

        def _detail_widget(self) -> Static | None: ...

        def _ensure_plugin_incoming_commits(
            self, entry: PluginCatalogEntry
        ) -> None: ...

        def _ensure_plugin_latest(self, entry: PluginCatalogEntry) -> None: ...

        def _plugin_incoming_commits_state(
            self, entry: PluginCatalogEntry
        ) -> tuple[IncomingCommits | None, bool]: ...

        def _is_item(self, option_list: OptionList, index: int) -> bool: ...

        def _option_list(self) -> OptionList | None: ...

        def _hints(self) -> str: ...

        def _refresh_scope_strip(self) -> None: ...

        def _render_agent_cli_history(self, *, force: bool = False) -> None: ...

        def _sync_header(self) -> None: ...

        def _sync_state_visibility(self) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

        def jump_hint_for(self, index: int) -> str | None: ...

        def reset_jump_state(self, *, repaint: bool = False) -> None: ...

    def _render_all(self) -> None:
        # A reload can add, drop, or reorder rows, so any painted hints and the
        # back stack's indices are dropped before the rows are rebuilt below.
        self.reset_jump_state()
        self._rebuild_groups()
        self._prune_marks()
        self._refresh_scope_strip()
        self._sync_header()
        self._update_static("#updates-hints", self._hints())
        self._rebuild_options()
        self._sync_state_visibility()
        self._render_detail_now(force=True)

    def _rebuild_groups(self) -> None:
        self._grouped = select_rows(
            self._rows,
            scope=self._scope,
            needle=self._filter_text.strip().casefold(),
        )

    def _rebuild_options(self, *, reuse_options: bool = False) -> None:
        option_list = self._option_list()
        if option_list is None:
            return
        preferred = self._restore_key or self._session_state.rows.identity
        self._restore_key = None
        rows = self._flat_rows()
        self._selection_guard.clear()
        reuse: dict[str, Option] = {}
        if reuse_options:
            reuse = {
                str(opt.id): opt for opt in option_list.options if opt.id is not None
            }
        options = self._create_options(reuse)
        option_list.set_options(options)
        self._rebuild_row_identity_maps(options, rows)
        selected_key: str | None = None
        if rows:
            if preferred is None and self._session_state.rows.row is None:
                row_index = next(
                    (i for i, row in enumerate(rows) if row.update_available), 0
                )
            else:
                row_index = restore_selection_by_identity(
                    rows,
                    prior_identity=preferred,
                    prior_visual_row=self._session_state.rows.row,
                    identity_fn=lambda row: row.key,
                )
            selected_key = rows[row_index].key
            option_index = self._row_option_index.get(selected_key)
            if option_index is not None:
                self._selection_guard.prepare(selected_key, row_index)
                option_list.highlighted = option_index
        else:
            option_list.highlighted = None
        self._record_bookmark(selected_key)
        self._update_static("#updates-hints", self._hints())

    def _flat_rows(self) -> list[UpdateRow]:
        return [row for _, _, rows in self._grouped for row in rows]

    def _rebuild_row_identity_maps(
        self, options: list[Option], rows: list[UpdateRow]
    ) -> None:
        """(Re)build the key-keyed lookup maps for the just-rebuilt rows."""
        self._row_option_index = {
            str(opt.id).removeprefix(_ROW_PREFIX): index
            for index, opt in enumerate(options)
            if opt.id and not str(opt.id).startswith(_HEADER_PREFIX)
        }
        self._row_logical_row = {row.key: index for index, row in enumerate(rows)}

    def _record_bookmark(self, key: str | None) -> None:
        if key is None:
            if self._rows and not self._filter_text.strip():
                self._session_state.rows.record(None, None)
            return
        self._session_state.rows.record(key, self._row_logical_row.get(key))

    def _create_options(self, reuse: dict[str, Option] | None = None) -> list[Option]:
        """Build OptionList items: disabled section headers + inventory rows.

        *reuse* maps option ids from the live list. Filter and scope changes
        keep those Option objects (and their cached visuals) so typing does
        not re-visualize every surviving row.
        """
        by_id = reuse or {}
        options: list[Option] = []
        row_index = 0
        for header_text, style, rows in self._grouped:
            section_key = rows[0].section
            header_id = f"{_HEADER_PREFIX}{section_key}"
            header = by_id.get(header_id)
            if header is None:
                header = Option(
                    Text(header_text, style=style),
                    id=header_id,
                    disabled=True,
                )
            options.append(header)
            for row in rows:
                option_id = f"{_ROW_PREFIX}{row.key}"
                existing = by_id.get(option_id)
                prompt = self._row_label(row_index, row)
                prompt_plain = prompt.plain if hasattr(prompt, "plain") else str(prompt)
                current_plain = ""
                if existing is not None:
                    current = existing.prompt
                    current_plain = (
                        current.plain if hasattr(current, "plain") else str(current)
                    )
                if existing is None or current_plain != prompt_plain:
                    existing = Option(prompt, id=option_id)
                options.append(existing)
                row_index += 1
        return options

    def _row_label(self, row_index: int, row: UpdateRow) -> Text:
        """The row text for *row*, jump-hint decorated while hints are up.

        *row_index* is the entry's position in the flat item list, which is
        the logical index space the shared jump mixin allocates hints over.
        """
        label = self._row_text(row)
        hint = self.jump_hint_for(row_index)
        if hint is None:
            return label
        return apply_jump_hint_prefix(label, hint)

    def _row_text(self, row: UpdateRow) -> Text:
        """A single list row: mark + status glyph + name + version + extras."""
        text = Text()
        if row.key in self._marked:
            text.append("[✓] ", style="bold #00D700")
        else:
            text.append("    ")
        if row.installed:
            text.append(_INSTALLED_GLYPH, style="green")
        else:
            text.append(_AVAILABLE_GLYPH, style="dim")
        text.append(" ")
        text.append(row.label, style=f"bold {row.accent}")
        if row.version_label:
            text.append("  ")
            text.append(row.version_label, style="dim")
        if row.kind == "agent-cli":
            text.append("  ")
            text.append(f"[{row.source.replace('_', ' ')}]", style="bold dim")
        if row.update_available:
            text.append("  ")
            text.append(_UPDATE_GLYPH, style="bold cyan")
        if self._verbose and row.kind == "plugin":
            entry = row.payload
            if isinstance(entry, PluginCatalogEntry):
                text.append("  ")
                text.append(f"★{entry.stars}", style="dim")
                if entry.updated_at:
                    text.append("  ")
                    text.append(entry.updated_at, style="dim")
        return text

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Repaint the detail panel for the newly highlighted row (debounced).

        The cursor highlight is already instant (the ``OptionList`` paints it
        itself); only the comparatively expensive detail rebuild is funneled
        through the debouncer so a held j/k collapses to one final paint. The
        hints line (which gates row actions on the highlighted row) is cheap,
        so it refreshes immediately.
        """
        if event.option_list.id != "updates-list":
            return
        if event.option is None or event.option.id is None:
            return
        option_id = str(event.option.id)
        if option_id.startswith(_HEADER_PREFIX):
            return
        key = option_id.removeprefix(_ROW_PREFIX)
        current = self._highlighted_row()
        current_key = current.key if current is not None else None
        current_row = (
            self._row_logical_row.get(current_key) if current_key is not None else None
        )
        if (
            current_key is None
            or current_row is None
            or key != current_key
            or self._selection_guard.should_ignore(
                key,
                current_row,
                current_identity=current_key,
                current_row=current_row,
            )
        ):
            return
        self._record_bookmark(current_key)
        self._update_static("#updates-hints", self._hints())
        self._schedule_detail()

    def _schedule_detail(self) -> None:
        debouncer = self._detail_debouncer
        if debouncer is None:
            self._render_detail_now()
            return
        debouncer.schedule(self._render_detail_now)

    def _render_detail_now(self, *, force: bool = False) -> None:
        """Paint the detail panel for the currently highlighted row.

        Re-reads the live highlight (so the latest selection wins after a
        debounced burst) and skips redundant work when the same row is
        already shown, unless *force* is set (used after a reload whose data
        may have changed under an unchanged selection).
        """
        row = self._highlighted_row()
        key = row.key if row is not None else None
        if not force and key == self._detail_key:
            return
        self._detail_key = key
        detail = self._detail_widget()
        if detail is None:
            return
        try:
            history = self.query_one("#updates-history", Static)  # type: ignore[attr-defined]
        except Exception:
            history = None
        if row is None:
            detail.update(_DETAIL_PLACEHOLDER)
            if history is not None:
                history.display = False
            return
        if row.kind == "core" and isinstance(row.payload, CorePackageVersion):
            detail.update(self._core_detail_panel(row.payload))
            if history is not None:
                history.display = False
            return
        if row.kind == "plugin" and isinstance(row.payload, PluginCatalogEntry):
            entry = row.payload
            self._ensure_plugin_incoming_commits(entry)
            self._ensure_plugin_latest(entry)
            detail.update(self._detail_renderable(entry))
            if history is not None:
                history.display = False
            return
        if row.kind == "agent-cli":
            if isinstance(row.payload, AgentCliStatus):
                detail.update(self._agent_cli_detail_panel(row.payload))
            if history is not None:
                history.display = True
                self._render_agent_cli_history(force=force)

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

    def _core_detail_panel(self, package: CorePackageVersion) -> Panel:
        """Per-package installed/latest display for one SASE core package."""
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column(style="bold", no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column()
        table.add_row(
            self._core_glyph(package),
            Text(package.name),
            self._core_version_cell(package),
            self._core_note_cell(package),
        )
        body: list[RenderableType] = [table]
        mode_line = self._mode_line()
        if mode_line is not None:
            body.append(Text(""))
            body.append(mode_line)
        incoming = self._core_incoming_section(package)
        if incoming is not None:
            body.append(Text(""))
            body.append(incoming)
        if isinstance(self._uv_tool, NotUvToolInstall):
            warning = Text()
            warning.append("! ", style="yellow")
            warning.append(
                "`sase update` unavailable — sase is not a `uv tool` install.",
                style="yellow",
            )
            body.append(warning)
        return Panel(Group(*body), title=package.name, border_style="#AF87FF")

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

    def _core_incoming_section(
        self, package: CorePackageVersion
    ) -> RenderableType | None:
        if not self._incoming_commits_enabled:
            return None
        if not package.update_available:
            return None
        incoming = self._core_incoming_commits.get(package.name)
        loading = self._loading and incoming is None
        if incoming is None and not loading:
            return None
        return build_incoming_commits_renderable(incoming, loading=loading)

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
            label = dev_state_label(package.latest_state)
            if label:
                return Text(label, style="dim")
            return Text("up to date", style="dim")
        if package.latest_version:
            return Text("up to date", style="dim")
        return Text("latest unknown", style="dim")

    def _current_entry(self) -> PluginCatalogEntry | None:
        row = self._highlighted_row()
        if row is None or row.kind != "plugin":
            return None
        payload = row.payload
        return payload if isinstance(payload, PluginCatalogEntry) else None

    def _highlighted_name(self) -> str | None:
        entry = self._current_entry()
        return entry.name if entry is not None else None

    def _highlighted_row(self) -> UpdateRow | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(option_list.highlighted)
        except Exception:
            return None
        option_id = opt.id
        if not option_id or str(option_id).startswith(_HEADER_PREFIX):
            return None
        return self._rows_by_key.get(str(option_id).removeprefix(_ROW_PREFIX))

    def _marked_keys_with(self, capability: str) -> tuple[str, ...]:
        """Marked row keys whose live row still carries *capability*."""
        return tuple(
            key
            for key in sorted(self._marked)
            if (row := self._rows_by_key.get(key)) is not None
            and capability in row.capabilities
        )

    def _marked_plugin_names(self) -> tuple[str, ...]:
        """Plugin names currently marked for install."""
        return tuple(
            key.removeprefix("plugin:") for key in self._marked_keys_with("install")
        )

    def _marked_cli_names(self) -> tuple[str, ...]:
        """Agent-CLI provider names currently marked for update."""
        return tuple(
            key.removeprefix("cli:") for key in self._marked_keys_with("mark_update")
        )

    def _refresh_row(self, key: str) -> bool:
        """Patch one visible inventory row in place after its mark bit changes."""
        option_list = self._option_list()
        row = self._rows_by_key.get(key)
        index = self._row_option_index.get(key)
        if option_list is None or row is None or index is None:
            return False
        option_list.replace_option_prompt_at_index(index, self._row_text(row))
        return True

    def _advance_mark_selection(self, capability: str) -> None:
        """Move the cursor to the next row carrying *capability* after a toggle."""
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return
        start = option_list.highlighted
        for offset in range(1, option_list.option_count + 1):
            index = (start + offset) % option_list.option_count
            if not self._is_item(option_list, index):
                continue
            option = option_list.get_option_at_index(index)
            key = str(option.id).removeprefix(_ROW_PREFIX)
            row = self._rows_by_key.get(key)
            if row is not None and capability in row.capabilities:
                option_list.highlighted = index
                return

    def _clear_marks(self, keys: Iterable[str] | None = None) -> None:
        """Clear *keys* (or every mark) and patch still-visible rows in place."""
        to_clear = set(self._marked if keys is None else keys) & self._marked
        if not to_clear:
            return
        self._marked -= to_clear
        for key in to_clear:
            self._refresh_row(key)
        self._update_static("#updates-hints", self._hints())

    def _prune_marks(self) -> None:
        """Drop marks whose row is gone or no longer carries a markable capability."""
        if not self._marked:
            return
        live = {
            row.key
            for row in self._rows
            if "install" in row.capabilities or "mark_update" in row.capabilities
        }
        self._marked &= live
