"""Fast, deterministic startup overrides for the Ace test harness."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any
from unittest.mock import patch

import sase.notifications as _notifications
from sase.ace.tui import AceApp
from sase.ace.tui.actions.agents import _loading as _agent_loading
from sase.ace.tui.actions.lifecycle import NotificationStartupState
from sase.ace.tui.modals import plugins_browser_pane as _plugins_browser_pane
from sase.ace.tui.modals import project_inventory_panes as _project_inventory_panes
from sase.ace.tui.util import stall_watchdog as _stall_watchdog
from sase.repo_inventory import RepoInventory
from sase.workspace_provider.inventory import WorkspaceInventory

_ORIGINAL_RUN_MOUNT_STATE_LOADS = AceApp._run_mount_state_loads
_ORIGINAL_RUN_AGENT_STARTUP = AceApp._run_agent_index_startup_prepare_and_refresh
_ORIGINAL_RUN_AXE_STARTUP = AceApp._run_axe_startup_init
_ORIGINAL_LOAD_AXE_STATUS_ASYNC = AceApp._load_axe_status_async
_ORIGINAL_SCHEDULE_FOLD_STATE_LOAD = AceApp._schedule_agents_fold_state_load
_ORIGINAL_SCHEDULE_DISMISSED_INDEX_SYNC = AceApp._schedule_dismissed_index_startup_sync
_ORIGINAL_START_ARTIFACT_WATCHER = AceApp._start_artifact_watcher
_ORIGINAL_START_PROMPT_SOURCE_WATCHER = AceApp._start_prompt_source_watcher
_ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD = AceApp._schedule_prompt_catalog_rebuild
_ORIGINAL_SCHEDULE_UPDATE_CHECK = AceApp._schedule_startup_update_toast_check
_ORIGINAL_SCHEDULE_AGENTS_SYNC_CHECK = AceApp._schedule_startup_agents_sync_check

_ORIGINAL_LOAD_AGENTS_FROM_DISK = _agent_loading.load_agents_from_disk_with_state
_ORIGINAL_READ_NOTIFICATION_SNAPSHOT = _notifications.read_notification_snapshot
_ORIGINAL_START_STALL_WATCHDOG = _stall_watchdog.start_event_loop_stall_watchdog
_ORIGINAL_LOAD_PLUGINS_CATALOG = _plugins_browser_pane._load_plugins_catalog
_ORIGINAL_COLLECT_REPO_INVENTORY = _project_inventory_panes.collect_repo_inventory
_ORIGINAL_COLLECT_WORKSPACE_INVENTORY = (
    _project_inventory_panes.collect_workspace_inventory
)


def _noop_startup_service(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for a background service suppressed by fast pilot startup."""


async def _run_fast_mount_state_loads(app: AceApp) -> None:
    """Install deterministic mount state without reading the host filesystem."""
    try:
        notification_state: NotificationStartupState = (set(), set(), [])
        if (
            _notifications.read_notification_snapshot
            is not _ORIGINAL_READ_NOTIFICATION_SNAPSHOT
        ):
            # Caller-supplied fixtures (notably the visual harness) remain the
            # source of truth. They are still called off the event loop so a
            # deliberately blocked fixture retains production scheduling.
            notification_state = await asyncio.to_thread(
                app._read_notifications_for_startup
            )
        app._initialize_agent_tracking(notification_state)
        app._apply_prompt_stash_counts(0, 0)
        # AcePage owns both ChangeSpec loader patches, so this retains the real
        # filtering, selection, and widget-application path without a disk scan.
        app._apply_changespecs(app._read_changespecs_from_disk())
    finally:
        app._mount_state_loads_done = True


def _finish_fast_agent_startup(app: AceApp) -> None:
    """Complete the empty Agents startup surface without scheduling I/O."""
    from sase.ace.tui.widgets import AgentInfoPanel, AgentList

    # The real loader establishes both projections before flipping its first-
    # load flag. Keep the same invariant so later tab switches can run the
    # production in-memory refilter path against an intentionally empty list.
    app._agents_with_children = []
    app._agents_refresh_pending_callbacks.clear()
    app._agents_refresh_scheduled = False
    app._agents_first_load_done = True
    try:
        app.query_one("#agent-list-panel", AgentList).loading = False
    except Exception:
        pass
    try:
        app.query_one("#agent-info-panel", AgentInfoPanel).set_loading(False)
    except Exception:
        pass
    app._maybe_end_startup_stopwatch()


async def _run_fast_agent_startup(app: AceApp) -> None:
    _finish_fast_agent_startup(app)


async def _run_fast_axe_startup(app: AceApp) -> None:
    """Complete the empty AXE startup surface without reading daemon state."""
    from sase.ace.tui.widgets import AxeDashboard, AxeInfoPanel

    app._axe_first_load_done = True
    try:
        app.query_one("#axe-dashboard", AxeDashboard).loading = False
    except Exception:
        pass
    try:
        app.query_one("#axe-info-panel", AxeInfoPanel).set_loading(False)
    except Exception:
        pass
    app._maybe_end_startup_stopwatch()


