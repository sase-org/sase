"""Detail-ownership regressions (child-epic phase ``detail-ownership``).

Every test pins one defect from the phase scope: Inbox debounced detail must
repaint after an Archive round trip, hidden Inbox paths must not disturb the
Archive's pending hydration on the shared debouncer, controller-moved Archive
selections must repaint, hydration must drop while the pulse is focused, the
empty-state path must clear Main panels, live ticks must stand down for
archived agents, and retained partial replies must be labeled partial.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_column import (
    column_runtime,
    refresh_column,
)
from sase.ace.tui.actions.agents._archive_reader import (
    _hydration_is_current,
    arm_archive_detail_hydration,
)
from sase.ace.tui.actions.agents._archive_view import (
    close_agents_archive_view,
    init_agents_archive_view_state,
    open_agents_archive_view,
)
from sase.ace.tui.actions.agents._display_diff import (
    build_agent_display_diff,
    panel_rebuild_scope,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.ace.tui.models.agent_archive_reader import mark_agent_archive_read_only
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.widgets._agent_detail_deck_refresh import (
    AgentDetailDeckRefreshMixin,
)
from sase.ace.tui.widgets.decks.final.view import FinalDeckView
from sase.ace.tui.widgets.decks.tool_runs.widget_live import ToolRunsLiveMixin
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    ColumnHarness,
    light_row,
)
from tests.ace.tui.test_agent_archive_view_foundation import _FakeApp, _make_agent
from tests.ace.tui.widgets._agent_display_helpers import (
    FakePromptPanel,
    make_agent,
    plain_of,
)


class _CountingFakeApp(_FakeApp):
    """Foundation fake that counts shared-debouncer schedules."""

    def __init__(self, *, agents: list[Agent]) -> None:
        super().__init__(agents=agents)
        self.schedules: list[Any] = []
        self.onboarding_calls = 0
        debouncer = self._agent_detail_debouncer
        original_schedule = debouncer.schedule

        def _counting_schedule(callback: Any) -> None:
            self.schedules.append(callback)
            original_schedule(callback)

        debouncer.schedule = _counting_schedule  # type: ignore[method-assign]
        from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry

        self._group_fold_registry = AgentGroupFoldRegistry()

    def _reapply_panel_heights(self) -> None:
        return

    def _sync_agents_onboarding(self, **kwargs: Any) -> bool:
        self.onboarding_calls += 1
        return False


def test_inbox_debounced_update_repaints_after_archive_round_trip() -> None:
    app = _FakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        arm_archive_detail_hydration(app)
        close_agents_archive_view(app)

        app._refresh_agents_display_debounced()
        app._fire_debounced_detail_update()

        assert app.detail_widget.full_calls == [("agent_0", None)]


def test_hidden_focus_refresh_preserves_archive_hydration() -> None:
    app = _CountingFakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        arm_archive_detail_hydration(app)
        assert len(app.schedules) == 1

        app._refresh_agent_focus_detail(render_immediate=True)

        assert len(app.schedules) == 1
        assert app._agent_detail_debouncer.is_pending


def test_hidden_focus_defer_never_steals_archive_ownership() -> None:
    app = _CountingFakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        arm_archive_detail_hydration(app)
        assert len(app.schedules) == 1

        app._refresh_agent_focus_detail(render_immediate=False)

        assert len(app.schedules) == 1
        token = app._agents_detail_scheduled_owner
        assert token is not None
        assert token.view == AGENTS_VIEW_ARCHIVE


def test_incremental_defer_skips_inbox_work_while_archive_owns_panel() -> None:
    from sase.ace.tui.actions.agents._loading import DISMISSABLE_STATUSES

    app = _CountingFakeApp(agents=[_make_agent("agent_0")])

    with override_flags(agents_archive_view=True):
        open_agents_archive_view(app)
        arm_archive_detail_hydration(app)
        schedules_before = len(app.schedules)
        assert schedules_before == 1

        agents = list(app._agents)
        diff = build_agent_display_diff(agents, agents)
        index = build_agent_panel_index(
            agents,
            dismissable_statuses=DISMISSABLE_STATUSES,
            merge_tribe_panels=False,
        )
        scope = panel_rebuild_scope(
            diff,
            agents,
            agents,
            previous_index=index,
            next_index=index,
            by_status=False,
        )
        handled = app._try_refresh_agents_display_incremental_impl(
            list(agents),
            diff=diff,
            scope=scope,
            defer_detail=True,
            merge_tribe_panels=False,
        )

        assert handled is True
        assert len(app.schedules) == schedules_before
        assert app.onboarding_calls == 0
        assert app.detail_widget.full_calls == []


async def test_controller_moved_selection_repaints_archive_detail() -> None:
    rows = [light_row("t00"), light_row("t01")]
    harness = ColumnHarness(rows)
    with override_flags(agents_archive_view=True):
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()
        assert harness.widget.last_items, "the warm corpus must yield list rows"

        # The initial install scheduled detail for the first key; forget it.
        harness.owner._agent_detail_debouncer.callbacks.clear()
        first_key = harness.archive.selected_key
        other_keys = [item.key for item in harness.widget.last_items if item.row]
        other = next(key for key in other_keys if key != first_key)

        # The controller moves the cursor without scheduling (exact-name
        # reveal / drift fallback / committed-query change); the column
        # refresh must notice the detail was last scheduled for another key.
        harness.archive.selected_key = other
        refresh_column(harness.owner)

        assert harness.archive.selected_key == other
        assert len(harness.owner._agent_detail_debouncer.callbacks) == 1
        assert column_runtime(harness.owner).last_detail_key == other


def test_pulse_focus_drops_pending_archive_hydration() -> None:
    owner: Any = SimpleNamespace()
    init_agents_archive_view_state(owner)

    with override_flags(agents_archive_view=True):
        owner._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
        owner._agents_archive_view.archive.selected_key = "u.m@t00"
        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST
        assert _hydration_is_current(owner, "u.m@t00", 0) is True

        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_PULSE
        assert _hydration_is_current(owner, "u.m@t00", 0) is False


class _DeckStub(AgentDetailDeckRefreshMixin):
    """Minimal host proving ``_deck_show_empty`` pushes an empty Main doc."""

    def __init__(self) -> None:
        self._agent_detail_generation = 0
        self._current_agent: Any = object()
        self._current_tribe_identity = None
        self._tribe_document_complete = True
        self._current_attempt_number = 1
        self.main_docs: list[tuple[Any, Any, Any]] = []
        self.source_emptied = 0

    def _deck_source_panel(self) -> Any:
        stub = self

        class _Source:
            def show_empty(self) -> None:
                stub.source_emptied += 1

        return _Source()

    @property
    def deck_area(self) -> Any:
        raise LookupError("no deck area mounted")

    def _on_main_document(
        self, content: object, partial: bool, digest: str | None
    ) -> None:
        self.main_docs.append((content, partial, digest))


def test_deck_show_empty_clears_stuck_main_card() -> None:
    stub = _DeckStub()
    stub._deck_show_empty()

    assert stub.source_emptied == 1
    assert stub._current_agent is None
    assert stub.main_docs == [("", False, None)]


def _executing_agent() -> Agent:
    agent = make_agent(status="RUNNING")
    agent.finalizer_status = {"phase": "executing"}
    return agent


def test_final_live_tick_stands_down_for_archived_agent() -> None:
    view = FinalDeckView.__new__(FinalDeckView)

    live = _executing_agent()
    view._live_agent = live
    assert view._live_subject_active() is True

    view._live_agent = mark_agent_archive_read_only(_executing_agent())
    assert view._live_subject_active() is False


def _live_tool_run_row() -> Any:
    return SimpleNamespace(state="running", verdict=None)


class _StopRecorder:
    def __init__(self) -> None:
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


def _archived_tool_runs_view() -> Any:
    view = ToolRunsLiveMixin.__new__(ToolRunsLiveMixin)
    view._live_timer = None
    view._live_rows = (_live_tool_run_row(),)
    view._current_agent = mark_agent_archive_read_only(make_agent(status="RUNNING"))
    view._current_worker = None
    return view


def test_tool_runs_live_tick_never_starts_for_archived_agent() -> None:
    view = _archived_tool_runs_view()
    started: list[Any] = []
    view.set_interval = lambda *args, **kwargs: started.append(args) or _StopRecorder()  # type: ignore[method-assign]

    view._sync_live_timer()

    assert started == []
    assert view._live_timer is None


def test_tool_runs_live_tick_stops_for_archived_agent() -> None:
    view = _archived_tool_runs_view()
    timer = _StopRecorder()
    view._live_timer = timer

    view._on_live_timer()

    assert timer.stops == 1
    assert view._live_timer is None


def test_archived_partial_reply_is_labeled_partial(tmp_path: Any) -> None:
    from pathlib import Path

    artifacts = Path(str(tmp_path)) / "run-artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text("Launch from @src/raw.py")
    (artifacts / "01_prompt.md").write_text("Expanded prompt body\n")
    (artifacts / "live_reply.md").write_text("partial hello")
    agent = make_agent(status="RUNNING", artifacts_dir=str(artifacts))
    assert agent.get_response_content() is None
    assert agent.get_live_reply_content() == "partial hello"
    mark_agent_archive_read_only(agent)

    panel = FakePromptPanel()
    panel.update_display(agent)

    assert "AGENT CHAT · partial" in plain_of(panel.captured[-1])


def test_completed_reply_is_not_labeled_partial(tmp_path: Any) -> None:
    from pathlib import Path

    artifacts = Path(str(tmp_path)) / "done-artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text("Launch from @src/raw.py")
    (artifacts / "01_prompt.md").write_text("Expanded prompt body\n")
    (artifacts / "response.md").write_text("Final response body\n")
    agent = make_agent(
        status="DONE",
        artifacts_dir=str(artifacts),
        response_path=str(artifacts / "response.md"),
    )
    assert agent.get_response_content() == "Final response body\n"

    panel = FakePromptPanel()
    panel.update_display(agent)

    plain = plain_of(panel.captured[-1])
    assert "AGENT CHAT" in plain
    assert "partial" not in plain
