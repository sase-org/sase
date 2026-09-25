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
