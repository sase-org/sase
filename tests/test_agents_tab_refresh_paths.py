"""Tests for agents-tab display and content-index refresh paths."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


def test_on_tab_finalizer_defers_selected_agent_file_refresh() -> None:
    """Agent-list finalization must not start file/diff work inline."""
    agent = _make_agent(status="RUNNING", cl_name="active")
    app = FakeAgentApp(query="")
    app.current_tab = "agents"
    app._agents = [agent]
    refresh_calls: list[dict[str, object]] = []
    refresh_file_calls = 0

    class _Detail:
        def refresh_current_file(self, _agent: Agent) -> None:
            nonlocal refresh_file_calls
            refresh_file_calls += 1

    def _refresh_agents_display(**kwargs: object) -> None:
        refresh_calls.append(kwargs)

    app._refresh_agents_display = _refresh_agents_display  # type: ignore[method-assign]
    app._get_selected_agent = lambda: agent  # type: ignore[method-assign]
    app.query_one = lambda *_args, **_kwargs: _Detail()  # type: ignore[method-assign]

    app._finalize_agent_list(
        on_agents_tab=True, selected_identity=agent.identity, save_unfiltered=True
    )

    assert refresh_calls == [{"list_changed": True, "defer_detail": True}]
    assert refresh_file_calls == 0


def test_refilter_can_defer_structural_display_refresh() -> None:
    """Navigation reveal can refilter in memory and paint exactly once later."""
    agent = _make_agent(status="RUNNING", cl_name="active")
    app = FakeAgentApp(query="")
    app.current_tab = "agents"
    app._agents_with_children = [agent]
    app._agents = [agent]
    refresh_calls: list[dict[str, object]] = []
    app._refresh_agents_display = (  # type: ignore[method-assign]
        lambda **kwargs: refresh_calls.append(kwargs)
    )

    app._refilter_agents(
        refresh_content_index=False,
        refresh_display=False,
    )

    assert app._agents == [agent]
    assert refresh_calls == []


@pytest.mark.asyncio
async def test_refilter_schedules_background_content_index_refresh(
    tmp_path: Any,
) -> None:
    (tmp_path / "live_reply.md").write_text("BACKGROUND NEEDLE", encoding="utf-8")
    agent = _make_agent(cl_name="metadata_miss", artifacts_dir=str(tmp_path))
    app = FakeAgentApp(query="needle")
    app._agent_content_search_cache = AgentContentSearchCache()
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._refilter_agents()

    assert app._agents == []
    task = app._agent_content_search_refresh_task
    assert task is not None
    await task

    assert app._agent_content_search_index is not None
    assert app._agents == [agent]


@pytest.mark.asyncio
async def test_stale_background_content_index_generation_is_ignored(
    tmp_path: Any,
) -> None:
    (tmp_path / "live_reply.md").write_text("STALE NEEDLE", encoding="utf-8")
    agent = _make_agent(cl_name="metadata_miss", artifacts_dir=str(tmp_path))
    app = FakeAgentApp(query="needle")
    app._agent_content_search_cache = AgentContentSearchCache()
    app._agents_with_children = [agent]
    app._agent_content_search_refresh_generation = 2
    worker_cache = app._agent_content_search_cache.fork()

    await app._run_agent_content_search_index_refresh(
        worker_cache=worker_cache,
        agents=[agent],
        query="needle",
        generation=1,
        source_generation=0,
        source_identities=(agent.identity,),
    )

    assert app._agent_content_search_index is None
    assert app._agents == []
