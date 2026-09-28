"""Shared fixtures for agent-tab cross-navigation tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._agent_tab_jump import AgentTabJumpMixin
from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models import Agent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.ace.tui.models.node_finder import (
    NodeFinderReason,
    NodeFinderRole,
    NodeFinderRow,
)
from sase.core.agent_tab import AgentTabKey

SASE = AgentTabKey.named("sase")


def view(token: Any = ("cross-nav-test",)) -> AgentTabsViewConfig:
    """Return a deterministic tab-view config for unit tests."""
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    name: str | None = None,
) -> Agent:
    """Build one agent row with a stable timestamp."""
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


class TabOwner(AgentTabsMixin, AgentTabJumpMixin):
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
        self._agent_tab_index = build_agent_tab_index(list(rows), view())


def two_tab_owner() -> TabOwner:
    """Return a two-tab owner scoped to the default tab."""
    owner = TabOwner([row("a"), row("b", tab="sase")])
    owner.reindex(owner._agents_with_children)
    owner._agents = _scoped_agents_for_owner(owner, list(owner._agents_query_result))
    return owner


def cross_tab_harness_class() -> Any:
    """Return a JumpHarness subclass with tab mixins and a rescope hook."""
    from ._member_jump_navigation_helpers import JumpHarness

    class _CrossTabHarness(JumpHarness, AgentTabsMixin, AgentTabJumpMixin):
        def _rescope_agents_to_active_tab(self) -> None:
            self._agents = _scoped_agents_for_owner(
                self, list(self._agents_query_result)
            )
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _refilter_agents(self, **kwargs: Any) -> None:
            super()._refilter_agents(**kwargs)
            self._agents = _scoped_agents_for_owner(self, list(self._agents))
            self._panel_group = AgentPanelGroup.from_agents(self._agents)

        def _save_current_tab_position(self) -> None:
            pass

        def _refresh_current_tab(self) -> None:
            pass

        def refresh_link_rail(self) -> None:
            pass

        def call_after_refresh(self, callback: Any) -> None:
            callback()

    return _CrossTabHarness


def prepare_cross_tab_app(
    rows: list[Agent],
    selected: Agent | None = None,
    *,
    harness_cls: Any | None = None,
) -> Any:
    """Build a cross-tab harness with index, query result, and panel group."""
    cls = harness_cls or cross_tab_harness_class()
    app = cls(rows, selected or rows[0])
    app._ensure_agent_tabs_state()
    app._agents_with_children = list(rows)
    app._agents_query_result = list(rows)
    app._agent_tab_index = build_agent_tab_index(list(rows), view())
    return app


class AnchorOwner(TabOwner, EntryJumpAgentHistoryMixin):
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
        return SimpleNamespace(focused_idx=0, panel_keys=[None], focused_key=None)


def finder_row(
    identity: Any,
    *,
    jumpable: bool = True,
    rendered: bool = False,
    tab_label: str = "",
) -> NodeFinderRow:
    """Build one Node Finder row, optionally tagged with an off-tab chip."""
    return NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=identity,
        jumpable=jumpable,
        reasons=frozenset()
        if rendered or tab_label
        else frozenset({NodeFinderReason.QUERY}),
        tab_label=tab_label,
    )
