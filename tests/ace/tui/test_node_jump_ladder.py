"""Identity reveal and query-clear coverage for the Node Finder ladder."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.navigation._agent_reveal import AgentRevealFailure
from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.feature_flags import override_flags
from tests.ace.tui.visual._ace_png_snapshot_startup import (
    patch_startup_loaders,
    wait_for_startup,
)

from ._member_jump_navigation_helpers import JumpHarness, make_clan


class _NodeJumpHarness(NodeJumpNavigationMixin, JumpHarness):
    """Production-shaped reveal harness with a query-hidden target."""

    def __init__(self) -> None:
        complete, container = make_clan(2)
        super().__init__(complete, container)
        self.target = container.runtime_children[1]
        self._agent_search_query = "status:FAILED"
        self.commits: list[str] = []
        self.transitions: list[tuple[str, str]] = []
        self.refresh_sources: list[str] = []

    def _try_reveal_agent_row(
        self, identity: tuple[Any, ...]
    ) -> AgentRevealFailure | None:
        if self._agent_search_query:
            return AgentRevealFailure.TARGET_FILTERED
        return super()._try_reveal_agent_row(identity)

    def _record_explicit_agents_query_commit(self, source: str) -> None:
        self.commits.append(source)
        self._agent_search_query = source

    def _record_agents_live_query_transition(
        self, old_source: str, new_source: str
    ) -> None:
        self.transitions.append((old_source, new_source))

    def _schedule_agents_async_refresh(self, *, source: str) -> None:
        self.refresh_sources.append(source)


class _HiddenNodeJumpHarness(NodeJumpNavigationMixin, JumpHarness):
    """Production-shaped I-hidden target with a controllable reload callback."""

    def __init__(self, *, query: str = "") -> None:
        visible = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visible",
            project_file="/tmp/project/project.sase",
            status="RUNNING",
            start_time=datetime(2026, 9, 10, 12, 0, 0),
        )
        self.target = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="hidden",
            project_file="/tmp/project/project.sase",
            status="RUNNING",
            start_time=datetime(2026, 9, 10, 12, 0, 0),
            hidden=True,
        )
        self._visible = visible
        super().__init__([visible], visible)
        self.hide_non_run_agents = True
        self._hideable_agents = [self.target]
        self._agent_search_query = query
        self.refresh_sources: list[str] = []
        self.pending_reload: Any | None = None

    def _refilter_agents(self, **kwargs: object) -> None:
        super()._refilter_agents(**kwargs)
        if not getattr(self, "hide_non_run_agents", False) and getattr(
            self, "_hideable_agents", ()
        ):
            self._agents_with_children = [self._visible, self.target]
            super()._refilter_agents(**kwargs)

    def _schedule_agents_async_refresh(
        self, *, source: str, on_complete: Any | None = None
    ) -> None:
        self.refresh_sources.append(source)
        self.pending_reload = on_complete

    def _show_hidden_agents_for_navigation(self, on_complete: Any) -> None:
        self.hide_non_run_agents = False
        self._refilter_agents()
        self._schedule_agents_async_refresh(source="filter", on_complete=on_complete)

    def finish_reload(self) -> None:
        assert self.pending_reload is not None
        callback = self.pending_reload
        self.pending_reload = None
        callback()


@pytest.mark.parametrize("unified", [False, True])
def test_query_hidden_identity_clears_once_then_reveals(unified: bool) -> None:
    app = _NodeJumpHarness()

    with override_flags(agents_unified_query=unified):
        assert app._jump_to_node_identity(app.target.identity, name="member-1")

    assert app._agent_search_query == ""
    assert app.commits == [""]
    assert app.transitions == ([("status:FAILED", "")] if unified else [])
    assert app.refresh_sources == ["filter"]
    assert app._agents[app.current_idx].identity == app.target.identity
    assert "Cleared Agents query" in app.notifications[-1]
    if unified:
        assert "f then ^ restores it" in app.notifications[-1]


def test_i_hidden_identity_flips_then_reveals() -> None:
    app = _HiddenNodeJumpHarness()

    assert app._jump_to_node_identity(app.target.identity, name="hidden")

    assert app.hide_non_run_agents is False
    assert app.refresh_sources == ["filter"]
    assert "Showing agents hidden by I to reach hidden" in app.notifications[-1]
    app.finish_reload()

    assert app._agents[app.current_idx].identity == app.target.identity


def test_i_hidden_identity_continues_to_the_query_rung() -> None:
    app = _HiddenNodeJumpHarness(query="status:FAILED")
    app.commits: list[str] = []

    def _reveal(identity: tuple[Any, ...]) -> AgentRevealFailure | None:
        if app.hide_non_run_agents:
            return AgentRevealFailure.TARGET_MISSING
        if app._agent_search_query:
            return AgentRevealFailure.TARGET_FILTERED
        return JumpHarness._try_reveal_agent_row(app, identity)

    app._try_reveal_agent_row = _reveal
    app._record_explicit_agents_query_commit = lambda query: (
        app.commits.append(query),
        setattr(app, "_agent_search_query", query),
    )

    assert app._jump_to_node_identity(app.target.identity, name="hidden")
    app.finish_reload()

    assert app.commits == [""]
    assert app._agents[app.current_idx].identity == app.target.identity


def test_i_hidden_identity_cancels_if_selection_moves_during_reload() -> None:
    app = _HiddenNodeJumpHarness()

    assert app._jump_to_node_identity(app.target.identity, name="hidden")
    app.current_tab = "services"
    app.finish_reload()

    assert "Jump to hidden cancelled — you moved" in app.notifications[-1]


async def test_real_ace_page_query_clear_retry_records_the_live_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the ladder against the real app, not only a navigation harness."""
    now = datetime(2026, 9, 10, 12, 0, 0)
    agents = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visible",
            project_file="/tmp/project/project.sase",
            status="RUNNING",
            start_time=now,
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="hidden",
            project_file="/tmp/project/project.sase",
            status="FAILED",
            start_time=now,
        ),
    ]
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        app = page.app
        app._record_explicit_agents_query_commit("status:FAILED")
        app._refilter_agents()
        attempts = 0

        def try_reveal(_identity: tuple[Any, ...]) -> AgentRevealFailure | None:
            nonlocal attempts
            attempts += 1
            return AgentRevealFailure.TARGET_FILTERED if attempts == 1 else None

        monkeypatch.setattr(app, "_try_reveal_agent_row", try_reveal)
        with override_flags(agents_unified_query=True):
            assert app._jump_to_node_identity(agents[0].identity, name="visible")
        await page.pause()

        assert attempts == 2
        assert app._agent_search_query == ""
