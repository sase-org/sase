"""Status, summary, and hint text for the Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static

from sase.plugins.catalog import PluginCatalog
from sase.plugins.render_common import humanize_age
from sase.uv_tool.detect import NotUvToolInstall

from .plugins_browser_constants import _SCOPE_NAV_HINT
from .plugins_browser_rows import UpdateRow, UpdateScope

_CURRENT_ACCENT = "#00D700"


class PluginsBrowserStatusMixin:
    """Summary, empty-state, and action-affordance text."""

    if TYPE_CHECKING:
        from sase.agent_clis.models import AgentCliStatus
        from sase.uv_tool.versions import CoreVersions

        _agent_cli_error: str | None
        _agent_cli_statuses: tuple[AgentCliStatus, ...]
        _catalog: PluginCatalog | None
        _core_error: str | None
        _core_versions: CoreVersions
        _error: str | None
        _filter_text: str
        _grouped: list[tuple[str, str, list[UpdateRow]]]
        _loading: bool
        _marked: set[str]
        _now: float
        _rows_by_key: dict[str, UpdateRow]
        _offline: bool
        _install_mode: str | None
        _rows: tuple[UpdateRow, ...]
        _scope: UpdateScope
        _uv_tool: object | None
        _verbose: bool

        def _flat_rows(self) -> list[UpdateRow]: ...

        def _has_item_rows(self) -> bool: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        @property
        def jump_mode_active(self) -> bool: ...

        @property
        def jump_back_stack(self) -> list[int]: ...

    def _all_up_to_date(self) -> bool:
        """Whether every update source has been checked and is current."""
        if self._loading or self._offline:
            return False
        if self._uv_tool is None or isinstance(self._uv_tool, NotUvToolInstall):
            return False
        return (
            self._core_source_current()
            and self._plugin_source_current()
            and self._agent_cli_source_current()
        )

    def _core_source_current(self) -> bool:
        """Whether every SASE core package has known-current latest evidence."""
        if self._core_error is not None:
            return False
        packages = self._core_versions.packages
        if not packages:
            return False
        return all(
            package.installed_version is not None
            and package.latest_checked
            and package.latest_error is None
            and package.latest_version is not None
            and not package.update_available
            for package in packages
        )

    def _plugin_source_current(self) -> bool:
        """Whether every installed plugin has known-current latest evidence."""
        if self._error is not None:
            return False
        catalog = self._catalog
        if catalog is None:
            return False
        return all(
            not entry.installed.installed
            or (
                entry.latest.checked
                and entry.latest.source != "unknown"
                and entry.latest.error is None
                and not entry.update_available
            )
            for entry in catalog.entries
        )

    def _agent_cli_source_current(self) -> bool:
        """Whether every installed agent CLI has known-current latest evidence."""
        if self._agent_cli_error is not None:
            return False
        return all(
            status.latest_version is not None
            and status.version_error is None
            and status.latest_error is None
            and not status.update_available
            for status in self._agent_cli_statuses
            if status.installed
        )

    def _sase_up_to_date(self) -> bool:
        """Whether the SASE/core/plugin update sources are checked and current."""
        if self._loading or self._offline:
            return False
        if not self._core_source_current() or not self._plugin_source_current():
            return False
        if self._uv_tool is None or isinstance(self._uv_tool, NotUvToolInstall):
            return False
        return True

    def _all_current_banner(self) -> Panel:
        """Confirm that SASE, plugins, and installed agent CLIs are current."""
        catalog = self._catalog
        installed_count = catalog.installed_count if catalog is not None else 0
        installed_agent_clis = sum(
            status.installed for status in self._agent_cli_statuses
        )
        package_versions = {
            package.name: package.installed_version
            for package in self._core_versions.packages
        }
        version_line = (
            f"sase v{package_versions.get('sase') or '?'} · "
            f"sase-core v{package_versions.get('sase-core') or '?'} · "
            f"{installed_count} {self._plural(installed_count, 'plugin')} current · "
            f"{installed_agent_clis} agent "
            f"{self._plural(installed_agent_clis, 'CLI')} current"
        )
        age = humanize_age(catalog.age_seconds(self._now)) if catalog else "unknown"

        copy = Table.grid(expand=True)
        copy.add_column()
        headline = Text("You're all up to date", style=f"bold {_CURRENT_ACCENT}")
        detail = Text(version_line, style="dim")
        freshness = Text(f"Last checked {age} · press r to re-check", style="dim")
        copy.add_row(headline)
        copy.add_row(detail)
        copy.add_row(freshness)

        layout = Table.grid(padding=(0, 1), expand=True)
        layout.add_column(
            no_wrap=True, justify="center", style=f"bold {_CURRENT_ACCENT}"
        )
        layout.add_column(ratio=1)
        layout.add_row("✓", copy)

        return Panel(
            Group(layout),
            border_style=_CURRENT_ACCENT,
            padding=(1, 2),
        )

    def _header_renderable(self) -> RenderableType:
        if self._all_up_to_date():
            return self._all_current_banner()
        return self._summary_text()

    def _sync_header(self) -> None:
        """Refresh the always-visible header (banner or summary)."""
        try:
            header = cast(
                Static,
                self.query_one("#updates-header", Static),  # type: ignore[attr-defined]
            )
        except Exception:
            return
        header.update(self._header_renderable())

    def _sync_state_visibility(self) -> None:
        """Show the list when populated; keep a failed-source status above it.

        A *reload* (refresh / offline toggle) keeps the already-painted rows
        visible -- the header reports loading instead -- so the list never
        flashes away and the focused highlight is preserved. The status
        placeholder is reserved for the initial load, the error state, and the
        genuinely empty / no-match cases.
        """
        try:
            status = cast(
                Static,
                self.query_one("#updates-status", Static),  # type: ignore[attr-defined]
            )
            option_list = cast(
                OptionList,
                self.query_one("#updates-list", OptionList),  # type: ignore[attr-defined]
            )
        except Exception:
            return
        message = self._status_message()
        status.update(message)
        status.display = bool(message)
        option_list.display = self._has_item_rows()

    def _summary_text(self) -> Text:
        """Header digest: row counts, cache age, mode, and source warnings."""
        text = Text(self._summary_line())
        if self._loading:
            return text
        text.append("\n")
        text.append(self._freshness_line())
        hint = self._summary_hint()
        if hint is not None:
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(hint, style="yellow")
        for source, message in self._failed_source_lines():
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(f"{source}: {message}", style="yellow")
        if isinstance(self._uv_tool, NotUvToolInstall):
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(
                "Plugin changes unavailable — sase is not a `uv tool` install.",
                style="yellow",
            )
        return text

    def _summary_line(self) -> str:
        if self._loading:
            return "Updates · loading..."
        core_updates = [
            row for row in self._rows if row.kind == "core" and row.update_available
        ]
        plugin_updates = sum(
            row.kind == "plugin" and row.update_available for row in self._rows
        )
        agent_cli_updates = sum(
            row.kind == "agent-cli" and row.update_available for row in self._rows
        )
        total = len(core_updates) + plugin_updates + agent_cli_updates
        parts = [f"↑ {total} {self._plural(total, 'update')}"]
        if len(core_updates) == 1:
            row = core_updates[0]
            installed = row.installed_version or "?"
            latest = row.latest_version or "?"
            parts.append(f"{row.label} {installed} → {latest}")
        else:
            parts.append(f"{len(core_updates)} SASE")
        parts.append(f"{plugin_updates} {self._plural(plugin_updates, 'plugin')}")
        parts.append(
            f"{agent_cli_updates} agent {self._plural(agent_cli_updates, 'CLI')}"
        )
        return " · ".join(parts)

    def _freshness_line(self) -> str:
        parts: list[str] = []
        parts.append(f"checked {self._cache_age_label()}")
        parts.append(self._install_mode_label())
        if self._offline:
            parts.append("⚠ OFFLINE")
        return " · ".join(parts)

    def _cache_age_label(self) -> str:
        catalog = self._catalog
        if catalog is None:
            return "unknown"
        return humanize_age(catalog.age_seconds(self._now))

    def _install_mode_label(self) -> str:
        if isinstance(self._uv_tool, NotUvToolInstall):
            return "not uv tool"
        mode = self._install_mode
        labels = {
            "managed": "PyPI (managed)",
            "dev": "Dev (editable)",
            "mixed": "Mixed",
        }
        return labels.get(mode or "", mode or "install mode unknown")

    def _failed_source_lines(self) -> tuple[tuple[str, str], ...]:
        lines: list[tuple[str, str]] = []
        if self._core_error is not None:
            lines.append(("SASE", self._core_error))
        else:
            core_message = self._row_source_failure_message("core")
            if core_message is not None:
                lines.append(("SASE", core_message))
        if self._error is not None:
            lines.append(("Plugins", self._error))
        else:
            plugin_message = self._row_source_failure_message("plugin")
            if plugin_message is not None:
                lines.append(("Plugins", plugin_message))
        if self._agent_cli_error is not None:
            lines.append(("Agent CLIs", self._agent_cli_error))
        else:
            agent_cli_message = self._row_source_failure_message("agent-cli")
            if agent_cli_message is not None:
                lines.append(("Agent CLIs", agent_cli_message))
        return tuple(lines)

    def _row_source_failure_message(self, kind: str) -> str | None:
        rows = [row for row in self._rows if row.kind == kind and row.installed]
        failures = [(row.label, row.error) for row in rows if row.error is not None]
        if failures:
            return self._failure_message("latest probe failed", failures)

        unknown_labels: list[str] = []
        for row in rows:
            if kind == "core":
                latest_checked = bool(getattr(row.payload, "latest_checked", False))
                if not latest_checked or row.latest_version is None:
                    unknown_labels.append(row.label)
            elif kind == "plugin":
                if row.source == "unknown" or row.latest_version is None:
                    unknown_labels.append(row.label)
            elif row.latest_version is None:
                unknown_labels.append(row.label)
        if unknown_labels:
            return self._labels_message("latest version unknown", unknown_labels)
        return None

    def _failure_message(self, prefix: str, failures: list[tuple[str, str]]) -> str:
        label, message = failures[0]
        if len(failures) == 1:
            return f"{prefix} for {label}: {message}"
        return f"{prefix} for {len(failures)} rows ({label}: {message})"

    def _labels_message(self, prefix: str, labels: list[str]) -> str:
        if len(labels) == 1:
            return f"{prefix} for {labels[0]}"
        preview = ", ".join(labels[:3])
        if len(labels) > 3:
            preview = f"{preview}, ..."
        return f"{prefix} for {len(labels)} rows ({preview})"

    def _summary_hint(self) -> str | None:
        """A warning / stale-cache line to surface under the counts, if any."""
        catalog = self._catalog
        if self._loading or catalog is None:
            return None
        if catalog.warnings:
            return catalog.warnings[0]
        if catalog.stale:
            age = humanize_age(catalog.age_seconds(self._now))
            return f"cache is stale (last updated {age}) — press r to refresh"
        return None

    def _status_message(self) -> str:
        if self._loading:
            return "Loading updates…"
        if self._error is not None:
            return f"Could not load plugins:\n{self._error}"
        if self._agent_cli_error is not None and not self._rows:
            return f"Could not load agent CLIs:\n{self._agent_cli_error}"
        if not self._rows:
            return "No updates found."
        if not self._has_item_rows():
            if self._filter_text.strip():
                return "Nothing matches the current filter."
            if self._scope == "outdated":
                return "Nothing needs an update."
            if self._scope == "installed":
                return "Nothing is installed."
            return "No updates found."
        return ""

    def _hints(self) -> str:
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action} · esc cancel"
        offline = " (on)" if self._offline else " off"
        verbose = " (on)" if self._verbose else " verb"
        parts: list[str] = []
        install_marks = sum(
            1
            for key in self._marked
            if (row := self._rows_by_key.get(key)) is not None
            and "install" in row.capabilities
        )
        if install_marks:
            parts.append(f"i install ({install_marks})")
        elif self._can_install_highlighted():
            parts.append("i install")
        if self._can_mark_highlighted():
            parts.append("I/space mark")
        row = self._highlighted_row()
        if self._can_update_sase():
            parts.append("u update core + plugins")
        parts.append("A update CLIs")
        parts.append("a sync agents")
        if self._can_switch_mode():
            parts.append("m switch")
        if self._can_update_highlighted():
            parts.append("U upd ↑")
        if self._can_uninstall_highlighted():
            parts.append("x rm")
        if row is not None and row.kind == "agent-cli":
            parts.append("H history")
        parts.extend(
            [
                "r reload",
                "ctrl+d/u scroll",
                f"o{offline}",
                f"v{verbose}",
                "/ filter",
                "' jump",
                _SCOPE_NAV_HINT,
                "Tab/Shift+Tab tab",
            ]
        )
        if self._marked:
            parts.append("esc clear")
        else:
            parts.append("esc")
        body = " · ".join(parts)
        aggregate = self._marked_work_line()
        if aggregate is None:
            return body
        return f"{aggregate}\n{body}"

    def _marked_work_line(self) -> str | None:
        """The always-visible marked-work aggregate; None when nothing is marked."""
        if not self._marked:
            return None
        install_count = 0
        cli_count = 0
        for key in self._marked:
            row = self._rows_by_key.get(key)
            if row is None:
                continue
            if "install" in row.capabilities:
                install_count += 1
            elif "mark_update" in row.capabilities:
                cli_count += 1
        chunks: list[str] = []
        if install_count:
            chunks.append(
                f"{install_count} {self._plural(install_count, 'plugin install')}"
            )
        if cli_count:
            chunks.append(f"{cli_count} {self._plural(cli_count, 'CLI update')}")
        if not chunks:
            chunks.append(f"{len(self._marked)} marked")
        visible = {row.key for row in self._flat_rows()}
        hidden = len(self._marked) - sum(1 for key in self._marked if key in visible)
        line = "Marked: " + " · ".join(chunks)
        if hidden:
            line += f" ({hidden} hidden by filter)"
        return line

    def _can_install_highlighted(self) -> bool:
        """Whether the highlighted row can be installed right now."""
        row = self._highlighted_row()
        return row is not None and "install" in row.capabilities

    def _can_mark_highlighted(self) -> bool:
        """Whether the highlighted row can be marked for install or CLI update."""
        row = self._highlighted_row()
        return row is not None and (
            "install" in row.capabilities or "mark_update" in row.capabilities
        )

    def _can_update_highlighted(self) -> bool:
        """Whether the highlighted row can be updated right now."""
        row = self._highlighted_row()
        return row is not None and "update" in row.capabilities

    def _can_update_sase(self) -> bool:
        """Whether the top-level ``sase update`` action can be offered."""
        return (
            not isinstance(self._uv_tool, NotUvToolInstall)
            and not self._all_up_to_date()
        )

    def _can_switch_mode(self) -> bool:
        """Whether install-mode switching can be offered."""
        return not isinstance(self._uv_tool, NotUvToolInstall)

    def _can_uninstall_highlighted(self) -> bool:
        """Whether the highlighted row can be uninstalled right now."""
        row = self._highlighted_row()
        return row is not None and "uninstall" in row.capabilities

    @staticmethod
    def _plural(count: int, singular: str) -> str:
        if count == 1:
            return singular
        if singular.endswith("y"):
            return f"{singular[:-1]}ies"
        return f"{singular}s"
