"""Switch-then-reveal cross-tab navigation tests (sase-1bc.6.1.4).

Covers the shared ``_ensure_agent_tab_for`` helper (switch, same-tab and
unknown-identity no-ops, flag-off identity), the off-tab label map, and
each routed entry point with its target on the non-active tab: shared
reveal success plus failed-reveal tab restore, revive select, Files
select, notification navigation, ``,J`` stopped jumps, jump-back anchors
across tabs, and Node Finder omission of off-tab rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._agent_tab_jump import (
    ensure_agent_tab_for_identity,
    off_tab_labels_for_owner,
    restore_agent_tab,
)
from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._agent_tab_jump import AgentTabJumpMixin
from sase.ace.tui.actions.agents._revive_state import AgentReviveStateMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.actions.agents._node_finder_finalize import (
    apply_snapshot_omission,
)
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models import Agent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.ace.tui.models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
)
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey
from sase.feature_flags import override_flags

from ._agent_unread_navigation_helpers import UnreadJumpApp


def _view(token: Any = ("cross-nav-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def _row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    name: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=datetime(2026, 9, 27, 12, 0, 0),
        stop_time=datetime(2026, 9, 27, 12, 5, 0),
        raw_suffix=suffix,
        agent_name=name or f"agent-{suffix}",
        agent_tab=tab,
    )


_SASE = AgentTabKey.named("sase")


class _TabOwner(AgentTabsMixin, AgentTabJumpMixin):
    """Minimal owner driving the tab mixins without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._jk_perf = None
        self._ensure_agent_tabs_state()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        """Fail closed: no list panel or strip is mounted in unit tests."""
        raise LookupError("no widget")

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Swallow toasts in unit tests."""

    def reindex(self, rows: list[Agent]) -> None:
        """Install *rows* as the roster and rebuild the tab index."""
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agent_tab_index = build_agent_tab_index(list(rows), _view())


def _two_tab_owner() -> _TabOwner:
    owner = _TabOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
    return owner


def test_ensure_switches_to_target_tab() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert [a.raw_suffix for a in owner._agents] == ["a"]
        previous = ensure_agent_tab_for_identity(
            owner, owner._agents_with_children[1].identity
        )
        assert previous == DEFAULT_AGENT_TAB_KEY
        assert owner._active_agent_tab == _SASE
        assert [a.raw_suffix for a in owner._agents] == ["b"]


def test_ensure_accepts_row_and_mixin_reports_switch() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert owner._ensure_agent_tab_for(owner._agents_with_children[1]) is True
        assert owner._active_agent_tab == _SASE
        assert owner._ensure_agent_tab_for(owner._agents_with_children[1]) is False


def test_ensure_noop_same_tab_unknown_and_flag_off() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert (
            ensure_agent_tab_for_identity(
                owner, owner._agents_with_children[0].identity
            )
            is None
        )
        assert (
            ensure_agent_tab_for_identity(owner, (AgentType.RUNNING, "x", "nope"))
            is None
        )
    with override_flags(agent_tabs=False):
        assert (
            ensure_agent_tab_for_identity(
                owner, owner._agents_with_children[1].identity
            )
            is None
        )
        assert owner._ensure_agent_tab_for(owner._agents_with_children[1]) is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_restore_agent_tab_returns_to_previous() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        previous = ensure_agent_tab_for_identity(
            owner, owner._agents_with_children[1].identity
        )
        assert owner._active_agent_tab == _SASE
        restore_agent_tab(owner, previous)
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert [a.raw_suffix for a in owner._agents] == ["a"]
        restore_agent_tab(owner, None)


def test_off_tab_labels_for_owner() -> None:
    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        labels = off_tab_labels_for_owner(owner)
        assert labels == {owner._agents_with_children[1].identity: "sase"}
    with override_flags(agent_tabs=False):
        assert off_tab_labels_for_owner(owner) == {}


def test_select_revived_agent_switches_tabs() -> None:
    # ``_select_revived_agent`` routes through ``_try_reveal_agent_row``, so
    # the harness needs the full reveal/fold machinery, not the minimal
    # ``_TabOwner``.
    _CrossTabHarness = _cross_tab_harness_class()

    class _ReviveHarness(_CrossTabHarness, AgentReviveStateMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _ReviveHarness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._select_revived_agent(rows[1]) is True
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_select_file_agent_switches_tabs() -> None:
    from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin

    # ``_select_file_agent`` routes through ``_try_reveal_agent_row`` too.
    _CrossTabHarness = _cross_tab_harness_class()

    class _FilesHarness(_CrossTabHarness, ArtifactsFilesActionsMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _FilesHarness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert app._select_file_agent(rows[1].identity, None) is True
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_notification_navigate_to_agent_tab_switches_tabs() -> None:
    from sase.ace.tui.actions.agents._notification_navigation import (
        navigate_to_agent_tab,
    )

    owner = _two_tab_owner()
    with override_flags(agent_tabs=True):
        assert navigate_to_agent_tab(owner, "proj") is True
        # cl_name matches both rows; the complete-roster scan finds the
        # default-tab row first, so no switch is needed here.
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        only_sase = _TabOwner([_row("a", tab="sase")])
        only_sase.reindex(only_sase._agents_with_children)
        only_sase._agents = []
        only_sase._active_agent_tab = DEFAULT_AGENT_TAB_KEY
        assert navigate_to_agent_tab(only_sase, "proj") is True
        assert only_sase._active_agent_tab == _SASE


def test_navigate_to_agent_tab_fallback_scan_restores_tab_on_failure() -> None:
    """The identity-scan fallback (no Node Finder ladder) owns its switch.

    ``jump_to_loaded_agent`` used to be pre-switched by its callers and
    never restored the tab on failure; the fallback path now switches and
    restores itself.
    """
    from sase.ace.tui.actions.agents._notification_navigation import (
        navigate_to_agent_tab,
    )

    row_a, row_b = _row("a"), _row("b", tab="sase")
    row_b.pid = 42
    owner = _TabOwner([row_a, row_b])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        # The cached query result goes stale after the switch: the target
        # no longer resolves there, so the scan must restore the tab.
        owner._agents_query_result = [row_a]
        assert navigate_to_agent_tab(owner, "proj", pid=42) is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def _cross_tab_harness_class() -> Any:
    from ._member_jump_navigation_helpers import JumpHarness
    from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin as _Tabs
    from sase.ace.tui.actions.agents._agent_tab_jump import (
        AgentTabJumpMixin as _Jump,
    )

    class _CrossTabHarness(JumpHarness, _Tabs, _Jump):
        def _rescope_agents_to_active_tab(self) -> None:
            with override_flags(agent_tabs=True):
                self._agents = _scoped_agents_for_owner(
                    self, list(self._agents_query_result)
                )
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            super()._refilter_agents(**kwargs)
            with override_flags(agent_tabs=True):
                self._agents = _scoped_agents_for_owner(self, list(self._agents))
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

    return _CrossTabHarness


def test_handle_jump_to_agent_crosses_tabs_through_ladder() -> None:
    """``handle_jump_to_agent`` no longer pre-switches tabs itself.

    It used to call ``_ensure_agent_tab_for`` before ``jump_to_loaded_agent``,
    so the ladder's own ``_try_reveal_agent_row`` saw no pending switch.
    Dropping the pre-switch lets the ladder own the whole cross-tab jump.
    """
    from sase.ace.tui.actions.agents._notification_handlers import (
        handle_jump_to_agent,
    )
    from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
    from sase.notifications import Notification

    _CrossTabHarness = _cross_tab_harness_class()

    class _Harness(_CrossTabHarness, NodeJumpNavigationMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _Harness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    app._hideable_agents = []

    notification = Notification(
        id="n-jump",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": "proj", "raw_suffix": "b"},
    )
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert handle_jump_to_agent(app, notification) is True
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_handle_jump_to_agent_failed_reveal_restores_tab() -> None:
    """A failed reveal through the ladder restores the tab it left.

    With the pre-switch dropped, the switch and its restore-on-failure both
    live inside ``_try_reveal_agent_row``.
    """
    from sase.ace.tui.actions.agents._notification_handlers import (
        handle_jump_to_agent,
    )
    from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
    from sase.notifications import Notification

    _CrossTabHarness = _cross_tab_harness_class()

    class _Harness(_CrossTabHarness, NodeJumpNavigationMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _Harness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    # Stale query result: the target no longer resolves once the tab
    # switches, so the reveal must fail and restore the previous tab.
    app._agents_query_result = [rows[0]]
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    app._hideable_agents = []

    notification = Notification(
        id="n-jump",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": "proj", "raw_suffix": "b"},
    )
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        assert handle_jump_to_agent(app, notification) is False
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_try_reveal_agent_row_switches_tabs() -> None:
    _CrossTabHarness = _cross_tab_harness_class()

    rows = [_row("a"), _row("b", tab="sase")]
    app = _CrossTabHarness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        failure = app._try_reveal_agent_row(rows[1].identity)
        assert failure is None
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_try_reveal_agent_row_back_jump_restores_source_tab_and_row() -> None:
    """A real cross-tab jump, then a back-jump, returns to the origin.

    The pre-fix ``_try_reveal_agent_row`` switched tabs (via
    ``ensure_agent_tab_for_identity``) before capturing the source row and
    saving the back-anchor, so the anchor recorded the destination tab's own
    remembered row instead of where the jump started. The existing
    back/forward tests call ``_ensure_agent_tab_for`` directly and never
    exercised the reveal's own ordering.
    """
    from sase.ace.tui.actions.agents._tab_scope import AgentTabScopeMixin

    _CrossTabHarness = _cross_tab_harness_class()

    class _Harness(_CrossTabHarness, AgentTabScopeMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _Harness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0

        failure = app._try_reveal_agent_row(rows[1].identity)
        assert failure is None
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity

        anchor = app._entry_jump_agents_anchor_stack[-1]
        assert anchor[0] == "agent"
        assert anchor[1] == 0
        assert anchor[-1] == "default"

        assert app._restore_agents_jump_anchor() is True
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert app._agents[app.current_idx].identity == rows[0].identity


def test_failed_reveal_restores_previous_tab() -> None:
    _CrossTabHarness = _cross_tab_harness_class()

    rows = [_row("a"), _row("b", tab="sase")]
    app = _CrossTabHarness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    # The cached query result is stale: it no longer holds the target, so
    # the post-switch reveal filters it out and must restore the old tab.
    app._agents_query_result = [rows[0]]
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        from sase.ace.tui.actions.navigation._agent_reveal import AgentRevealFailure

        failure = app._try_reveal_agent_row(rows[1].identity)
        assert failure is AgentRevealFailure.TARGET_FILTERED
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


class _AnchorOwner(_TabOwner, EntryJumpAgentHistoryMixin):
    """Tab owner with jump-anchor history for cross-tab back-jumps."""

    def __init__(self, rows: list[Agent]) -> None:
        super().__init__(rows)
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._agent_panels_grouped = False
        self._collapsed_panel_keys: set[Any] = set()

    def _agent_tab_scope_token(self) -> str:
        from sase.ace.tui.actions.agents._tab_scope import (
            current_agent_tab_scope_token,
        )

        return current_agent_tab_scope_token(self)

    def _panel_keys_per_agent(self) -> list[Any]:
        return [None] * len(self._agents)

    @property
    def _panel_group(self) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(focused_idx=0, panel_keys=[None], focused_key=None)


def test_jump_anchor_records_tab_and_restores_across_tabs() -> None:
    owner = _AnchorOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        owner.current_idx = 0
        owner._save_agents_jump_anchor()
        saved = owner._entry_jump_agents_anchor_stack[-1]
        assert saved == ("agent", 0, None, "default")
        assert (
            owner._ensure_agent_tab_for(owner._agents_with_children[1].identity) is True
        )
        assert owner._restore_agents_jump_anchor() is True
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert owner.current_idx == 0


def test_jump_forward_returns_across_tabs() -> None:
    owner = _AnchorOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        owner.current_idx = 0
        owner._save_agents_jump_anchor()
        assert (
            owner._ensure_agent_tab_for(owner._agents_with_children[1].identity) is True
        )
        assert owner._restore_agents_jump_anchor() is True
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        forward_stack = owner._entry_jump_agents_forward_stack()
        assert forward_stack == [("agent", 0, None, "named:sase")]
        anchor = owner._pop_agents_jump_anchor(forward_stack)
        assert anchor is not None
        owner._restore_agents_jump_anchor_value(anchor)
        assert owner._active_agent_tab == _SASE
        assert owner.current_idx == 0


def test_jump_anchor_with_gone_tab_is_dropped() -> None:
    owner = _AnchorOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        owner._entry_jump_agents_anchor_stack.append(("agent", 0, None, "named:gone"))
        assert owner._restore_agents_jump_anchor() is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_pop_anchor_restores_starting_tab_when_every_anchor_is_stale() -> None:
    """A failed back-jump must not leave the tab switched.

    The anchor names a real tab (so the pop loop switches to it first), but
    the row index it recorded no longer exists there. With the stack
    exhausted, the call must restore the tab it started on instead of
    stranding the user on the last anchor's tab.
    """
    owner = _AnchorOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        owner._entry_jump_agents_anchor_stack.append(("agent", 99, None, "named:sase"))
        assert owner._pop_agents_jump_anchor() is None
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_pop_anchor_without_tab_token_belongs_to_current_tab() -> None:
    """An anchor saved while the flag was off (no tab token) still validates.

    Comparing a missing token against the current tab's token literally
    always failed once the flag was on, dropping every legacy anchor as
    stale; it should instead be treated as belonging to whatever tab is
    current now.
    """
    owner = _AnchorOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = _scoped_agents_for_owner(
            owner, list(owner._agents_query_result)
        )
        owner._entry_jump_agents_anchor_stack.append(("agent", 0, None))
        anchor = owner._pop_agents_jump_anchor()
        assert anchor == ("agent", 0, None)
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_stopped_jump_crosses_tabs() -> None:
    rows = [_row("a", status="RUNNING"), _row("b", tab="sase", status="PLAN")]
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    app._ensure_agent_tabs_state()
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0

        def _rescope() -> None:
            app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
            app._panel_group = AgentPanelGroup.from_agents(app._agents)

        app._rescope_agents_to_active_tab = _rescope  # type: ignore[method-assign]
        assert app._jump_to_next_stopped_agent() is True
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


def test_stopped_jump_unchanged_flag_off() -> None:
    rows = [_row("a", status="PLAN"), _row("b", tab="sase", status="DONE")]
    app = UnreadJumpApp(rows, with_panels=True)
    with override_flags(agent_tabs=False):
        assert app._jump_to_next_stopped_agent() is True
        assert app._agents[app.current_idx].identity == rows[0].identity


def test_jump_to_off_tab_timed_candidate_reveals_through_collapsed_clan() -> None:
    """``,j`` reveals an off-tab candidate hidden under a collapsed clan fold.

    ``_off_tab_jump_candidates`` builds candidates from the tab-independent
    query result, which can include a row hidden under a collapsed fold on
    its own tab. The old post-switch plain scan of ``_agents`` never found
    such a row (fold-hidden rows are absent from the filtered roster
    entirely) and wrongly toasted "not found"; the fix reveals through the
    same fold-expanding pipeline as every other cross-tab jump.
    """
    from sase.ace.tui.actions.agents._unread_jump_candidates import (
        TimedAgentJumpCandidate,
    )
    from sase.ace.tui.models._agent_tree import agent_fold_key
    from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
    from sase.ace.tui.models.fold_state import FoldStateManager

    from ._member_jump_navigation_helpers import make_clan

    projected, container = make_clan(2)
    container.agent_tab = "sase"
    member = container.runtime_children[1]
    member.status = "DONE"

    class _Harness(UnreadJumpApp):
        def _rescope_agents_to_active_tab(self) -> None:
            with override_flags(agent_tabs=True):
                folded, _ = filter_agents_by_fold_state(
                    self._agents_with_children, self._fold_manager
                )
                self._agents = _scoped_agents_for_owner(self, folded)
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            with override_flags(agent_tabs=True):
                folded, _ = filter_agents_by_fold_state(
                    self._agents_with_children, self._fold_manager
                )
                self._agents = _scoped_agents_for_owner(self, folded)
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

    app = _Harness(projected, with_panels=True)
    app._fold_manager = FoldStateManager()
    app._agents_with_children = list(projected)
    app._agents_query_result = list(projected)
    app._ensure_agent_tabs_state()
    app._agent_tab_index = build_agent_tab_index(list(projected), _view())
    app._unread_completed_agent_ids = {member.identity}

    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)

    with override_flags(agent_tabs=True):
        app._refilter_agents()
        assert app._agents == []

        sase_key = app._agent_tab_index.key_for(member)
        candidate = TimedAgentJumpCandidate(
            identity=member.identity,
            panel_key=None,
            jump_time=None,
            visible_idx=None,
            tab_key=sase_key,
        )

        def _predicate(agent: Agent) -> bool:
            return agent.identity in app._unread_completed_agent_ids

        assert app._jump_to_off_tab_timed_candidate(
            candidate, predicate=_predicate, after_select=None
        )
        assert app._active_agent_tab == sase_key
        assert app._agents[app.current_idx].identity == member.identity


def test_jump_to_off_tab_timed_candidate_rolls_back_anchor_and_tab_on_mismatch() -> (
    None
):
    """A stale off-tab candidate rolls back both the anchor and the tab.

    The saved back-anchor and the tab switch used to survive a failed
    reveal, so the next ``,j`` picked the same stuck candidate again.
    """
    from sase.ace.tui.actions.agents._unread_jump_candidates import (
        TimedAgentJumpCandidate,
    )

    rows = [_row("a", status="RUNNING"), _row("b", tab="sase", status="DONE")]
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    app._ensure_agent_tabs_state()
    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0

        def _rescope() -> None:
            app._agents = _scoped_agents_for_owner(app, list(app._agents_query_result))
            app._panel_group = AgentPanelGroup.from_agents(app._agents)

        app._rescope_agents_to_active_tab = _rescope  # type: ignore[method-assign]

        candidate = TimedAgentJumpCandidate(
            identity=rows[1].identity,
            panel_key=None,
            jump_time=None,
            visible_idx=None,
            tab_key=_SASE,
        )
        result = app._jump_to_off_tab_timed_candidate(
            candidate, predicate=lambda _agent: False, after_select=None
        )
        assert result is False
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY
        assert app._entry_jump_agents_anchor_stack == []


def _finder_row(
    identity: Any,
    *,
    jumpable: bool = True,
    rendered: bool = False,
    tab_label: str = "",
) -> NodeFinderRow:
    from sase.ace.tui.models.node_finder import NodeFinderReason

    return NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=identity,
        jumpable=jumpable,
        reasons=frozenset()
        if rendered or tab_label
        else frozenset({NodeFinderReason.QUERY}),
        tab_label=tab_label,
    )


def test_omission_keeps_off_tab_rows() -> None:
    owner = _two_tab_owner()
    on_tab = owner._agents_with_children[0].identity
    off_tab = owner._agents_with_children[1].identity
    rows = [
        _finder_row(on_tab, rendered=True),
        _finder_row(off_tab, tab_label="sase"),
    ]
    kept, index, _chains = apply_snapshot_omission(list(rows), set(), {on_tab}, set())
    assert {row.identity for row in kept} == {on_tab, off_tab}
    assert index[off_tab] == 1


def test_node_finder_off_tab_chip_survives_other_hidden_reasons() -> None:
    """An off-tab row keeps its chip even when it is also query-hidden.

    ``build_snapshot_rows`` used to add the off-tab chip only when
    ``reason_mask == 0``, so an off-tab row that was also folded or
    query-hidden got no chip and looked unreachable in the Node Finder.
    """
    from sase.ace.tui.actions.navigation._entry_jump_mode import EntryJumpModeMixin
    from sase.ace.tui.actions.agents._node_finder_snapshot import (
        build_node_finder_snapshot,
    )
    from sase.ace.tui.models.node_finder import NodeFinderReason, NodeFinderRole

    _CrossTabHarness = _cross_tab_harness_class()

    class _Harness(_CrossTabHarness, EntryJumpModeMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _Harness(rows, rows[0])
    app._agent_search_query = ""
    app.hide_non_run_agents = False
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True, agents_unified_query=False):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        # A search query that only "a" matches gives "b" a QUERY hidden
        # reason on top of already being off-tab.
        app._agent_search_query = "agent-a"

        snap = build_node_finder_snapshot(app)
        row = next(
            row
            for row in snap.rows
            if row.role is NodeFinderRole.NODE and row.identity == rows[1].identity
        )
        assert NodeFinderReason.QUERY in row.reasons
        assert row.tab_label == "sase"


def test_reveal_last_launch_target_restores_tab_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised exception mid-reveal still restores the tab it left.

    ``_reveal_last_launch_target`` only restored the tab when the reveal
    machinery returned a failure, not when it raised; the previous tab is
    now tracked outside the try body so both paths restore it.
    """
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    _CrossTabHarness = _cross_tab_harness_class()

    class _Harness(_CrossTabHarness, KillAndEditLastLaunchMixin):
        pass

    rows = [_row("a"), _row("b", tab="sase")]
    app = _Harness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch"
        ".reveal_agent_navigation_target",
        _boom,
    )

    with override_flags(agent_tabs=True):
        app._agents = _scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        app._reveal_last_launch_target(rows[1].identity)
        assert app._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_monitor_jump_agent_widening_gated_on_flag() -> None:
    """The Procs monitor-jump widening only searches child rows with the flag on.

    ``_monitor_jump_agent`` switched from ``_agents`` to
    ``_agents_with_children`` unconditionally, widening flag-off matches to
    rows previously excluded as hidden children.
    """
    from sase.ace.tui.modals.procs_pane_agent_jump import _monitor_jump_agent

    hidden_child = _row("child")
    hidden_child.monitor_id = "proc-1"

    class _App:
        _agents: list[Agent] = []
        _agents_with_children = [hidden_child]

    app = _App()
    with override_flags(agent_tabs=False):
        assert _monitor_jump_agent(app, "proc-1") is None
    with override_flags(agent_tabs=True):
        assert _monitor_jump_agent(app, "proc-1") is hidden_child


