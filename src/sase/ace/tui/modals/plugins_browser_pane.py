"""Updates pane for the Config Center modal.

This widget hosts the **Updates** tab of :class:`ConfigCenterModal`: pane-local
Core / Plugins / Agent CLIs sub-tabs sharing one threaded inventory load and
the same update services used by the CLI.
"""

from __future__ import annotations

import time
from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, OptionList, Static
from textual.worker import Worker, WorkerState

from sase.agent_clis.history import AgentCliUpdateRun, read_agent_cli_update_runs
from sase.agent_clis.models import AgentCliUpdateResult
from sase.agent_clis.operations import (
    execute_agent_cli_updates,
    plan_agent_cli_updates,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.operations import (
    execute_install as execute_install,
    execute_install_many as execute_install_many,
    execute_uninstall as execute_uninstall,
    execute_update as execute_update,
)
from sase.updates.incoming_commits import (
    IncomingCommits,
    IncomingCommitsCacheKey,
    fetch_incoming_commit_groups,
    fetch_incoming_commits,
)
from sase.uv_tool.detect import NotUvToolInstall, UvToolInstall
from sase.uv_tool.versions import CoreVersions, collect_installed_core_versions

from .plugins_browser_constants import _DETAIL_PLACEHOLDER, _SUBTAB_NAV_HINT
from .config_center_session import UpdatesSessionState, UpdatesSubTab
from .plugins_browser_agent_clis import (
    AgentCliBrowserMixin,
    AgentCliHistoryConfig,
    load_agent_cli_history_config,
)
from .plugins_browser_comprehensive_update import (
    ComprehensiveUpdateActionsMixin,
    ComprehensiveUpdateRequest,
)
from .plugins_browser_controls import PluginsBrowserControlsMixin
from .plugins_browser_dev_update import (
    DevUpdatePreview,
    execute_tui_dev_update,
    make_plugin_dev_update_preview,
    make_sase_dev_update_preview,
)
from .plugins_browser_incoming import (
    IncomingCommitsConfig,
    PluginsBrowserIncomingCommitsMixin,
    load_incoming_commits_config,
)
from .plugins_browser_input import PluginsFilterInput
from .plugins_browser_install import (
    InstallManyPreview,
    InstallPreview,
    PluginInstallActionsMixin,
    install_many_success_message,
    install_many_summary,
    install_not_found_message,
    install_success_message,
    install_summary,
    plan_install_many_preview,
    missing_plugin_message,
    plan_install_preview,
)
from .plugins_browser_list import PluginsBrowserList
from .plugins_browser_loading import (
    PluginsLoadResult,
    load_plugins_catalog_for_pane,
    probe_uv_tool,
)
from .plugins_browser_mode_switch import (
    ModeSwitchActionsMixin,
    ModeSwitchPreview,
    make_mode_switch_preview,
)
from .plugins_browser_operations import (
    PluginsBrowserOperationsMixin,
    callable_accepts_keyword,
)
from .plugins_browser_rendering import PluginsBrowserRenderingMixin
from .plugins_browser_sase_update import (
    SaseUpdateActionsMixin,
    installed_version,
    load_receipt_for_summary,
    run_planned_sase_update_summary as run_planned_sase_update_summary,
    run_sase_update_summary as run_sase_update_summary,
    sase_update_success_message,
)
from .plugins_browser_status import PluginsBrowserStatusMixin
from ..widgets.panel_tab_strip import PanelTab, PanelTabStrip
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
    not_installed_message,
    plan_update_preview,
    update_subject,
    update_success_message,
    update_summary,
)

