"""Startup/mount mixin for the ace TUI app.

Houses ``__init__`` state initialization plus the ``on_mount`` handler and
its post-mount helpers. Split out of ``app.py`` to keep the main module
focused on the class shell (reactive declarations, compose, watchers).
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any, Literal, cast

from textual.timer import Timer
from textual.worker import Worker

from sase.axe.state import AxeMetrics, AxeStatus, LumberjackMetrics, LumberjackStatus

from ...query import parse_query
from ...query.types import QueryExpr
from ..activity_log import ActivityLog
from ..models.fold_state import FoldStateManager

if TYPE_CHECKING:
    from ..models import Agent
    from ..models.agent import AgentType
    from .navigation._types import JumpAllResult

log = logging.getLogger(__name__)

TabName = Literal["changespecs", "agents", "axe"]


class StartupMixin:
    """Mixin providing app state initialization and mount-time setup."""

    # Attributes set by ``_init_app_state`` and referenced from other mixins.
    query_string: str
    parsed_query: QueryExpr
    refresh_interval: int
    theme: str
    _current_idx: int
    _current_attempt_number: int | None
    _auto_start_axe: bool
    _restart_axe: bool
    _mounting: bool
    _agents_first_load_done: bool
    _axe_first_load_done: bool
    _refresh_timer: Timer | None
    _countdown_timer: Timer | None
    _countdown_remaining: int
    _activity_log: ActivityLog
    _last_activity_time: float
    _last_activity_flush: float
    _pinned_idle: bool
    _post_mount_background_loads_started: bool
    _jump_all_last_position: JumpAllResult | None

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
        self._current_attempt_number = None
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
        self._refresh_timer = None
        self._countdown_timer = None
        self._countdown_remaining = refresh_interval

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

        # Entry jump-back state (' toggle)
        self._entry_jump_last_index: dict[str, int] = {}
        self._entry_jump_last_panel: dict[str, str | None] = {}

        # Cross-tab jump back state (`)
        self._jump_all_last_position = None

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
        self._agents_last_idx: int = 0
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
        # state so cycling modes (g) doesn't lose collapse intent on the
        # mode the user came from.  ``_group_fold_registry`` always
        # points at the active mode's slot; the cycle action swaps it
        # in via :meth:`_ensure_mode_registry` so existing call sites
        # (loading, folding, display) keep reading a single attribute.
        from ..models.agent_group_fold import AgentGroupFoldRegistry
        from ..models.agent_groups import GroupingMode

        self._grouping_mode: GroupingMode = GroupingMode.STANDARD
        self._group_fold_registries: dict[GroupingMode, AgentGroupFoldRegistry] = {
            GroupingMode.STANDARD: AgentGroupFoldRegistry(),
        }
        self._group_fold_registry: AgentGroupFoldRegistry = self._group_fold_registries[
            GroupingMode.STANDARD
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

        # Debounce timer for j/k navigation detail panel updates
        self._detail_update_timer: Timer | None = None

        # Axe state
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

        # Debounce timer for axe j/k navigation detail updates.
        self._axe_detail_update_timer: Timer | None = None
        self._axe_loading_placeholder_shown: bool = False

        # Lumberjack cycling state (new axe architecture)
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_idx: int | None = None

        # AXE side-panel item list and saved position
        from ..widgets.bgcmd_list import AxeItem

        self._axe_items: list[AxeItem] = []
        self._axe_last_idx: int = 0
        self._axe_fold_manager = FoldStateManager()
        self._axe_fold_manager.expand("axe")  # start expanded by default

        # Query history stacks for prev/next navigation
        from ...query_history import load_query_history

        self._query_history = load_query_history()

        # Per-query ChangeSpec selection persistence
        from ...query_selection import load_query_selections

        self._query_selections = load_query_selections()

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
        # Merge xprompt-derived snippets (user-defined snippets take precedence)
        from sase.xprompt.snippet_bridge import get_xprompt_snippets

        xp_snippets = get_xprompt_snippets()
        xp_snippets.update(user_snippets)
        self._snippets: dict[str, str] = xp_snippets

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

    async def on_mount(self) -> None:
        """Set up the app on mount.

        Async so each disk read can ``await asyncio.to_thread(...)``
        between applying to widgets — the event loop stays free between
        helpers so the ``KeybindingFooter`` startup stopwatch can tick at
        ~10Hz through the multi-second startup gap.
        """
        import asyncio

        from ..widgets import (
            InactiveIndicator,
            KeybindingFooter,
            TabBar,
        )

        self._mounting = True
        try:
            # Wire keymap registry to widgets
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.set_keymap_registry(self._keymap_registry)
            tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
            tab_bar.set_keymap_registry(self._keymap_registry)

            # Initialize agent tracking for completion notifications
            unread_ids = await asyncio.to_thread(self._read_unread_notification_ids)  # type: ignore[attr-defined]
            self._initialize_agent_tracking(unread_ids)  # type: ignore[attr-defined]

            # Load initial changespecs with the startup query
            all_cs = await asyncio.to_thread(self._read_changespecs_from_disk)  # type: ignore[attr-defined]
            self._apply_changespecs(all_cs)  # type: ignore[attr-defined]

            # If no results, try saved queries as fallback; if none work, open
            # the Agents tab instead
            if not self.changespecs:  # type: ignore[attr-defined]
                if not await self._try_startup_fallback_async():  # type: ignore[attr-defined]
                    self.current_tab = "agents"  # type: ignore[assignment,attr-defined]

            last_name = await asyncio.to_thread(self._read_last_selection_name)  # type: ignore[attr-defined]
            self._restore_last_selection(last_name)  # type: ignore[attr-defined]
            await asyncio.to_thread(self._save_current_query)  # type: ignore[attr-defined]

            # Show loading indicators on panels that populate asynchronously
            # so users see pulsing spinners / dim ellipses instead of
            # "loaded, empty" state during the ~3.5s gap before first data.
            self._apply_startup_loading_state()

            # Defer startup background loads until after first paint.
            # The launcher schedules agents and axe tasks independently so
            # the AXE startup path is never blocked by a slow agent load.
            self.call_after_refresh(self._start_post_mount_background_loads)  # type: ignore[attr-defined]

            # Write initial activity timestamp, idle state, and PID file.
            # If pinned idle was active in the previous session, restore it.
            from sase.ace.tui_activity import (
                read_pinned_idle,
                write_activity_timestamp,
                write_idle_state,
                write_last_keypress,
                write_tui_pid,
            )

            from ..activity_log import ActivityEventType

            write_tui_pid()
            self._activity_log.record(ActivityEventType.SESSION_START)
            if read_pinned_idle():
                self._pinned_idle = True
                if hasattr(self, "_last_activity_time"):
                    del self._last_activity_time
                write_activity_timestamp(0)
                write_idle_state(True)
                indicator = self.query_one("#inactive-indicator", InactiveIndicator)  # type: ignore[attr-defined]
                indicator.set_idle(True, pinned=True)
                self._activity_log.record(ActivityEventType.IDLE_RESTORED)
            else:
                self._last_activity_time = time.monotonic()
                self._last_activity_flush = time.monotonic()
                now = time.time()
                write_activity_timestamp(now)
                write_last_keypress(now)
                write_idle_state(False)

            # Set up auto-refresh timer if enabled
            if self.refresh_interval > 0:
                self._countdown_remaining = self.refresh_interval
                countdown_tick = self._on_countdown_tick  # type: ignore[attr-defined]
                auto_refresh = self._on_auto_refresh  # type: ignore[attr-defined]
                self._countdown_timer = self.set_interval(  # type: ignore[attr-defined]
                    1, countdown_tick, name="countdown"
                )
                self._refresh_timer = self.set_interval(  # type: ignore[attr-defined]
                    self.refresh_interval, auto_refresh, name="auto-refresh"
                )
        finally:
            self._mounting = False

    def _start_post_mount_background_loads(self) -> None:
        """Launch post-mount startup loads once, without serial dependency."""
        if self._post_mount_background_loads_started:
            return
        self._post_mount_background_loads_started = True
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_agents_async_refresh),  # type: ignore[attr-defined]
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup agent refresh")
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_axe_startup_init),  # type: ignore[attr-defined]
                thread=False,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.exception("Failed to schedule startup axe init")

    def _maybe_end_startup_stopwatch(self) -> None:
        """End startup stopwatch once both async startup surfaces are loaded."""
        if not (self._agents_first_load_done and self._axe_first_load_done):
            return
        try:
            from ..widgets import KeybindingFooter

            self.query_one(  # type: ignore[attr-defined]
                "#keybinding-footer", KeybindingFooter
            ).end_startup_stopwatch()
        except Exception:
            pass

    def _apply_startup_loading_state(self) -> None:
        """Mark async-loaded panels as loading so the user sees spinners.

        Flips ``.loading`` on the two AgentList widgets and the AxeDashboard
        (driving Textual's built-in LoadingIndicator), and switches the
        Agents tab label plus info panels into their dim-ellipsis state.
        The flags are cleared once the first async load completes.
        """
        from ..widgets import (
            AgentInfoPanel,
            AgentList,
            AxeDashboard,
            AxeInfoPanel,
            TabBar,
        )

        if not self._agents_first_load_done:
            try:
                self.query_one("#agent-list-panel", AgentList).loading = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                tab_bar = self.query_one("#tab-bar", TabBar)  # type: ignore[attr-defined]
                tab_bar.update_agents_count(0, 0, show_hidden=False, loading=True)
            except Exception:
                pass
            try:
                self.query_one("#agent-info-panel", AgentInfoPanel).set_loading(True)  # type: ignore[attr-defined]
            except Exception:
                pass

        if not self._axe_first_load_done:
            try:
                self.query_one("#axe-dashboard", AxeDashboard).loading = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.query_one("#axe-info-panel", AxeInfoPanel).set_loading(True)  # type: ignore[attr-defined]
            except Exception:
                pass
