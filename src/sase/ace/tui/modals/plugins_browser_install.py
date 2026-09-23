"""Install planning and actions for the Config Center Updates plugin browser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sase.plugins.catalog import PluginCatalogEntry
from sase.uv_tool.detect import NotUvToolInstall
from sase.uv_tool.errors import NotAUvToolInstallError

from .plugins_browser_install_combined import PluginCombinedInstallActionsMixin
from .plugins_browser_install_messages import (
    install_many_success_message,
    install_many_summary,
    install_not_found_message,
    install_success_message,
    install_summary,
    missing_plugin_message,
)
from .plugins_browser_install_previews import (
    CombinedInstallPreview,
    InstallManyPreview,
    InstallPreview,
    plan_install_many_preview,
    plan_install_preview,
)
from .plugins_browser_install_single import PluginSingleInstallActionsMixin

if TYPE_CHECKING:
    from textual.app import App
    from textual.worker import Worker

    from .plugins_browser_rows import UpdateRow

__all__ = [
    "CombinedInstallPreview",
    "InstallManyPreview",
    "InstallPreview",
    "PluginInstallActionsMixin",
    "install_many_success_message",
    "install_many_summary",
    "install_not_found_message",
    "install_success_message",
    "install_summary",
    "missing_plugin_message",
    "plan_install_many_preview",
    "plan_install_preview",
]


class PluginInstallActionsMixin(
    PluginSingleInstallActionsMixin,
    PluginCombinedInstallActionsMixin,
):
    """Install actions for :class:`PluginsBrowserPane`."""

    if TYPE_CHECKING:
        _agent_cli_install_plan_worker: Worker[Any] | None
        _loading: bool
        _plan_worker: Worker[Any] | None
        _uv_tool: object | None
        app: App[Any]

        def _begin_agent_cli_install_plan(self, names: tuple[str, ...]) -> None: ...

        def _begin_combined_install_plan(
            self, cli_names: tuple[str, ...], plugin_names: tuple[str, ...]
        ) -> None: ...

        def _begin_install_many_plan(self, names: tuple[str, ...]) -> None: ...

        def _begin_install_plan(self, name: str) -> None: ...

        def _current_entry(self) -> PluginCatalogEntry | None: ...

        def _highlighted_row(self) -> UpdateRow | None: ...

        def _install_highlighted_cli_row(self, row: UpdateRow) -> None: ...

        def _marked_cli_install_names(self) -> tuple[str, ...]: ...

        def _marked_plugin_names(self) -> tuple[str, ...]: ...

        def _notify(
            self,
            message: str,
            *,
            severity: Literal["information", "warning", "error"] = "information",
        ) -> None: ...

        def _on_combined_install_preview(
            self, preview: CombinedInstallPreview
        ) -> None: ...

        def _on_install_many_preview(self, preview: InstallManyPreview) -> None: ...

        def _on_single_install_preview(
            self, preview: InstallPreview | None
        ) -> None: ...

    def action_install(self) -> None:
        """Install marked rows, or the highlighted row when none are marked.

        The marked-set path installs everything marked for install, whether
        plugins, agent CLIs, or both. With no marks, the highlighted row
        decides: plugins keep the historical single-install behavior and a
        missing agent CLI starts the CLI install flow.
        """
        if (
            self._loading
            or self._plan_worker is not None
            or self._agent_cli_install_plan_worker is not None
        ):
            return
        plugin_names = self._marked_plugin_names()
        cli_names = self._marked_cli_install_names()
        if plugin_names and cli_names:
            self._begin_combined_install_plan(cli_names, plugin_names)
            return
        if cli_names:
            self._begin_agent_cli_install_plan(cli_names)
            return
        if plugin_names:
            if isinstance(self._uv_tool, NotUvToolInstall):
                self._notify(
                    str(NotAUvToolInstallError(self._uv_tool)), severity="warning"
                )
                return
            self._begin_install_many_plan(plugin_names)
            return
        entry = self._current_entry()
        if entry is not None:
            if entry.installed.installed:
                self._notify(f"{entry.name} is already installed.")
                return
            if isinstance(self._uv_tool, NotUvToolInstall):
                self._notify(
                    str(NotAUvToolInstallError(self._uv_tool)), severity="warning"
                )
                return
            self._begin_install_plan(entry.name)
            return
        row = self._highlighted_row()
        if row is not None and row.kind == "agent-cli":
            self._install_highlighted_cli_row(row)

    def _on_install_preview(
        self,
        preview: InstallPreview | InstallManyPreview | CombinedInstallPreview | None,
    ) -> None:
        """Route a planned install to a toast (terminal) or the confirm modal."""
        if preview is None:
            return
        if isinstance(preview, CombinedInstallPreview):
            self._on_combined_install_preview(preview)
            return
        if isinstance(preview, InstallManyPreview):
            self._on_install_many_preview(preview)
            return
        self._on_single_install_preview(preview)


_InstallPreview = InstallPreview
_InstallManyPreview = InstallManyPreview
_plan_install_preview = plan_install_preview
_plan_install_many_preview = plan_install_many_preview
_install_summary = install_summary
_install_many_summary = install_many_summary
_install_success_message = install_success_message
_install_many_success_message = install_many_success_message
_missing_plugin_message = missing_plugin_message
_not_found_message = install_not_found_message
