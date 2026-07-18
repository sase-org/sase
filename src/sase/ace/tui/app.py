"""Main Textual App for the ace TUI."""

import logging
import os
import sys
from typing import Literal

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Header

from sase.logs import current_toast_session, record_toast

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ..changespec import ChangeSpec
from ..query import to_canonical_string
from ._changespec_list_layout import (
    CL_LIST_MAX_PANEL_WIDTH,
    CL_LIST_MIN_PANEL_WIDTH,
)
from .models.fold_state import FoldLevel
from .actions import (
    AgentsMixin,
    AgentWorkflowMixin,
    ArtifactBugsMixin,
    ArtifactsMixin,
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
    PostUpdateToastMixin,
    ProposalRebaseMixin,
    RenameMixin,
    ReproActionsMixin,
    StartupMixin,
    StatusActionsMixin,
    SyncMixin,
    TaskActionsMixin,
    UpdateToastMixin,
    WorkspaceActionsMixin,
)
from .bindings import DEFAULT_BINDINGS
from .exit_action import AceExitAction
from .util.perf import JKPerfTimer, is_enabled as _perf_enabled
from .widgets import (
    AgentDetail,
    AgentInfoPanel,
    AgentList,
    AliasOverridesIndicator,
    ArtifactsSubTab,
    ArtifactsView,
    AxeDashboard,
    AxeInfoPanel,
    BgCmdList,
    KeybindingFooter,
    LLMOverrideIndicator,
    NotificationIndicator,
    StashedPromptsIndicator,
    TabBar,
    TabQuickStart,
    TaskIndicator,
    UpdatesAvailableIndicator,
)
from .tab_order import ARTIFACTS_TAB, TabName

log = logging.getLogger(__name__)

# Width bounds for dynamic list panel sizing (in terminal cells)
# MIN must fit the PR status line plus padding/border; the refresh countdown
# lives on the info panel's second row.
_MIN_LIST_WIDTH = CL_LIST_MIN_PANEL_WIDTH
_MAX_LIST_WIDTH = CL_LIST_MAX_PANEL_WIDTH

# Width bounds for agent list panel
_MIN_AGENT_LIST_WIDTH = 60
_MAX_AGENT_LIST_WIDTH = 130

# Width bounds for the AXE-tab sidebar (#bgcmd-list-container).
# Min matches the previous default of 35 so the empty / short-label
# sidebar keeps its historical look; max is raised well above the prior
# fixed cap of 50 so long lumberjack / chop / bgcmd labels can grow the
# sidebar to fit (Phase 1 of sdd/epics/202605/axe_tab_visual_redesign.md).
_MIN_BGCMD_LIST_WIDTH = 35
_MAX_BGCMD_LIST_WIDTH = 80
# Cells reserved for the right-hand AXE dashboard so a wide sidebar can't
# starve it on narrow terminals.
_BGCMD_LIST_RESERVED_FOR_DASHBOARD = 40


