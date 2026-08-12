"""Agent, panel, fold, and notification state for ACE startup."""

from __future__ import annotations

import asyncio
import signal
from collections import OrderedDict
from collections.abc import Callable
from types import FrameType
from typing import TYPE_CHECKING, Any, Literal

from textual.timer import Timer
from textual.worker import Worker

from ..models.agent_runner_slots import RunnerCapacitySnapshot
from ..models.fold_state import FoldStateManager, SectionFoldStateManager

if TYPE_CHECKING:
    from ...agent_query import QueryExpr as AgentQueryExpr
    from ..models import Agent
    from ..models.agent import AgentType
    from ..models.agent_fold_persistence import AgentsFoldStateSnapshot
    from ..models.agent_loader import AgentLoadState
    from ..models.agent_panels import PanelFoldSweepRecord, PanelIsolationRevert
    from ..widgets.prompt_panel._member_roster import (
        MemberJumpContainerIdentity,
        MemberJumpMap,
    )
    from .agents._fold_persistence import AgentFoldIntent
    from .agents._panel_hint_folding import FoldHintTarget
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire


def init_agent_state(self: Any) -> None:
    """Initialize agent loading, grouping, panel, and notification state."""
    # Tab state - track position in each tab
    self._patches_last_idx = 0
    self._patches_last_name = None
    self._agents_last_idx = 0
    self._agents_last_identity = None
    self._agents = []
    self._agent_runner_capacity = RunnerCapacitySnapshot()
    self._agents_loading = False
    self._agents_refresh_pending = False
    self._agents_refresh_pending_source = "unknown"
    self._agents_refresh_pending_full_history = False
    self._agents_refresh_pending_full_history_reason = None
    self._agents_refresh_pending_revalidate_index = False
    self._agents_refresh_pending_callbacks = []
    self._agents_refresh_scheduled = False
    self._agents_refresh_scheduled_source = "unknown"
    self._agents_refresh_scheduled_full_history = False
    self._agents_refresh_scheduled_full_history_reason = None
    self._agents_refresh_scheduled_revalidate_index = False
    self._agents_refresh_active_source = "unknown"
    self._agents_refresh_async_tasks = set()
    self._agents_artifact_delta_scheduled = None
    self._agents_artifact_delta_pending = None
    self._loader_cleanup_running = False
    self._loader_cleanup_pending = False
    self._loader_cleanup_pending_request = None
    self._loader_cleanup_async_tasks = set()
    self._startup_telemetry_async_tasks = set()
    self._agents_refresh_debounce_armed = False
    self._agents_refresh_debounce_source = "unknown"
    self._agents_index_revalidate_pending = False
    self._agents_index_revalidate_armed_mono = 0.0
    self._agents_index_revalidate_last_mono = 0.0
    self._artifact_index_maintenance_running = False
    self._artifact_index_maintenance_pending = False
    self._artifact_index_maintenance_pending_request = None
    self._artifact_index_maintenance_last_mono = 0.0
    self._artifact_index_schema_rebuild_in_flight = False
    self._artifact_index_schema_bypass = False
    self._dismissed_index_sync_pending_after_schema_rebuild = False
    # Deferred Tier 2 reconcile: set when a load arrives with
    # incomplete history. The reconcile is then triggered lazily by an
    # input-quiet tick or explicit full-history refresh action rather than
    # firing immediately at startup (see ``_loading_apply`` and
    # ``_maybe_trigger_input_quiet_tier2_reconcile``).
    self._agents_history_reconcile_pending = False
    self._agents_history_reconcile_armed_mono = 0.0
    self._agent_load_state = None
    self._agents_index_repair_notice_key = None
    self._agents_seen_complete_history = False
    self._agents_repro_capture = None
    self._agents_repro_auto_check_enabled = False
    self._agents_repro_auto_capture_burst_active = False
    self._agents_repro_last_invariant_failures = []
    self._agents_repro_output_dir = ""
    self._artifact_file_tmux_pane_id = None
    self._artifact_file_tmux_decoration_state = None
    self._artifact_file_viewer_previous_sigusr1_handler = None
    # Bounded LRU; eviction happens in
    # ``_panel_artifact_files._artifact_file_cache_put`` once the cache exceeds
    # ARTIFACT_FILE_PAGE_CACHE_MAX entries.
    self._artifact_file_page_cache = OrderedDict()
    self._artifact_file_discovery_inflight = {}
    self._post_mount_background_loads_started = False
    self._patches_loading = False
    self._patches_refresh_scheduled = False
    self._patches_refresh_pending = False
    self._has_always_visible = False
    self._hidden_count = 0
    self._agent_search_query = ""

    # Cached parsed agent-query AST keyed by raw query string so
    # re-renders skip the parse. ``None`` AST means "no filter".
    self._agent_query_cache = None
    # Last agent-query parse error, surfaced by the filter modal.
    self._agent_query_parse_error = None

    # Lazy cache of lowercased prompt/reply content for the `/` filter.
    # Populated only when a search query is active.
    from ..models.agent_content_search import (
        AgentContentSearchCache,
        AgentContentSearchIndex,
    )

    self._agent_content_search_cache = AgentContentSearchCache()
    self._agent_content_search_index = None
    self._agent_content_search_source_generation = 0
    self._agent_content_search_refresh_generation = 0
    self._agent_content_search_refresh_task = None

    # Fold state for nested workflow steps
    self._fold_manager = FoldStateManager()
    self._fold_counts = {}
    # Session-only metadata-panel fold state.  Individual sections inherit
    # ``panel_fold_level`` unless an action records an override here.
    self._panel_fold_overrides = SectionFoldStateManager()
    # Exact number-to-member maps emitted by rendered container rosters.
    # Digit navigation validates the selected container identity against
    # this in-memory registry before using a target.
    self._member_jump_maps = {}
    self._member_jump_pending_digit = None
    self._member_jump_pending_container_identity = None

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
        load_patch_grouping_mode,
    )
    from ..models.agent_group_fold import AgentGroupFoldRegistry
    from ..models.agent_groups import GroupingMode

    self._grouping_mode = load_agent_grouping_mode()
    self._group_fold_registries = {
        self._grouping_mode: AgentGroupFoldRegistry(),
    }
    self._group_fold_registry = self._group_fold_registries[self._grouping_mode]
    # When non-None, the user has navigated onto a group banner row
    # (only possible when that group is collapsed).  Banner-aware
    # actions look at this to target the group instead of the
    # underlying agent.
    self._current_group_key = None

    # Patches-tab grouping state (mirrors the Agents-tab attributes above
    # but with its own enum and per-mode fold registries so cycling
    # one tab cannot leak collapse intent into the other).
    # Empty registry on first paint => every group expanded.
    from ..models.group_fold import GroupFoldRegistry
    from ..models.patch_groups import PatchGroupingMode

    self._patch_grouping_mode = load_patch_grouping_mode()
    self._patch_group_fold_registries = {
        self._patch_grouping_mode: GroupFoldRegistry(),
    }
    self._patch_group_fold_registry = self._patch_group_fold_registries[
        self._patch_grouping_mode
    ]
    # Active banner focus on the Patches tab (Phase 4 will surface this on
    # navigation; Phase 3 just needs a stable attribute to clear on
    # mode cycle and pass through to ``PatchList.update_list``).
    self._current_patch_group_key = None

    # Nonblocking grouping-mode persistence state.  The cycle action
    # maintains a latest-value write per target so repeated keypresses
    # cannot leave an older mode on disk after a slower write finishes.
    self._grouping_mode_save_pending = {}
    self._grouping_mode_save_inflight = set()
    self._grouping_mode_save_active = {}

    # Tribe-driven side-panel collection. Initialized empty (@default
    # main pane only); rebuilt by ``_load_agents`` whenever the
    # agent set changes.
    from ..models.agent_panels import AgentPanelGroup, PanelKey

    self._agent_panels_grouped = False
    self._panel_group = AgentPanelGroup()
    # Whole-panel collapse state is session-scoped in-memory state whose
    # lifetime is each panel's. Group/workflow fold registries are still
    # persisted by a one-shot post-first-paint load, pre-load mutation
    # journal, and latest-generation off-thread writer.
    self._collapsed_panel_keys = set()
    self._expanded_panel_keys = set()
    # ``H`` remembers one pre-isolation split-panel layout in memory. The
    # record is intentionally session-local and never enters fold-state
    # persistence.
    self._panel_isolation_revert = None
    # ``-`` remembers at most one sweep record per panel, so a second
    # press can reverse exactly what the first one closed.
    self._panel_fold_sweep_records = {}
    # Expanded panels use an explicit whole-panel focus bit; collapsed
    # panels imply whole-panel focus from their persisted fold state.
    self._expanded_panel_focus = False
    # Last selectable row or collapsed banner per panel, restored by ``l``
    # and Escape when descending from whole-panel focus.
    self._panel_selection_memory = {}
    # Tribe-scoped single-key fold mode (app-level ``L``). Its maps cover
    # group banners and structural/workflow row owners in the focused
    # panel, separately from file hints and apostrophe jump hints.
    self._panel_fold_hint_mode_active = False
    self._panel_fold_hint_intent = "toggle"
    self._panel_fold_hint_snapshot = ()
    self._panel_fold_hint_to_target = {}
    self._panel_fold_target_to_hint = {}
    self._panel_fold_hint_pending_prefix = ""
    self._agents_fold_state_load_started = False
    self._agents_fold_state_load_resolved = False
    self._agents_fold_state_loaded_snapshot = None
    self._agents_fold_state_merged = False
    self._agents_fold_state_intents = []
    self._agents_fold_state_save_requested = False
    self._agents_fold_state_save_generation = 0
    self._agents_fold_state_completed_generation = 0
    self._agents_fold_state_save_pending = None
    self._agents_fold_state_save_task = None
    self._agents_fold_state_load_worker = None
    self._agents_fold_restore_needs_focus_snap = False

    # j/k navigation caches (Phase 2 of jk_navigation_reliability):
    # ``_panel_navigation_stops`` and ``panel_key_per_agent`` are
    # called several times per keystroke; memoize them so a 20-key
    # autorepeat burst rebuilds the agent tree at most once.  Cache
    # keys include the agents-list ref, ``_panel_group`` ref +
    # focused index, the fold registry's monotonic ``version``, and
    # the active grouping mode — every invalidator already mutates
    # one of those, so no explicit bumps are needed at writers.
    self._nav_stops_cache = None
    self._unread_jump_candidates_cache = None
    self._panel_keys_cache = None
    self._agent_panel_index_cache = None
    self._agent_neighbor_index_cache = None
    self._dismiss_revive_epoch = 0
    self._agent_info_metrics_cache = None

    # Agent completion tracking for notifications
    from ...dismissed_agents import (
        dismissed_agents_file_signature,
        load_dismissed_agents,
    )

    self._last_unread_ids = set()
    self._delivered_notification_activity_cursors = set()
    self._notification_snapshot_cache = None
    self._notification_snapshot_version = 0
    self._notification_snapshot_refresh_pending = False
    self._notification_snapshot_refresh_followup = False
    self._notification_deadline_timer = None
    self._notification_deadline_epoch = None
    self._notification_poll_scheduled = False
    self._notification_poll_running = False
    self._notification_poll_pending = False
    self._unread_completed_agent_ids = set()
    self._manual_unread_agent_ids = set()
    self._pending_bulk_read_agent_ids = None
    self._agent_display_status_by_identity = {}
    self._dismissed_agents = load_dismissed_agents()
    self._dismissed_agents_disk_signature = dismissed_agents_file_signature()
    self._dismissed_agents_disk_identities = set(self._dismissed_agents)
    self._dismissed_agents_disk_signature_initialized = True
    # The artifact-index dismissed-projection sync is deliberately NOT
    # run here: it is O(archive) on signature drift (and unbounded on
    # a corrupt index), and __init__ runs before Textual ever paints.
    # The post-mount startup worker runs it in a thread instead
    # (StartupMixin._run_dismissed_index_startup_sync).
    self._dismissed_agent_objects = []
    # The recent dismissed-agent group cache is intentionally left empty at
    # startup: the revive modal (`_revive_agent`) re-reads the recent store
    # from disk and merges it into this cache every time it opens, so a cold
    # init would only duplicate that read on the latency-sensitive cold-start
    # path. See sdd/tales/202606/recent_restore_perf_fix.md.
    self._recent_dismissed_agent_groups = []
    self._revived_agent_raw_suffixes = set()
    self._marked_agents = set()
    # Explicit mark order (the order rows were marked with ``m``); kept
    # alongside ``_marked_agents`` because a set cannot preserve the order
    # the bulk kill-and-edit prompt stack must follow.
    self._marked_agent_order = []

    # Agent status override system (for PLAN/PLAN APPROVED/QUESTION statuses)
    self._agent_status_overrides = {}
    self._agent_pre_question_status = {}
    self._dismiss_persistence_inflight = set()
    self._kill_persistence_inflight = set()

    # Plan feedback context (set when user presses 'f' in plan approval modal)
    from .agents._types import PlanFeedbackContext

    self._plan_feedback_context = None

    # Debouncer for j/k navigation detail panel updates (agents tab)
    from ..util.debounce import DetailPanelDebouncer

    self._agent_detail_debouncer = DetailPanelDebouncer(self)
