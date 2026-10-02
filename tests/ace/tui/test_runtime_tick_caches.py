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


def _counting_rust(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap the Rust aggregation with a call counter; return the counter."""
    import sase.core.agent_runtime_facade as facade_mod

    calls: list[int] = []
    real_aggregate = facade_mod.aggregate_clan_runtime

    def _counting(members, *, now=None):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real_aggregate(members, now=now)

    monkeypatch.setattr(aggregate_mod, "aggregate_clan_runtime", _counting)
    return calls


def _running_container() -> tuple[object, object]:
    """Return a (parent, child) pair with an active aggregate runtime."""
    from .widgets.agent_list_runtime_helpers import agent

    parent = agent(status="RUNNING", start=datetime(2026, 4, 25, 14, 0, 0))
    child = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 0),
        raw_suffix="20260425140100",
        cl_name="demo.child",
    )
    parent.runtime_children = [child]
    return parent, child


def test_aggregate_result_skips_rust_within_same_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ticks in one wall-clock second share one Rust aggregation."""
    aggregate_mod._aggregate_wires_cache.clear()
    aggregate_mod._aggregate_result_cache.clear()
    calls = _counting_rust(monkeypatch)
    parent, _child = _running_container()
    first = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 14, 1, 0, 100000), {id(parent)}
    )
    second = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 14, 1, 0, 900000), {id(parent)}
    )
    assert first is not None and second is not None
    assert second is first
    assert len(calls) == 1


def test_aggregate_result_settled_reused_across_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settled aggregate never re-runs the Rust aggregation."""
    from .widgets.agent_list_runtime_helpers import agent

    aggregate_mod._aggregate_wires_cache.clear()
    aggregate_mod._aggregate_result_cache.clear()
    calls = _counting_rust(monkeypatch)
    parent = agent(status="DONE", start=datetime(2026, 4, 25, 14, 0, 0))
    child = agent(
        status="DONE",
        start=datetime(2026, 4, 25, 14, 0, 0),
        stop=datetime(2026, 4, 25, 14, 5, 0),
        raw_suffix="20260425140100",
        cl_name="demo.child",
    )
    parent.runtime_children = [child]
    first = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 15, 0, 0), {id(parent)}
    )
    second = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 16, 30, 0), {id(parent)}
    )
    assert first is not None and second is not None
    assert not first.active
    assert second is first
    assert second.elapsed_seconds == 300.0
    assert len(calls) == 1


def test_aggregate_result_hour_rows_skip_within_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hour-plus rows re-aggregate at most once per displayed minute."""
    aggregate_mod._aggregate_wires_cache.clear()
    aggregate_mod._aggregate_result_cache.clear()
    calls = _counting_rust(monkeypatch)
    parent, _child = _running_container()
    parent.start_time = datetime(2026, 4, 25, 12, 0, 0)
    parent.run_start_time = datetime(2026, 4, 25, 12, 0, 0)
    for child in parent.runtime_children:
        child.start_time = datetime(2026, 4, 25, 12, 0, 0)
        child.run_start_time = datetime(2026, 4, 25, 12, 0, 0)
    first = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 14, 5, 0), {id(parent)}
    )
    assert first is not None
    assert first.elapsed_seconds >= 3600
    second = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 14, 5, 30), {id(parent)}
    )
    assert second is first
    third = aggregate_mod._aggregate_runtime(
        parent, datetime(2026, 4, 25, 14, 6, 1), {id(parent)}
    )
    assert third is not first
    assert third is not None
    assert third.elapsed_seconds == first.elapsed_seconds + 61
    assert len(calls) == 2


def test_aggregate_result_recomputes_on_membership_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new member row misses the result cache (union semantics kept)."""
    from .widgets.agent_list_runtime_helpers import agent

    aggregate_mod._aggregate_wires_cache.clear()
    aggregate_mod._aggregate_result_cache.clear()
    calls = _counting_rust(monkeypatch)
    parent, _child = _running_container()
    now = datetime(2026, 4, 25, 14, 1, 0)
    aggregate_mod._aggregate_runtime(parent, now, {id(parent)})
    assert len(calls) == 1
    newcomer = agent(
        status="RUNNING",
        start=datetime(2026, 4, 25, 14, 0, 30),
        raw_suffix="20260425140200",
        cl_name="demo.newcomer",
    )
    parent.runtime_children = [*parent.runtime_children, newcomer]
    aggregate_mod._aggregate_runtime(parent, now, {id(parent)})
    assert len(calls) == 2
