"""Updates pane for the Config Center modal.

This widget hosts the **Updates** tab of :class:`ConfigCenterModal`: one
merged inventory of SASE core packages, plugins, and agent CLIs sharing one
threaded load and the same update services used by the CLI.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from textual.containers import Vertical
from textual.worker import Worker

from sase.agent_clis.history import AgentCliUpdateRun, read_agent_cli_update_runs
from sase.agent_clis.models import AgentCliUpdateResult
from sase.agent_clis.operations import (
    execute_agent_cli_updates,
    plan_agent_cli_updates,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
from sase.plugins.catalog import PluginCatalog
from sase.plugins.latest import enrich_entry_latest
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

from .config_center_session import UpdatesSessionState
from .plugins_browser_agent_clis import (
    AgentCliBrowserMixin,
    AgentCliHistoryConfig,
    load_agent_cli_history_config,
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
from .plugins_browser_latest import PluginsBrowserLatestMixin
from .plugins_browser_input import PluginsFilterInput
from .plugins_browser_jump import PluginsBrowserJumpMixin
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
from .plugins_browser_layout import PluginsBrowserLayoutMixin
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
from .plugins_browser_rows import UpdateRow, UpdateScope, build_update_rows
from .plugins_browser_sase_update import (
    SaseUpdateActionsMixin,
    installed_version,
    load_receipt_for_summary,
    run_planned_sase_update_summary as run_planned_sase_update_summary,
    run_sase_update_summary as run_sase_update_summary,
    sase_update_success_message,
)
from .plugins_browser_status import PluginsBrowserStatusMixin
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
from .plugins_browser_workers import (
    PluginsBrowserWorkersMixin,
    _FRESH_EDITABLE_ROOTS_TTL_SECONDS,
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
_enrich_entry_latest = enrich_entry_latest
_callable_accepts_keyword = callable_accepts_keyword
_plan_agent_cli_updates = plan_agent_cli_updates
_execute_agent_cli_updates = execute_agent_cli_updates
_read_agent_cli_update_runs = read_agent_cli_update_runs
_AgentCliHistoryConfig = AgentCliHistoryConfig
_load_agent_cli_history_config = load_agent_cli_history_config
_build_update_rows = build_update_rows

_monotonic = time.monotonic


class PluginsBrowserPane(
    PluginsBrowserJumpMixin,
    PluginsBrowserLayoutMixin,
    PluginsBrowserWorkersMixin,
    AgentCliBrowserMixin,
    ModeSwitchActionsMixin,
    SaseUpdateActionsMixin,
    PluginInstallActionsMixin,
    PluginUninstallActionsMixin,
    PluginUpdateActionsMixin,
    PluginsBrowserOperationsMixin,
    PluginsBrowserIncomingCommitsMixin,
    PluginsBrowserLatestMixin,
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
        ("right_square_bracket", "cycle_scope", "Next Scope"),
        ("left_square_bracket", "cycle_scope_reverse", "Previous Scope"),
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
        ("apostrophe", "jump_to_entry", "Jump"),
        ("escape", "clear_marks_or_close", "Close"),
    ]

    def __init__(
        self,
        *,
        auto_load: bool = True,
        session_state: UpdatesSessionState | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._session_state = session_state or UpdatesSessionState()
        self._auto_load = auto_load
        self._scope: UpdateScope = self._session_state.scope
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
        self._marked: set[str] = set()
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
        self._agent_cli_results: dict[str, AgentCliUpdateResult] = {}
        self._agent_cli_history_key: tuple[str | None, bool] | None = None
        self._selection_guard = ProgrammaticSelectionGuard()
        self._updates_loaded_once = False
        self._grouped: list[tuple[str, str, list[UpdateRow]]] = []
        #: The merged row model, rebuilt once per load on the worker thread.
        self._rows: tuple[UpdateRow, ...] = ()
        self._rows_by_key: dict[str, UpdateRow] = {}
        #: Key-keyed lookup maps rebuilt once per `_rebuild_options()` call so
        #: highlight/mark/detail lookups stay O(1) instead of scanning the
        #: option list or `_grouped` per call.
        self._row_option_index: dict[str, int] = {}
        self._row_logical_row: dict[str, int] = {}
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
        #: One-shot uv-tool detection: gates whether mutations are possible.
        #: ``None`` until the first real load probes it.
        self._uv_tool: UvToolInstall | NotUvToolInstall | None = None
        #: Debounces the (cheap-but-not-free) detail rebuild so a held j/k
        #: paints exactly one final detail; created on mount once an app exists.
        self._detail_debouncer: DetailPanelDebouncer | None = None
        #: Key of the row currently shown in the detail panel (dedup guard).
        self._detail_key: str | None = None
        #: Row to re-highlight after the next reload (selection preservation).
        self._restore_key: str | None = self._session_state.rows.identity
        incoming_config = _load_incoming_commits_config()
        self._incoming_commits_enabled = incoming_config.enabled
        self._incoming_commits_limit = incoming_config.max_per_repo
        self._incoming_commits_confirm_limit = incoming_config.confirm_max_per_repo
        #: Bounded LRU: a long session highlighting many installed-and-
        #: updatable rows must not grow this without limit.
        self._incoming_commit_cache: OrderedDict[
            IncomingCommitsCacheKey, IncomingCommits
        ] = OrderedDict()
        self._incoming_commit_loading: set[IncomingCommitsCacheKey] = set()
        self._incoming_commit_workers: dict[int, IncomingCommitsCacheKey] = {}
        self._plugin_latest_loading: set[str] = set()
        self._plugin_latest_workers: dict[int, str] = {}
        self._core_incoming_commits: dict[str, IncomingCommits] = {}
        self._install_mode: str | None = None
        self._dev_root: str | None = None
