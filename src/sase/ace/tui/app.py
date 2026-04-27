"""Main Textual App for the ace TUI."""

import logging
import os
import sys
from typing import Literal

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Header

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ..changespec import ChangeSpec
from ..query import to_canonical_string
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
    StartupMixin,
    StatusActionsMixin,
    SyncMixin,
    TaskActionsMixin,
    WorkspaceActionsMixin,
)
from .bindings import DEFAULT_BINDINGS
from .util.perf import JKPerfTimer, is_enabled as _perf_enabled
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
_MIN_AGENT_LIST_WIDTH = 60
_MAX_AGENT_LIST_WIDTH = 80


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
    StartupMixin,
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
    _current_attempt_number: int | None
    _jk_perf: JKPerfTimer | None

    @property
    def current_idx(self) -> int:
        """Current selection index (manual property to avoid reactive refresh)."""
        return self._current_idx

    @current_idx.setter
    def current_idx(self, value: int) -> None:
        old = self._current_idx
        self._current_idx = value
        if old != value:
            # Moving to a different agent clears any selected-attempt view.
            self._current_attempt_number = None
            if self._jk_perf is not None:
                self._jk_perf.mark_model_updated()
            from .util.trace import set_trace_context

            set_trace_context(current_idx=value)
            self.watch_current_idx(old, value)

    @property
    def current_attempt_number(self) -> int | None:
        """Selected attempt number when an attempt child row is active.

        ``None`` means the live/current attempt (the parent agent row).
        """
        return self._current_attempt_number

    @current_attempt_number.setter
    def current_attempt_number(self, value: int | None) -> None:
        old = self._current_attempt_number
        self._current_attempt_number = value
        if old != value and self.current_tab == "agents":
            self._refresh_agents_display_debounced()

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
        self._jk_perf = JKPerfTimer() if _perf_enabled() else None
        self._init_app_state(
            query=query,
            model_tier_override=model_tier_override,
            refresh_interval=refresh_interval,
            auto_start_axe=auto_start_axe,
            restart_axe=restart_axe,
        )

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

    def _jk_perf_begin(self, action: str) -> None:
        """Record a key-to-paint sample start, when SASE_TUI_PERF=1."""
        if self._jk_perf is not None:
            self._jk_perf.begin(action, self.current_tab)

    def watch_current_idx(self, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if self.current_tab == "changespecs":
                self._refresh_changespecs_display_debounced()
            elif self.current_tab == "agents":
                self._refresh_agents_display_debounced()
            elif self.current_tab == "axe":
                self._refresh_axe_display_debounced()
            if self._jk_perf is not None:
                self.call_after_refresh(self._jk_perf.mark_painted)

    def watch_current_tab(self, old_tab: TabName, new_tab: TabName) -> None:
        """React to tab changes by showing/hiding views."""
        if old_tab == new_tab:
            return

        from .util.trace import set_trace_context

        set_trace_context(current_tab=new_tab)

        # Cancel any pending detail-panel debouncer for the tab we're leaving;
        # the new tab will redraw fresh and the deferred work would land in a
        # now-hidden view.
        if old_tab == "agents":
            self._agent_detail_debouncer.cancel()
        elif old_tab == "axe":
            self._axe_detail_debouncer.cancel()
        elif old_tab == "changespecs":
            self._changespec_detail_debouncer.cancel()

        # Tab changes always cancel one-key jump mode.
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        self._entry_jump_hint_to_banner = {}
        self._entry_jump_banner_to_hint = {}

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
            # During mount, on_mount will schedule the initial async load;
            # skip here to avoid a redundant synchronous cold load.
            if self._mounting:
                pass
            elif getattr(self, "_agents_with_children", None):
                # Show cached data immediately, then refresh async
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