def test_run_log_modal_jump_crosses_tabs_through_fold_expanding_reveal() -> None:
    """The run-log modal's jump routes through the shared reveal ladder.

    ``action_jump_to_agent_tab`` used to scan ``app._agents`` directly after
    a pre-switch, so a target hidden under a collapsed clan fold on another
    agent tab (absent from the filtered roster entirely) left the toast
    "Agent not found on Agents tab" instead of expanding the fold.
    """
    from sase.ace.tui.models._agent_tree import agent_fold_key
    from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
    from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal

    from ._member_jump_navigation_helpers import JumpHarness, make_clan

    class _Harness(JumpHarness, AgentTabsMixin, AgentTabJumpMixin):
        def _rescope_agents_to_active_tab(self) -> None:
            with override_flags(agent_tabs=True):
                folded, _ = filter_agents_by_fold_state(
                    self._agents_with_children, self._fold_manager
                )
                self._agents = _scoped_agents_for_owner(self, folded)
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            with override_flags(agent_tabs=True):
                folded, _ = filter_agents_by_fold_state(
                    self._agents_with_children, self._fold_manager
                )
                self._agents = _scoped_agents_for_owner(self, folded)
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _save_current_tab_position(self) -> None:
            pass

    class _FakeModal:
        def __init__(self, app: Any, target: Agent) -> None:
            self.app = app
            self._target = target
            self.dismissed = False

        def _get_highlighted_agent(self) -> Agent | None:
            return self._target

        def _is_dismissed(self, _agent: Agent) -> bool:
            return False

        def dismiss(self) -> None:
            self.dismissed = True

    projected, container = make_clan(2)
    container.agent_tab = "sase"
    member = container.runtime_children[1]

    app = _Harness(projected, container)
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(projected)
    app._agents_query_result = list(projected)
    app._agent_tab_index = build_agent_tab_index(list(projected), _view())

    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)

    with override_flags(agent_tabs=True):
        app._refilter_agents()
        assert app._agents == []

        modal = _FakeModal(app, member)
        AgentRunLogModal.action_jump_to_agent_tab(modal)  # type: ignore[arg-type]

        assert modal.dismissed is True
        assert app._active_agent_tab == AgentTabKey.named("sase")
        assert app._agents[app.current_idx].identity == member.identity


def test_run_log_modal_jump_unchanged_flag_off() -> None:
    """A flag-off jump still resolves the target through the same ladder.

    With the flag off, ``ensure_agent_tab_for_identity`` is a no-op (no tabs
    exist to switch between), so the jump degrades to a plain same-roster
    reveal, matching pre-epic behavior.
    """
    from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal

    _CrossTabHarness = _cross_tab_harness_class()

    class _App(_CrossTabHarness):
        def _save_current_tab_position(self) -> None:
            pass

    class _FakeModal:
        def __init__(self, app: Any, target: Agent) -> None:
            self.app = app
            self._target = target
            self.dismissed = False

        def _get_highlighted_agent(self) -> Agent | None:
            return self._target

        def _is_dismissed(self, _agent: Agent) -> bool:
            return False

        def dismiss(self) -> None:
            self.dismissed = True

    rows = [_row("a"), _row("b")]
    app = _App(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)

    with override_flags(agent_tabs=False):
        app._agents = list(rows)
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0

        modal = _FakeModal(app, rows[1])
        AgentRunLogModal.action_jump_to_agent_tab(modal)  # type: ignore[arg-type]

        assert modal.dismissed is True
        assert app._agents[app.current_idx].identity == rows[1].identity
