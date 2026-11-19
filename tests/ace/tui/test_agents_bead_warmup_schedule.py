"""Scheduling, coalescing, and candidate-scope coverage for bead warmup."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._loading_bead_warmup import _AgentBeadWarmupCandidates
from sase.ace.tui.models.agent_bead import (
    _BEAD_DISPLAY_CACHE,
    _bead_display_cache_key,
)
from tests.ace.tui._agents_bead_warmup_helpers import (
    FakeApp,
    clear_bead_display_cache,
    make_agent,
)

__all__ = [
    "test_schedule_collapses_to_one_detached_worker",
    "test_schedule_marks_pending_while_running",
    "test_schedule_noop_before_first_load",
    "test_schedule_skips_empty_candidate_scan",
    "test_schedule_spawns_worker_after_first_load",
    "test_warmup_candidates_bound_historical_waiters_and_stranded_projects",
    "test_warmup_candidates_include_expired_cached_bead_candidates",
    "test_warmup_candidates_include_stale_wait_bead_statuses",
    "test_warmup_candidates_only_uncached_bead_candidates",
]


def test_schedule_noop_before_first_load() -> None:
    app = FakeApp()
    app._agents_first_load_done = False

    app._schedule_bead_confirmation_warmup(source="apply")

    assert app._scheduled == []
    assert app._bead_warmup_scan_scheduled is False


@pytest.mark.asyncio
async def test_schedule_spawns_worker_after_first_load() -> None:
    app = FakeApp()
    app._agents = [make_agent()]

    app._schedule_bead_confirmation_warmup(source="apply")

    assert app._bead_warmup_scan_scheduled is True
    assert app._bead_warmup_scan_source == "apply"
    assert len(app._bead_warmup_async_tasks) == 1
    task = next(iter(app._bead_warmup_async_tasks))
    assert task.get_name() == "sase-agents-bead-warmup"
    await task


@pytest.mark.asyncio
async def test_schedule_collapses_to_one_detached_worker() -> None:
    app = FakeApp()
    app._agents = [make_agent()]

    app._schedule_bead_confirmation_warmup(source="apply")
    app._schedule_bead_confirmation_warmup(source="auto_refresh")

    assert len(app._bead_warmup_async_tasks) == 1
    await next(iter(app._bead_warmup_async_tasks))


def test_schedule_marks_pending_while_running() -> None:
    app = FakeApp()
    app._agents = [make_agent()]
    app._bead_warmup_scan_running = True

    app._schedule_bead_confirmation_warmup(source="stranded_resolve")

    assert app._bead_warmup_scan_pending is True
    assert app._scheduled == []


def test_schedule_skips_empty_candidate_scan() -> None:
    app = FakeApp()
    app._agents = []

    app._schedule_bead_confirmation_warmup(source="apply")

    assert app._bead_warmup_scan_scheduled is False
    assert app._bead_warmup_async_tasks == set()


def test_warmup_candidates_only_uncached_bead_candidates() -> None:
    app = FakeApp()
    confirmed = make_agent(agent_name="sase-a.1", cl_name="confirmed", raw_suffix="1")
    missing = make_agent(agent_name="sase-b.2", cl_name="missing", raw_suffix="2")
    cold = make_agent(agent_name="sase-c.3", cl_name="cold", raw_suffix="3")
    ordinary = make_agent(agent_name="reviewer", cl_name="ordinary", raw_suffix="4")
    modern_phase = make_agent(
        agent_name="sase-d.1",
        epic_bead_id="sase-d",
        phase_bead_id="sase-d.1",
        cl_name="modern-phase",
        raw_suffix="5",
    )

    confirmed_key = _bead_display_cache_key(confirmed)
    missing_key = _bead_display_cache_key(missing)
    assert confirmed_key is not None and missing_key is not None
    _BEAD_DISPLAY_CACHE.set(confirmed_key, "sase-a.1 - desc")
    _BEAD_DISPLAY_CACHE.set(missing_key, None)
    # ``cold`` and ``ordinary`` are left uncached; only ``cold`` has a candidate.
    app._agents = [confirmed, missing, cold, ordinary, modern_phase]

    assert app._bead_warmup_candidates() == _AgentBeadWarmupCandidates(
        bead_display_agents=(cold,),
        stranded_projects=("proj",),
    )


def test_warmup_candidates_include_expired_cached_bead_candidates() -> None:
    app = FakeApp()
    expired_confirmed = make_agent(
        agent_name="sase-a.1", cl_name="expired-confirmed", raw_suffix="1"
    )
    expired_missing = make_agent(
        agent_name="sase-b.2", cl_name="expired-missing", raw_suffix="2"
    )
    fresh_confirmed = make_agent(
        agent_name="sase-c.3", cl_name="fresh-confirmed", raw_suffix="3"
    )
    for agent, value in (
        (expired_confirmed, "sase-a.1 - desc"),
        (expired_missing, None),
    ):
        key = _bead_display_cache_key(agent)
        assert key is not None
        _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, value)
    fresh_key = _bead_display_cache_key(fresh_confirmed)
    assert fresh_key is not None
    _BEAD_DISPLAY_CACHE.set(fresh_key, "sase-c.3 - desc")
    app._agents = [expired_confirmed, expired_missing, fresh_confirmed]

    assert app._bead_warmup_candidates() == _AgentBeadWarmupCandidates(
        bead_display_agents=(expired_confirmed, expired_missing),
        stranded_projects=("proj",),
    )


def test_warmup_candidates_include_stale_wait_bead_statuses() -> None:
    app = FakeApp()
    waiter = make_agent(
        agent_name="waiter",
        status="WAITING",
        waiting_for_beads=["sase-1"],
        cl_name="waiter",
        raw_suffix="waiter",
    )
    app._agents = [waiter]

    assert app._bead_warmup_candidates() == _AgentBeadWarmupCandidates(
        wait_bead_status_agents=(waiter,),
        stranded_projects=("proj",),
    )


def test_warmup_candidates_bound_historical_waiters_and_stranded_projects() -> None:
    app = FakeApp()
    app._agents = []
    app._agents_with_children = [
        make_agent(
            agent_name=f"waiter-{index}",
            cl_name=f"waiter-{index}",
            raw_suffix=f"waiter-{index}",
            status="WAITING",
            project_file=f"/tmp/project-{index}/proj.sase",
            waiting_for_beads=[f"sase-{index}"],
        )
        for index in range(80)
    ]
    app._surfaced_bead_warmup_agents = lambda: []  # type: ignore[method-assign]

    first = app._bead_warmup_candidates()
    second = app._bead_warmup_candidates()

    assert len(first.wait_bead_status_agents) == 32
    assert len(second.wait_bead_status_agents) == 32
    assert (
        len(
            {
                agent.identity
                for agent in (
                    *first.wait_bead_status_agents,
                    *second.wait_bead_status_agents,
                )
            }
        )
        == 64
    )
    assert len(first.stranded_projects) <= 4
    assert len(second.stranded_projects) <= 4
    assert first.stranded_scan_more is True
    assert second.stranded_scan_more is True
