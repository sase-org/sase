"""Shared fakes and factories for agent panel display tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._panel_navigation import AgentPanelNavigationMixin
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus


class _Styles:
    def __init__(self) -> None:
        self.height: Any = None


class _ListWidget:
    def __init__(self, wid: str, option_count: int) -> None:
        self.id = wid
        self.option_count = option_count
        self.styles = _Styles()
        self.border_title: str | None = None
        self._classes: set[str] = set()
        self.update_list_calls = 0
        self.last_agents: list[Agent] = []
        self.last_local_idx: int | None = None
        self.last_tribe_labels: list[str | None] | None = None
        self.last_panel_tribe: str | None = None
        self.last_fold_registry: object | None = None
        self.render_collapsed_calls = 0
        self._panel_collapsed = False

    def update_list(
        self, agents: list[Agent], local_idx: int | None = None, **kwargs: Any
    ) -> None:
        self.update_list_calls += 1
        self.last_agents = agents
        self.last_local_idx = local_idx
        self.last_tribe_labels = kwargs.get("tribe_labels")
        self.last_panel_tribe = kwargs.get("panel_tribe")
        self.last_fold_registry = kwargs.get("fold_registry")
        self._panel_collapsed = False
        self._agents = agents
        grouping_mode = kwargs.get("grouping_mode")
        if grouping_mode is not None:
            self._grouping_mode = grouping_mode

    def render_collapsed(self, *, grouping_mode: Any) -> None:
        self.render_collapsed_calls += 1
        self.option_count = 0
        self._panel_collapsed = True
        self._grouping_mode = grouping_mode

    def update_highlight(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def clear_highlight(self) -> None:
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return

    def remove(self) -> None:
        return


class _Size:
    def __init__(self, height: int) -> None:
        self.height = height


class _Container:
    def __init__(self, children: list[_ListWidget], height: int) -> None:
        self.children = list(children)
        self.size = _Size(height)

    def mount(self, widget: _ListWidget) -> None:
        self.children.append(widget)

    def move_child(
        self,
        child: _ListWidget,
        *,
        before: _ListWidget | int | None = None,
        after: _ListWidget | int | None = None,
    ) -> None:
        if child in self.children:
            self.children.remove(child)
        if before is not None:
            idx = before if isinstance(before, int) else self.children.index(before)
            self.children.insert(idx, child)
        elif after is not None:
            idx = after if isinstance(after, int) else self.children.index(after)
            self.children.insert(idx + 1, child)
        else:
            self.children.append(child)


class _FakeApp(AgentDisplayMixin):
    def __init__(
        self,
        agents: list[Agent],
        option_counts: list[int],
        container_height: int,
        *,
        focused_key: str | None = None,
        agent_panels_grouped: bool = False,
    ) -> None:
        self._agents = agents
        self._fold_counts = {}
        self._agent_search_query = ""
        self._detail_update_timer = None
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._entry_jump_banner_to_hint = {}
        self._entry_jump_panel_to_hint = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._agent_panels_grouped = agent_panels_grouped
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key,
            merge_tribe_panels=agent_panels_grouped,
        )
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_keys: set[str | None] = set()
        self._expanded_panel_focus = False
        self._agent_search_query = ""
        self._session_mounted_panel_identities: dict[
            str | None, set[tuple[AgentType, str, str | None]]
        ] = {}
        self._session_sticky_query = ""

        assert len(option_counts) == len(self._panel_group.panel_keys), (
            "option_counts must match the number of panels"
        )
        self._panel_widgets: dict[str, _ListWidget] = {}
        for key, count in zip(self._panel_group.panel_keys, option_counts, strict=True):
            wid = panel_widget_id_for_key(key)
            self._panel_widgets[wid] = _ListWidget(wid, count)
        self._container = _Container(
            list(self._panel_widgets.values()), container_height
        )

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-list-container":
            return self._container
        wid = selector.lstrip("#")
        return self._panel_widgets[wid]

    def _focus_focused_panel_widget(self) -> None:
        return

    def _resolve_focused_panel(self) -> AgentPanelFocus | None:
        if not self._expanded_panel_focus:
            return None
        return AgentPanelFocus(
            panel_key=self._panel_group.focused_key,
            collapsed=False,
        )


class _InteractiveFakeApp(
    AgentSelectionMixin,
    AgentPanelNavigationMixin,
    _FakeApp,
):
    def _refresh_agent_footer_bindings_only(self) -> None:
        return

    def _refresh_agent_focus_detail(self, **_kwargs: Any) -> None:
        return


def _title_text(widget: _ListWidget) -> Text:
    title = widget.border_title
    assert isinstance(title, Text)
    return title


def _agent(*, name: str, tribe: str | None, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
    )


def _three_panel_agents() -> list[Agent]:
    """3 panels: no_tribe, @apple, @banana."""
    return [
        _agent(name="u1", tribe=None, suffix="t1"),
        _agent(name="a1", tribe="apple", suffix="t2"),
        _agent(name="b1", tribe="banana", suffix="t3"),
    ]


def _pw(app: _FakeApp, key: str | None) -> _ListWidget:
    return app._panel_widgets[panel_widget_id_for_key(key)]


def _two_tribe_assigned_panel_agents() -> list[Agent]:
    """2 panels: @apple, @banana."""
    return [
        _agent(name="a1", tribe="apple", suffix="t1"),
        _agent(name="b1", tribe="banana", suffix="t2"),
    ]
