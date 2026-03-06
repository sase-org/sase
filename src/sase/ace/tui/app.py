"""Main Textual App for the ace TUI."""

import os
import sys
import time
from typing import Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header

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
    EventHandlersMixin,
    HintActionsMixin,
    MarkingMixin,
    NavigationMixin,
    ProposalRebaseMixin,
    RenameMixin,
    StatusActionsMixin,
    SyncMixin,
    WorkspaceActionsMixin,
)
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
)

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
    EventHandlersMixin,
    MarkingMixin,
    NavigationMixin,
    ProposalRebaseMixin,
    RenameMixin,
    StatusActionsMixin,
    SyncMixin,
    WorkspaceActionsMixin,
    BaseActionsMixin,
    HintActionsMixin,
    App[None],
):
    """TUI application for navigating ChangeSpecs."""

    TITLE = "sase ace"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("j", "next_changespec", "Next", show=False),
        Binding("k", "prev_changespec", "Previous", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("s", "change_status", "Status", show=False),
        Binding("r", "run_workflow", "Run", show=False),
        Binding("M", "mail", "Mail", show=False),
        Binding("d", "show_diff", "Diff", show=False),
        Binding("w", "reword", "Reword", show=False),
        Binding("W", "add_tag", "Add Tag", show=False),
        Binding("v", "view_files", "View", show=False),
        Binding("h", "hooks_or_collapse", "Hooks / Collapse", show=False),
        Binding("H", "hooks_or_collapse_all", "Hooks / Collapse All", show=False),
        Binding("z", "start_fold_mode", "Fold", show=False),
        Binding("a", "accept_proposal", "Accept", show=False),
        Binding("b", "rebase", "Rebase", show=False),
        Binding("R", "start_rewind", "Rewind", show=False),
        Binding("T", "open_tmux", "Tmux", show=False),
        Binding("t", "start_tmux_mode", "Tmux Mode", show=False),
        Binding("C", "checkout", "Checkout", show=False),
        Binding("c", "start_checkout_mode", "Checkout Mode", show=False),
        # Note: "!" binding removed - use "a" then "@" to mark ready to mail
        Binding("y", "refresh", "Refresh", show=False),
        Binding("Y", "sync", "Sync", show=False),
        Binding("slash", "edit_query", "Edit Query", show=False),
        Binding("e", "edit_spec", "Edit Spec", show=False),
        Binding("ctrl+d", "scroll_detail_down", "Scroll Down", show=False),
        Binding("ctrl+u", "scroll_detail_up", "Scroll Up", show=False),
        Binding("ctrl+f", "scroll_prompt_down", "Scroll Prompt Down", show=False),
        Binding("ctrl+b", "scroll_prompt_up", "Scroll Prompt Up", show=False),
        # Saved query keybindings (1-9, 0)
        Binding("1", "load_saved_query_1", "Load Q1", show=False),
        Binding("2", "load_saved_query_2", "Load Q2", show=False),
        Binding("3", "load_saved_query_3", "Load Q3", show=False),
        Binding("4", "load_saved_query_4", "Load Q4", show=False),
        Binding("5", "load_saved_query_5", "Load Q5", show=False),
        Binding("6", "load_saved_query_6", "Load Q6", show=False),
        Binding("7", "load_saved_query_7", "Load Q7", show=False),
        Binding("8", "load_saved_query_8", "Load Q8", show=False),
        Binding("9", "load_saved_query_9", "Load Q9", show=False),
        Binding("0", "load_saved_query_0", "Load Q0", show=False),
        # Tab switching
        Binding("tab", "next_tab", "Next Tab", show=False, priority=True),
        Binding("shift+tab", "prev_tab", "Prev Tab", show=False, priority=True),
        # Axe control (AXE tab only - global access via !x)
        Binding("X", "toggle_axe", "Start/Stop Axe", show=False),
        Binding("Q", "stop_axe_and_quit", "Stop & Quit", show=False),
        # Agent workflow (all tabs) - shows project/CL selection modals
        Binding("at", "start_custom_agent", "Run Agent", show=False),
        # Run agent from ChangeSpec (CLs tab only)
        Binding("space", "start_agent_from_changespec", "Run Agent (CL)", show=False),
        # Bang mode prefix (all tabs) - !x = toggle axe, !! = run bgcmd
        Binding("exclamation_mark", "start_bang_mode", "Bang Mode", show=False),
        # Marking (CLs tab only)
        Binding("m", "toggle_mark", "Mark", show=False),
        Binding("n", "rename_cl", "Rename", show=False),
        Binding("u", "clear_marks", "Unmark All", show=False),
        Binding("S", "bulk_change_status", "Bulk Status", show=False),
        Binding("N", "show_notifications", "Notifications", show=False),
        Binding("x", "kill_agent", "Kill", show=False),
        Binding("l", "expand_or_layout", "Expand / Layout", show=False),
        Binding("L", "expand_all_folds", "Expand All", show=False),
        Binding("p", "toggle_layout", "Layout", show=False),
        Binding("i", "toggle_thinking", "Thinking", show=False),
        Binding("I", "mark_inactive", "Mark Inactive", show=False),
        # Copy to clipboard (changespecs tab - % followed by key)
        Binding("percent_sign", "copy_tab_content", "Copy", show=False),
        # Scroll to top/bottom (Axe tab)
        Binding("g", "scroll_to_top", "Top", show=False),
        Binding("G", "scroll_to_bottom", "Bottom", show=False),
        # Help
        Binding("question_mark", "show_help", "Help", show=False),
        # XPrompt browser
        Binding("number_sign", "browse_xprompts", "XPrompts", show=False),
        # Query history navigation
        Binding("circumflex_accent", "prev_query", "Prev Query", show=False),
        Binding("underscore", "next_query", "Next Query", show=False),
        # ChangeSpec history navigation (vim-style jumplist)
        Binding("ctrl+o", "prev_changespec_history", "Prev CL History", show=False),
        Binding("ctrl+k", "next_changespec_history", "Next CL History", show=False),
        # Ancestor/child/sibling navigation
        Binding("<", "start_ancestor_mode", "Ancestor", show=False),
        Binding(">", "start_child_mode", "Child", show=False),
        Binding("~", "start_sibling_mode", "Sibling", show=False),
        # Hide/show reverted
        Binding("full_stop", "toggle_hide_reverted", "Toggle Reverted", show=False),
        # Leader mode (for quick shortcuts)
        Binding("comma", "start_leader_mode", "Leader", show=False),
        # File cycling (agents tab)
        Binding("ctrl+n", "next_agent_file", "Next File", show=False),
        Binding("ctrl+p", "prev_agent_file", "Prev File", show=False),
        Binding("E", "edit_panel", "Edit Panel", show=False),
        Binding("plus", "expand_file_trim", "Expand", show=False),
        Binding("minus", "collapse_file_trim", "Collapse", show=False),
        Binding("equals_sign", "reset_file_trim", "Reset Trim", show=False),
        Binding("asterisk", "show_all_file_lines", "Show All", show=False),
        # Jump to CL from agent (agents tab)
        Binding("enter", "jump_to_agent_changespec", "Go to CL", show=False),
    ]

    # Reactive properties
    changespecs: reactive[list[ChangeSpec]] = reactive([], recompose=False)
    current_idx: reactive[int] = reactive(0, recompose=False)
    hooks_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    commits_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    mentors_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    current_tab: reactive[TabName] = reactive("changespecs", recompose=False)
    axe_running: reactive[bool] = reactive(False, recompose=False)
    hide_reverted: reactive[bool] = reactive(True, recompose=False)
    hide_non_run_agents: reactive[bool] = reactive(True, recompose=False)
    marked_indices: reactive[set[int]] = reactive(set, recompose=False)

    def __init__(
        self,
        query: str = "!!!",
        model_tier_override: Literal["large", "small"] | None = None,
        refresh_interval: int = 10,
        auto_start_axe: bool = True,
    ) -> None:
        """Initialize the ace TUI app.

        Args:
            query: Query string for filtering ChangeSpecs
            model_tier_override: Override model tier for all LLM provider instances
            refresh_interval: Auto-refresh interval in seconds (0 to disable)
            auto_start_axe: Whether to auto-start the axe daemon on startup
        """
        super().__init__()
        self.theme = "flexoki"
        self._auto_start_axe = auto_start_axe
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

        # Checkout/tmux mode state (for c/t key sub-commands)
        self._checkout_mode_active: bool = False
        self._tmux_mode_active: bool = False

        # Copy mode state (for % key sub-commands)
        self._copy_mode_active: bool = False

        # Activity tracking state (for inactivity detection)
        self._last_activity_time: float = 0.0
        self._last_activity_flush: float = 0.0

        # Leader mode state (for , key sub-commands)
        self._leader_mode_active: bool = False

        # Bang mode state (for ! key sub-commands)
        self._bang_mode_active: bool = False

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
        self._has_always_visible: bool = False
        self._hidden_count: int = 0
        self._agent_search_query: str = ""

        # Fold state for nested workflow steps
        from .models.fold_state import FoldStateManager

        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}

        # Agent completion tracking for notifications
        from ..dismissed_agents import load_dismissed_agents

        self._last_unread_count: int = 0
        self._dismissed_agents = load_dismissed_agents()
        self._dismissed_agent_objects: list[Agent] = []

        # Agent status override system (for PLANNING/PLAN APPROVED/QUESTION statuses)
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}

        # Debounce timer for j/k navigation detail panel updates
        self._detail_update_timer: Timer | None = None

        # Axe state
        self._axe_status: AxeStatus | None = None
        self._axe_metrics: AxeMetrics | None = None
        self._axe_output: str = ""
        self._axe_pinned_to_bottom: bool = True

        # Background command state
        from .bgcmd import BackgroundCommandInfo

        self._axe_current_view: Literal["axe"] | int = "axe"
        self._bgcmd_slots: list[tuple[int, BackgroundCommandInfo]] = []

        # Lumberjack cycling state (new axe architecture)
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_idx: int | None = None

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

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header()
        with Horizontal(id="top-bar"):
            yield TabBar(id="tab-bar")
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
                    with Vertical(id="agent-detail-container"):
                        yield AgentDetail(id="agent-detail-panel")
            # Axe Tab (hidden by default)
            with Horizontal(id="axe-view", classes="hidden"):
                # Left panel (bgcmd list) - hidden by default, shown when bgcmds exist
                with Vertical(id="bgcmd-list-container", classes="hidden"):
                    yield BgCmdList(id="bgcmd-list-panel")
                # Right panel (dashboard)
                with Vertical(id="axe-container"):
                    yield AxeInfoPanel(id="axe-info-panel")
                    yield AxeDashboard(id="axe-dashboard")
        yield KeybindingFooter(id="keybinding-footer")
        yield Footer()

    def on_mount(self) -> None:
        """Set up the app on mount."""
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

        # Initialize axe status
        self._load_axe_status()

        # Auto-start axe if enabled and not already running
        if self._auto_start_axe and not self.axe_running:
            self._start_axe()

        # Write initial activity timestamp, idle state, and PID file
        self._last_activity_time = time.monotonic()
        self._last_activity_flush = time.monotonic()
        from sase.ace.tui_activity import (
            write_activity_timestamp,
            write_idle_state,
            write_tui_pid,
        )

        write_activity_timestamp(time.time())
        write_idle_state(False)
        write_tui_pid()

        # Set up auto-refresh timer if enabled
        if self.refresh_interval > 0:
            self._countdown_remaining = self.refresh_interval
            self._countdown_timer = self.set_interval(
                1, self._on_countdown_tick, name="countdown"
            )
            self._refresh_timer = self.set_interval(
                self.refresh_interval, self._on_auto_refresh, name="auto-refresh"
            )

    def _initialize_agent_tracking(self) -> None:
        """Initialize notification tracking by seeding unread count.

        This ensures we don't trigger bell/toast for notifications that
        were already unread when the TUI started.
        """
        from sase.notifications import load_notifications

        notifications = load_notifications()
        unread_count = sum(1 for n in notifications if not n.read)
        self._last_unread_count = unread_count

        indicator = self.query_one("#notification-indicator", NotificationIndicator)
        indicator.set_count(unread_count)

    def _save_current_selection(self) -> None:
        """Save the currently selected ChangeSpec name."""
        from ..last_selection import save_last_selection

        if self.changespecs:
            changespec = self.changespecs[self.current_idx]
            save_last_selection(changespec.name)
            self._save_selection_for_current_query()

    def _restore_last_selection(self) -> None:
        """Restore the previously selected ChangeSpec if it exists."""
        from ..last_selection import load_last_selection

        last_name = load_last_selection()
        if last_name is None:
            return
        for idx, cs in enumerate(self.changespecs):
            if cs.name == last_name:
                self.current_idx = idx
                return

    async def action_quit(self) -> None:
        """Quit the application, saving the current selection."""
        self._save_current_selection()
        from sase.ace.tui_activity import (
            remove_idle_state,
            remove_tui_pid,
            write_activity_timestamp,
        )

        write_activity_timestamp(time.time())
        remove_idle_state()
        remove_tui_pid()
        self.exit()

    def action_mark_inactive(self) -> None:
        """Mark user as inactive by writing epoch 0."""
        from sase.ace.tui_activity import write_activity_timestamp, write_idle_state

        write_activity_timestamp(0)
        write_idle_state(True)
        # Clear activity tracking so _on_countdown_tick() doesn't overwrite
        # the inactive marker (epoch 0) with the current time.  The next
        # real key press will re-enable tracking via on_key().
        if hasattr(self, "_last_activity_time"):
            del self._last_activity_time
        indicator = self.query_one("#inactive-indicator", InactiveIndicator)
        indicator.set_idle(True)

    def watch_current_idx(self, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if self.current_tab == "changespecs":
                self._refresh_display()
            elif self.current_tab == "agents":
                self._refresh_agents_display_debounced()

    def watch_current_tab(self, old_tab: TabName, new_tab: TabName) -> None:
        """React to tab changes by showing/hiding views."""
        if old_tab == new_tab:
            return

        # Cancel any pending debounce timer when leaving agents tab
        if old_tab == "agents" and self._detail_update_timer is not None:
            self._detail_update_timer.stop()
            self._detail_update_timer = None

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
            # Load agents on first access or refresh
            self._load_agents()
        else:  # axe
            changespecs_view.add_class("hidden")
            agents_view.add_class("hidden")
            axe_view.remove_class("hidden")
            # Load axe status
            self._load_axe_status()

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