def _schedule_prompt_catalog_without_startup_warm(
    app: AceApp,
    *,
    reason: str,
    force: bool = False,
    config_dirty: bool = False,
) -> None:
    """Skip automatic warming while retaining page-requested catalog loads."""
    if reason == "startup_warm":
        return
    _ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD(
        app,
        reason=reason,
        force=force,
        config_dirty=config_dirty,
    )


def _empty_plugins_catalog(**_kwargs: Any) -> Any:
    """Return an inert Updates-pane snapshot for unrelated mounted tabs."""
    return _plugins_browser_pane._PluginsLoadResult(
        catalog=None,
        error=None,
        now=0.0,
    )


def _empty_repo_inventory(*_args: Any, **_kwargs: Any) -> RepoInventory:
    return RepoInventory((), ())


def _empty_workspace_inventory(
    *_args: Any,
    **_kwargs: Any,
) -> WorkspaceInventory:
    return WorkspaceInventory((), ())


def _patch_method_if_unchanged(
    stack: AsyncExitStack,
    name: str,
    original: Any,
    replacement: Any,
) -> None:
    """Patch an AceApp method unless a caller already supplied a fixture."""
    if getattr(AceApp, name) is original:
        stack.enter_context(patch.object(AceApp, name, replacement))


def _install_fast_startup_overrides(stack: AsyncExitStack) -> None:
    """Install the scoped nonessential-service overrides used by AcePage."""
    _patch_method_if_unchanged(
        stack,
        "_run_mount_state_loads",
        _ORIGINAL_RUN_MOUNT_STATE_LOADS,
        _run_fast_mount_state_loads,
    )

    if (
        AceApp._run_agent_index_startup_prepare_and_refresh
        is _ORIGINAL_RUN_AGENT_STARTUP
        and _agent_loading.load_agents_from_disk_with_state
        is _ORIGINAL_LOAD_AGENTS_FROM_DISK
    ):
        stack.enter_context(
            patch.object(
                AceApp,
                "_run_agent_index_startup_prepare_and_refresh",
                _run_fast_agent_startup,
            )
        )

    if (
        AceApp._run_axe_startup_init is _ORIGINAL_RUN_AXE_STARTUP
        and AceApp._load_axe_status_async is _ORIGINAL_LOAD_AXE_STATUS_ASYNC
    ):
        stack.enter_context(
            patch.object(AceApp, "_run_axe_startup_init", _run_fast_axe_startup)
        )

    for name, original in (
        ("_schedule_agents_fold_state_load", _ORIGINAL_SCHEDULE_FOLD_STATE_LOAD),
        (
            "_schedule_dismissed_index_startup_sync",
            _ORIGINAL_SCHEDULE_DISMISSED_INDEX_SYNC,
        ),
        ("_start_artifact_watcher", _ORIGINAL_START_ARTIFACT_WATCHER),
        (
            "_start_prompt_source_watcher",
            _ORIGINAL_START_PROMPT_SOURCE_WATCHER,
        ),
        ("_schedule_startup_update_toast_check", _ORIGINAL_SCHEDULE_UPDATE_CHECK),
        ("_schedule_startup_agents_sync_check", _ORIGINAL_SCHEDULE_AGENTS_SYNC_CHECK),
    ):
        _patch_method_if_unchanged(stack, name, original, _noop_startup_service)

    _patch_method_if_unchanged(
        stack,
        "_schedule_prompt_catalog_rebuild",
        _ORIGINAL_SCHEDULE_PROMPT_CATALOG_REBUILD,
        _schedule_prompt_catalog_without_startup_warm,
    )
    if (
        _stall_watchdog.start_event_loop_stall_watchdog
        is _ORIGINAL_START_STALL_WATCHDOG
    ):
        stack.enter_context(
            patch.object(
                _stall_watchdog,
                "start_event_loop_stall_watchdog",
                _noop_startup_service,
            )
        )
    if _plugins_browser_pane._load_plugins_catalog is _ORIGINAL_LOAD_PLUGINS_CATALOG:
        stack.enter_context(
            patch.object(
                _plugins_browser_pane,
                "_load_plugins_catalog",
                _empty_plugins_catalog,
            )
        )
    if (
        _project_inventory_panes.collect_repo_inventory
        is _ORIGINAL_COLLECT_REPO_INVENTORY
    ):
        stack.enter_context(
            patch.object(
                _project_inventory_panes,
                "collect_repo_inventory",
                _empty_repo_inventory,
            )
        )
    if (
        _project_inventory_panes.collect_workspace_inventory
        is _ORIGINAL_COLLECT_WORKSPACE_INVENTORY
    ):
        stack.enter_context(
            patch.object(
                _project_inventory_panes,
                "collect_workspace_inventory",
                _empty_workspace_inventory,
            )
        )
