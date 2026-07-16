"""Phase-5 two-phase detail update + generation token tests.

The debounced agent-list refresh should update the detail prompt header
immediately (cheap, no workers) and defer file/tools/diff worker
spawns until the j/k burst settles.  Each ``update_display`` /
``update_display_immediate`` / ``update_display_with_hints`` call bumps the
monotonic generation token so debounced workers can drop stale results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets._agent_detail_panels import DetailPanelMode
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel._agent_display_state import AgentHintRender


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _ListWidget:
    def __init__(self, wid: str = "agent-list-panel") -> None:
        self.id = wid
        self._classes: set[str] = set()

    def update_list(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def update_highlight(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return


class _FakeAgentDetail:
    """Stand-in for ``AgentDetail`` that records both phases."""

    def __init__(self) -> None:
        self.immediate_calls: list[tuple[str | None, int | None]] = []
        self.full_calls: list[tuple[str | None, int | None]] = []
        self._agent_detail_generation: int = 0
        self.tools_detail_level = 0

    def update_display(
        self,
        agent: Agent,
        *,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        self._agent_detail_generation += 1
        self.full_calls.append((agent.cl_name, attempt_number))

    def update_display_immediate(
        self, agent: Agent, attempt_number: int | None = None
    ) -> None:
        self._agent_detail_generation += 1
        self.immediate_calls.append((agent.cl_name, attempt_number))

    def show_empty(self) -> None:
        return

    def is_file_visible(self) -> bool:
        return False

    def is_tools_visible(self) -> bool:
        return False


class _FooterWidget:
    def update_agent_bindings(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return


class _GenerationPromptPanel:
    def __init__(self, detail: AgentDetail) -> None:
        self.detail = detail
        self.attempt_view_mode = ""
        self.attempt_pinned_number: int | None = None
        self.render_context: dict[str, Any] = {}
        self.hint_render_generations: list[int] = []

    def set_agent_detail_render_context(self, **context: Any) -> None:
        self.render_context = context

    def update_display(self, _agent: Agent) -> None:
        return

    def update_display_with_hints(self, _agent: Agent) -> AgentHintRender:
        self.hint_render_generations.append(self.detail._agent_detail_generation)
        return AgentHintRender(file_hints={}, tool_call_reports={})


class _SecondaryPanel:
    def update_display(self, *_args: Any, **_kwargs: Any) -> None:
        return


class _Scroll:
    def add_class(self, _name: str) -> None:
        return


def _detail_with_generation_context() -> tuple[AgentDetail, _GenerationPromptPanel]:
    detail = AgentDetail.__new__(AgentDetail)
    detail._current_agent = None
    detail._current_attempt_number = None
    detail._attempt_view_mode = "merged"
    detail._agent_detail_generation = 7
    detail._panel_mode = DetailPanelMode.AUTO
    detail._has_file_content = False
    detail._has_tools_content = False
    detail._update_panel_indicators = lambda: None  # type: ignore[method-assign]
    prompt_panel = _GenerationPromptPanel(detail)
    file_panel = _SecondaryPanel()
    tools_panel = _SecondaryPanel()
    scroll = _Scroll()

    def query_one(selector: str, _type: object) -> object:
        if selector == "#agent-prompt-panel":
            return prompt_panel
        if selector == "#agent-file-panel":
            return file_panel
        if selector == "#agent-tools-panel":
            return tools_panel
        return scroll

    detail.query_one = query_one  # type: ignore[method-assign]
    return detail, prompt_panel


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)


class _QueryResult:
    def __init__(self, items: list[_ListWidget]) -> None:
        self._items = items

    def results(self, _type=None):  # type: ignore[no-untyped-def]
        return iter(self._items)


def _make_agent(cl_name: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
    )


class _FakeApp(AgentDisplayMixin):
    def __init__(self, *, agents: list[Agent]) -> None:
        self._agents = agents
        self._fold_counts = {}
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._countdown_remaining = 0

        from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(self._agents)
        self._pending_callback = None

        list_widget = _ListWidget()
        self._container = _Container([list_widget])
        self.detail_widget = _FakeAgentDetail()
        self._widgets = {
            "#agent-list-panel": list_widget,
            "#agent-list-container": self._container,
            "#agent-detail-panel": self.detail_widget,
            "#keybinding-footer": _FooterWidget(),
        }

    def query_one(self, selector: str, _type=None):  # type: ignore[no-untyped-def]
        return self._widgets[selector]

    def query(self, selector: str):  # type: ignore[no-untyped-def]
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback):  # type: ignore[no-untyped-def]
        self._pending_callback = callback
        return _Timer()

    def _update_agents_info_panel(self) -> None:
        return

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return None

    def _get_selected_agent(self) -> Agent:
        return self._agents[self.current_idx]


def test_debounced_refresh_runs_immediate_phase_only() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    app._refresh_agents_display_debounced()

    assert app.detail_widget.immediate_calls == [("agent_0", None)]
    assert app.detail_widget.full_calls == []
    assert app._agent_detail_debouncer.is_pending


def test_jk_burst_only_full_updates_final_selection() -> None:
    """50-agent j/k burst spawns the heavy detail update for the final selection only."""
    agents = [_make_agent(f"agent_{i}") for i in range(50)]
    app = _FakeApp(agents=agents)
    app._panel_group = type(app._panel_group).from_agents(agents)

    for i in range(50):
        app.current_idx = i
        app._refresh_agents_display_debounced()

    # Each j/k tick takes the cheap immediate path.
    assert len(app.detail_widget.immediate_calls) == 50
    # Heavy path has not fired yet — debouncer is still pending.
    assert app.detail_widget.full_calls == []
    assert app._agent_detail_debouncer.is_pending

    # Simulate the debouncer settling on the final selection.
    app._fire_debounced_detail_update()

    assert len(app.detail_widget.full_calls) == 1
    assert app.detail_widget.full_calls[0] == ("agent_49", None)


def test_generation_token_increments_per_phase() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0"), _make_agent("agent_1")])
    start = app.detail_widget._agent_detail_generation

    app.current_idx = 0
    app._refresh_agents_display_debounced()
    after_first_immediate = app.detail_widget._agent_detail_generation
    assert after_first_immediate == start + 1

    app.current_idx = 1
    app._refresh_agents_display_debounced()
    assert app.detail_widget._agent_detail_generation == start + 2

    app._fire_debounced_detail_update()
    # Full update path also bumps the generation.
    assert app.detail_widget._agent_detail_generation == start + 3


def test_hint_render_advances_generation_and_rejects_prior_render_context() -> None:
    detail, prompt_panel = _detail_with_generation_context()
    agent = _make_agent("agent_0")
    detail._update_display_impl(agent)
    is_current = prompt_panel.render_context["is_current"]

    assert is_current(agent.identity, 7, "merged", None)

    detail.update_display_with_hints(agent)

    assert detail._agent_detail_generation == 8
    assert prompt_panel.hint_render_generations == [8]
    assert not is_current(agent.identity, 7, "merged", None)
    assert prompt_panel.render_context["generation"] == 8
    assert prompt_panel.render_context["is_current"](agent.identity, 8, "merged", None)

    detail.update_display_with_hints(agent)

    assert detail._agent_detail_generation == 9
    assert prompt_panel.hint_render_generations == [8, 9]
