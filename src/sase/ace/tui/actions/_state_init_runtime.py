"""Runtime and refresh state initialized before the ACE TUI mounts."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.timer import Timer

from sase.xprompt.highlight_theme import ACE_THEME_NAME

from ...config import get_ace_page_size
from ...query import parse_query_for_profile
from ...query.limit_token import LimitTokenError, ensure_limit, extract_limit
from ...query.types import StringMatch
from ...query_profile import compiled_profile_for_builtin_pane
from ..exit_action import AceExitAction
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate
from .agents_sync import initialize_agents_sync_state
from .update_toast import _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS

if TYPE_CHECKING:
    from ..app import TabName
    from ..models.agent import AgentType
    from ..modals.config_center_modal import CenterTab


def init_runtime_state(
    self: Any,
    *,
    query: str,
    refresh_interval: int,
    auto_start_axe: bool,
    restart_axe: bool,
    initial_tab: TabName,
) -> None:
    """Initialize startup, refresh, watcher, and artifacts-scope state."""
    self._current_idx = 0
    self._current_attempt_number = None
    # Bypass the ``current_tab`` watcher: setting it via descriptor would
    # try to query widgets that haven't been composed yet. The reactive's
    # internal storage was initialized to "artifacts" by ``App.__init__``;
    # overwrite it here so first paint reflects the requested tab.
    self._reactive_current_tab = initial_tab
    # The Admin Center always opens home-first, but a repeated opener may
    # resume the last section that was successfully active in this or a
    # previous ACE process; a second, non-priority opener meaning inside a
    # working tab jumps to the alternate slot of the same pair. This is
    # one bounded read before the event loop starts; panes and their
    # state remain scoped to one modal lifetime.
    from ..modals.config_center_session import AdminCenterSessionState
    from ..modals.config_center_state import load_admin_center_tab_history
    from ..modals.notification_section_modes import NotificationSectionModes

    self._admin_center_session_state = AdminCenterSessionState()
    self._admin_center_history = load_admin_center_tab_history()
    self._last_admin_center_tab = self._admin_center_history.current
    self._admin_center_tab_durable = self._admin_center_history
    self._admin_center_tab_queued = None
    self._admin_center_tab_save_generation = 0
    self._admin_center_tab_completed_generation = 0
    self._admin_center_tab_save_pending = None
    self._admin_center_tab_save_task = None
    # Notification list section mode choices are per ACE process by design.
    self._notification_section_modes = NotificationSectionModes()
    self._init_proc_observer()
    self.theme = ACE_THEME_NAME
    self._auto_start_axe = auto_start_axe
    self._restart_axe = restart_axe
    self.exit_action = AceExitAction.QUIT
    self._controlled_exit_started = False
    # Set during on_mount to suppress reactive-watcher cold loads that
    # would otherwise duplicate work the mount body already performs.
    self._mounting = False
    # Startup loading flags: flipped to True once the first async load
    # completes. Used to distinguish "not yet loaded" from "loaded, empty"
    # in the TUI's agents and axe surfaces.
    self._patches_first_load_done = False
    self._agents_first_load_done = False
    self._axe_first_load_done = False
    self._mount_state_loads_done = False
    # Durable one-record-per-session startup telemetry (StartupTelemetryMixin).
    # ``_startup_process_start_mono`` is stamped by ``AceApp.__init__`` itself,
    # the earliest point in the ACE-specific code path; it excludes interpreter
    # startup and argument parsing, which are shared by every ``sase``
    # subcommand and already measured separately via ``-X importtime``.
    self._startup_process_start_mono = time.monotonic()
    self._startup_on_mount_mono = None
    self._startup_first_paint_mono = None
    self._startup_initial_tab = None
    self._startup_agents_ready_mono = None
    self._startup_axe_ready_mono = None
    self._startup_visible_ready_mono = None
    self._startup_telemetry_recorded = False
    self._agents_onboarding_launch_targets_available = False
    self._agents_onboarding_launch_targets_refresh_scheduled = False
    self._agents_onboarding_launch_targets_refresh_running = False
    self._agents_onboarding_launch_targets_refresh_pending = False
    self._agents_onboarding_plugins_installed = True
    self._agents_onboarding_plugins_refresh_scheduled = False
    self._agents_onboarding_plugins_refresh_running = False
    self._agents_onboarding_plugins_refresh_pending = False
    self._update_toast_shown = False
    # Provider names from the last *completed* automatic update result.
    # ``None`` means no completed result has supplied authority yet; an
    # empty tuple is an authoritative completed result with no candidates.
    self._automatic_update_status = None
    self._automatic_update_provider_names = None
    self._automatic_update_check_in_flight = False
    self._automatic_update_check_interval_seconds = (
        _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS
    )
    self._automatic_update_check_timer = None
    initialize_agents_sync_state(self)
    # Deferred live-workspace pencil-hint scan coalescing. The expensive
    # per-agent live VCS diff is computed in a background worker after the
    # first agents load applies (never on the startup-critical loader
    # path); these flags collapse refresh bursts into one trailing scan.
    self._live_hints_scan_scheduled = False
    self._live_hints_scan_running = False
    self._live_hints_scan_pending = False
    self._live_hints_scan_source = "unknown"
    self._pump_free_async_tasks = set()
    self._auto_refresh_scheduled = False
    self._auto_refresh_running = False
    self._auto_refresh_pending = False
    self._auto_refresh_deferred = False
    self._axe_status_refresh_scheduled = False
    self._axe_status_refresh_running = False
    self._axe_status_refresh_pending = False
    self._axe_targeted_refresh_scheduled = False
    self._axe_targeted_refresh_running = False
    self._axe_targeted_refresh_pending = False
    # Deferred bead-confirmation warmup coalescing. Row/header rendering can
    # only show confirmed bead UI from cache, so the per-candidate bead-store
    # lookup runs in a background worker after an agents load applies; these
    # flags collapse refresh bursts into one trailing scan.
    self._bead_warmup_scan_scheduled = False
    self._bead_warmup_scan_running = False
    self._bead_warmup_scan_pending = False
    self._bead_warmup_scan_source = "unknown"
    self._bead_warmup_async_tasks = set()
    # Deferred agent-family plan-preview warmup coalescing. Completion rows
    # read family previews from memory only; plan/bead resolution runs after
    # Agents loads or after a completion menu sees an unresolved family.
    self._family_preview_scan_scheduled = False
    self._family_preview_scan_running = False
    self._family_preview_scan_pending = False
    self._family_preview_scan_source = "unknown"
    self._family_preview_async_tasks = set()
    # Deferred persisted diff-badge classification coalescing. Row
    # rendering can only show the badge from its precomputed field, so the
    # per-row diff/commit reads run in a background worker after an
    # agents load applies; these flags collapse refresh bursts into one
    # trailing scan.
    self._diff_badge_scan_scheduled = False
    self._diff_badge_scan_running = False
    self._diff_badge_scan_pending = False
    self._diff_badge_scan_source = "unknown"
    self._diff_badge_async_tasks = set()
    self._patch_limit_truncated = False
    self.query_string = ensure_limit(query, get_ace_page_size())
    patch_profile = compiled_profile_for_builtin_pane("patches")
    if patch_profile is None:
        raise ValueError("Patch query profile is not registered")
    try:
        remainder, _cap = extract_limit(self.query_string)
    except LimitTokenError:
        remainder = self.query_string
    self.parsed_query = (
        StringMatch("")
        if not remainder.strip()
        else parse_query_for_profile(remainder, patch_profile)
    )
    from ...query import get_sole_project_filter

    # Shared Artifacts scope state is memory-only for this TUI session.
    # Project inventory itself remains lazy and is read off-thread on the
    # first project-backed pane activation.
    self.artifacts_project_scope = get_sole_project_filter(self.parsed_query)
    self._patch_query_scope_seed_attempted = False
    self._patch_query_scope_seed_baseline = None
    self._artifacts_project_choices = None
    self._artifacts_project_choices_loading = False
    self._artifacts_project_picker_pending = False
    self._artifacts_scope_was_picked = False
    self.artifacts_plan_target_bead_id = None
    self.refresh_interval = refresh_interval
    from ..tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS

    self._slow_tool_call_threshold_ms = SLOW_TOOL_CALL_THRESHOLD_MS
    self._refresh_timer = None
    self._countdown_timer = None
    self._countdown_remaining = refresh_interval

    # Phase 5: navigation gate + inotify watcher for event-driven
    # background refresh.  ``_fs_watcher`` is attached during on_mount
    # post-load and cleared on quit.
    self._nav_gate = NavigationGate()
    self._fs_watcher = None
    self._sdd_beads_dir = None
    self._stall_watchdog = None
    self._stall_watchdog_suspend_signals_wired = False

    # Phase 7 event-driven auto-refresh state.  When the inotify
    # watcher is active, ``_on_artifact_change`` flips the dirty
    # flags; the auto-refresh tick only does work for flags that are
    # set (or when the slow sanity floor below has elapsed). Defaults
    # mark "dirty" so the first tick still primes everything when no
    # watcher event has fired yet.
    self._dirty_patches = True
    self._dirty_agents = True
    self._dirty_agent_artifact_dirs = ()
    self._dirty_deleted_agent_artifact_dirs = ()
    self._dirty_agent_artifact_fallback_reason = None
    self._expected_agent_artifact_deletions = {}
    self._expected_agent_artifact_deletions_lock = threading.Lock()
    self._dirty_axe = True
    self._dirty_notifications = True
    self._artifact_change_defer_pending = False
    self._last_full_sanity_refresh = 0.0
    self._prompt_editor_suspended = False
    self._last_agents_load_mono = 0.0
    # Per-STARTING-agent agent_meta.json/waiting.json (mtime_ns, size)
    # cache used by the countdown-tick STARTING-transition poll. Each
    # tuple slot is ``None`` when that marker was absent on the previous
    # tick so a subsequent file appearance still triggers a refresh
    # nudge.
    self._starting_poll_meta_cache = {}