_PluginsFilterInput = PluginsFilterInput
_PluginList = PluginsBrowserList
_InstallPreview = InstallPreview
_InstallManyPreview = InstallManyPreview
_install_success_message = install_success_message
_install_many_success_message = install_many_success_message
_install_summary = install_summary
_install_many_summary = install_many_summary
_missing_plugin_message = missing_plugin_message
_not_found_message = install_not_found_message
_plan_install_preview = plan_install_preview
_plan_install_many_preview = plan_install_many_preview
_PluginsLoadResult = PluginsLoadResult
_load_plugins_catalog = load_plugins_catalog_for_pane
_collect_installed_core_versions = collect_installed_core_versions
_probe_uv_tool = probe_uv_tool
_ModeSwitchPreview = ModeSwitchPreview
_make_mode_switch_preview = make_mode_switch_preview
_DevUpdatePreview = DevUpdatePreview
_execute_tui_dev_update = execute_tui_dev_update
_make_plugin_dev_update_preview = make_plugin_dev_update_preview
_make_sase_dev_update_preview = make_sase_dev_update_preview
_UpdatePreview = UpdatePreview
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
_run_planned_sase_update_summary = run_planned_sase_update_summary
_sase_update_success_message = sase_update_success_message
_IncomingCommitsConfig = IncomingCommitsConfig
_fetch_incoming_commits = fetch_incoming_commits
_fetch_incoming_commit_groups = fetch_incoming_commit_groups
_load_incoming_commits_config = load_incoming_commits_config
_callable_accepts_keyword = callable_accepts_keyword
_plan_agent_cli_updates = plan_agent_cli_updates
_execute_agent_cli_updates = execute_agent_cli_updates
_read_agent_cli_update_runs = read_agent_cli_update_runs
_AgentCliHistoryConfig = AgentCliHistoryConfig
_load_agent_cli_history_config = load_agent_cli_history_config

_SUBTAB_ORDER: tuple[UpdatesSubTab, ...] = ("core", "plugins", "agent-clis")
_SUBTAB_WIDGET_IDS: dict[UpdatesSubTab, str] = {
    "core": "updates-subtab-core",
    "plugins": "updates-subtab-plugins",
    "agent-clis": "updates-subtab-agent-clis",
}
_SUBTABS: tuple[PanelTab, ...] = (
    PanelTab("core", "Core", "#AF87FF"),
    PanelTab("plugins", "Plugins", "#AF87FF"),
    PanelTab("agent-clis", "Agent CLIs", "#AF87FF"),
)
_FRESH_EDITABLE_ROOTS_TTL_SECONDS = 60.0
_monotonic = time.monotonic


