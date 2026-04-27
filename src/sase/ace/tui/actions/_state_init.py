"""State initialization for the ace TUI app's startup mixin.

Houses ``_init_app_state``, split out of ``startup.py`` to keep both
modules under the per-file line budget. Inherited by ``StartupMixin``.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Literal

from textual.timer import Timer
from textual.worker import Worker

from ...query import parse_query
from ..activity_log import ActivityLog
from ..models.fold_state import FoldStateManager
from ..util.fs_watcher import ArtifactWatcher
from ..util.nav_gate import NavigationGate

if TYPE_CHECKING:
    from ...agent_query import QueryExpr as AgentQueryExpr
    from ..models import Agent
    from ..models.agent import AgentType
    from .axe_display._loaders import AxeItemKey
    from .navigation._types import JumpAllResult

log = logging.getLogger(__name__)

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
    ) -> None:
        """Initialize all instance state for ``AceApp``.

        Called from ``AceApp.__init__`` after ``super().__init__()``. All
        one-time state setup lives here (rather than inline) so ``app.py``
        stays focused on the class shell.
        """
        self._current_idx = 0
        self._current_attempt_number: int | None = None
        self._init_task_queue()  # type: ignore[attr-defined]
        self.theme = "flexoki"
        self._auto_start_axe = auto_start_axe
        self._restart_axe = restart_axe
        # Set during on_mount to suppress reactive-watcher cold loads that
        # would otherwise duplicate work the mount body already performs.
        self._mounting = False
        # Startup loading flags: flipped to True once the first async load
        # completes. Used to distinguish "not yet loaded" from "loaded, empty"
        # in the TUI's agents and axe surfaces.
        self._agents_first_load_done = False
        self._axe_first_load_done = False
        self.query_string = query
        self.parsed_query = parse_query(query)
        self.refresh_interval = refresh_interval
        self._refresh_timer: Timer | None = None
        self._countdown_timer: Timer | None = None
        self._countdown_remaining = refresh_interval

        # Phase 5: navigation gate + inotify watcher for event-driven
        # background refresh.  ``_fs_watcher`` is attached during on_mount
        # post-load and cleared on quit.
        self._nav_gate = NavigationGate()
        self._fs_watcher: ArtifactWatcher | None = None

        # Phase 7 event-driven auto-refresh state.  When the inotify
        # watcher is active, ``_on_artifact_change`` flips the dirty
        # flags; the auto-refresh tick only does work for flags that are
        # set (or when the slow sanity floor below has elapsed). Defaults
        # mark "dirty" so the first tick still primes everything when no
        # watcher event has fired yet.
        self._dirty_changespecs: bool = True
        self._dirty_agents: bool = True
        self._dirty_axe: bool = True
        self._last_full_sanity_refresh: float = 0.0

        # Hint mode state
        self._hint_mode_active: bool = False
        self._hint_mode_hints_for: str | None = (
            None  # None/"all" or "hooks_latest_only"
        )
        self._hint_mappings: dict[int, str] = {}
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

        # Activity tracking state (for inactivity detection)
        self._last_activity_time = 0.0
        self._last_activity_flush = 0.0
        self._pinned_idle = False

        self._activity_log = ActivityLog()
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

        # Bang mode state (for ! key sub-commands)
        self._bang_mode_active: bool = False

        # Axe worker state (for background start/stop)
        self._axe_worker: Worker[Any] | None = None

        # Custom mode state (for user-defined prefix-key modes)
        self._custom_mode_active: str | None = None

        # One-key jump mode state (V)
        self._entry_jump_mode_active: bool = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        # Agents-tab banner targets (kept in their own maps so the int-keyed
        # agent maps above can stay shared with CLs / AXE tabs).
        from .navigation.jump_hints import BannerJumpTarget

        self._entry_jump_hint_to_banner: dict[str, BannerJumpTarget] = {}
        self._entry_jump_banner_to_hint: dict[BannerJumpTarget, str] = {}

        # Entry jump-back state (' toggle)
        self._entry_jump_last_index: dict[str, int] = {}
        self._entry_jump_last_panel: dict[str, str | None] = {}
        # Banner-aware agents-tab anchor; ``None`` when the user has not yet
        # used jump mode on the agents tab.
        self._entry_jump_last_agents_anchor: (
            tuple[Literal["agent"], int, int] | BannerJumpTarget | None
        ) = None

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
        self._hidden_reverted_count: int = 0  # Count of filtered reverted CLs

        # Tab state - track position in each tab
        self._changespecs_last_idx: int = 0
        self._changespecs_last_name: str | None = None
        self._agents_last_idx: int = 0
        self._agents_last_identity: tuple[AgentType, str, str | None] | None = None
        self._agents: list[Agent] = []
        self._agents_loading: bool = False
        self._agents_refresh_pending: bool = False
        self._agents_refresh_scheduled: bool = False
        self._post_mount_background_loads_started = False
        self._changespecs_loading: bool = False
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
        from ..models.agent_content_search import AgentContentSearchCache

        self._agent_content_search_cache = AgentContentSearchCache()

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
        from ...grouping_mode_state import load_grouping_mode
        from ..models.agent_group_fold import AgentGroupFoldRegistry
        from ..models.agent_groups import GroupingMode

        self._grouping_mode: GroupingMode = load_grouping_mode()
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

        # Tag-driven side-panel collection.  Initialized empty (untagged
        # main pane only); rebuilt by ``_load_agents`` whenever the
        # agent set changes.
        from ..models.agent_panels import AgentPanelGroup

        self._panel_group: AgentPanelGroup = AgentPanelGroup()

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
        self._agent_panel_index_cache: tuple[Any, Any] | None = None

        # Agent completion tracking for notifications
        from ...dismissed_agents import load_dismissed_agents

        self._last_unread_ids: set[str] = set()
        self._dismissed_agents = load_dismissed_agents()
        self._dismissed_agent_objects: list[Agent] = []
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()

        # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
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

        # Axe state
        from sase.axe.state import (
            AxeMetrics,
            AxeStatus,
            LumberjackMetrics,
            LumberjackStatus,
        )

        self._axe_status: AxeStatus | None = None
        self._axe_metrics: AxeMetrics | None = None
        self._axe_output: str = ""
        self._axe_pinned_to_bottom: bool = True
        self._axe_cmds_hidden: bool = False

        # Background command state
        from ..bgcmd import BackgroundCommandInfo

        self._axe_current_view: Literal["axe"] | int = "axe"
        self._bgcmd_slots: list[tuple[int, BackgroundCommandInfo]] = []

        # Axe navigation caches: populated by the async collector so that
        # Ctrl+N / Ctrl+P render without touching disk. Empty until the
        # first async load completes (first-paint shows empty placeholders).
        from .axe_display import BgCmdSnapshot

        self._axe_lumberjack_statuses: dict[str, LumberjackStatus | None] = {}
        self._axe_lumberjack_metrics: dict[str, LumberjackMetrics | None] = {}
        self._axe_lumberjack_log_tails: dict[str, str] = {}
        self._axe_bgcmd_details: dict[int, BgCmdSnapshot] = {}

        # Debouncer for axe j/k navigation detail updates.
        self._axe_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self._axe_loading_placeholder_shown: bool = False

        # Debouncer for changespecs j/k navigation detail updates.
        self._changespec_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]

        # Lumberjack cycling state (new axe architecture)
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_idx: int | None = None

        # AXE side-panel item list and saved position
        from ..widgets.bgcmd_list import AxeItem

        self._axe_items: list[AxeItem] = []
        self._axe_last_idx: int = 0
        self._axe_last_item_key: AxeItemKey | None = None
        self._axe_fold_manager = FoldStateManager()
        self._axe_fold_manager.expand("axe")  # start expanded by default

        # Query history stacks for prev/next navigation
        from ...query_history import load_query_history

        self._query_history = load_query_history()

        # Per-query ChangeSpec selection persistence
        from ...query_selection import load_query_selections

        self._query_selections = load_query_selections()

        # Saved-query slots cached in memory.  ``SearchQueryPanel`` reads
        # this on every render so we keep it disk-free; the cache is
        # refreshed by :meth:`_invalidate_saved_queries_cache` on explicit
        # save/delete.
        from ...saved_queries import load_saved_queries

        self._saved_queries: dict[str, str] = load_saved_queries()

        # ChangeSpec history stacks for ctrl+o/ctrl+i navigation (session-based)
        from ..changespec_history import create_empty_stacks as create_cs_history_stacks

        self._changespec_history = create_cs_history_stacks()

        # Load inactive_seconds from merged config
        from sase.config import load_merged_config

        merged = load_merged_config()
        ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
        self._inactive_seconds: int = int(
            ace_cfg.get("inactive_seconds", 600) if isinstance(ace_cfg, dict) else 600
        )
        user_snippets: dict[str, str] = (
            ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
        )
        # Defer the xprompt snippet scan (which walks disk-backed xprompt
        # definitions) until the prompt entry / help modal asks for it.
        # Cold startup's first paint never needs snippets, so skipping
        # this on the mount path keeps the stopwatch tight.
        self._user_snippets = dict(user_snippets)
        self._snippets_cache: dict[str, str] | None = None

        # Build keymap registry from config
        from ..keymaps import (
            BUILTIN_MODE_NAMES,
            KeymapRegistry,
            build_app_bindings,
            key_display_name,
            load_keymap_registry,
        )

        self._keymap_registry: KeymapRegistry = load_keymap_registry(
            ace_cfg if isinstance(ace_cfg, dict) else {}
        )

        # Build prefix→mode_name lookup for custom (non-builtin) modes.
        self._custom_mode_prefixes: dict[str, str] = {
            mode.prefix: name
            for name, mode in self._keymap_registry.modes.items()
            if name not in BUILTIN_MODE_NAMES and mode.prefix
        }

        # Replace instance bindings with registry-driven bindings.
        from textual.binding import BindingsMap

        _app_bindings = build_app_bindings(self._keymap_registry.app)
        self._bindings = BindingsMap(_app_bindings)
        log.debug(
            "Keymap registry loaded: %d bindings, display=%s",
            len(_app_bindings),
            key_display_name(self._keymap_registry.app.next_changespec),
        )

        # Set global model tier override in environment if specified
        if model_tier_override:
            os.environ["SASE_MODEL_TIER_OVERRIDE"] = model_tier_override
