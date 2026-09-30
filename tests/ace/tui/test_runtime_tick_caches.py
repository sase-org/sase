"""Cached wait-status maps and change-only runtime patching (sase-1d7.10)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui._agent_completion_wait import collect_agent_wait_status_maps
from sase.ace.tui._agent_wait_cache import cached_agent_wait_status_maps_for_app
from sase.ace.tui.actions.agents._roster_generation import (
    bump_tribe_assignment_generation,
    notify_roster_status_mutation,
    set_agents_roster,
)
from sase.ace.tui.models import _agent_time_aggregate as aggregate_mod
from sase.ace.tui.widgets.agent_list import AgentList

from .widgets.agent_list_runtime_helpers import (
    AgentListHarness,
    agent,
    agent_row_index,
)


def _stub_app(roster: list) -> SimpleNamespace:
    app = SimpleNamespace()
    app._agents_roster_generation = 0
    app._agents_tribe_assignment_generation = 0
    app._agents_with_children = list(roster)
    app._agents = list(roster)
    return app


def test_wait_maps_cached_per_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.ace.tui._agent_completion_wait as wait_mod

    builds: list[int] = []
    real_collect = wait_mod.collect_agent_wait_status_maps

    def _counting(roster):  # type: ignore[no-untyped-def]
        builds.append(1)
        return real_collect(roster)

    monkeypatch.setattr(wait_mod, "collect_agent_wait_status_maps", _counting)
    # The cache module imported the function at call time, so patch the
    # attribute it reads as well.
    import sase.ace.tui._agent_wait_cache as cache_mod

    monkeypatch.setattr(
        cache_mod,
        "collect_agent_wait_status_maps",
        _counting,
        raising=False,
    )
    app = _stub_app([agent(cl_name="a"), agent(cl_name="b")])
    first = cached_agent_wait_status_maps_for_app(app)
    second = cached_agent_wait_status_maps_for_app(app)
    assert second is first
    assert len(builds) == 1


def test_wait_maps_invalidate_on_roster_and_tribe_bump() -> None:
    app = _stub_app([agent(cl_name="a")])
    first = cached_agent_wait_status_maps_for_app(app)
    set_agents_roster(app, agents_with_children=list(app._agents_with_children))
    second = cached_agent_wait_status_maps_for_app(app)
    assert second is not first
    third = cached_agent_wait_status_maps_for_app(app)
    assert third is second
    bump_tribe_assignment_generation(app)
    fourth = cached_agent_wait_status_maps_for_app(app)
    assert fourth is not third
    notify_roster_status_mutation(app)
    fifth = cached_agent_wait_status_maps_for_app(app)
    assert fifth is not fourth


def test_aggregate_wires_cached_across_ticks() -> None:
    aggregate_mod._aggregate_wires_cache.clear()
    parent = agent(status="RUNNING", start=datetime(2026, 4, 25, 14, 0, 0))
    child = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        raw_suffix="20260425140100",
        cl_name="demo.child",
    )
    parent.runtime_children = [child]
    now_a = datetime(2026, 4, 25, 14, 1, 0)
    now_b = datetime(2026, 4, 25, 14, 1, 1)
    first = aggregate_mod._aggregate_runtime(parent, now_a, {id(parent)})
    assert first is not None
    cache_size = len(aggregate_mod._aggregate_wires_cache)
    assert cache_size >= 1
    second = aggregate_mod._aggregate_runtime(parent, now_b, {id(parent)})
    assert second is not None
    assert len(aggregate_mod._aggregate_wires_cache) == cache_size
    assert second.elapsed_seconds == first.elapsed_seconds + 1


def test_aggregate_wires_rebuild_when_member_inputs_change() -> None:
    aggregate_mod._aggregate_wires_cache.clear()
    parent = agent(status="RUNNING", start=datetime(2026, 4, 25, 14, 0, 0))
    child = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        raw_suffix="20260425140100",
        cl_name="demo.child",
    )
    parent.runtime_children = [child]
    now = datetime(2026, 4, 25, 14, 1, 0)
    aggregate_mod._aggregate_runtime(parent, now, {id(parent)})
    size_before = len(aggregate_mod._aggregate_wires_cache)
    newcomer = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 30),
        raw_suffix="20260425140200",
        cl_name="demo.newcomer",
    )
    parent.runtime_children = [child, newcomer]
    aggregate_mod._aggregate_runtime(parent, now, {id(parent)})
    assert len(aggregate_mod._aggregate_wires_cache) == size_before + 1


@pytest.mark.asyncio
async def test_patch_active_runtime_rows_skips_unchanged_suffix() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 12, 0, 0)
        running = agent(status="RUNNING", start=start)
        widget.update_list(
            [running],
            current_idx=0,
            now=datetime(2026, 4, 25, 14, 5, 0),
        )
        await pilot.pause()
        # "2h05m" hour granularity: one second later the text is identical.
        assert widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 5, 1)) == 0
        # A full minute later the minute bucket advances.
        assert widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 6, 0)) == 1


@pytest.mark.asyncio
async def test_suffix_only_patch_reuses_left_without_cache_invalidate() -> None:
    app = AgentListHarness()
    async with app.run_test() as pilot:
        widget = app.query_one(AgentList)
        start = datetime(2026, 4, 25, 14, 0, 0)
        running = agent(status="RUNNING", start=start)
        widget.update_list(
            [running],
            current_idx=0,
            now=datetime(2026, 4, 25, 14, 0, 59),
        )
        await pilot.pause()
        row = agent_row_index(widget, 0)
        before = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert before.rstrip().endswith("🏃‍♂️ 59s")
        calls: list[int] = []
        real_invalidate = widget._agent_render_cache.invalidate_agent

        def _counting(identity):  # type: ignore[no-untyped-def]
            calls.append(1)
            return real_invalidate(identity)

        widget._agent_render_cache.invalidate_agent = _counting  # type: ignore[method-assign]
        patched = widget.patch_active_runtime_rows(datetime(2026, 4, 25, 14, 1, 0))
        await pilot.pause()
        after = widget.get_option_at_index(row).prompt.plain  # type: ignore[union-attr]
        assert patched == 1
        assert after.rstrip().endswith("🏃‍♂️ 1m")
        assert calls == []
