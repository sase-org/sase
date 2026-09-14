"""Tests for the Agents-tab `V` metadata pager action end to end."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._metadata_pager import AgentMetadataPagerMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.pager.document import PagerDocument
from sase.pager.screen import PagerScreen

from tests.ace.agent_artifact_startup_fixtures import make_agent


class _FakeApp(AgentMetadataPagerMixin):
    def __init__(self, agent: object | None) -> None:
        self.current_tab = "agents"
        self._agent = agent
        self._agents = [agent] if agent is not None else []
        self.pushed_screens: list[PagerScreen] = []
        self._worker_coro: object | None = None

    def _get_selected_agent(self) -> object | None:
        return self._agent

    def run_worker(self, coro: object, **_kwargs: object) -> object:
        self._worker_coro = coro
        return MagicMock()

    def call_from_thread(self, fn: object, *args: object) -> object:
        return fn(*args)  # type: ignore[operator]

    def push_screen(self, screen: object) -> None:
        self.pushed_screens.append(screen)  # type: ignore[arg-type]


def _section_titles(document: PagerDocument) -> list[str]:
    return [section.title for section in document.sections]


async def _run_action(app: _FakeApp) -> None:
    app.action_view_agent_metadata()
    if app._worker_coro is not None:
        await app._worker_coro  # type: ignore[misc]


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_v_on_a_running_agent_pushes_a_metadata_document(_mock: object) -> None:
    agent = make_agent(status="RUNNING")
    agent.model = "opus"
    app = _FakeApp(agent)

    await _run_action(app)

    assert len(app.pushed_screens) == 1
    screen = app.pushed_screens[0]
    assert isinstance(screen, PagerScreen)
    titles = _section_titles(screen.document)
    assert "IDENTITY" in titles
    assert "MODEL" in titles
    assert "TIMELINE" in titles
    content_bodies = [
        section.plain_text
        for section in screen.document.sections
        if section.title == "CONTENT"
    ]
    assert not any("Response:" in body for body in content_bodies)


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_v_on_a_done_agent_shows_response_path(_mock: object) -> None:
    agent = make_agent(status="DONE")
    agent.response_path = "/tmp/response.md"
    app = _FakeApp(agent)

    await _run_action(app)

    screen = app.pushed_screens[0]
    content = next(s for s in screen.document.sections if s.title == "CONTENT")
    assert "Response:" in content.plain_text
    assert "/tmp/response.md" in content.plain_text


async def test_v_is_a_no_op_for_remote_fleet_rows() -> None:
    agent = make_agent(status="RUNNING")
    agent.fleet_origin_alias = "remote-host"
    app = _FakeApp(agent)

    await _run_action(app)

    assert app.pushed_screens == []
    assert app._worker_coro is None


async def test_v_is_a_no_op_with_no_selection() -> None:
    app = _FakeApp(None)

    await _run_action(app)

    assert app.pushed_screens == []
    assert app._worker_coro is None


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_v_on_a_family_container_row_does_not_crash(_mock: object) -> None:
    child = make_agent(cl_name="child", raw_suffix="20250101120500")
    root = make_agent(cl_name="root", raw_suffix="20250101120000")
    root.agent_family = "root"
    root.agent_family_role = "root"
    root.followup_agents = [child]
    app = _FakeApp(root)

    await _run_action(app)

    assert len(app.pushed_screens) == 1
    titles = _section_titles(app.pushed_screens[0].document)
    assert "IDENTITY" in titles


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_v_on_a_clan_container_row_does_not_crash(_mock: object) -> None:
    clan = make_agent(cl_name="clan-row", raw_suffix="20250101120000")
    clan.is_clan_container = True
    clan.agent_clan = "myclan"
    app = _FakeApp(clan)

    await _run_action(app)

    assert len(app.pushed_screens) == 1
    titles = _section_titles(app.pushed_screens[0].document)
    assert "IDENTITY" in titles


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_refresh_provider_looks_up_the_agent_by_identity(_mock: object) -> None:
    agent = make_agent(status="RUNNING")
    app = _FakeApp(agent)

    await _run_action(app)

    screen = app.pushed_screens[0]
    refresh_fn = screen._refresh_document_fn
    assert refresh_fn is not None
    refreshed = refresh_fn()
    assert refreshed is not None
    assert refreshed.title == screen.document.title


@patch(
    "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
    return_value=DetailHeaderSummary(),
)
async def test_refresh_provider_returns_none_when_the_row_is_gone(
    _mock: object,
) -> None:
    agent = make_agent(status="RUNNING")
    app = _FakeApp(agent)

    await _run_action(app)

    screen = app.pushed_screens[0]
    app._agents = []
    refresh_fn = screen._refresh_document_fn
    assert refresh_fn is not None
    assert refresh_fn() is None