class AceApp(
    AgentWorkflowMixin,
    AgentsMixin,
    AxeMixin,
    ArtifactBugsMixin,
    ArtifactsMixin,
    ChangeSpecMixin,
    ClipboardMixin,
    CustomModeMixin,
    EventHandlersMixin,
    LifecycleMixin,
    MarkingMixin,
    NavigationMixin,
    PostUpdateToastMixin,
    ProposalRebaseMixin,
    RenameMixin,
    ReproActionsMixin,
    StartupMixin,
    StatusActionsMixin,
    SyncMixin,
    TaskActionsMixin,
    UpdateToastMixin,
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
    deltas_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    panel_fold_level: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    current_tab: reactive[TabName] = reactive("changespecs", recompose=False)
    current_artifacts_subtab: reactive[ArtifactsSubTab] = reactive(
        "prs", recompose=False
    )
    axe_running: reactive[bool] = reactive(False, recompose=False)
    hide_reverted: reactive[bool] = reactive(True, recompose=False)
    hide_submitted: reactive[bool] = reactive(True, recompose=False)
    hide_non_run_agents: reactive[bool] = reactive(True, recompose=False)
    marked_indices: reactive[set[int]] = reactive(set, recompose=False)

    exit_action: AceExitAction
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
            cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
            if callable(cancel_member_jump):
                cancel_member_jump(refresh_footer=False)
            # Moving to a different agent clears any selected-attempt view.
            self._current_attempt_number = None
            if self._jk_perf is not None:
                self._jk_perf.mark_model_updated()
            from .util.trace import set_trace_context, trace_event

            set_trace_context(current_idx=value)
            trace_event(
                "selection.current_idx.set",
                old=old,
                new=value,
            )
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
        initial_tab: TabName = "agents",
    ) -> None:
        """Initialize the ace TUI app.

        Args:
            query: Query string for filtering ChangeSpecs
            model_tier_override: Override model tier for all LLM provider instances
            refresh_interval: Auto-refresh interval in seconds (0 to disable)
            auto_start_axe: Whether to auto-start the axe daemon on startup
            restart_axe: Whether to restart the axe daemon on startup
            initial_tab: Tab to focus on startup ("changespecs", "agents", or "axe")
        """
        super().__init__()
        from .util.app_version import format_app_title, initial_app_version

        self.title = format_app_title(initial_app_version())
        current_toast_session()
        self._jk_perf = JKPerfTimer() if _perf_enabled() else None
        self._init_app_state(
            query=query,
            model_tier_override=model_tier_override,
            refresh_interval=refresh_interval,
            auto_start_axe=auto_start_axe,
            restart_axe=restart_axe,
            initial_tab=initial_tab,
        )

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: Literal["information", "warning", "error"] = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        """Show a Textual toast and persist it to the TUI toast history."""
        super().notify(
            message,
            title=title,
            severity=severity,
            timeout=timeout,
            markup=markup,
        )
        record_toast(message=message, title=title, severity=severity)

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
        if action in (
            "next_tab",
            "prev_tab",
            "clear_marks",
            "activate_bug_link",
        ):
            from textual.screen import ModalScreen

            if isinstance(self.screen, ModalScreen):
                return False
        if action in ("next_tab", "prev_tab"):
            from .widgets.vim_text_area import VimTextArea

            if isinstance(self.focused, VimTextArea):
                return False
        from .actions.artifact_bugs import BUG_ARTIFACT_ACTIONS
        from .actions.artifacts import (
            COMMITS_ARTIFACT_ACTIONS,
            NON_PRS_ARTIFACT_ACTIONS,
            PLANS_ARTIFACT_ACTIONS,
        )

        if (
            self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_subtab != "prs"
            and action not in NON_PRS_ARTIFACT_ACTIONS
            and not (
                self.current_artifacts_subtab in {"commits", "plans"}
                and action == "edit_query"
            )
        ):
            return False
        if action in BUG_ARTIFACT_ACTIONS:
            return (
                self.current_tab == ARTIFACTS_TAB
                and self.current_artifacts_subtab == "bugs"
            )
        if action in COMMITS_ARTIFACT_ACTIONS:
            return (
                self.current_tab == ARTIFACTS_TAB
                and self.current_artifacts_subtab == "commits"
            )
        if (
            action == "refresh"
            and self.current_tab == ARTIFACTS_TAB
            and self.current_artifacts_subtab in {"bugs", "commits"}
        ):
            # ``y`` copies the selected Bugs/Commits artifact; explicit pane
            # refresh is registry-backed and defaults to ``R``.
            return False
        if action in {
            "cycle_artifacts_subtab",
            "cycle_artifacts_subtab_reverse",
        }:
            if self.current_tab != ARTIFACTS_TAB:
                return False
        if action in {
            "show_artifacts_prs",
            "show_artifacts_commits",
            "show_artifacts_bugs",
            "show_artifacts_plans",
        }:
            if self.current_tab != ARTIFACTS_TAB:
                return False
        if action == "open_saved_query_picker":
            if (
                self.current_tab != ARTIFACTS_TAB
                or self.current_artifacts_subtab != "prs"
            ):
                return False
        if action in PLANS_ARTIFACT_ACTIONS:
            if (
                self.current_tab != ARTIFACTS_TAB
                or self.current_artifacts_subtab != "plans"
            ):
                return False
        if action == "pick_artifacts_project":
            if (
                self.current_tab != ARTIFACTS_TAB
                or self.current_artifacts_subtab == "prs"
            ):
                return False
        if action in {"toggle_thinking", "toggle_thinking_reverse", "toggle_layout"}:
            if self.current_tab != "agents":
                return False
        if action in {
            "next_agent_metadata_section",
            "prev_agent_metadata_section",
        }:
            if self.current_tab != "agents":
                return False
        if action == "jump_to_entry_forward" and self.current_tab == "agents":
            return False
        if action in {"change_status", "bulk_change_status"}:
            if self.current_tab != ARTIFACTS_TAB:
                return False
        if action == "save_marked_agents":
            if self.current_tab != "agents":
                return False
        if action == "zoom_panel" and self.current_tab != "agents":
            return False
        return super().check_action(action, parameters)

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        # Apply the requested initial tab as visible; others start hidden.
        initial_tab = self.current_tab
        cs_classes = "" if initial_tab == "changespecs" else "hidden"
        agents_classes = "" if initial_tab == "agents" else "hidden"
        axe_classes = "" if initial_tab == "axe" else "hidden"
        yield Header()
        with Horizontal(id="top-bar"):
            yield TabBar(id="tab-bar")
            yield TaskIndicator(id="task-indicator")
            yield UpdatesAvailableIndicator(id="updates-indicator")
            yield LLMOverrideIndicator(id="llm-override-indicator")
            yield AliasOverridesIndicator(id="alias-overrides-indicator")
            yield StashedPromptsIndicator(id="stashed-prompts-indicator")
            yield NotificationIndicator(id="notification-indicator")
        with Horizontal(id="main-container"):
            yield ArtifactsView(id="changespecs-view", classes=cs_classes)
            with Vertical(id="agents-view", classes=agents_classes):
                yield AgentInfoPanel(id="agent-info-panel")
                with Horizontal(id="agents-content"):
                    with Vertical(id="agent-list-container"):
                        yield AgentList(id="agent-list-panel")
                    with Vertical(id="agent-detail-container"):
                        yield AgentDetail(id="agent-detail-panel")
                        yield TabQuickStart(
                            tab="agents",
                            id="agent-quickstart-panel",
                            classes="hidden",
                        )
            with Horizontal(id="axe-view", classes=axe_classes):
                with Vertical(id="bgcmd-list-container"):
                    yield BgCmdList(id="bgcmd-list-panel")
                with Vertical(id="axe-container"):
                    yield AxeInfoPanel(id="axe-info-panel")
                    yield AxeDashboard(id="axe-dashboard")
        yield KeybindingFooter(id="keybinding-footer")

    def _jk_perf_begin(self, action: str) -> None:
        """Record a key-to-paint sample start, when SASE_TUI_PERF=1."""
        if self._jk_perf is not None:
            self._jk_perf.begin(action, self.current_tab)

    def watch_current_idx(self, old_idx: int, new_idx: int) -> None:
        """React to current_idx changes."""
        if old_idx != new_idx:
            if (
                self.current_tab == ARTIFACTS_TAB
                and self.current_artifacts_subtab == "prs"
            ):
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

        cancel_member_jump = getattr(self, "_cancel_member_jump_pending", None)
        if callable(cancel_member_jump):
            cancel_member_jump(refresh_footer=False)

        from .util.trace import set_trace_context

        set_trace_context(current_tab=new_tab)

        # Cancel any pending detail-panel debouncer for the tab we're leaving;
        # the new tab will redraw fresh and the deferred work would land in a
        # now-hidden view.
        if old_tab == "agents":
            self._agent_detail_debouncer.cancel()
        elif old_tab == "axe":
            self._axe_detail_debouncer.cancel()
        elif old_tab == ARTIFACTS_TAB and self.current_artifacts_subtab == "prs":
            self._changespec_detail_debouncer.cancel()

        if old_tab == "agents" and getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode(refresh_titles=False)

        # Tab changes always cancel one-key jump mode.
        self._cancel_non_pr_artifacts_jump_mode()
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index = {}
        self._entry_jump_index_to_hint = {}
        self._entry_jump_hint_to_banner = {}
        self._entry_jump_banner_to_hint = {}
        self._entry_jump_hint_to_panel = {}
        self._entry_jump_panel_to_hint = {}
        self._entry_jump_hint_to_changespec_banner = {}
        self._entry_jump_changespec_banner_to_hint = {}

        # Update tab bar indicator
        tab_bar = self.query_one("#tab-bar", TabBar)
        tab_bar.update_tab(new_tab)

        changespecs_view = self.query_one("#changespecs-view", ArtifactsView)
        agents_view = self.query_one("#agents-view")
        axe_view = self.query_one("#axe-view")

        if old_tab == ARTIFACTS_TAB:
            changespecs_view.deactivate_current()

        if new_tab == ARTIFACTS_TAB:
            changespecs_view.remove_class("hidden")
            agents_view.add_class("hidden")
            axe_view.add_class("hidden")
            changespecs_view.activate_current()
            if self.current_artifacts_subtab == "prs":
                self._refresh_display()
            else:
                self._ensure_artifacts_project_choices()
                self.query_one(
                    "#keybinding-footer", KeybindingFooter
                ).show_artifacts_pane()
        elif new_tab == "agents":
            changespecs_view.add_class("hidden")
            agents_view.remove_class("hidden")
            axe_view.add_class("hidden")
            self._sync_artifact_file_viewer_layout()
            # During mount, on_mount will schedule the initial async load;
            # skip here to avoid a redundant synchronous cold load.
            if self._mounting:
                pass
            else:
                # Show cached data (if any) immediately, then refresh async.
                # When the cache is empty, ``_refilter_agents`` falls through
                # to scheduling an async refresh, so the cold-load arm picks
                # up the same loading-row paint as ``on_mount``.
                self._refilter_agents()
                # Only re-fetch on tab switch when there's pending work to
                # consume — the auto-refresh path tab-gates the loader, so
                # switching to a clean agents view should not pay the load
                # cost. Guard against early-startup tab-watch ticks.
                if getattr(self, "_dirty_agents", False) and not getattr(
                    self, "_agents_loading", False
                ):
                    if hasattr(self, "_schedule_agents_async_refresh"):
                        self._schedule_agents_async_refresh(source="tab_switch")
        else:  # axe
            changespecs_view.add_class("hidden")
            agents_view.add_class("hidden")
            axe_view.remove_class("hidden")
            # Show existing state immediately, then refresh async
            self._refresh_axe_display()
            self._schedule_axe_async_refresh()

        # If one of the tab-scoped popup panels is open, refresh it in place
        # with the new tab context.
        from .modals import HelpModal

        screen = self.screen
        if isinstance(screen, HelpModal):
            if new_tab == "agents":
                self._prepare_agents_help_guide_state()
            screen.refresh_for_tab(
                new_tab,
                self.canonical_query_string,
                registry=self._keymap_registry,
                saved_queries=dict(self._saved_queries),
                agents_launch_targets_available=(
                    self._agents_onboarding_launch_targets_available
                ),
                agents_plugins_installed=self._agents_onboarding_plugins_installed,
            )

    def watch_current_artifacts_subtab(
        self,
        old_subtab: ArtifactsSubTab,
        new_subtab: ArtifactsSubTab,
    ) -> None:
        """Switch Artifacts panes and preserve PR detail/refresh isolation."""
        if old_subtab == new_subtab:
            return
        if self._entry_jump_mode_active:
            self._exit_entry_jump_mode()
        else:
            self._cancel_non_pr_artifacts_jump_mode()
        try:
            view = self.query_one("#changespecs-view", ArtifactsView)
        except Exception:
            return
        if old_subtab == "prs":
            self._changespec_detail_debouncer.cancel()
        view.switch_to(new_subtab)
        if self.current_tab != ARTIFACTS_TAB:
            return
        if new_subtab == "prs":
            self._refresh_display()
        else:
            self._ensure_artifacts_project_choices()
            self.query_one("#keybinding-footer", KeybindingFooter).show_artifacts_pane()
