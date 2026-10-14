"""Tests for app-level link subject cache helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions import link_subject as link_subject_actions
from sase.ace.tui.actions.link_subject import LinkSubjectMixin
from sase.ace.tui.relations.link_index import LinkChip, LinkIndex
from sase.ace.tui.relations.link_subject import LinkSubject
from sase.core.artifact_entry_target import ArtifactEntryTarget


def _chip() -> LinkChip:
    return LinkChip(
        relation="implements",
        label="implements",
        directed=True,
        this_is_source=True,
        neighbor_ref="bead:sase-uv.2",
        neighbor_target=ArtifactEntryTarget("beads", ("sase", "task", "sase-uv.2")),
        accent="#D787FF",
        icon="*",
        why="",
        origin="manual",
        uses=1,
        created_by="test",
        created_at="2026-08-27T00:00:00Z",
        writable=True,
    )


class _AvailabilityApp(LinkSubjectMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = (
            SimpleNamespace(agent_name="agent-a", identity=("agent-a",)),
            SimpleNamespace(agent_name="agent-b", identity=("agent-b",)),
        )
        self._link_index = LinkIndex(
            by_ref={"agent:agent-a": (_chip(),)},
            targets_by_ref={},
            source_key=("test",),
        )
        self._link_index_errors = ()
        self._link_index_loading = False
        self._link_index_pending = False
        self._link_index_generation = 1
        self._link_subject_cache = None
        self._link_follow_available_cache = None
        self._link_rail_refresh_scheduled = False
        self.scheduled_sources: list[str] = []

    def _get_selected_agent(self) -> object | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _schedule_link_index_refresh(self, *, source: str) -> None:
        self.scheduled_sources.append(source)


def test_link_follow_availability_recomputes_only_on_selection_or_index_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _AvailabilityApp()
    selected_calls: list[int] = []

    def _selected(app_obj: _AvailabilityApp) -> LinkSubject | None:
        selected_calls.append(app_obj.current_idx)
        agent = app_obj._get_selected_agent()
        if agent is None:
            return None
        name = str(getattr(agent, "agent_name", ""))
        return LinkSubject(
            ref=f"agent:{name}",
            target=ArtifactEntryTarget("agents", (name,)),
            accent="#0062FF",
            icon="*",
        )

    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _selected)

    assert app.link_follow_available_for_selection() is True
    assert app.link_follow_available_for_selection() is True
    assert selected_calls == [0]

    app.current_idx = 1
    assert app.link_follow_available_for_selection() is False
    assert selected_calls == [0, 1]

    app._link_index_generation += 1
    assert app.link_follow_available_for_selection() is False
    assert selected_calls == [0, 1, 1]


def test_link_subject_cache_shared_by_availability_edges_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _AvailabilityApp()
    selected_calls: list[int] = []

    def _selected(app_obj: _AvailabilityApp) -> LinkSubject:
        selected_calls.append(app_obj.current_idx)
        return LinkSubject(
            ref="agent:agent-a",
            target=ArtifactEntryTarget("agents", ("agent-a",)),
            accent="#0062FF",
            icon="*",
        )

    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _selected)

    assert app.link_follow_available_for_selection() is True
    assert len(app.link_edges_for_selection()) == 1
    assert app.link_subject_for_selection() is not None
    assert selected_calls == [0]


class _AsyncLinkApp(LinkSubjectMixin):
    def __init__(self, index: LinkIndex) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = (
            SimpleNamespace(agent_name="agent-a", identity=("agent-a",)),
            SimpleNamespace(agent_name="agent-b", identity=("agent-b",)),
        )
        self._link_index = index
        self._link_index_errors = ()
        self._link_index_loading = False
        self._link_index_pending = False
        self._link_index_generation = 1
        self._link_subject_cache = None
        self._link_follow_available_cache = None
        self._link_chip_requests = set()
        self._link_rail_refresh_scheduled = False
        self._link_rail_tasks: set[asyncio.Task[Any]] = set()
        self.rail_refreshed = asyncio.Event()
        self.refresh_count = 0

    def _get_selected_agent(self) -> object | None:
        return self._agents[self.current_idx]

    def refresh_link_rail(self) -> None:
        self.refresh_count += 1
        self.rail_refreshed.set()


def _native_chip_wire(ref: str) -> dict[str, object]:
    neighbor = "bead:from-a" if ref == "agent:agent-a" else "bead:from-b"
    return {
        "relation": "related",
        "label": "related",
        "directed": False,
        "this_is_source": True,
        "neighbor_ref": neighbor,
        "neighbor_kind": "bead",
        "neighbor_target": None,
        "why": ref,
        "origin": "manual",
        "uses": 1,
        "created_by": "test",
        "created_at": "2026-10-13T00:00:00Z",
        "writable": True,
    }


def _app_subject(app: _AsyncLinkApp) -> LinkSubject | None:
    agent = app._get_selected_agent()
    if agent is None:
        return None
    name = str(agent.agent_name)
    return LinkSubject(
        ref=f"agent:{name}",
        target=ArtifactEntryTarget("agents", (name,)),
        accent="#0062FF",
        icon="*",
    )


@pytest.mark.asyncio
async def test_cold_chip_lookup_runs_on_worker_and_selection_race_keeps_refs_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    index = LinkIndex(
        by_ref=_ChipMapping(object(), (("__external__", "#FF5F5F", "•"),)),
        targets_by_ref={},
        source_key=("test",),
    )
    app = _AsyncLinkApp(index)
    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _app_subject)
    ui_thread = threading.get_ident()
    a_started = threading.Event()
    a_release = threading.Event()
    query_threads: dict[str, int] = {}
    query_lock = threading.Lock()

    def query(_handle: object, ref: str) -> list[dict[str, object]]:
        with query_lock:
            query_threads[ref] = threading.get_ident()
        if ref == "agent:agent-a":
            a_started.set()
            assert a_release.wait(timeout=10)
        return [_native_chip_wire(ref)]

    monkeypatch.setattr(index_facade, "index_chips", query)

    assert app.link_edges_for_selection() == ()
    assert await asyncio.to_thread(a_started.wait, 10)
    assert query_threads["agent:agent-a"] != ui_thread

    app.current_idx = 1
    assert app.link_edges_for_selection() == ()
    await asyncio.wait_for(app.rail_refreshed.wait(), timeout=10)
    chips_b = app.link_edges_for_selection()
    assert len(chips_b) == 1
    assert chips_b[0].why == "agent:agent-b"
    assert query_threads["agent:agent-b"] != ui_thread

    a_release.set()
    await asyncio.gather(*tuple(app._link_rail_tasks), return_exceptions=True)
    assert app.link_edges_for_selection()[0].why == "agent:agent-b"
    assert app._link_follow_available_cache == (
        app._link_follow_available_cache_key(),
        True,
    )


@pytest.mark.asyncio
async def test_chip_query_failure_spawn_failure_and_teardown_release_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    index = LinkIndex(
        by_ref=_ChipMapping(object(), (("__external__", "#FF5F5F", "•"),)),
        targets_by_ref={},
        source_key=("test",),
    )
    app = _AsyncLinkApp(index)
    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _app_subject)
    calls = 0

    def fail_once(_handle: object, ref: str) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("query failed")
        return [_native_chip_wire(ref)]

    monkeypatch.setattr(index_facade, "index_chips", fail_once)
    with monkeypatch.context() as patcher:

        def no_spawn(_owner: object, coro: object, **_kwargs: object) -> None:
            coro.close()  # type: ignore[attr-defined]
            return None

        patcher.setattr(link_subject_actions, "spawn_pump_free_task", no_spawn)
        assert app.link_edges_for_selection() == ()
        assert app._link_chip_requests == set()

    assert app.link_edges_for_selection() == ()
    await asyncio.gather(*tuple(app._link_rail_tasks), return_exceptions=True)
    assert app._link_chip_requests == set()
    assert app.link_edges_for_selection() == ()
    await asyncio.wait_for(app.rail_refreshed.wait(), timeout=10)
    assert app.link_edges_for_selection()[0].why == "agent:agent-a"
    assert calls == 2

    # A blocked query is cancelled like the app's teardown path. Its pending
    # guard is removed even though the worker thread finishes independently.
    fresh = LinkIndex(
        by_ref=_ChipMapping(object(), (("__external__", "#FF5F5F", "•"),)),
        targets_by_ref={},
        source_key=("fresh",),
    )
    app._link_index = fresh
    app._link_index_generation += 1
    started = threading.Event()
    release = threading.Event()

    def blocked(_handle: object, ref: str) -> list[dict[str, object]]:
        started.set()
        assert release.wait(timeout=10)
        return [_native_chip_wire(ref)]

    monkeypatch.setattr(index_facade, "index_chips", blocked)
    assert app.link_edges_for_selection() == ()
    assert await asyncio.to_thread(started.wait, 10)
    tasks = tuple(app._link_rail_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert app._link_chip_requests == set()
    release.set()


@pytest.mark.asyncio
async def test_old_chip_result_is_discarded_after_index_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.relations.link_index import _ChipMapping

    import sase.core.artifact_link_index_facade as index_facade

    index = LinkIndex(
        by_ref=_ChipMapping(object(), (("__external__", "#FF5F5F", "•"),)),
        targets_by_ref={},
        source_key=("old",),
    )
    app = _AsyncLinkApp(index)
    monkeypatch.setattr(link_subject_actions, "selected_link_subject", _app_subject)
    started = threading.Event()
    release = threading.Event()

    def blocked(_handle: object, ref: str) -> list[dict[str, object]]:
        started.set()
        assert release.wait(timeout=10)
        return [_native_chip_wire(ref)]

    monkeypatch.setattr(index_facade, "index_chips", blocked)
    assert app.link_edges_for_selection() == ()
    assert await asyncio.to_thread(started.wait, 10)
    app._link_index = LinkIndex(
        by_ref={"agent:agent-a": (_chip(),)},
        targets_by_ref={},
        source_key=("new",),
    )
    app._link_index_generation += 1
    release.set()
    await asyncio.gather(*tuple(app._link_rail_tasks), return_exceptions=True)
    assert app.refresh_count == 0
    assert app._link_chip_requests == set()


class _RailRefreshApp(LinkSubjectMixin):
    def __init__(self) -> None:
        self._link_rail_refresh_scheduled = False
        self.callbacks: list[Callable[[], None]] = []
        self.refreshed = 0

    def call_after_refresh(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def _refresh_link_rail_now(self) -> None:
        self._link_rail_refresh_scheduled = False
        self.refreshed += 1


def test_refresh_link_rail_coalesces_repeated_requests_in_one_tick() -> None:
    app = _RailRefreshApp()

    app.refresh_link_rail()
    app.refresh_link_rail()
    app.refresh_link_rail()

    assert len(app.callbacks) == 1
    assert app.refreshed == 0
    callback = app.callbacks.pop()
    callback()
    assert app.refreshed == 1

    app.refresh_link_rail()
    assert len(app.callbacks) == 1
