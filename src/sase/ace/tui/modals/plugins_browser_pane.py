"""Updates pane for the Config Center modal.

This widget hosts the **Updates** tab of :class:`ConfigCenterModal`: a compact
SASE core update surface plus the plugin master/detail browser mirroring the
``sase plugin list`` and ``sase plugin show`` experience in the TUI. Catalog
loading, render helpers, and mutation actions live in sibling modules so this
file stays focused on widget composition, worker coordination, and
input/navigation glue.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.operations import (
    InstallOutcome,
    InstallReady,
    UninstallOutcome,
    UninstallReady,
    UpdateOutcome,
    UpdateReady,
    execute_install,
    execute_uninstall,
    execute_update,
)
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.versions import CoreVersions, collect_installed_core_versions

from .plugins_browser_constants import (
    _BUILTIN_GROUP,
    _COMMUNITY_GROUP,
    _DETAIL_PLACEHOLDER,
    _HEADER_PREFIX,
    _ITEM_PREFIX,
)
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    execute_tui_dev_update,
    make_plugin_dev_update_preview,
    make_sase_dev_update_preview,
)
from .plugins_browser_input import PluginsFilterInput
from .plugins_browser_install import (
    InstallPreview,
    PluginInstallActionsMixin,
    install_not_found_message,
    install_success_message,
    install_summary,
    missing_plugin_message,
    plan_install_preview,
)
from .plugins_browser_loading import (
    PluginsLoadResult,
    load_plugins_catalog_for_pane,
    probe_uv_tool,
)
from .plugins_browser_rendering import PluginsBrowserRenderingMixin
from .plugins_browser_sase_update import (
    SaseUpdateActionsMixin,
    installed_version,
    load_receipt_for_summary,
    run_sase_update_summary,
    sase_update_success_message,
)
from .plugins_browser_uninstall import (
    PluginUninstallActionsMixin,
    UninstallPreview,
    already_absent_message,
    plan_uninstall_preview,
    uninstall_success_message,
    uninstall_summary,
)
from .plugins_browser_update import (
    PluginUpdateActionsMixin,
    UpdatePreview,
    no_plugins_message,
    not_installed_message,
    plan_update_preview,
    update_subject,
    update_success_message,
    update_summary,
)

_PluginsFilterInput = PluginsFilterInput
_InstallPreview = InstallPreview
_install_success_message = install_success_message
_install_summary = install_summary
_missing_plugin_message = missing_plugin_message
_not_found_message = install_not_found_message
_plan_install_preview = plan_install_preview
_PluginsLoadResult = PluginsLoadResult
_load_plugins_catalog = load_plugins_catalog_for_pane
_collect_installed_core_versions = collect_installed_core_versions
_probe_uv_tool = probe_uv_tool
_DevUpdatePreview = DevUpdatePreview
_execute_tui_dev_update = execute_tui_dev_update
_make_plugin_dev_update_preview = make_plugin_dev_update_preview
_make_sase_dev_update_preview = make_sase_dev_update_preview
_UpdatePreview = UpdatePreview
_no_plugins_message = no_plugins_message
_not_installed_message = not_installed_message
_plan_update_preview = plan_update_preview
_update_subject = update_subject
_update_success_message = update_success_message
_update_summary = update_summary
_UninstallPreview = UninstallPreview
_already_absent_message = already_absent_message
_plan_uninstall_preview = plan_uninstall_preview
_uninstall_success_message = uninstall_success_message
_uninstall_summary = uninstall_summary
_installed_version = installed_version
_load_receipt_for_summary = load_receipt_for_summary
_run_sase_update_summary = run_sase_update_summary
_sase_update_success_message = sase_update_success_message


class PluginsBrowserPane(
    SaseUpdateActionsMixin,
    PluginInstallActionsMixin,
    PluginUninstallActionsMixin,
    PluginUpdateActionsMixin,
    PluginsBrowserRenderingMixin,
    Vertical,
):
    """Browser for SASE core + plugin updates (Config Center -> Updates)."""

    can_focus = False

    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("i", "install", "Install"),
        ("x", "uninstall", "Uninstall"),
        ("u", "update", "Update"),
        ("U", "update_all", "Update all"),
        ("S", "update_sase", "Sase update"),
        ("r", "refresh", "Refresh"),
        ("o", "toggle_offline", "Offline"),
        ("v", "toggle_verbose", "Verbose"),
        ("slash", "focus_filter", "Filter"),
    ]

    def __init__(self, *, auto_load: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._auto_load = auto_load
        self._catalog: PluginCatalog | None = None
        self._core_versions: CoreVersions = _collect_installed_core_versions()
        self._error: str | None = None
        self._loading = auto_load
        self._now = time.time()
        self._filter_text = ""
        self._offline = False
        self._verbose = False
        self._grouped: list[tuple[str, str, list[PluginCatalogEntry]]] = []
        self._worker: Worker[Any] | None = None
        #: Worker computing an install plan/preview before the confirm modal.
        self._plan_worker: Worker[Any] | None = None
        #: Worker computing an update plan/preview before the confirm modal.
        self._update_plan_worker: Worker[Any] | None = None
        #: Worker computing an uninstall plan/preview before the confirm modal.
        self._uninstall_plan_worker: Worker[Any] | None = None
        #: Worker computing an editable-install dev update plan/preview for S.
        self._sase_update_plan_worker: Worker[Any] | None = None
        #: One-shot uv-tool detection: gates whether mutations are possible.
        #: ``None`` until the first real load probes it.
        self._uv_tool: UvToolInstall | NotUvToolInstall | None = None
        #: Debounces the (cheap-but-not-free) detail rebuild so a held j/k
        #: paints exactly one final detail; created on mount once an app exists.
        self._detail_debouncer: DetailPanelDebouncer | None = None
        #: Name of the plugin currently shown in the detail panel (dedup guard).
        self._detail_name: str | None = None
        #: Plugin to re-highlight after the next reload (selection preservation).
        self._restore_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(self._core_versions_panel(), id="sase-core-versions")
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
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._sync_state_visibility()
        if self._auto_load:
            self._start_load(force=False)

    def focus_default(self) -> None:
        """Focus the list (browse-first) when the Updates tab activates."""
        option_list = self._option_list()
        if option_list is not None:
            option_list.focus()

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        # Re-highlight whatever is selected now once the reload lands so a
        # refresh / offline toggle doesn't snap the user back to the top.
        self._restore_name = self._highlighted_name()
        self._sync_state_visibility()
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        self._update_static("#sase-core-versions", self._core_versions_panel())
        refresh = force
        offline = self._offline

        def task() -> _PluginsLoadResult:
            return _load_plugins_catalog(refresh=refresh, offline=offline)

        self._worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._plan_worker = None
                self._on_install_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._plan_worker = None
                self._notify(self._worker_error_text(event.worker), severity="error")
            return
        if event.worker is self._update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._update_plan_worker = None
                self._on_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._update_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="update"),
                    severity="error",
                )
            return
        if event.worker is self._uninstall_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._uninstall_plan_worker = None
                self._on_uninstall_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._uninstall_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="uninstall"),
                    severity="error",
                )
            return
        if event.worker is self._sase_update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._sase_update_plan_worker = None
                self._on_sase_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._sase_update_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="sase update"),
                    severity="error",
                )
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._catalog = getattr(result, "catalog", None)
            self._error = getattr(result, "error", None)
            self._now = getattr(result, "now", self._now)
            # Keep a previously-detected probe result if a stubbed loader (or a
            # failed probe) returns None -- "detect once" per the epic.
            probed = getattr(result, "uv_tool", None)
            if probed is not None:
                self._uv_tool = probed
            core_versions = getattr(result, "core_versions", None)
            if core_versions is not None:
                self._core_versions = core_versions
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._render_all()

    @staticmethod
    def _worker_error_text(worker: Worker[Any], *, kind: str = "install") -> str:
        if worker.error:
            return str(worker.error)
        return f"Could not plan the {kind}."

    def _make_install_preview(self, name: str, *, offline: bool) -> _InstallPreview:
        return _plan_install_preview(name, offline=offline)

    @staticmethod
    def _execute_install(plan: InstallReady) -> InstallOutcome:
        return execute_install(plan)

    def _make_update_preview(
        self, query: str | None, *, all_plugins: bool, offline: bool
    ) -> _UpdatePreview:
        return _plan_update_preview(query, all_plugins=all_plugins, offline=offline)

    @staticmethod
    def _execute_update(plan: UpdateReady) -> UpdateOutcome:
        return execute_update(plan)

    @staticmethod
    def _make_plugin_dev_update_preview(
        query: str | None,
        *,
        all_plugins: bool,
        receipt: object | None,
    ) -> _DevUpdatePreview:
        return _make_plugin_dev_update_preview(
            query,
            all_plugins=all_plugins,
            receipt=receipt if isinstance(receipt, ToolReceipt) else None,
        )

    @staticmethod
    def _execute_dev_update(plan: Any) -> Any:
        return _execute_tui_dev_update(plan)

    def _make_uninstall_preview(
        self, query: str, *, offline: bool
    ) -> _UninstallPreview:
        return _plan_uninstall_preview(query, offline=offline)

    @staticmethod
    def _execute_uninstall(plan: UninstallReady) -> UninstallOutcome:
        return execute_uninstall(plan)

    @staticmethod
    def _run_sase_update_summary(install: object | None) -> tuple[UpdateSummary, float]:
        return run_sase_update_summary(install)

    @staticmethod
    def _make_sase_update_preview(receipt: object | None) -> _DevUpdatePreview:
        return _make_sase_dev_update_preview(
            receipt if isinstance(receipt, ToolReceipt) else None
        )

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

    def action_refresh(self) -> None:
        """Refetch the catalog and latest versions (the ``-r/--refresh`` analog)."""
        if self._loading:
            return
        self._start_load(force=True)

    def action_toggle_offline(self) -> None:
        """Toggle offline (cache-only) mode and reload (the ``-o`` analog)."""
        if self._loading:
            return
        self._offline = not self._offline
        self._start_load(force=False)

    def action_toggle_verbose(self) -> None:
        """Toggle the list rows' verbose columns (stars / updated)."""
        self._verbose = not self._verbose
        self._rebuild_options()
        self._update_static("#plugins-hints", self._hints())
        self._render_detail_now(force=True)

    def _notify(
        self,
        message: str,
        *,
        severity: Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Toast *message*, tolerating an already-unmounted pane/app."""
        try:
            self.app.notify(message, severity=severity)
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "plugins-filter-input":
            return
        self._filter_text = event.value
        self._rebuild_groups()
        self._rebuild_options()
        self._sync_state_visibility()
        self._render_detail_now(force=True)

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
            self._render_detail_now(force=True)
        self.focus_default()

    def _option_list(self) -> OptionList | None:
        try:
            return self.query_one("#plugins-list", OptionList)
        except Exception:
            return None

    def _detail_widget(self) -> Static | None:
        try:
            return self.query_one("#plugins-detail", Static)
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

    def _update_static(self, selector: str, content: RenderableType) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:
            pass
