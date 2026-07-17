"""State initialization for the ace TUI app's startup mixin.

Houses ``_init_app_state``, split out of ``startup.py`` to keep both
modules under the per-file line budget. Inherited by ``StartupMixin``.
"""

from __future__ import annotations

import asyncio
import signal
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any, Literal

from textual.timer import Timer
from textual.worker import Worker

from ...query import parse_query
from ..exit_action import AceExitAction
from ..models.fold_state import FoldStateManager
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate
from ._state_init_late import init_late_startup_state
from .update_toast import _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS

if TYPE_CHECKING:
    from ...agent_query import QueryExpr as AgentQueryExpr
    from ..app import TabName
    from ..models import Agent
    from ..models.agent import AgentType
    from ..models.agent_loader import AgentLoadState
    from ..models.agent_fold_persistence import AgentsFoldStateSnapshot
    from ..tools.report import SlowToolCallReportSpec
    from ..widgets.prompt_panel._agent_display_state import CommitViewSpec
    from .agents._fold_persistence import AgentFoldIntent
    from .navigation._types import JumpAllResult
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire
    from sase.core.query_corpus_facade import QueryCorpus

__all__ = ["StateInitMixin"]


class StateInitMixin:
    """Mixin housing the multi-section ``_init_app_state`` method."""

    def _init_app_state(
        self,
        query: str,
        model_tier_override: Literal["large", "small"] | None,
        refresh_interval: int,
        auto_start_axe: bool,
        restart_axe: bool,
        initial_tab: TabName,
    ) -> None:
        """Initialize all instance state for ``AceApp``.

        Called from ``AceApp.__init__`` after ``super().__init__()``. All
        one-time state setup lives here (rather than inline) so ``app.py``
        stays focused on the class shell.
        """
        self._current_idx = 0
        self._current_attempt_number: int | None = None
        # Bypass the ``current_tab`` watcher: setting it via descriptor would
        # try to query widgets that haven't been composed yet. The reactive's
        # internal storage was initialized to "changespecs" by ``App.__init__``;
        # overwrite it here so first paint reflects the requested tab.
        self._reactive_current_tab = initial_tab  # type: ignore[attr-defined]
        self._init_task_queue()  # type: ignore[attr-defined]
        self.theme = "flexoki"
        # Seed the last-focused Admin Center tab from disk so a fresh TUI
        # reopens ``#`` on the tab used in a previous run. A single small file
        # read; falls back to "config" when absent/malformed/stale. Validated
        # against the Admin Center's tab order (the single source of truth).
        from ..modals.config_center_modal import _TAB_ORDER

        from ...admin_center_tab import load_admin_center_tab

        self._admin_center_tab: str = load_admin_center_tab(_TAB_ORDER) or "config"
        # Latest-value coalescing for off-thread persistence of the active tab
        # (see ``BaseActionsMixin._persist_admin_center_tab``).
        self._admin_center_tab_save_pending: str | None = None
        self._admin_center_tab_save_inflight: bool = False
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
        self._changespecs_first_load_done = False
        self._agents_first_load_done = False
        self._axe_first_load_done = False
        self._mount_state_loads_done = False
        self._agents_onboarding_launch_targets_available = False
        self._agents_onboarding_launch_targets_refresh_scheduled = False
        self._agents_onboarding_launch_targets_refresh_running = False
        self._agents_onboarding_launch_targets_refresh_pending = False
        self._agents_onboarding_plugins_installed = True
        self._agents_onboarding_plugins_refresh_scheduled = False
        self._agents_onboarding_plugins_refresh_running = False
        self._agents_onboarding_plugins_refresh_pending = False
        self._update_toast_shown = False
        self._automatic_update_check_in_flight = False
        self._automatic_update_check_interval_seconds = (
            _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS
        )
        self._automatic_update_check_timer: Timer | None = None
        # Deferred live-workspace pencil-hint scan coalescing. The expensive
        # per-agent live VCS diff is computed in a background worker after the
        # first agents load applies (never on the startup-critical loader
        # path); these flags collapse refresh bursts into one trailing scan.
        self._live_hints_scan_scheduled = False
        self._live_hints_scan_running = False
        self._live_hints_scan_pending = False
        self._live_hints_scan_source = "unknown"
        self._pump_free_async_tasks: set[asyncio.Task[object]] = set()
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
        self._bead_warmup_async_tasks: set[asyncio.Task[None]] = set()
        self.query_string = query
        self.parsed_query = parse_query(query)
        from ...query import get_sole_project_filter

        # Shared Artifacts scope state is memory-only for this TUI session.
        # Project inventory itself remains lazy and is read off-thread on the
        # first project-backed pane activation.
        self.artifacts_project_scope: str | None = get_sole_project_filter(
            self.parsed_query
        )
        self._artifacts_project_choices: Any = None
        self._artifacts_project_choices_loading = False
        self._artifacts_project_picker_pending = False
        self._artifacts_scope_was_picked = False
        self.artifacts_plan_target_bead_id: str | None = None
        self.refresh_interval = refresh_interval
        from ..tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS

        self._slow_tool_call_threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS
        self._refresh_timer: Timer | None = None
        self._countdown_timer: Timer | None = None
        self._countdown_remaining = refresh_interval

        # Phase 5: navigation gate + inotify watcher for event-driven
        # background refresh.  ``_fs_watcher`` is attached during on_mount
        # post-load and cleared on quit.
        self._nav_gate = NavigationGate()
        self._fs_watcher: ArtifactWatcher | None = None
        self._sdd_beads_dir: Path | None = None
        self._stall_watchdog: Any = None
        self._stall_watchdog_suspend_signals_wired: bool = False

        # Phase 7 event-driven auto-refresh state.  When the inotify
        # watcher is active, ``_on_artifact_change`` flips the dirty
        # flags; the auto-refresh tick only does work for flags that are
        # set (or when the slow sanity floor below has elapsed). Defaults
        # mark "dirty" so the first tick still primes everything when no
        # watcher event has fired yet.
        self._dirty_changespecs: bool = True
        self._dirty_agents: bool = True
        self._dirty_agent_artifact_dirs: tuple[Path, ...] = ()
        self._dirty_deleted_agent_artifact_dirs: tuple[Path, ...] = ()
        self._dirty_agent_artifact_fallback_reason: str | None = None
        self._expected_agent_artifact_deletions: dict[str, float] = {}
        self._expected_agent_artifact_deletions_lock = threading.Lock()
        self._dirty_axe: bool = True
        self._dirty_notifications: bool = True
        self._artifact_change_defer_pending: bool = False
        self._last_full_sanity_refresh: float = 0.0
        self._last_agents_load_mono: float = 0.0
        # Per-STARTING-agent agent_meta.json/waiting.json (mtime_ns, size)
        # cache used by the countdown-tick STARTING-transition poll. Each
        # tuple slot is ``None`` when that marker was absent on the previous
        # tick so a subsequent file appearance still triggers a refresh
        # nudge.
        self._starting_poll_meta_cache: dict[
            tuple[AgentType, str, str | None],
            tuple[tuple[int, int] | None, tuple[int, int] | None],
        ] = {}

        # Hint mode state
        self._hint_mode_active: bool = False
        self._hint_mode_hints_for: str | None = (
            None  # None/"all" or "hooks_latest_only"
        )
        self._hint_mappings: dict[int, str] = {}
        self._hint_tool_call_reports: dict[str, SlowToolCallReportSpec] = {}
        self._hint_commit_views: dict[int, CommitViewSpec] = {}
        self._hook_hint_to_idx: dict[int, int] = {}
        self._hint_to_entry_id: dict[int, str] = {}
        self._hint_changespec_name: str = ""

        # Accept mode state
        self._accept_mode_active: bool = False
        self._accept_last_base: str | None = None

        # Rewind mode state
        self._rewind_mode_active: bool = False

        # Fold mode state (for z key sub-command)
        self._fold_mode_active: bool = False

        # Checkout mode state (for c key sub-commands)
        self._checkout_mode_active: bool = False

        # Copy mode state (for % key sub-commands)
        self._copy_mode_active: bool = False

        # Last input timestamp used to defer non-urgent background work.
        self._last_input_mono = 0.0
        self._last_input_action: str | None = None
        # Stable widget refs cached during ``on_mount`` so hot paths (j/k
        # navigation, debounced detail refresh, mark toggle) skip repeated
        # ``query_one`` walks against the DOM. ``None`` until mount runs;
        # callers must fall back to ``query_one`` while these are unset
        # (e.g. tests that exercise mixin methods without mounting).
        self._w_changespec_list: Any = None
        self._w_changespec_detail: Any = None
        self._w_ancestors_children: Any = None
        self._w_changespec_info_panel: Any = None
        self._w_footer: Any = None
        self._w_search_query_panel: Any = None
        self._w_agent_detail: Any = None
        self._w_agent_info_panel: Any = None
        self._w_tab_bar: Any = None

        # Cached graph index over ``_all_changespecs``; rebuilt only when the
        # list identity changes (see ``_get_changespec_graph_index``).
        self._changespec_graph_index: Any = None
        self._changespec_graph_index_for_id: int | None = None

        # Leader mode state (for , key sub-commands)
        self._leader_mode_active: bool = False
        self._last_leader_key: str | None = None

        # Bang mode state (for ! key sub-commands)
        self._bang_mode_active: bool = False

        # Axe worker state (for background start/stop)
        self._axe_worker: Worker[Any] | None = None
        self._axe_worker_operation: Literal["start", "stop", "restart"] | None = None

        # Custom mode state (for user-defined prefix-key modes)
        self._custom_mode_active: str | None = None

        # One-key jump mode state (V)
        self._entry_jump_mode_active: bool = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        # Agents-tab banner targets (kept in their own maps so the int-keyed
        # agent maps above can stay shared with ChangeSpecs / AXE tabs).
        from .navigation.jump_hints import (
            AgentJumpAnchor,
            BannerJumpTarget,
            EntryJumpAnchor,
            PanelJumpTarget,
        )

        self._entry_jump_hint_to_banner: dict[str, BannerJumpTarget] = {}
        self._entry_jump_banner_to_hint: dict[BannerJumpTarget, str] = {}
        self._entry_jump_hint_to_panel: dict[str, PanelJumpTarget] = {}
        self._entry_jump_panel_to_hint: dict[PanelJumpTarget, str] = {}

        # ChangeSpecs-tab banner jump-hint maps for grouped mode.  Banner identity
        # is the group key tuple — there's no panel scope on ChangeSpecs so the
        # tuple alone is sufficient.  Empty in flat mode and on tabs that
        # don't render banner rows.
        self._entry_jump_hint_to_changespec_banner: dict[str, tuple[str, ...]] = {}
        self._entry_jump_changespec_banner_to_hint: dict[tuple[str, ...], str] = {}

        # Entry jump-stack state. Non-Agents tabs keep per-tab row/banner
        # anchor stacks; the Agents tab uses richer anchors so panel and
        # banner focus can be restored.
        self._entry_jump_index_stack: dict[str, list[EntryJumpAnchor]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[EntryJumpAnchor]] = {}
        self._entry_jump_last_panel: dict[str, str | None] = {}
        self._entry_jump_agents_anchor_stack: list[AgentJumpAnchor] = []
        self._entry_jump_agents_forward_anchor_stack: list[AgentJumpAnchor] = []

        # Cross-tab jump back state (`)
        self._jump_all_last_position: JumpAllResult | None = None

        # Ancestor/child/sibling navigation state
        self._ancestor_mode_active: bool = False
        self._child_mode_active: bool = False
        self._sibling_mode_active: bool = False
        self._child_key_buffer: str = ""  # Buffer for multi-key child sequences
        self._ancestor_keys: dict[str, str] = {}  # name -> keymap
        self._children_keys: dict[str, str] = {}  # key -> name (for navigation)
        self._sibling_keys: dict[str, str] = {}  # key -> name (for sibling navigation)
        from ...changespec import ChangeSpec

        self._all_changespecs: list[ChangeSpec] = []  # Cache for ancestry lookup
        self._query_corpus: QueryCorpus | None = None
        self._query_corpus_source_list_id: int | None = None
        self._hidden_reverted_count: int = 0  # Count of filtered reverted ChangeSpecs

        # Tab state - track position in each tab
        self._changespecs_last_idx: int = 0
        self._changespecs_last_name: str | None = None
        self._agents_last_idx: int = 0
        self._agents_last_identity: tuple[AgentType, str, str | None] | None = None
        self._agents: list[Agent] = []
        self._agents_loading: bool = False
        self._agents_refresh_pending: bool = False
        self._agents_refresh_pending_source: str = "unknown"
        self._agents_refresh_pending_full_history: bool = False
        self._agents_refresh_pending_full_history_reason: str | None = None
        self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
        self._agents_refresh_scheduled: bool = False
        self._agents_refresh_scheduled_source: str = "unknown"
        self._agents_refresh_scheduled_full_history: bool = False
        self._agents_refresh_scheduled_full_history_reason: str | None = None
        self._agents_refresh_active_source: str = "unknown"
        self._agents_refresh_async_tasks: set[asyncio.Task[None]] = set()
        self._loader_cleanup_running: bool = False
        self._loader_cleanup_pending: bool = False
        self._loader_cleanup_pending_request: Any | None = None
        self._loader_cleanup_async_tasks: set[asyncio.Task[None]] = set()
        self._agents_refresh_debounce_armed: bool = False
        self._agents_refresh_debounce_source: str = "unknown"
        self._artifact_index_maintenance_running: bool = False
        self._artifact_index_maintenance_pending: bool = False
        self._artifact_index_maintenance_pending_request: Any | None = None
        self._artifact_index_maintenance_last_mono: float = 0.0
        self._artifact_index_schema_rebuild_in_flight: bool = False
        self._artifact_index_schema_bypass: bool = False
        self._dismissed_index_sync_pending_after_schema_rebuild: bool = False
        # Deferred Tier 2 reconcile: set when a load arrives with
        # incomplete history. The reconcile is then triggered lazily by an
        # input-quiet tick or explicit full-history refresh action rather than
        # firing immediately at startup (see ``_loading_apply`` and
        # ``_maybe_trigger_input_quiet_tier2_reconcile``).
        self._agents_history_reconcile_pending: bool = False
        self._agents_history_reconcile_armed_mono: float = 0.0
        self._agent_load_state: AgentLoadState | None = None
        self._agents_index_repair_notice_key: tuple[str | None, str | None] | None = (
            None
        )
        self._agents_seen_complete_history: bool = False
        self._agents_repro_capture: Any = None
        self._agents_repro_auto_check_enabled: bool = False
        self._agents_repro_auto_capture_burst_active: bool = False
        self._agents_repro_last_invariant_failures: list[Any] = []
        self._agents_repro_output_dir: str = ""
        self._artifact_tmux_pane_id: str | None = None
        self._artifact_tmux_decoration_state: Any = None
        self._artifact_viewer_previous_sigusr1_handler: (
            signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
        ) = None
        # Bounded LRU; eviction happens in
        # ``_panel_artifacts._artifact_cache_put`` once the cache exceeds
        # AGENT_ARTIFACT_PAGE_CACHE_MAX entries.
        self._agent_artifact_page_cache: OrderedDict[tuple[Any, ...], list[Any]] = (
            OrderedDict()
        )
        self._agent_artifact_discovery_inflight: dict[
            tuple[Any, ...], asyncio.Task[Any]
        ] = {}
        self._post_mount_background_loads_started = False
        self._changespecs_loading: bool = False
        self._changespecs_refresh_scheduled: bool = False
        self._changespecs_refresh_pending: bool = False
        self._has_always_visible: bool = False
        self._hidden_count: int = 0
        self._agent_search_query: str = ""

        # Cached parsed agent-query AST keyed by raw query string so
        # re-renders skip the parse. ``None`` AST means "no filter".
        self._agent_query_cache: tuple[str, AgentQueryExpr | None] | None = None
        # Last agent-query parse error, surfaced by the filter modal.
        self._agent_query_parse_error: str | None = None

        # Lazy cache of lowercased prompt/reply content for the `/` filter.
        # Populated only when a search query is active.
        from ..models.agent_content_search import (
            AgentContentSearchCache,
            AgentContentSearchIndex,
        )

        self._agent_content_search_cache = AgentContentSearchCache()
        self._agent_content_search_index: AgentContentSearchIndex | None = None
        self._agent_content_search_source_generation: int = 0
        self._agent_content_search_refresh_generation: int = 0
        self._agent_content_search_refresh_task: asyncio.Task[None] | None = None

        # Fold state for nested workflow steps
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}

        # Group fold: tracks per-group collapse state for the agents-tab
        # two-level grouping tree (project → name-root).  Layers *above*
        # the per-workflow fold manager — workflow folds only take effect
        # once the enclosing group is expanded.  Empty registry => every
        # group expanded (first-paint default).
        #
        # Per-mode registry: each grouping mode maintains its own fold
        # state so cycling grouping mode doesn't lose collapse intent on
        # the mode the user came from.  ``_group_fold_registry`` always
        # points at the active mode's slot; the cycle action swaps it
        # in via :meth:`_ensure_mode_registry` so existing call sites
        # (loading, folding, display) keep reading a single attribute.
        from ...grouping_strategy import (
            load_agent_grouping_mode,
            load_changespec_grouping_mode,
        )
        from ..models.agent_group_fold import AgentGroupFoldRegistry
        from ..models.agent_groups import GroupingMode

        self._grouping_mode: GroupingMode = load_agent_grouping_mode()
        self._group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry] = {
            self._grouping_mode: AgentGroupFoldRegistry(),
        }
        self._group_fold_registry: AgentGroupFoldRegistry = self._group_fold_registries[
            self._grouping_mode
        ]
        # When non-None, the user has navigated onto a group banner row
        # (only possible when that group is collapsed).  Banner-aware
        # actions look at this to target the group instead of the
        # underlying agent.
        self._current_group_key: tuple[str, ...] | None = None

        # ChangeSpecs-tab grouping state (mirrors the Agents-tab attributes above
        # but with its own enum and per-mode fold registries so cycling
        # one tab cannot leak collapse intent into the other).
        # Empty registry on first paint => every group expanded.
        from ..models.changespec_groups import ChangeSpecGroupingMode
        from ..models.group_fold import GroupFoldRegistry

        self._changespec_grouping_mode: ChangeSpecGroupingMode = (
            load_changespec_grouping_mode()
        )
        self._changespec_group_fold_registries: dict[
            ChangeSpecGroupingMode, GroupFoldRegistry
        ] = {
            self._changespec_grouping_mode: GroupFoldRegistry(),
        }
        self._changespec_group_fold_registry: GroupFoldRegistry = (
            self._changespec_group_fold_registries[self._changespec_grouping_mode]
        )
        # Active banner focus on the ChangeSpecs tab (Phase 4 will surface this on
        # navigation; Phase 3 just needs a stable attribute to clear on
        # mode cycle and pass through to ``ChangeSpecList.update_list``).
        self._current_changespec_group_key: tuple[str, ...] | None = None

        # Nonblocking grouping-mode persistence state.  The cycle action
        # maintains a latest-value write per target so repeated keypresses
        # cannot leave an older mode on disk after a slower write finishes.
        self._grouping_mode_save_pending: dict[str, object] = {}
        self._grouping_mode_save_inflight: set[str] = set()
        self._grouping_mode_save_active: dict[str, object] = {}

        # Tag-driven side-panel collection.  Initialized empty (untagged
        # main pane only); rebuilt by ``_load_agents`` whenever the
        # agent set changes.
        from ..models.agent_panels import AgentPanelGroup, PanelKey

        self._agent_panels_grouped: bool = False
        self._panel_group: AgentPanelGroup = AgentPanelGroup()
        # Whole-panel collapse state is independent of the group/workflow fold
        # registries so expanding a panel restores its in-panel folds exactly
        # as they were. The fields below drive a one-shot post-first-paint load,
        # pre-load mutation journal, and latest-generation off-thread writer.
        self._collapsed_panel_keys: set[PanelKey] = set()
        # Numeric, set-oriented panel folding mode (leader ``,H``).  Its maps
        # are deliberately separate from file hints and apostrophe jump hints.
        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot: tuple[PanelKey, ...] = ()
        self._panel_fold_hint_to_key: dict[int, PanelKey] = {}
        self._panel_fold_key_to_hint: dict[PanelKey, int] = {}
        self._agents_fold_state_load_started = False
        self._agents_fold_state_load_resolved = False
        self._agents_fold_state_loaded_snapshot: AgentsFoldStateSnapshot | None = None
        self._agents_fold_state_merged = False
        self._agents_fold_state_intents: list[AgentFoldIntent] = []
        self._agents_fold_state_save_requested = False
        self._agents_fold_state_save_generation = 0
        self._agents_fold_state_completed_generation = 0
        self._agents_fold_state_save_pending: (
            tuple[int, AgentsFoldStateSnapshot] | None
        ) = None
        self._agents_fold_state_save_task: asyncio.Task[None] | None = None
        self._agents_fold_state_load_worker: Worker[Any] | None = None
        self._agents_fold_restore_needs_focus_snap = False

        # j/k navigation caches (Phase 2 of jk_navigation_reliability):
        # ``_panel_navigation_stops`` and ``panel_key_per_agent`` are
        # called several times per keystroke; memoize them so a 20-key
        # autorepeat burst rebuilds the agent tree at most once.  Cache
        # keys include the agents-list ref, ``_panel_group`` ref +
        # focused index, the fold registry's monotonic ``version``, and
        # the active grouping mode — every invalidator already mutates
        # one of those, so no explicit bumps are needed at writers.
        self._nav_stops_cache: tuple[Any, ...] | None = None
        self._panel_keys_cache: tuple[Any, ...] | None = None
        self._agent_panel_index_cache: tuple[Any, bool, Any] | None = None
        self._agent_neighbor_index_cache: tuple[Any, ...] | None = None
        self._dismiss_revive_epoch: int = 0
        self._agent_info_metrics_cache: tuple[Any, ...] | None = None

        # Agent completion tracking for notifications
        from ...dismissed_agents import (
            dismissed_agents_file_signature,
            load_dismissed_agents,
        )

        self._last_unread_ids: set[str] = set()
        self._notification_snapshot_cache: Any | None = None
        self._notification_snapshot_version: int = 0
        self._notification_snapshot_refresh_pending: bool = False
        self._notification_snapshot_refresh_followup: bool = False
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_display_status_by_identity: dict[
            tuple[AgentType, str, str | None], str
        ] = {}
        self._dismissed_agents = load_dismissed_agents()
        self._dismissed_agents_disk_signature = dismissed_agents_file_signature()
        self._dismissed_agents_disk_identities = set(self._dismissed_agents)
        self._dismissed_agents_disk_signature_initialized = True
        # The artifact-index dismissed-projection sync is deliberately NOT
        # run here: it is O(archive) on signature drift (and unbounded on
        # a corrupt index), and __init__ runs before Textual ever paints.
        # The post-mount startup worker runs it in a thread instead
        # (StartupMixin._run_dismissed_index_startup_sync).
        self._dismissed_agent_objects: list[Agent] = []
        # The recent dismissed-agent group cache is intentionally left empty at
        # startup: the revive modal (`_revive_agent`) re-reads the recent store
        # from disk and merges it into this cache every time it opens, so a cold
        # init would only duplicate that read on the latency-sensitive cold-start
        # path. See sdd/tales/202606/recent_restore_perf_fix.md.
        self._recent_dismissed_agent_groups: list[SavedAgentGroupWire] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        # Explicit mark order (the order rows were marked with ``m``); kept
        # alongside ``_marked_agents`` because a set cannot preserve the order
        # the bulk kill-and-edit prompt stack must follow.
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []

        # Agent status override system (for PLAN/PLAN APPROVED/QUESTION statuses)
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._kill_persistence_inflight: set[tuple[AgentType, str, str | None]] = set()

        # Plan feedback context (set when user presses 'f' in plan approval modal)
        from .agents._types import PlanFeedbackContext

        self._plan_feedback_context: PlanFeedbackContext | None = None

        # Debouncer for j/k navigation detail panel updates (agents tab)
        from ..util.debounce import DetailPanelDebouncer

        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]

        init_late_startup_state(self, model_tier_override)
