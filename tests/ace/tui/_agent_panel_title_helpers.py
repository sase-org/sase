"""Shared helpers for agent panel title tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_panels import (
    _PANEL_COUNT_STYLE,
    _PANEL_METRIC_STYLES,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _ListWidget:
    def __init__(self, wid: str) -> None:
        self.id = wid
        self.border_title: Text | str | None = None
        self.highlighted: int | None = None
        self._classes: set[str] = set()

    def update_list(self, *args: Any, **kwargs: Any) -> None:
        return

    def update_highlight(self, *args: Any, **kwargs: Any) -> None:
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)

    def mount(self, widget: _ListWidget) -> None:
        self.children.append(widget)


class _FakeApp(AgentDisplayMixin):
    def __init__(
        self, agents: list[Agent], *, merge_tribe_panels: bool = False
    ) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._detail_update_timer = None
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._agent_panels_grouped = merge_tribe_panels
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            merge_tribe_panels=merge_tribe_panels,
        )

        from sase.ace.tui.actions.agents._display import _panel_widget_id

        self._panel_widgets: dict[str, _ListWidget] = {}
        for idx in range(len(self._panel_group.panel_keys)):
            wid = _panel_widget_id(idx)
            self._panel_widgets[wid] = _ListWidget(wid)
        self._container = _Container(list(self._panel_widgets.values()))

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-list-container":
            return self._container
        wid = selector.lstrip("#")
        return self._panel_widgets[wid]

    def _focus_focused_panel_widget(self) -> None:
        return


def _agent(
    *,
    name: str,
    tribe: str | None = None,
    suffix: str,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    agent_family_parallel: bool = False,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        agent_family_parallel=agent_family_parallel,
    )


def _title_text(widget: _ListWidget) -> Text:
    title = widget.border_title
    assert isinstance(title, Text)
    return title


def _assert_title_span(
    title: Text, *, start: int, end: int, style: str, text: str
) -> None:
    assert title.plain[start:end] == text
    assert any(
        span.start == start and span.end == end and span.style == style
        for span in title.spans
    )


def _assert_title_range_style(title: Text, *, start: int, end: int, style: str) -> None:
    assert title.plain[start:end]
    for position in range(start, end):
        resolved_style = next(
            (
                str(span.style)
                for span in reversed(title.spans)
                if span.start <= position < span.end
            ),
            str(title.style) if title.style else None,
        )
        assert resolved_style == style, (
            f"expected {title.plain[position]!r} at {position} to use {style}; "
            f"got {resolved_style}"
        )


def _assert_title_metric_styles(
    title: Text,
    *,
    neutral_ranges: list[tuple[int, int]],
    metric_digits: list[tuple[int, str]],
) -> None:
    for start, end in neutral_ranges:
        _assert_title_range_style(title, start=start, end=end, style=_PANEL_COUNT_STYLE)
    for position, metric_name in metric_digits:
        _assert_title_range_style(
            title,
            start=position,
            end=position + 1,
            style=_PANEL_METRIC_STYLES[metric_name],
        )
