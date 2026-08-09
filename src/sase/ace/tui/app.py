"""Main Textual App for the ace TUI."""

import logging
import os
import sys
from typing import TYPE_CHECKING, Literal

from textual.app import App
from textual.reactive import reactive

from sase.ace.tui.util.session_registration import register_ace_session
from sase.logs import current_toast_session, record_toast

if TYPE_CHECKING:
    from sase.vcs_log.filter_query import CommitLogFilterValues

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ..patch import Patch
from ..query import to_canonical_string
from .actions import (
    AgentsMixin,
    AgentsSyncActionsMixin,
    AgentWorkflowMixin,
    ArtifactBugsMixin,
    ArtifactsMixin,
    AxeMixin,
    BaseActionsMixin,
    PatchMixin,
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
from ._app_action_availability import check_app_action
from ._app_layout import (
    BGCMD_LIST_RESERVED_FOR_DASHBOARD as _BGCMD_LIST_RESERVED_FOR_DASHBOARD,
)
from ._app_layout import (
    MAX_AGENT_LIST_WIDTH as _MAX_AGENT_LIST_WIDTH,
)
from ._app_layout import (
    MAX_BGCMD_LIST_WIDTH as _MAX_BGCMD_LIST_WIDTH,
)
from ._app_layout import (
    MAX_LIST_WIDTH as _MAX_LIST_WIDTH,
)
from ._app_layout import (
    MIN_AGENT_LIST_WIDTH as _MIN_AGENT_LIST_WIDTH,
)
from ._app_layout import (
    MIN_BGCMD_LIST_WIDTH as _MIN_BGCMD_LIST_WIDTH,
)
from ._app_layout import (
    MIN_LIST_WIDTH as _MIN_LIST_WIDTH,
)
from ._app_layout import AppLayoutMixin
from ._app_watchers import AppWatchersMixin
from .artifact_tabs import (
    DEFAULT_ARTIFACTS_SUBTAB,
    DEFAULT_FILES_SUBTAB,
    ArtifactsPaneKey,
    ArtifactsSubTab,
    FilesSubTab,
    artifacts_pane_key,
)
from .bindings import DEFAULT_BINDINGS
from .exit_action import AceExitAction
from .models.fold_state import FoldLevel
from .tab_order import TabInput, TabName, normalize_tab_name
from .util.perf import JKPerfTimer, is_enabled as _perf_enabled

log = logging.getLogger(__name__)

__all__ = [
    "AceApp",
    "_BGCMD_LIST_RESERVED_FOR_DASHBOARD",
    "_MAX_AGENT_LIST_WIDTH",
    "_MAX_BGCMD_LIST_WIDTH",
    "_MAX_LIST_WIDTH",
    "_MIN_AGENT_LIST_WIDTH",
    "_MIN_BGCMD_LIST_WIDTH",
    "_MIN_LIST_WIDTH",
]


class AceApp(
    AppLayoutMixin,
    AppWatchersMixin,
    AgentWorkflowMixin,
    AgentsMixin,
    AgentsSyncActionsMixin,
    AxeMixin,
    ArtifactBugsMixin,
    ArtifactsMixin,
    PatchMixin,
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
    """TUI application for navigating Patches."""

    TITLE = "sase ace"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = DEFAULT_BINDINGS

    patches: reactive[list[Patch]] = reactive([], recompose=False)
    hooks_collapsed: reactive[FoldLevel] = reactive(
        FoldLevel.COLLAPSED, recompose=False
    )
    stitches_collapsed: reactive[FoldLevel] = reactive(
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
    current_tab: reactive[TabName] = reactive("artifacts", recompose=False)
    current_artifacts_subtab: reactive[ArtifactsSubTab] = reactive(
        DEFAULT_ARTIFACTS_SUBTAB, recompose=False
    )
    current_files_subtab: reactive[FilesSubTab] = reactive(
        DEFAULT_FILES_SUBTAB, recompose=False
    )
    axe_running: reactive[bool] = reactive(False, recompose=False)
    axe_description_expanded: reactive[bool] = reactive(True, recompose=False)
    hide_reverted: reactive[bool] = reactive(True, recompose=False)
    hide_submitted: reactive[bool] = reactive(True, recompose=False)
    hide_non_run_agents: reactive[bool] = reactive(True, recompose=False)
    marked_indices: reactive[set[int]] = reactive(set, recompose=False)

    exit_action: AceExitAction
    _current_idx: int
    _current_attempt_number: int | None
    _jk_perf: JKPerfTimer | None
    _commits_default_filter: "CommitLogFilterValues"
    _commits_default_query_diagnostic: str | None

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
            remember_panel_selection = getattr(
                self, "_remember_focused_panel_selection", None
            )
            if callable(remember_panel_selection):
                remember_panel_selection(("agent", value))

    @property
    def current_attempt_number(self) -> int | None:
        """Selected attempt number; ``None`` means the live attempt."""
        return self._current_attempt_number

    @current_attempt_number.setter
    def current_attempt_number(self, value: int | None) -> None:
        old = self._current_attempt_number
        self._current_attempt_number = value
        if old != value and self.current_tab == "agents":
            self._refresh_agents_display_debounced()

    def validate_current_tab(self, value: TabInput) -> TabName:
        """Normalize legacy tab aliases before storing app state."""
        return normalize_tab_name(value)

    def __init__(
        self,
        query: str = "!!!",
        model_tier_override: Literal["large", "small"] | None = None,
        refresh_interval: int = 10,
        auto_start_axe: bool = True,
        restart_axe: bool = False,
        initial_tab: TabInput = "agents",
    ) -> None:
        """Initialize the ace TUI app."""
        super().__init__()
        from .util.app_version import format_app_title, initial_app_version

        self.title = format_app_title(initial_app_version())
        current_toast_session()
        register_ace_session(self.title)
        self._jk_perf = JKPerfTimer() if _perf_enabled() else None
        self._init_app_state(
            query=query,
            model_tier_override=model_tier_override,
            refresh_interval=refresh_interval,
            auto_start_axe=auto_start_axe,
            restart_axe=restart_axe,
            initial_tab=normalize_tab_name(initial_tab),
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
        """Get the canonical (normalized) form of the query string."""
        return to_canonical_string(self.parsed_query)

    @property
    def current_artifacts_pane_key(self) -> ArtifactsPaneKey:
        """Return the visible leaf pane that owns Artifacts state."""
        return artifacts_pane_key(
            self.current_artifacts_subtab,
            self.current_files_subtab,
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Return whether an action is available in the current UI context."""
        return check_app_action(self, action, parameters, super().check_action)

    def _jk_perf_begin(self, action: str) -> None:
        """Record a key-to-paint sample start, when SASE_TUI_PERF=1."""
        if self._jk_perf is not None:
            self._jk_perf.begin(action, self.current_tab)