class PluginsBrowserPane(
    ComprehensiveUpdateActionsMixin,
    AgentCliBrowserMixin,
    ModeSwitchActionsMixin,
    SaseUpdateActionsMixin,
    PluginInstallActionsMixin,
    PluginUninstallActionsMixin,
    PluginUpdateActionsMixin,
    PluginsBrowserOperationsMixin,
    PluginsBrowserIncomingCommitsMixin,
    PluginsBrowserControlsMixin,
    PluginsBrowserStatusMixin,
    PluginsBrowserRenderingMixin,
    Vertical,
):
    """Browser for SASE core, plugin, and agent-CLI updates."""

    can_focus = True

    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("right_square_bracket", "cycle_subtab", "Next Sub-tab"),
        ("left_square_bracket", "cycle_subtab_reverse", "Previous Sub-tab"),
        ("i", "install", "Install"),
        ("I", "toggle_install_mark", "Mark"),
        ("space", "toggle_mark", "Mark"),
        ("x", "uninstall", "Uninstall"),
        ("m", "switch_mode", "Switch mode"),
        ("u", "update_sase", "Update core + plugins"),
        ("A", "update_agent_clis", "Update agent CLIs"),
        ("H", "toggle_history_scope", "History scope"),
        ("a", "sync_agents", "Sync agents"),
        ("U", "update", "Update plugin"),
        ("r", "refresh", "Refresh"),
        ("ctrl+d", "scroll_detail_down", "Scroll Down"),
        ("ctrl+u", "scroll_detail_up", "Scroll Up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
        ("shift+g", "scroll_to_bottom", "Bottom"),
        ("o", "toggle_offline", "Offline"),
        ("v", "toggle_verbose", "Verbose"),
        ("slash", "focus_filter", "Filter"),
        ("escape", "clear_marks_or_close", "Close"),
    ]

    def __init__(
        self,
        *,
        auto_load: bool = True,
        auto_update_on_load: bool = False,
        comprehensive_provider_names: tuple[str, ...] | None = None,
        session_state: UpdatesSessionState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._session_state = session_state or UpdatesSessionState()
        self._auto_load = auto_load
        self._auto_update_on_load = auto_update_on_load
        self._comprehensive_update_request = (
            ComprehensiveUpdateRequest(comprehensive_provider_names)
            if auto_update_on_load
            else None
        )
        # A synchronous bridge used only while invoking the historical
        # ``_start_sase_update_preview`` hook after the load.  It keeps that
        # compatibility surface while the one-shot request itself is consumed.
        self._starting_comprehensive_request: ComprehensiveUpdateRequest | None = None
        self._active_subtab: UpdatesSubTab = self._session_state.active_subtab
        self._catalog: PluginCatalog | None = None
        self._core_versions: CoreVersions = _collect_installed_core_versions()
        self._error: str | None = None
        self._loading = auto_load
        # Pane-local handoff from a completed online load to a near-immediate
        # update preview.  The tuple is replaced as one value so roots and
        # their monotonic completion timestamp cannot get out of sync.
        self._fresh_editable_roots_evidence: tuple[frozenset[str], float] | None = None
        self._now = time.time()
        self._filter_text = ""
        self._marked_install: set[str] = set()
        self._offline = False
        self._verbose = False
        self._agent_cli_statuses = ()
        self._agent_cli_error: str | None = None
        self._agent_cli_colors: dict[str, str] = {}
        self._agent_cli_history: tuple[AgentCliUpdateRun, ...] = ()
        self._agent_cli_history_error: str | None = None
        self._agent_cli_history_config: AgentCliHistoryConfig = (
            _load_agent_cli_history_config()
        )
        self._marked_agent_clis: set[str] = set()
        self._agent_cli_results: dict[str, AgentCliUpdateResult] = {}
        self._agent_cli_detail_name: str | None = None
        self._agent_cli_history_key: tuple[str | None, bool] | None = None
        self._plugin_selection_guard = ProgrammaticSelectionGuard()
        self._agent_cli_selection_guard = ProgrammaticSelectionGuard()
        self._updates_loaded_once = False
        self._grouped: list[tuple[str, str, list[PluginCatalogEntry]]] = []
        self._worker: Worker[Any] | None = None
        #: Worker computing an install plan/preview before the confirm modal.
        self._plan_worker: Worker[Any] | None = None
        #: Worker computing an update plan/preview before the confirm modal.
        self._update_plan_worker: Worker[Any] | None = None
        #: Worker computing an uninstall plan/preview before the confirm modal.
        self._uninstall_plan_worker: Worker[Any] | None = None
        #: Worker computing an editable-install dev update plan/preview for u.
        self._sase_update_plan_worker: Worker[Any] | None = None
        #: Worker computing a PyPI/dev install-mode switch plan.
        self._mode_switch_plan_worker: Worker[Any] | None = None
        #: Worker computing the pane-wide agent-CLI update preview.
        self._agent_cli_plan_worker: Worker[Any] | None = None
        #: Worker composing the snapshot-gated SASE + provider preview.
        self._comprehensive_update_plan_worker: Worker[Any] | None = None
        #: One-shot uv-tool detection: gates whether mutations are possible.
        #: ``None`` until the first real load probes it.
        self._uv_tool: UvToolInstall | NotUvToolInstall | None = None
        #: Debounces the (cheap-but-not-free) detail rebuild so a held j/k
        #: paints exactly one final detail; created on mount once an app exists.
        self._detail_debouncer: DetailPanelDebouncer | None = None
        #: Name of the plugin currently shown in the detail panel (dedup guard).
        self._detail_name: str | None = None
        #: Plugin to re-highlight after the next reload (selection preservation).
        self._restore_name: str | None = self._session_state.plugins.identity
        incoming_config = _load_incoming_commits_config()
        self._incoming_commits_enabled = incoming_config.enabled
        self._incoming_commits_limit = incoming_config.max_per_repo
        self._incoming_commits_confirm_limit = incoming_config.confirm_max_per_repo
        self._incoming_commit_cache: dict[IncomingCommitsCacheKey, IncomingCommits] = {}
        self._incoming_commit_loading: set[IncomingCommitsCacheKey] = set()
        self._incoming_commit_workers: dict[int, IncomingCommitsCacheKey] = {}
        self._core_incoming_commits: dict[str, IncomingCommits] = {}
        self._install_mode: str | None = None
        self._dev_root: str | None = None

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(
            _SUBTABS,
            self._active_subtab,
            uppercase_active=True,
            id="updates-subtabs",
        )
        with ContentSwitcher(
            initial=_SUBTAB_WIDGET_IDS[self._active_subtab],
            id="updates-subtab-switcher",
        ):
            with Vertical(id=_SUBTAB_WIDGET_IDS["core"]):
                banner = Static(self._all_current_banner(), id="updates-current-banner")
                banner.display = False
                yield banner
                yield Static(self._core_versions_panel(), id="sase-core-versions")
                yield Static(self._core_hints(), id="updates-core-hints", markup=False)
            with Vertical(id=_SUBTAB_WIDGET_IDS["plugins"]):
                yield Static(self._summary_text(), id="plugins-summary", markup=False)
                yield _PluginsFilterInput(
                    placeholder="/ filter plugins…", id="plugins-filter-input"
                )
                with Horizontal(id="plugins-panels"):
                    with Vertical(id="plugins-list-panel"):
                        yield Static(
                            self._status_message(), id="plugins-status", markup=False
                        )
                        yield _PluginList(*self._create_options(), id="plugins-list")
                    with Vertical(id="plugins-detail-panel"):
                        with VerticalScroll(id="plugins-detail-scroll"):
                            yield Static(
                                _DETAIL_PLACEHOLDER,
                                id="plugins-detail",
                                markup=False,
                            )
                yield Static(self._hints(), id="plugins-hints", markup=False)
            with Vertical(id=_SUBTAB_WIDGET_IDS["agent-clis"]):
                yield Static(
                    self._agent_cli_summary(), id="agent-clis-summary", markup=False
                )
                with Horizontal(id="agent-clis-panels"):
                    with Vertical(id="agent-clis-list-panel"):
                        yield Static(
                            self._agent_cli_status_message(),
                            id="agent-clis-status",
                            markup=False,
                        )
                        yield _PluginList(id="agent-clis-list")
                    with Vertical(id="agent-clis-detail-panel"):
                        with VerticalScroll(id="agent-clis-detail-scroll"):
                            yield Static(
                                "Select an agent CLI to view its update details.",
                                id="agent-clis-detail",
                                markup=False,
                            )
                            yield Static("", id="agent-clis-history", markup=False)
                yield Static(
                    self._agent_cli_hints(), id="agent-clis-hints", markup=False
                )

    def on_mount(self) -> None:
        self._detail_debouncer = DetailPanelDebouncer(self.app)
        self._sync_state_visibility()
        self._sync_current_banner()
        if self._auto_load:
            self._start_load(force=False)

    def on_unmount(self) -> None:
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "update_sase":
            return self._can_update_sase()
        if action == "update_agent_clis":
            return not self._loading and self._agent_cli_plan_worker is None
        if action == "sync_agents":
            return callable(getattr(self.app, "action_sync_agents", None))
        if action == "toggle_history_scope":
            return self._active_subtab == "agent-clis"
        plugin_only = {
            "install",
            "toggle_install_mark",
            "uninstall",
            "switch_mode",
            "update",
            "toggle_verbose",
            "focus_filter",
        }
        if action in plugin_only and self._active_subtab != "plugins":
            return False
        browse_only = {
            "next_option",
            "prev_option",
            "toggle_mark",
            "scroll_detail_down",
            "scroll_detail_up",
            "scroll_to_top",
            "scroll_to_bottom",
        }
        if action in browse_only and self._active_subtab == "core":
            return False
        return super().check_action(action, parameters)

    @on(PanelTabStrip.TabClicked)
    def _on_subtab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        event.stop()
        if event.tab_id in _SUBTAB_ORDER:
            self._switch_to_subtab(cast(UpdatesSubTab, event.tab_id))

    def _switch_to_subtab(self, subtab: UpdatesSubTab) -> None:
        self._active_subtab = subtab
        self._session_state.active_subtab = subtab
        if self._detail_debouncer is not None:
            self._detail_debouncer.cancel()
        try:
            self.query_one(
                "#updates-subtab-switcher", ContentSwitcher
            ).current = _SUBTAB_WIDGET_IDS[subtab]
            self.query_one("#updates-subtabs", PanelTabStrip).set_active_tab(subtab)
        except Exception:
            return
        self.focus_default()

    def _cycle_subtab(self, step: int) -> None:
        index = _SUBTAB_ORDER.index(self._active_subtab)
        self._switch_to_subtab(_SUBTAB_ORDER[(index + step) % len(_SUBTAB_ORDER)])

    def action_cycle_subtab(self) -> None:
        self._cycle_subtab(1)

    def action_cycle_subtab_reverse(self) -> None:
        self._cycle_subtab(-1)

    def _core_hints(self) -> str:
        offline = " (on)" if self._offline else " off"
        return " · ".join(
            (
                "u core+plugins",
                "A agent CLIs",
                "a sync agents",
                "r reload",
                f"o{offline}",
                _SUBTAB_NAV_HINT,
                "esc",
            )
        )

    def action_sync_agents(self) -> None:
        """Delegate ``a`` to ACE's shared tracked full-sync action."""
        action = getattr(self.app, "action_sync_agents", None)
        if callable(action):
            action()

    def _start_load(self, *, force: bool) -> None:
        self._loading = True
        self._error = None
        # A reload invalidates the prior handoff immediately.  Only this
        # load's successful online result may establish new evidence.
        self._fresh_editable_roots_evidence = None
        # Re-highlight whatever is selected now once the reload lands so a
        # refresh / offline toggle doesn't snap the user back to the top.
        self._restore_name = (
            self._highlighted_name() or self._session_state.plugins.identity
        )
        self._core_incoming_commits = {}
        self._sync_state_visibility()
        self._sync_current_banner()
        self._update_static("#plugins-summary", self._summary_text())
        self._update_static("#plugins-hints", self._hints())
        self._update_static("#updates-core-hints", self._core_hints())
        self._update_static("#agent-clis-summary", self._agent_cli_summary())
        self._update_static("#agent-clis-hints", self._agent_cli_hints())
        self._update_static("#sase-core-versions", self._core_versions_panel())
        refresh = force
        offline = self._offline
        incoming_commits_enabled = self._incoming_commits_enabled
        incoming_commits_limit = self._incoming_commits_limit
        agent_cli_history_enabled = self._agent_cli_history_config.enabled

        def task() -> _PluginsLoadResult:
            return _load_plugins_catalog(
                refresh=refresh,
                offline=offline,
                incoming_commits_enabled=incoming_commits_enabled,
                incoming_commits_limit=incoming_commits_limit,
                agent_cli_history_enabled=agent_cli_history_enabled,
            )

        self._worker = self.run_worker(
            task, thread=True, exclusive=True, exit_on_error=False
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        incoming_key = self._incoming_commit_workers.get(id(event.worker))
        if incoming_key is not None:
            self._on_incoming_commits_worker_state(event, incoming_key)
            return
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
        if event.worker is self._comprehensive_update_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._comprehensive_update_plan_worker = None
                self._on_comprehensive_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._comprehensive_update_plan_worker = None
                self._notify(
                    self._worker_error_text(
                        event.worker,
                        kind="comprehensive update",
                    ),
                    severity="error",
                )
            return
        if event.worker is self._mode_switch_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._mode_switch_plan_worker = None
                self._on_mode_switch_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._mode_switch_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="mode switch"),
                    severity="error",
                )
            return
        if event.worker is self._agent_cli_plan_worker:
            if event.state == WorkerState.SUCCESS:
                self._agent_cli_plan_worker = None
                self._on_agent_cli_update_preview(event.worker.result)
            elif event.state == WorkerState.ERROR:
                self._agent_cli_plan_worker = None
                self._notify(
                    self._worker_error_text(event.worker, kind="agent CLI update"),
                    severity="error",
                )
            return
        if event.worker is not self._worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self._loading = False
            self._updates_loaded_once = True
            self._catalog = getattr(result, "catalog", None)
            self._error = getattr(result, "error", None)
            self._now = getattr(result, "now", self._now)
            fresh_roots = frozenset(getattr(result, "fresh_editable_roots", ()))
            self._fresh_editable_roots_evidence = None
            if self._error is None and not self._offline and fresh_roots:
                self._fresh_editable_roots_evidence = (
                    fresh_roots,
                    _monotonic(),
                )
            # Keep a previously-detected probe result if a stubbed loader (or a
            # failed probe) returns None -- "detect once" per the epic.
            probed = getattr(result, "uv_tool", None)
            if probed is not None:
                self._uv_tool = probed
            core_versions = getattr(result, "core_versions", None)
            if core_versions is not None:
                self._core_versions = core_versions
            install_mode = getattr(result, "install_mode", None)
            if install_mode is not None:
                self._install_mode = install_mode
            dev_root = getattr(result, "dev_root", None)
            if dev_root is not None:
                self._dev_root = dev_root
            self._core_incoming_commits = dict(
                getattr(result, "core_incoming_commits", {}) or {}
            )
            self._agent_cli_statuses = tuple(
                getattr(result, "agent_cli_statuses", ()) or ()
            )
            self._agent_cli_error = getattr(result, "agent_cli_error", None)
            self._agent_cli_colors = dict(getattr(result, "agent_cli_colors", {}) or {})
            self._agent_cli_history = tuple(
                getattr(result, "agent_cli_history", ()) or ()
            )
            self._agent_cli_history_error = getattr(
                result, "agent_cli_history_error", None
            )
            self._render_all()
            update_status = getattr(result, "update_status", None)
            refresh_indicator = getattr(
                self.app,
                "_schedule_updates_indicator_revalidation",
                None,
            )
            if update_status is not None and callable(refresh_indicator):
                refresh_indicator(update_status)
            if self._auto_update_on_load:
                self._auto_update_on_load = False
                request = self._comprehensive_update_request
                self._comprehensive_update_request = None
                provider_names = request.provider_names if request is not None else None
                if self._all_up_to_date() and not provider_names:
                    self._notify(
                        "Everything is already up to date.",
                        severity="information",
                    )
                else:
                    fresh_roots = self._reusable_fresh_editable_roots()

                    def _start_captured_request() -> None:
                        # Consume before invoking the planning hook so closing,
                        # cancellation, or a scheduling failure cannot replay it.
                        self._starting_comprehensive_request = request
                        try:
                            self._start_sase_update_preview(
                                already_refreshed_roots=fresh_roots
                            )
                        finally:
                            self._starting_comprehensive_request = None

                    self.app.call_later(_start_captured_request)
        elif event.state == WorkerState.ERROR:
            self._auto_update_on_load = False
            self._comprehensive_update_request = None
            self._starting_comprehensive_request = None
            self._loading = False
            self._fresh_editable_roots_evidence = None
            self._error = (
                str(event.worker.error) if event.worker.error else "load failed"
            )
            self._core_incoming_commits = {}
            self._render_all()

    def _reusable_fresh_editable_roots(
        self,
        *,
        now: float | None = None,
        ttl_seconds: float = _FRESH_EDITABLE_ROOTS_TTL_SECONDS,
    ) -> frozenset[str]:
        """Return load-refreshed roots while their short handoff is fresh."""
        evidence = self._fresh_editable_roots_evidence
        if evidence is None:
            return frozenset()
        roots, completed_at = evidence
        current = _monotonic() if now is None else now
        age = current - completed_at
        if 0.0 <= age <= ttl_seconds:
            return roots
        return frozenset()
