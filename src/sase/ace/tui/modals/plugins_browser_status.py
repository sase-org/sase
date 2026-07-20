"""Status, summary, and hint text for the Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import OptionList, Static

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.render_common import humanize_age
from sase.uv_tool.detect import NotUvToolInstall

from .plugins_browser_constants import _SUBTAB_NAV_HINT

_CURRENT_ACCENT = "#00D700"


class PluginsBrowserStatusMixin:
    """Summary, empty-state, and action-affordance text."""

    if TYPE_CHECKING:
        _catalog: PluginCatalog | None
        from sase.uv_tool.versions import CoreVersions

        _core_versions: CoreVersions
        _error: str | None
        _filter_text: str
        _grouped: list[tuple[str, str, list[PluginCatalogEntry]]]
        _loading: bool
        _now: float
        _offline: bool
        _install_mode: str | None
        _marked_install: set[str]
        _uv_tool: object | None
        _verbose: bool

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _can_install_entry(self, entry: PluginCatalogEntry | None) -> bool: ...

    def _all_up_to_date(self) -> bool:
        """Whether every update source has been checked and is current."""
        if self._loading or self._error is not None:
            return False
        catalog = self._catalog
        if catalog is None:
            return False
        if self._uv_tool is None or isinstance(self._uv_tool, NotUvToolInstall):
            return False
        if self._offline:
            return False
        if catalog.updates_available != 0:
            return False
        return all(
            package.installed_version is not None
            and package.latest_checked
            and package.latest_error is None
            and not package.update_available
            for package in self._core_versions.packages
        )

    def _all_current_banner(self) -> Panel:
        """Hero confirmation shown when SASE core and plugins are current."""
        catalog = self._catalog
        installed_count = catalog.installed_count if catalog is not None else 0
        package_versions = {
            package.name: package.installed_version
            for package in self._core_versions.packages
        }
        version_line = (
            f"sase v{package_versions.get('sase') or '?'} · "
            f"sase-core v{package_versions.get('sase-core') or '?'} · "
            f"{installed_count} {self._plural(installed_count, 'plugin')} current"
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

    def _sync_current_banner(self) -> None:
        """Refresh and show/hide the all-current banner."""
        try:
            banner = cast(
                Static,
                self.query_one("#updates-current-banner", Static),  # type: ignore[attr-defined]
            )
        except Exception:
            return
        show_banner = self._all_up_to_date()
        if show_banner:
            banner.update(self._all_current_banner())
        banner.display = show_banner

    def _sync_state_visibility(self) -> None:
        """Show the list when populated, else the status placeholder.

        A *reload* (refresh / offline toggle) keeps the already-painted rows
        visible -- the header reports "loading..." instead -- so the list never
        flashes away and the focused highlight is preserved. The status
        placeholder is reserved for the initial load, the error state, and the
        genuinely empty / no-match cases.
        """
        has_rows = any(entries for _, _, entries in self._grouped)
        try:
            status = cast(
                Static,
                self.query_one("#plugins-status", Static),  # type: ignore[attr-defined]
            )
            option_list = cast(
                OptionList,
                self.query_one("#plugins-list", OptionList),  # type: ignore[attr-defined]
            )
        except Exception:
            return
        status.update(self._status_message())
        show_status = self._error is not None or not has_rows
        status.display = show_status
        option_list.display = not show_status

    def _summary_text(self) -> Text:
        """Header summary: counts line + offline badge + warning/stale hint."""
        text = Text(self._summary_line())
        if self._offline:
            text.append("   ")
            text.append("⚠ OFFLINE", style="bold yellow")
        if isinstance(self._uv_tool, NotUvToolInstall):
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(
                "Plugin changes unavailable — sase is not a `uv tool` install.",
                style="yellow",
            )
        hint = self._summary_hint()
        if hint is not None:
            text.append("\n")
            text.append("⚠ ", style="yellow")
            text.append(hint, style="yellow")
        return text

    def _summary_line(self) -> str:
        if self._loading:
            return "Plugins · loading…"
        catalog = self._catalog
        if catalog is None:
            return "Plugins · unavailable"
        total = len(catalog.entries)
        installed = catalog.installed_count
        updates = catalog.updates_available
        age = humanize_age(catalog.age_seconds(self._now))
        return (
            f"{total} plugins · {installed} installed · "
            f"{updates} updates available · cached {age}"
        )

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
        offline = " (on)" if self._offline else " off"
        verbose = " (on)" if self._verbose else " verb"
        parts: list[str] = []
        mark_count = len(self._marked_install)
        if mark_count:
            parts.append(f"i install ({mark_count})")
        elif self._can_install_highlighted():
            parts.append("i install")
        if self._can_mark_highlighted():
            parts.append("I/space mark")
        if self._can_update_sase():
            parts.append("u update core + plugins")
        parts.append("A update agent CLIs")
        if self._can_switch_mode():
            parts.append("m switch")
        if self._can_update_highlighted():
            parts.append("U upd ↑")
        if self._can_uninstall_highlighted():
            parts.append("x rm")
        parts.extend(
            [
                "r reload",
                "ctrl+d/u scroll",
                f"o{offline}",
                f"v{verbose}",
                "/ filter",
                _SUBTAB_NAV_HINT,
                "Tab/Shift+Tab tab",
            ]
        )
        if mark_count:
            parts.append(f"{mark_count} marked")
            parts.append("esc clear")
        else:
            parts.append("esc")
        return " · ".join(parts)

    def _can_install_highlighted(self) -> bool:
        """Whether the highlighted plugin can be installed right now."""
        return self._can_install_entry(self._current_entry())

    def _can_mark_highlighted(self) -> bool:
        """Whether the highlighted plugin can be marked for install."""
        if self._loading:
            return False
        return self._can_install_entry(self._current_entry())

    def _can_update_highlighted(self) -> bool:
        """Whether the highlighted plugin can be updated right now."""
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        entry = self._current_entry()
        return (
            entry is not None and entry.installed.installed and entry.update_available
        )

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
        """Whether the highlighted plugin can be uninstalled right now."""
        if isinstance(self._uv_tool, NotUvToolInstall):
            return False
        entry = self._current_entry()
        return entry is not None and entry.installed.installed

    @staticmethod
    def _plural(count: int, singular: str) -> str:
        if count == 1:
            return singular
        if singular.endswith("y"):
            return f"{singular[:-1]}ies"
        return f"{singular}s"
