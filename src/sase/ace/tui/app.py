"""Main Textual App for the ace TUI."""

import logging
import os
import sys
import time
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header
from textual.worker import Worker

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sase.axe.state import AxeMetrics, AxeStatus

from ..changespec import ChangeSpec
from ..query import parse_query, to_canonical_string
from ..query.types import QueryExpr
from .models.fold_state import FoldLevel
from .actions import (
    AgentsMixin,
    AgentWorkflowMixin,
    AxeMixin,
    BaseActionsMixin,
    ChangeSpecMixin,
    ClipboardMixin,
    CustomModeMixin,
    EventHandlersMixin,
    HintActionsMixin,
    LifecycleMixin,
    MarkingMixin,
    NavigationMixin,
    ProposalRebaseMixin,
    RenameMixin,
    StatusActionsMixin,
    SyncMixin,
    TaskActionsMixin,
    WorkspaceActionsMixin,
)
from .bindings import DEFAULT_BINDINGS
from .models import Agent
from .models.agent import AgentType
from .widgets import (
    AgentDetail,
    AgentInfoPanel,
    AgentList,
    AncestorsChildrenPanel,
    AxeDashboard,
    AxeInfoPanel,
    BgCmdList,
    ChangeSpecDetail,
    ChangeSpecInfoPanel,
    ChangeSpecList,
    InactiveIndicator,
    KeybindingFooter,
    NotificationIndicator,
    SearchQueryPanel,
    TabBar,
    TaskIndicator,
)

log = logging.getLogger(__name__)

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Width bounds for dynamic list panel sizing (in terminal cells)
# MIN must fit: "ChangeSpec: X/Y   (auto-refresh in Ns)" + padding/border
_MIN_LIST_WIDTH = 43
_MAX_LIST_WIDTH = 80

# Width bounds for agent list panel
_MIN_AGENT_LIST_WIDTH = 40
_MAX_AGENT_LIST_WIDTH = 70


