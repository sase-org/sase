"""Regression tests for Agents-tab view hints surviving detail refreshes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pytest

from sase.ace.tui.actions.agents import _loading_helpers
from sase.ace.tui.actions.agents._display_detail import DetailMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    AgentHintRender,
    CommitViewSpec,
)
from sase.glossary.read_report import GlossaryReadReportSpec
from sase.ace.tui.widgets.prompt_panel._messages import AgentDetailHeaderEnriched


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feat-hints",
        project_file="/tmp/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 9, 12, 0, 0),
        raw_suffix="20260709120000",
    )


def _unchanged_attempt_history(_agent: Agent) -> bool:
    return False


class _RecordingAgentDetail:
    def __init__(self) -> None:
        self.update_display_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.update_display_immediate_calls: list[
            tuple[tuple[Any, ...], dict[str, Any]]
        ] = []
        self.update_display_with_hints_calls: list[Agent] = []
        self.hint_document_current = False
        # Defaults to "still streaming" (bead sase-l6.4): most enrichment
        # publishes land mid-stream, so a typed hint value should keep
        # suppressing renumbering unless a test opts into the completed case.
        self.header_summary_complete = False
        self.detail_header_summary_complete_calls: list[Agent] = []
        self.show_empty_calls = 0
        self.commit_view = CommitViewSpec(
            short_sha="abc1234",
            sha="abc1234567890",
            repo_name="repo",
            cwd=None,
            subject="commit subject",
            message="commit body",
            diff_path=None,
            is_primary=True,
        )
        self.tool_reports = cast(
            dict[str, SlowToolCallReportSpec],
            {"tool-call-1": object()},
        )
        self.glossary_reports = cast(
            dict[str, GlossaryReadReportSpec],
            {"glossary-1": object()},
        )
        self.hint_render = AgentHintRender(
            file_hints={2: "/tmp/project/file.py"},
            tool_call_reports=self.tool_reports,
            commit_views={3: self.commit_view},
            glossary_reports=self.glossary_reports,
        )

    def update_display(self, *args: Any, **kwargs: Any) -> None:
        self.update_display_calls.append((args, kwargs))

    def update_display_immediate(self, *args: Any, **kwargs: Any) -> None:
        self.update_display_immediate_calls.append((args, kwargs))

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        self.update_display_with_hints_calls.append(agent)
        return self.hint_render

    def hint_document_is_current(self, agent: Agent) -> bool:
        assert agent is not None
        return self.hint_document_current

    def detail_header_summary_complete(self, agent: Agent) -> bool:
        self.detail_header_summary_complete_calls.append(agent)
        return self.header_summary_complete

    def show_empty(self) -> None:
        self.show_empty_calls += 1


class _RecordingFooter:
    pass


class _RecordingDebouncer:
    def __init__(self) -> None:
        self.scheduled: list[Any] = []

    def schedule(self, callback: Any) -> None:
        self.scheduled.append(callback)


class _FakeApp(DetailMixin):
    def __init__(
        self,
        *,
        hint_mode_active: bool = True,
        current_tab: str = "agents",
        hint_input_value: str = "",
    ) -> None:
        self.agent = _agent()
        self.detail = _RecordingAgentDetail()
        self.footer = _RecordingFooter()
        self._agent_detail_debouncer = _RecordingDebouncer()
        self.current_idx = 0
        self.current_attempt_number = None
        self.current_tab = current_tab
        self.refresh_interval = 10
        self._agents = [self.agent]
        self._agents_first_load_done = True
        self._agent_search_query = ""
        self._hint_mode_active = hint_mode_active
        self._hint_mode_hints_for: str | None = None
        self._hint_mappings = {1: "/tmp/project/old.py"}
        self._hint_commit_views = {}
        self._hint_tool_call_reports = cast(
            dict[str, SlowToolCallReportSpec],
            {"old-tool-call": object()},
        )
        self._hint_glossary_reports = cast(
            dict[str, GlossaryReadReportSpec],
            {"old-glossary": object()},
        )
        self.info_updates = 0
        self.footer_updates: list[Agent | None] = []
        self.hint_input = type("_HintInput", (), {"value": hint_input_value})()
        self._widgets: dict[str, Any] = {
            "#agent-detail-panel": self.detail,
            "#keybinding-footer": self.footer,
            "#hint-input": self.hint_input,
        }

    def query_one(self, selector: str, _type: Any = None) -> Any:
        del _type
        return self._widgets[selector]

    def _get_selected_agent(self) -> Agent | None:
        return self.agent

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_footer_update(
        self,
        agent_detail: Any,
        footer_widget: Any,
        current_agent: Agent | None,
    ) -> None:
        del agent_detail, footer_widget
        self.footer_updates.append(current_agent)


@pytest.fixture(autouse=True)
def _no_attempt_history_hydration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _loading_helpers,
        "hydrate_agent_attempt_history",
        _unchanged_attempt_history,
    )


def test_agent_detail_refresh_preserves_active_view_hints() -> None:
    app = _FakeApp(hint_mode_active=True)

    app._apply_agent_detail_update(app.detail, app.footer)  # type: ignore[arg-type]

    assert app.detail.update_display_calls == []
    assert app.detail.update_display_with_hints_calls == [app.agent]
    assert app._hint_mappings == app.detail.hint_render.file_hints
    assert app._hint_commit_views == app.detail.hint_render.commit_views
    assert app._hint_tool_call_reports == app.detail.hint_render.tool_call_reports
    assert app._hint_glossary_reports == app.detail.hint_render.glossary_reports
    assert app.footer_updates == [app.agent]


def test_agent_detail_refresh_skips_current_hint_document() -> None:
    app = _FakeApp(hint_mode_active=True)
    app.detail.hint_document_current = True

    app._apply_agent_detail_update(app.detail, app.footer)  # type: ignore[arg-type]

    assert app.detail.update_display_calls == []
    assert app.detail.update_display_with_hints_calls == []
    assert app._hint_mappings == {1: "/tmp/project/old.py"}
    assert app.footer_updates == [app.agent]


def test_agent_detail_immediate_preserves_active_view_hints() -> None:
    app = _FakeApp(hint_mode_active=True)

    app._apply_agent_detail_immediate()

    assert app.detail.update_display_immediate_calls == []
    assert app.detail.update_display_with_hints_calls == [app.agent]
    assert app._hint_mappings == app.detail.hint_render.file_hints
    assert app._hint_commit_views == app.detail.hint_render.commit_views
    assert app._hint_tool_call_reports == app.detail.hint_render.tool_call_reports
    assert app._hint_glossary_reports == app.detail.hint_render.glossary_reports
    assert app.footer_updates == []


def test_debounced_agent_detail_refresh_preserves_active_view_hints() -> None:
    app = _FakeApp(hint_mode_active=True)

    app._fire_debounced_detail_update()

    assert app.detail.update_display_calls == []
    assert app.detail.update_display_with_hints_calls == [app.agent]
    assert app._hint_mappings == app.detail.hint_render.file_hints
    assert app._hint_commit_views == app.detail.hint_render.commit_views
    assert app._hint_tool_call_reports == app.detail.hint_render.tool_call_reports
    assert app._hint_glossary_reports == app.detail.hint_render.glossary_reports
    assert app.info_updates == 1
    assert app.footer_updates == [app.agent]


def test_agent_detail_refresh_uses_plain_render_when_hint_mode_inactive() -> None:
    app = _FakeApp(hint_mode_active=False)

    app._apply_agent_detail_update(app.detail, app.footer)  # type: ignore[arg-type]

    assert app.detail.update_display_with_hints_calls == []
    assert len(app.detail.update_display_calls) == 1
    assert app._hint_mappings == {1: "/tmp/project/old.py"}
    assert app.footer_updates == [app.agent]


def test_header_enrichment_completion_refreshes_active_view_hints() -> None:
    app = _FakeApp(hint_mode_active=True)

    app.on_agent_detail_header_enriched(AgentDetailHeaderEnriched(app.agent.identity))

    assert app.detail.update_display_with_hints_calls == [app.agent]
    assert app._agent_detail_debouncer.scheduled == []
    assert app._hint_mappings == app.detail.hint_render.file_hints
    assert app._hint_commit_views == app.detail.hint_render.commit_views
    assert app._hint_tool_call_reports == app.detail.hint_render.tool_call_reports
    assert app._hint_glossary_reports == app.detail.hint_render.glossary_reports


def test_unchanged_header_enrichment_skips_current_hint_document() -> None:
    app = _FakeApp(hint_mode_active=True)
    app.detail.hint_document_current = True

    app.on_agent_detail_header_enriched(AgentDetailHeaderEnriched(app.agent.identity))

    assert app.detail.update_display_with_hints_calls == []
    assert app._agent_detail_debouncer.scheduled == []
    assert app._hint_mappings == {1: "/tmp/project/old.py"}


def test_header_enrichment_completion_keeps_typed_hint_numbers_stable() -> None:
    app = _FakeApp(hint_mode_active=True, hint_input_value="2")
    app.detail.header_summary_complete = False

    app.on_agent_detail_header_enriched(AgentDetailHeaderEnriched(app.agent.identity))

    assert app.detail.update_display_with_hints_calls == []
    assert app._agent_detail_debouncer.scheduled == []
    assert app._hint_mappings == {1: "/tmp/project/old.py"}


def test_header_enrichment_completion_keeps_typed_hint_numbers_stable_when_complete() -> (
    None
):
    """A publish that finished the last lane still gets through, even typed."""
    app = _FakeApp(hint_mode_active=True, hint_input_value="2")
    app.detail.header_summary_complete = True

    app.on_agent_detail_header_enriched(AgentDetailHeaderEnriched(app.agent.identity))

    assert app.detail.update_display_with_hints_calls == [app.agent]
    assert app.detail.detail_header_summary_complete_calls == [app.agent]


def test_header_enrichment_completion_uses_plain_refresh_without_hint_mode() -> None:
    app = _FakeApp(hint_mode_active=False)

    app.on_agent_detail_header_enriched(AgentDetailHeaderEnriched(app.agent.identity))

    assert app.detail.update_display_with_hints_calls == []
    assert app._agent_detail_debouncer.scheduled == [app._fire_debounced_detail_update]
