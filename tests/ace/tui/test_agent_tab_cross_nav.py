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
from sase.ace.tui.actions.agents._tab_scope import scoped_agents_for_owner
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
from sase.ace.tui.models.agent_tab_index import (
    build_agent_tab_index,
    clear_agent_tab_index_cache,
)
from sase.ace.tui.models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
)
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey
from sase.feature_flags import override_flags

from ._agent_unread_navigation_helpers import UnreadJumpApp


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    clear_agent_tab_index_cache()
    yield
    clear_agent_tab_index_cache()


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
        self._agents = scoped_agents_for_owner(self, list(self._agents_query_result))

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
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
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


class _ReviveOwner(_TabOwner, AgentReviveStateMixin):
    """Tab owner with revive selection for the cross-tab select test."""


def test_select_revived_agent_switches_tabs() -> None:
    owner = _ReviveOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
        target = owner._agents_with_children[1]
        assert owner._select_revived_agent(target) is True
        assert owner._active_agent_tab == _SASE
        assert owner.current_idx == 0
        assert owner._agents[owner.current_idx].identity == target.identity


def test_select_file_agent_switches_tabs() -> None:
    from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin

    class _FilesOwner(_TabOwner, ArtifactsFilesActionsMixin):
        pass

    owner = _FilesOwner([_row("a"), _row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    with override_flags(agent_tabs=True):
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
        target = owner._agents_with_children[1]
        assert owner._select_file_agent(target.identity, None) is True
        assert owner._active_agent_tab == _SASE
        assert owner._agents[owner.current_idx].identity == target.identity


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


def _cross_tab_harness_class() -> Any:
    from ._member_jump_navigation_helpers import JumpHarness
    from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin as _Tabs
    from sase.ace.tui.actions.agents._agent_tab_jump import (
        AgentTabJumpMixin as _Jump,
    )

    class _CrossTabHarness(JumpHarness, _Tabs, _Jump):
        def _rescope_agents_to_active_tab(self) -> None:
            with override_flags(agent_tabs=True):
                self._agents = scoped_agents_for_owner(
                    self, list(self._agents_query_result)
                )
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            super()._refilter_agents(**kwargs)
            with override_flags(agent_tabs=True):
                self._agents = scoped_agents_for_owner(self, list(self._agents))
                self._panel_group = AgentPanelGroup.from_agents(self._agents)

    return _CrossTabHarness


def test_try_reveal_agent_row_switches_tabs() -> None:
    _CrossTabHarness = _cross_tab_harness_class()

    rows = [_row("a"), _row("b", tab="sase")]
    app = _CrossTabHarness(rows, rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    with override_flags(agent_tabs=True):
        app._agents = scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0
        failure = app._try_reveal_agent_row(rows[1].identity)
        assert failure is None
        assert app._active_agent_tab == _SASE
        assert app._agents[app.current_idx].identity == rows[1].identity


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
        app._agents = scoped_agents_for_owner(app, list(app._agents_query_result))
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
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
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
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
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
        owner._agents = scoped_agents_for_owner(owner, list(owner._agents_query_result))
        owner._entry_jump_agents_anchor_stack.append(("agent", 0, None, "named:gone"))
        assert owner._restore_agents_jump_anchor() is False
        assert owner._active_agent_tab == DEFAULT_AGENT_TAB_KEY


def test_stopped_jump_crosses_tabs() -> None:
    rows = [_row("a", status="RUNNING"), _row("b", tab="sase", status="PLAN")]
    app = UnreadJumpApp(rows, with_panels=True)
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), _view())
    app._ensure_agent_tabs_state()
    with override_flags(agent_tabs=True):
        app._agents = scoped_agents_for_owner(app, list(rows))
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app.current_idx = 0

        def _rescope() -> None:
            app._agents = scoped_agents_for_owner(app, list(app._agents_query_result))
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