class AceApp(
    AgentWorkflowMixin,
    AgentsMixin,
    AxeMixin,
    ChangeSpecMixin,
    ClipboardMixin,
    CustomModeMixin,
    EventHandlersMixin,
    LifecycleMixin,
    MarkingMixin,
    NavigationMixin,
    ProposalRebaseMixin,
    RenameMixin,
    StatusActionsMixin,
    SyncMixin,
    TaskActionsMixin,
    WorkspaceActionsMixin,
    BaseActionsMixin,
    HintActionsMixin,
    App[None],
):
    """TUI application for navigating ChangeSpecs."""

    TITLE = "sase ace"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = DEFAULT_BINDINGS

    # Reactive properties
    changespecs: reactive[list[ChangeSpec]] = reactive([], recompose=False)
    hooks_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    commits_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    mentors_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    timestamps_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    current_tab: reactive[TabName] = reactive("changespecs", recompose=False)
    axe_running: reactive[bool] = reactive(False, recompose=False)
    hide_reverted: reactive[bool] = reactive(True, recompose=False)
    hide_submitted: reactive[bool] = reactive(True, recompose=False)
    hide_non_run_agents: reactive[bool] = reactive(True, recompose=False)
    marked_indices: reactive[set[int]] = reactive(set, recompose=False)

    _current_idx: int

    @property
    def current_idx(self) -> int:
        """Current selection index (manual property to avoid reactive refresh)."""
        return self._current_idx

    @current_idx.setter
    def current_idx(self, value: int) -> None:
        old = self._current_idx
        self._current_idx = value
        if old != value:
            self.watch_current_idx(old, value)

    def __init__(
        self,
        query: str = "!!!",
        model_tier_override: Literal["large", "small"] | None = None,
        refresh_interval: int = 10,
        auto_start_axe: bool = True,
        restart_axe: bool = False,
    ) -> None:
        """Initialize the ace TUI app.

        Args:
            query: Query string for filtering ChangeSpecs
            model_tier_override: Override model tier for all LLM provider instances
            refresh_interval: Auto-refresh interval in seconds (0 to disable)
            auto_start_axe: Whether to auto-start the axe daemon on startup
            restart_axe: Whether to restart the axe daemon on startup
        """
        super().__init__()
        self._current_idx = 0
        self._init_task_queue()
        self.theme = "flexoki"
        self._auto_start_axe = auto_start_axe
        self._restart_axe = restart_axe
        self.query_string = query
        self.parsed_query: QueryExpr = parse_query(query)
        self.refresh_interval = refresh_interval
        self._refresh_timer: Timer | None = None
        self._countdown_timer: Timer | None = None
        self._countdown_remaining: int = refresh_interval

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
        self._last_activity_time: float = 0.0
        self._last_activity_flush: float = 0.0
        self._pinned_idle: bool = False

        # Activity event log (for Activity Dashboard modal)
        from .activity_log import ActivityLog

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
        self._all_changespecs: list[ChangeSpec] = []  # Cache for ancestry lookup
        self._hidden_reverted_count: int = 0  # Count of filtered reverted CLs

        # Tab state - track position in each tab
        self._changespecs_last_idx: int = 0
        self._agents_last_idx: int = 0
        self._agents: list[Agent] = []
        self._agents_loading: bool = False
        self._has_always_visible: bool = False
        self._hidden_count: int = 0
        self._agent_search_query: str = ""

        # Panel focus state for pinned panel split
        from .actions.agents._core import PanelFocus

        self._pinned_panel_focused: PanelFocus = "main"
        self._main_panel_indices: list[int] = []
        self._pinned_panel_indices: list[int] = []
        self._non_child_main_indices: list[int] = []

        # Fold state for nested workflow steps
        from .models.fold_state import FoldStateManager

        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}

        # Agent completion tracking for notifications
        from ..dismissed_agents import load_dismissed_agents
        from ..pinned_agents import load_pinned_agents

        self._last_unread_count: int = 0
        self._dismissed_agents = load_dismissed_agents()
        self._dismissed_agent_objects: list[Agent] = []
        self._pinned_agents = load_pinned_agents()

        from ..agent_order import load_agent_order

        self._agent_custom_order = load_agent_order()

        # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}

        # Plan feedback context (set when user presses 'f' in plan approval modal)
        from sase.ace.tui.actions.agents._types import PlanFeedbackContext

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
        from .bgcmd import BackgroundCommandInfo

        self._axe_current_view: Literal["axe"] | int = "axe"
        self._bgcmd_slots: list[tuple[int, BackgroundCommandInfo]] = []

        # Lumberjack cycling state (new axe architecture)
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_idx: int | None = None

        # AXE side-panel item list and saved position
        from .widgets.bgcmd_list import AxeItem

        self._axe_items: list[AxeItem] = []
        self._axe_last_idx: int = 0
        self._axe_fold_manager = FoldStateManager()
        self._axe_fold_manager.expand("axe")  # start expanded by default

        # Query history stacks for prev/next navigation
        from ..query_history import load_query_history

        self._query_history = load_query_history()

        # Per-query ChangeSpec selection persistence
        from ..query_selection import load_query_selections

        self._query_selections = load_query_selections()

        # ChangeSpec history stacks for ctrl+o/ctrl+i navigation (session-based)
        from .changespec_history import create_empty_stacks as create_cs_history_stacks

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
        from .keymaps import (
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

    @property
    def canonical_query_string(self) -> str:
        """Get the canonical (normalized) form of the query string.

        Converts the parsed query back to a string with:
        - Explicit AND keywords between atoms
        - Uppercase AND/OR keywords
        - Quoted strings (not @-shorthand)
        """
        return to_canonical_string(self.parsed_query)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable tab switching when a modal screen is active or prompt is focused.

        This allows modals (e.g. revive agent modal) to use priority tab
        bindings without the app-level next_tab/prev_tab consuming the key
        first. It also lets the prompt text area handle Tab for snippet
        expansion.
        """
        if action in ("next_tab", "prev_tab"):
            from textual.screen import ModalScreen

            if isinstance(self.screen, ModalScreen):
                return False
            from .widgets.prompt_text_area import PromptTextArea

            if isinstance(self.focused, PromptTextArea):
                return False
        return super().check_action(action, parameters)

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header()
        with Horizontal(id="top-bar"):
            yield TabBar(id="tab-bar")
            yield TaskIndicator(id="task-indicator")
            yield InactiveIndicator(id="inactive-indicator")
            yield NotificationIndicator(id="notification-indicator")
        with Horizontal(id="main-container"):
            # ChangeSpecs Tab (default visible)
            with Horizontal(id="changespecs-view"):
                with Vertical(id="list-container"):
                    yield ChangeSpecInfoPanel(id="info-panel")
                    yield ChangeSpecList(id="list-panel")
                    yield AncestorsChildrenPanel(id="ancestors-children-panel")
                with Vertical(id="detail-container"):
                    yield SearchQueryPanel(id="search-query-panel")
                    with VerticalScroll(id="detail-scroll"):
                        yield ChangeSpecDetail(id="detail-panel")
            # Agents Tab (hidden by default)
            with Vertical(id="agents-view", classes="hidden"):
                yield AgentInfoPanel(id="agent-info-panel")
                with Horizontal(id="agents-content"):
                    with Vertical(id="agent-list-container"):
                        yield AgentList(id="agent-list-panel")
                        with Vertical(id="pinned-panel-container"):
                            yield AgentList(panel="pinned", id="pinned-list-panel")
                    with Vertical(id="agent-detail-container"):
                        yield AgentDetail(id="agent-detail-panel")
            # Axe Tab (hidden by default)
            with Horizontal(id="axe-view", classes="hidden"):
                # Left panel (bgcmd list) - always visible on AXE tab
                with Vertical(id="bgcmd-list-container"):
                    yield BgCmdList(id="bgcmd-list-panel")
                # Right panel (dashboard)
                with Vertical(id="axe-container"):
                    yield AxeInfoPanel(id="axe-info-panel")
                    yield AxeDashboard(id="axe-dashboard")
        yield KeybindingFooter(id="keybinding-footer")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the app on mount."""
        # Wire keymap registry to widgets
        footer = self.query_one("#keybinding-footer", KeybindingFooter)
        footer.set_keymap_registry(self._keymap_registry)
        tab_bar = self.query_one("#tab-bar", TabBar)
        tab_bar.set_keymap_registry(self._keymap_registry)

        # Initialize agent tracking for completion notifications
        self._initialize_agent_tracking()

        # Load initial changespecs with the startup query
        self._load_changespecs()

        # If no results, try saved queries as fallback; if none work, open
        # the Agents tab instead
        if not self.changespecs:
            if not self._try_startup_fallback():
                self.current_tab = "agents"  # type: ignore[assignment]

        self._restore_last_selection()
        self._save_current_query()

        # Load agents so the tab bar count is populated on startup
        self._load_agents()

        # Initialize axe status
        self._load_axe_status()

        # Restart axe if requested and currently running
        if self._restart_axe and self.axe_running:
            self._restart_axe_daemon()
        # Auto-start axe if enabled and not already running (skip if restart was triggered)
        elif self._auto_start_axe and not self.axe_running:
            self._start_axe()

        # Write initial activity timestamp, idle state, and PID file.
        # If pinned idle was active in the previous session, restore it.
        from sase.ace.tui_activity import (
            read_pinned_idle,
            write_activity_timestamp,
            write_idle_state,
            write_last_keypress,
            write_tui_pid,
        )

        from .activity_log import ActivityEventType

        write_tui_pid()
        self._activity_log.record(ActivityEventType.SESSION_START)
        if read_pinned_idle():
            self._pinned_idle = True
            if hasattr(self, "_last_activity_time"):
                del self._last_activity_time
            write_activity_timestamp(0)
            write_idle_state(True)
            indicator = self.query_one("#inactive-indicator", InactiveIndicator)
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
            self._countdown_timer = self.set_interval(
                1, self._on_countdown_tick, name="countdown"
            )
            self._refresh_timer = self.set_interval(
                self.refresh_interval, self._on_auto_refresh, name="auto-refresh"
            )

    def watch_current_idx(self, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if self.current_tab == "changespecs":
                self._refresh_display()
            elif self.current_tab == "agents":
                self._refresh_agents_display_debounced()
            elif self.current_tab == "axe":
                self._refresh_axe_display()

    def watch_current_tab(self, old_tab: TabName, new_tab: TabName) -> None:
        """React to tab changes by showing/hiding views."""
        if old_tab == new_tab:
            return

        # Cancel any pending debounce timer when leaving agents tab
        if old_tab == "agents" and self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

        # Tab changes always cancel one-key jump mode.
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}

        # Update tab bar indicator
        tab_bar = self.query_one("#tab-bar", TabBar)
        tab_bar.update_tab(new_tab)

        changespecs_view = self.query_one("#changespecs-view")
        agents_view = self.query_one("#agents-view")
        axe_view = self.query_one("#axe-view")

        if new_tab == "changespecs":
            changespecs_view.remove_class("hidden")
            agents_view.add_class("hidden")
            axe_view.add_class("hidden")
            self._refresh_display()
        elif new_tab == "agents":
            changespecs_view.add_class("hidden")
            agents_view.remove_class("hidden")
            axe_view.add_class("hidden")
            # Show cached data immediately if available, then refresh async
            if getattr(self, "_agents_with_children", None):
                self._refilter_agents()
                self._schedule_agents_async_refresh()
            else:
                # First load ever — must block to populate initial state
                self._load_agents()
        else:  # axe
            changespecs_view.add_class("hidden")
            agents_view.add_class("hidden")
            axe_view.remove_class("hidden")
            # Show existing state immediately, then refresh async
            self._refresh_axe_display()
            self._schedule_axe_async_refresh()

        # If help modal is open, refresh it with new tab context
        from .modals import HelpModal

        if isinstance(self.screen, HelpModal):
            self.screen.dismiss(None)
            self.push_screen(
                HelpModal(
                    current_tab=new_tab,
                    active_query=self.canonical_query_string,
                )
            )
