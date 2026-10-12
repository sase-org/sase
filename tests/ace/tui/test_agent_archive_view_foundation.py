"""View-foundation tests: flag states, selection seams, refresh ownership.

The beta-off cases prove the Inbox keeps its existing behavior with no new
view exposed. The beta-on cases prove startup is always Inbox, opening the
Archive parks the Inbox, the Archive owns the shared detail panel while
active, pending Inbox work drops across a view switch, hidden Inbox refreshes
never cancel the Archive's debounce, and returning restores and repaints.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import (
    archive_detail_owns_panel,
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    init_agents_archive_view_state,
    _invalidate_agents_detail_ownership,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
)
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.feature_flags import override_flags


def _make_agent(cl_name: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
    )


class _ListWidget:
    def __init__(self) -> None:
        self.id = "agent-list-panel"

    def update_highlight(self, *args: Any, **kwargs: Any) -> None:
        return


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)


class _QueryResult:
    def __init__(self, items: list[_ListWidget]) -> None:
        self._items = items

    def results(self, _type: Any = None) -> Any:
        return iter(self._items)


class _FakeAgentDetail:
    """Stand-in for ``AgentDetail`` that records every paint."""

    def __init__(self) -> None:
        self.immediate_calls: list[tuple[str | None, int | None]] = []
        self.full_calls: list[tuple[str | None, int | None]] = []
        self.tribe_calls: list[tuple[object, bool]] = []
        self.empty_calls = 0
        self.llm_calls_detail_level = 0

    def update_display(
        self,
        agent: Agent,
        *,
        stale_threshold_seconds: int = 10,
        attempt_number: int | None = None,
    ) -> None:
        self.full_calls.append((agent.cl_name, attempt_number))

    def update_display_immediate(
        self, agent: Agent, attempt_number: int | None = None
    ) -> None:
        self.immediate_calls.append((agent.cl_name, attempt_number))

    def show_empty(self) -> None:
        self.empty_calls += 1

    def show_tribe_summary(self, snapshot: object, *, cheap: bool = False) -> None:
        self.tribe_calls.append((snapshot, cheap))

    def is_file_visible(self) -> bool:
        return False

    def is_llm_calls_visible(self) -> bool:
        return False


class _FooterWidget:
    def __init__(self) -> None:
        self.binding_updates = 0

    def update_agent_bindings(self, *args: Any, **kwargs: Any) -> None:
        self.binding_updates += 1


class _Timer:
    def stop(self) -> None:
        return


class _FakeApp(AgentDisplayMixin):
    def __init__(self, *, agents: list[Agent]) -> None:
        self._agents = agents
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self._current_group_key = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents = set()
        self._pending_callback = None
        self.info_updates = 0
        self.highlights = 0
        init_agents_archive_view_state(self)

        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._panel_group = AgentPanelGroup.from_agents(self._agents)

        list_widget = _ListWidget()
        self._container = _Container([list_widget])
        self.detail_widget = _FakeAgentDetail()
        self.footer_widget = _FooterWidget()
        self._widgets = {
            "#agent-detail-panel": self.detail_widget,
            "#keybinding-footer": self.footer_widget,
        }

    def query_one(self, selector: str, _type: Any = None) -> Any:
        return self._widgets[selector]

    def query(self, selector: str) -> Any:
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback: Any) -> Any:
        self._pending_callback = callback
        return _Timer()

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _refresh_panel_highlights(self) -> None:
        self.highlights += 1

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return None

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def _enriched_message(agent: Agent) -> Any:
    stopped: list[bool] = []

    def stop() -> None:
        stopped.append(True)

    message = SimpleNamespace(agent_identity=agent.identity, stop=stop)
    message.stopped = stopped
    return message


def test_flag_off_preserves_inbox_detail() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags():
        outcome = open_agents_archive_view(app)
        assert outcome.status == "disabled"
        assert outcome.view == AGENTS_VIEW_INBOX
        assert not archive_detail_owns_panel(app)

        app._refresh_agents_display_debounced()

    assert app.detail_widget.immediate_calls == [("agent_0", None)]
    assert app.detail_widget.full_calls == []
    assert app._agent_detail_debouncer.is_pending


def test_flag_off_selection_stays_inbox_only() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags():
        selection = get_agents_tab_selection(app)
        assert selection.view == AGENTS_VIEW_INBOX
        assert selection.row_kind == "agent"
        assert selection.agent is not None
        assert selection.read_only is False
        assert archive_read_only_context(app) is None


def test_startup_is_always_inbox() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        state = app._agents_archive_view
        assert state.active_view == AGENTS_VIEW_INBOX
        assert state.generation == 0
        assert state.parked_inbox is None
        assert state.archive.selected_key is None
        assert not archive_detail_owns_panel(app)


def test_open_parks_inbox_and_blocks_detail() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0"), _make_agent("agent_1")])
    app._agent_search_query = "model:opus"
    app.current_idx = 1

    with override_flags(agents_archive_view=True):
        outcome = open_agents_archive_view(app)

        assert outcome.status == "opened"
        assert outcome.view == AGENTS_VIEW_ARCHIVE
        assert archive_detail_owns_panel(app)
        parked = app._agents_archive_view.parked_inbox
        assert parked is not None
        assert parked.committed_query == "model:opus"
        assert parked.scroll == 1

        app._refresh_agents_display_debounced()

        assert app.detail_widget.immediate_calls == []
        assert app.detail_widget.full_calls == []
        assert app.detail_widget.tribe_calls == []
        assert app.footer_widget.binding_updates == 0
        # List chrome still refreshes while hidden, feeding the later pulse.
        assert app.info_updates == 1


def test_pending_debounce_dropped_after_switch() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        app._refresh_agent_focus_detail(render_immediate=False)
        assert app._agent_detail_debouncer.is_pending

        open_agents_archive_view(app)
        app._fire_debounced_detail_update()

        assert app.detail_widget.immediate_calls == []
        assert app.detail_widget.full_calls == []


def test_stale_token_dropped_after_return() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        app._refresh_agent_focus_detail(render_immediate=False)
        open_agents_archive_view(app)
        close_agents_archive_view(app)

        app._fire_debounced_detail_update()

        assert app.detail_widget.full_calls == []


def test_return_to_inbox_restores_and_repaints() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0"), _make_agent("agent_1")])
    app._agent_search_query = "model:opus"
    app.current_idx = 1

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        outcome = close_agents_archive_view(app)

        assert outcome.status == "returned"
        assert outcome.view == AGENTS_VIEW_INBOX
        assert app._agent_search_query == "model:opus"
        assert app.current_idx == 1
        assert not archive_detail_owns_panel(app)

        app._refresh_agents_display_debounced()

    assert app.detail_widget.immediate_calls == [("agent_1", None)]


def test_no_selected_agent_leakage_into_archive() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)

        selection = get_agents_tab_selection(app)
        assert selection.view == AGENTS_VIEW_ARCHIVE
        assert selection.row_kind == "none"
        assert selection.agent is None
        assert selection.archive_key is None
        assert selection.read_only is True
        assert archive_read_only_context(app) is None
        # The parked Inbox agent is still there for live callers only.
        assert app._get_selected_agent() is not None
        assert app._agents == [app._agents[0]]
        assert len(app._agents) == 1

        app._agents_archive_view.archive.selected_key = "bob-cli-5p.4"
        selection = get_agents_tab_selection(app)
        assert selection.row_kind == "agent"
        assert selection.agent is None
        assert selection.archive_key == "bob-cli-5p.4"
        context = archive_read_only_context(app)
        assert context is not None
        assert context.archive_key == "bob-cli-5p.4"
        assert context.read_only is True


def test_async_handlers_drop_while_archive_owns_panel() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])
    agent = app._agents[0]

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)

        message = _enriched_message(agent)
        app.on_agent_detail_header_enriched(message)
        assert not app._agent_detail_debouncer.is_pending
        assert message.stopped == []

        app.on_clan_section_snapshot_loaded(
            SimpleNamespace(agent_identity=agent.identity, stop=lambda: None)
        )
        app.on_tribe_section_snapshot_loaded(
            SimpleNamespace(panel_identity="tribe:x", stop=lambda: None)
        )
        assert not app._agent_detail_debouncer.is_pending
        assert app.detail_widget.full_calls == []


def test_hidden_inbox_refresh_keeps_archive_debounce() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        app._refresh_agent_focus_detail(render_immediate=False)
        assert app._agent_detail_debouncer.is_pending

        open_agents_archive_view(app)
        app._refresh_agents_display_impl(list_changed=False, defer_detail=False)

        assert app._agent_detail_debouncer.is_pending
        assert app.detail_widget.immediate_calls == []
        assert app.detail_widget.full_calls == []
        assert app.footer_widget.binding_updates == 0


def test_hidden_inbox_refresh_repaints_with_flag_off() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags():
        app._refresh_agent_focus_detail(render_immediate=False)
        assert app._agent_detail_debouncer.is_pending

        app._refresh_agents_display_impl(list_changed=False, defer_detail=False)

        assert not app._agent_detail_debouncer.is_pending
        assert app.detail_widget.full_calls == [("agent_0", None)]


def test_invalidate_bumps_generation_for_teardown() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        token = app._agents_archive_view.generation
        app._refresh_agent_focus_detail(render_immediate=False)
        assert app._agents_archive_view.generation == token

        _invalidate_agents_detail_ownership(app)

        assert app._agents_archive_view.generation == token + 1
        app._fire_debounced_detail_update()
        assert app.detail_widget.full_calls == []


def test_explicit_arrival_records_query_and_name() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])
    app._agent_search_query = "model:opus"

    with override_flags(agents_archive_view=True):
        outcome = open_agents_archive_view_with_query(
            app,
            query='in:archive name:"bob-cli-5p.4"',
            agent_name="bob-cli-5p.4",
        )

        assert outcome.status == "opened"
        assert outcome.view == AGENTS_VIEW_ARCHIVE
        assert outcome.committed_query == 'in:archive name:"bob-cli-5p.4"'
        assert outcome.exact_agent_name == "bob-cli-5p.4"
        archive = app._agents_archive_view.archive
        assert archive.committed_query == 'in:archive name:"bob-cli-5p.4"'
        assert archive.pending_exact_name == "bob-cli-5p.4"
        assert archive.selected_key is None
        parked = app._agents_archive_view.parked_inbox
        assert parked is not None
        assert parked.committed_query == "model:opus"


def test_open_close_idempotency() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        first = open_agents_archive_view(app)
        second = open_agents_archive_view(app)
        assert (first.status, second.status) == ("opened", "already_open")
        assert second.generation == first.generation

        returned = close_agents_archive_view(app)
        repeat = close_agents_archive_view(app)
        assert (returned.status, repeat.status) == ("returned", "already_inbox")
