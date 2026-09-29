"""Tribe panel flicker: debounced refresh and cheap placeholder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.agent_detail import AgentDetail


def _make_agent(cl_name: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
    )


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _ListWidget:
    def __init__(self, wid: str = "agent-list-panel") -> None:
        self.id = wid
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

    def clear_highlight(self) -> None:
        return


class _FakeAgentDetail:
    """Stand-in for AgentDetail with a complete-document predicate."""

    def __init__(self, complete_identity: object | None = None) -> None:
        self.immediate_calls: list[tuple[str | None, int | None]] = []
        self.full_calls: list[tuple[str | None, int | None]] = []
        self._agent_detail_generation: int = 0
        self.llm_calls_detail_level = 0
        self.tribe_calls: list[tuple[object, bool]] = []
        self._complete_identity = complete_identity

    def shows_complete_tribe_document(self, identity: object | None) -> bool:
        return identity is not None and identity == self._complete_identity

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

    def show_tribe_summary(self, snapshot: object, *, cheap: bool = False) -> None:
        self._agent_detail_generation += 1
        self.tribe_calls.append((snapshot, cheap))

    def is_file_visible(self) -> bool:
        return False

    def is_llm_calls_visible(self) -> bool:
        return False


class _FooterWidget:
    def update_agent_bindings(self, *args: Any, **kwargs: Any) -> None:
        return


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)


class _QueryResult:
    def __init__(self, items: list[_ListWidget]) -> None:
        self._items = items

    def results(self, _type: Any = None) -> Any:
        return iter(self._items)


class _FakeApp(AgentDisplayMixin):
    def __init__(self, *, agents: list[Agent]) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
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

    def query_one(self, selector: str, _type: Any = None) -> Any:
        return self._widgets[selector]

    def query(self, selector: str) -> Any:
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback: Any) -> Any:
        self._pending_callback = callback
        return _Timer()

    def _update_agents_info_panel(self) -> None:
        return

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return None

    def _get_selected_agent(self) -> Agent:
        return self._agents[self.current_idx]


class _SummaryApp(AgentSelectionMixin, _FakeApp):
    def __init__(self, *, agents: list[Agent]) -> None:
        super().__init__(agents=agents)
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._collapsed_panel_keys = {"collapsed"}
        for agent in self._agents:
            agent.tribe = "collapsed"
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key="collapsed",
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        wid = panel_widget_id_for_key("collapsed")
        list_widget = _ListWidget(wid)
        self._container = _Container([list_widget])
        self._widgets["#agent-list-container"] = self._container
        self._widgets[f"#{wid}"] = list_widget


def test_same_tribe_refresh_skips_cheap_placeholder() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    focus = app._resolve_focused_panel()
    assert focus is not None
    app.detail_widget._complete_identity = focus.container_identity

    app._refresh_agents_display_debounced()

    assert app.detail_widget.tribe_calls == []
    assert app.detail_widget.immediate_calls == []
    assert app.detail_widget.full_calls == []
    assert app._agent_detail_debouncer.is_pending


def test_different_tribe_still_gets_cheap_placeholder() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app.detail_widget._complete_identity = ("panel", "other-tribe")

    app._refresh_agents_display_debounced()

    assert len(app.detail_widget.tribe_calls) == 1
    assert app.detail_widget.tribe_calls[0][1] is True
    assert app._agent_detail_debouncer.is_pending


def test_fire_debounced_defers_while_prompt_input_active() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app._prompt_input_active = lambda: True  # type: ignore[attr-defined]

    app._fire_debounced_detail_update()

    assert app.detail_widget.tribe_calls == []
    assert app._agent_detail_debouncer.is_pending

    app._prompt_input_active = lambda: False  # type: ignore[attr-defined]
    app._fire_debounced_detail_update()

    assert len(app.detail_widget.tribe_calls) == 1
    assert app.detail_widget.tribe_calls[0][1] is False


def test_refresh_tribe_summary_only_defers_while_prompt_input_active() -> None:
    agents = [_make_agent("agent_0"), _make_agent("agent_1")]
    app = _SummaryApp(agents=agents)
    app._prompt_input_active = lambda: True  # type: ignore[attr-defined]

    assert app._refresh_tribe_summary_only() is True
    assert app.detail_widget.tribe_calls == []
    assert app._agent_detail_debouncer.is_pending


async def test_shows_complete_tribe_document_lifecycle() -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    class _LifecycleApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    agent = _make_agent("agent_0")
    snapshot = build_agent_tribe_summary_snapshot(
        "collapsed", [agent], panel_collapsed=True
    )
    app = _LifecycleApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=True)
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=False)
        await pilot.pause()
        assert detail.shows_complete_tribe_document(snapshot.container_identity) is True
        assert detail.shows_complete_tribe_document(("panel", "other")) is False

        detail.show_empty()
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )

        detail.show_tribe_summary(snapshot, cheap=False)
        await pilot.pause()
        assert detail.shows_complete_tribe_document(snapshot.container_identity) is True
        detail.update_display(agent)
        await pilot.pause()
        assert (
            detail.shows_complete_tribe_document(snapshot.container_identity) is False
        )
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert prompt is not None
