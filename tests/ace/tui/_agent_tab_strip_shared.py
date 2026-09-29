"""Shared harness for the split agent-tab-strip tests.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._agent_tabs import AgentTabsMixin
from sase.ace.tui.actions.agents._tab_scope import _scoped_agents_for_owner
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tab_index import build_agent_tab_index
from sase.ace.tui.widgets.agent_tab_strip import AgentTabDescriptor
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey

__all__ = [
    "BLOG",
    "SASE",
    "TabOwner",
    "make_descriptors",
    "make_row",
    "make_view",
    "two_tab_owner",
]

SASE = AgentTabKey.named("sase")
BLOG = AgentTabKey.named("blog")


def make_view(token: Any = ("strip-test",)) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=False,
        machine_order=(),
        pinned_by_alias={},
        named_order={},
        token=token,
    )


def make_row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    origin_alias: str | None = None,
    origin_id: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=datetime(2026, 9, 28, 8, 0, 0),
        raw_suffix=suffix,
        agent_tab=tab,
        fleet_origin_alias=origin_alias,
        fleet_origin_installation_id=origin_id,
    )


def make_descriptors(
    active: AgentTabKey = SASE,
    *,
    arrival_blog: bool = False,
) -> tuple[AgentTabDescriptor, ...]:
    return (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="main",
            accent="#AFAFAF",
            count=2,
            is_default=True,
        ),
        AgentTabDescriptor(
            key=SASE,
            label="sase",
            accent="#AF87FF",
            count=12,
            stopped=1,
            unread=2,
        ),
        AgentTabDescriptor(
            key=BLOG,
            label="blog",
            accent="#5FD7FF",
            count=3,
            has_arrival=arrival_blog,
        ),
    )


class TabOwner(AgentTabsMixin):
    """Minimal owner driving the tab mixin without the full app."""

    def __init__(self, rows: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(rows)
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._jk_perf = None
        self._agent_search_query = ""
        self._agent_load_state = None
        self._unread_completed_agent_ids: set[Any] = set()
        self.notices: list[str] = []
        self._ensure_agent_tabs_state()

    def _rescope_agents_to_active_tab(self) -> None:
        self._agents = _scoped_agents_for_owner(self, list(self._agents_query_result))

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        """Fail closed: no strip is mounted in unit tests."""
        raise LookupError("no widget")

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Collect toasts instead of showing them."""
        self.notices.append(str(message))

    def reindex(self, rows: list[Agent]) -> None:
        """Install *rows* as the roster and rebuild the tab index."""
        self._agents_with_children = list(rows)
        self._agents_query_result = list(rows)
        self._agent_tab_index = build_agent_tab_index(list(rows), make_view())


def two_tab_owner() -> TabOwner:
    owner = TabOwner(
        [make_row("a"), make_row("b", tab="sase"), make_row("c", tab="sase")]
    )
    owner.reindex(owner._agents_with_children)
    return owner
