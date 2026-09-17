"""Tests for agents-tab display and content-index refresh paths."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.actions.agents._display_detail_info import AgentInfoDisplayMixin
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_runner_slots import RunnerCapacitySnapshot
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_live_query_engine import agents_history_query_key
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.feature_flags import override_flags

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


class _InfoMetricsHarness(AgentInfoDisplayMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self.current_idx = 0
        self.refresh_interval = 10
        self._agents = agents
        self._unread_completed_agent_ids = set()
        self._agent_search_query = ""
        self._agent_search_query_seeded = False
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key = None
        self._countdown_remaining = 10
        self._agent_info_metrics_cache = None
        self._agent_runner_capacity = RunnerCapacitySnapshot()
        self._agent_panel_index_cache = None
        self._agent_panels_grouped = False

    def _agent_panel_index(self):
        return build_agent_panel_index(self._agents, dismissable_statuses=())


@pytest.fixture(autouse=True)
def _pin_legacy_agent_query_dialect() -> Iterator[None]:
    """sase-zf.2: these tests exercise the legacy agent_query dialect explicitly."""
    with override_flags(agents_unified_query=False):
        yield


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
async def test_capacity_refresh_from_cached_roster_updates_info_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _make_agent(
        status="RUNNING",
        cl_name="runner",
        raw_suffix="20260917120000",
        artifacts_dir="/tmp/projects/demo/artifacts/ace-run/20260917120000",
        pid=100,
        runner_is_live=True,
    )
    waiter = _make_agent(
        status="WAITING",
        cl_name="waiter",
        raw_suffix="20260917120100",
        artifacts_dir="/tmp/projects/demo/artifacts/ace-run/20260917120100",
        pid=101,
        slot_requested_at="2026-09-17T12:01:00-04:00",
        wait_runners=0,
        wait_runners_explicit=False,
    )
    app = FakeAgentApp(query="")
    app.current_tab = "agents"
    app._agents = [running, waiter]
    app._agents_with_children = [running, waiter]
    app._agent_runner_capacity = RunnerCapacitySnapshot()
    app._agents_capacity_generation = 1
    app._agents_capacity_applied_generation = 0
    updates: list[str] = []
    app._update_agents_info_panel = lambda: updates.append("panel")  # type: ignore[method-assign]

    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 1)
    monkeypatch.setattr(
        "sase.core.agent_hold_facade.active_agent_hold_records",
        lambda: [],
    )

    await app._run_agents_capacity_refresh_from_roster(
        generation=1,
        source="test",
    )

    assert app._agent_runner_capacity.effective_limit == 1
    assert app._agent_runner_capacity.slots_in_use == 1
    assert app._agent_runner_capacity.queued_count == 1
    assert updates == ["panel"]


def test_agent_info_metrics_cache_tracks_in_place_status_mutations() -> None:
    agent = _make_agent(status="RUNNING", cl_name="active")
    app = _InfoMetricsHarness([agent])

    first = app._agent_info_metrics()
    agent.status = "DONE"
    second = app._agent_info_metrics()

    assert first[2] == 1
    assert second[2] == 0
    assert second[5] == 1


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


@pytest.mark.asyncio
async def test_async_full_history_discarded_when_query_changes_after_disk_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FakeAgentApp(query="cl:old")
    app._nav_gate = NavigationGate(window_s=0.25)
    app._agents_refresh_pending = False
    app._agents_refresh_pending_source = "unknown"
    app._agents_refresh_pending_full_history = False
    app._agents_refresh_pending_full_history_reason = None
    app._agents_refresh_pending_revalidate_index = False
    app._agents_refresh_pending_prefix_completion = False
    app._agents_refresh_pending_callbacks = []
    app._agents_refresh_scheduled = False
    app._agents_refresh_scheduled_source = "unknown"
    app._agents_refresh_scheduled_full_history = False
    app._agents_refresh_scheduled_full_history_reason = None
    app._agents_refresh_scheduled_revalidate_index = False
    app._agents_refresh_scheduled_prefix_completion = False
    app._agents_refresh_active_source = "unknown"
    app._agents_refresh_active_prefix_completion = False
    app._agents_artifact_delta_scheduled = None
    app._agents_artifact_delta_pending = None
    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0
    app._agents_seen_complete_history = False
    app._agents_complete_history_query_key = None
    app._scheduled_refreshes: list[str] = []
    fired: list[str] = []

    def fake_spawn() -> None:
        app._scheduled_refreshes.append("refresh")

    def fake_load_agents(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        app._agent_search_query = "cl:new"
        return SimpleNamespace(
            all_agents=[_make_agent(cl_name="old")],
            dismissed_from_loader=[],
            load_state=AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="artifact_index",
                used_artifact_index=True,
                history_query_key=agents_history_query_key(
                    "cl:old",
                    use_unified_query=False,
                ),
            ),
        )

    app._spawn_agents_refresh_task = fake_spawn  # type: ignore[method-assign]
    app._external_dismissal_merge_result = lambda _snapshot: None  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
        fake_load_agents,
    )
    monkeypatch.setattr(
        "sase.ace.patch.find_all_patches_cached",
        lambda **_kwargs: [],
    )

    app._schedule_agents_async_refresh(
        full_history=True,
        full_history_reason="manual_full_history_refresh",
        on_complete=lambda: fired.append("complete"),
    )
    await app._run_agents_async_refresh()

    assert app._agents == []
    assert app._agents_seen_complete_history is False
    assert app._agents_complete_history_query_key is None
    assert fired == []
    assert app._agents_refresh_pending_callbacks
    assert app._agents_refresh_scheduled is True
    assert app._agents_refresh_scheduled_full_history is True
    assert (
        app._agents_refresh_scheduled_full_history_reason
        == "manual_full_history_refresh"
    )
