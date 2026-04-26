"""Per-panel dynamic height regimes for the Agents-tab tag stack.

When the sum of natural panel heights fits the agent-list container,
each panel is sized to exactly fit its content (Fits regime). When it
overflows, panels are weighted by ``option_count + 1`` using fractional
units (Overflow regime).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.css.scalar import Unit

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


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

    def update_list(self, *_args: Any, **_kwargs: Any) -> None:
        self.update_list_calls += 1

    def update_highlight(self, *_args: Any, **_kwargs: Any) -> None:
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
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


class _FakeApp(AgentDisplayMixin):
    def __init__(
        self,
        agents: list[Agent],
        option_counts: list[int],
        container_height: int,
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
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(agents)

        from sase.ace.tui.actions.agents._display import _panel_widget_id

        assert len(option_counts) == len(self._panel_group.panel_keys), (
            "option_counts must match the number of panels"
        )
        self._panel_widgets: dict[str, _ListWidget] = {}
        for idx, count in enumerate(option_counts):
            wid = _panel_widget_id(idx)
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


def _agent(*, name: str, tag: str | None, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=suffix,
    )


def _three_panel_agents() -> list[Agent]:
    """3 panels: untagged, @apple, @banana."""
    return [
        _agent(name="u1", tag=None, suffix="t1"),
        _agent(name="a1", tag="apple", suffix="t2"),
        _agent(name="b1", tag="banana", suffix="t3"),
    ]


def test_fits_regime_assigns_natural_cell_heights() -> None:
    # 3 panels with option counts 2 / 4 / 6 → naturals 4 / 6 / 8 = 18 ≤ 30.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    apple = app._panel_widgets["agent-list-panel-1"]
    banana = app._panel_widgets["agent-list-panel-2"]

    assert main.styles.height.unit is Unit.CELLS
    assert main.styles.height.value == 4.0
    assert apple.styles.height.unit is Unit.CELLS
    assert apple.styles.height.value == 6.0
    assert banana.styles.height.unit is Unit.CELLS
    assert banana.styles.height.value == 8.0


def test_overflow_regime_assigns_proportional_fr_weights() -> None:
    # 3 panels with option counts 1 / 5 / 25 → naturals 3 / 7 / 27 = 37 > 12.
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 5, 25], container_height=12)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    apple = app._panel_widgets["agent-list-panel-1"]
    banana = app._panel_widgets["agent-list-panel-2"]

    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 2.0  # option_count 1 + 1
    assert apple.styles.height.unit is Unit.FRACTION
    assert apple.styles.height.value == 6.0  # option_count 5 + 1
    assert banana.styles.height.unit is Unit.FRACTION
    assert banana.styles.height.value == 26.0  # option_count 25 + 1


def test_single_panel_fills_container_with_natural_height() -> None:
    # Only the untagged main pane; option_count 3 → natural 5 ≤ 40.
    agents = [_agent(name="u1", tag=None, suffix="t1")]
    app = _FakeApp(agents, option_counts=[3], container_height=40)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    assert main.styles.height.unit is Unit.CELLS
    assert main.styles.height.value == 5.0


def test_pre_mount_zero_height_leaves_styles_alone() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=0)

    app._refresh_panel_widgets(jump_hints=None)

    for widget in app._panel_widgets.values():
        assert widget.styles.height is None


def test_reapply_does_not_rebuild_option_lists() -> None:
    """Resize path re-runs height math without calling ``update_list``."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[2, 4, 6], container_height=30)

    app._refresh_panel_widgets(jump_hints=None)
    rebuilds_after_initial = {
        wid: w.update_list_calls for wid, w in app._panel_widgets.items()
    }

    # Simulate a layout cycle that shrinks the container, then re-run only
    # the height computation (no option-list rebuild).
    app._container.size = _Size(height=12)
    widgets: Any = list(app._panel_widgets.values())
    app._apply_panel_heights(app._container, widgets)

    # No additional update_list calls — only heights changed.
    for wid, prior in rebuilds_after_initial.items():
        assert app._panel_widgets[wid].update_list_calls == prior

    # Heights flipped to the overflow regime.
    main = app._panel_widgets["agent-list-panel"]
    assert main.styles.height.unit is Unit.FRACTION
    assert main.styles.height.value == 3.0  # option_count 2 + 1
