"""Worker ownership isolation tests for the Agents tab graph."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    agent_session_root,
    clan_container,
    clan_graph,
    delta_load_state,
    row_observation,
    row_prefix,
    unrelated_delta,
)
from tests._agents_tab_query_helpers import FakeAgentApp


@contextmanager
def _pause_runtime_clear(
    monkeypatch: pytest.MonkeyPatch,
    *,
    error: BaseException | None = None,
) -> Iterator[tuple[threading.Event, threading.Event]]:
    started = threading.Event()
    release = threading.Event()
    from sase.ace.tui.models import _agent_ordering

    real_clear = _agent_ordering._clear_runtime_children

    def pausing_clear(*args: Any, **kwargs: Any) -> None:
        real_clear(*args, **kwargs)
        started.set()
        if not release.wait(timeout=5.0):
            raise TimeoutError("normalization barrier was not released")
        if error is not None:
            raise error

    monkeypatch.setattr(_agent_ordering, "_clear_runtime_children", pausing_clear)
    try:
        yield started, release
    finally:
        release.set()


def _run_worker(
    live: list[Agent],
    incoming: list[Agent],
    started: threading.Event,
) -> tuple[threading.Thread, list[Any], list[Exception]]:
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=delta_load_state(),
    )
    result: list[Any] = []
    failed: list[Exception] = []

    def worker() -> None:
        try:
            result.append(
                prepare_loaded_agents_worker_boundary(
                    incoming,
                    [],
                    set(),
                    False,
                    snapshot,
                )
            )
        except Exception as exc:
            failed.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=5.0)
    return thread, result, failed


def test_worker_pause_does_not_clear_live_clan_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    assert "🎭" in prefix and "🤖" in prefix

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_observation(container) == before
        assert row_prefix(container) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert row_observation(container) == before
        assert row_prefix(container) == prefix
        prepared = clan_container(result[0].fold.unfiltered_agents)
        assert prepared is not container
        assert row_prefix(prepared) == prefix
        assert ordered_row_providers(prepared) == ("claude", "codex")


def test_worker_pause_does_not_clear_live_agent_session_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = agent_session_graph()
    root = agent_session_root(live)
    before = row_observation(root)
    prefix = row_prefix(root)
    assert root.is_agent_session_container_row
    assert "🎭" in prefix and "🤖" in prefix

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_observation(root) == before
        assert row_prefix(root) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert row_observation(root) == before
        prepared = agent_session_root(result[0].fold.unfiltered_agents)
        assert prepared is not root
        assert prepared.is_agent_session_container_row
        assert row_prefix(prepared) == prefix


def test_worker_exception_does_not_damage_live_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    boom = RuntimeError("normalize failed")

    with _pause_runtime_clear(monkeypatch, error=boom) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        assert row_prefix(container) == prefix
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert result == []
        assert failed and "normalize failed" in str(failed[0])
        assert row_observation(container) == before
        assert row_prefix(container) == prefix


def test_abandoned_worker_thread_cannot_mutate_live_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the await does not stop the thread; isolation still holds."""
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)

    with _pause_runtime_clear(monkeypatch) as (started, release):
        thread, result, failed = _run_worker(live, [unrelated_delta()], started)
        # Simulate asyncio.to_thread cancellation: drop the waiter, thread continues.
        assert row_observation(container) == before
        release.set()
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert failed == []
        assert result
        assert row_observation(container) == before
        assert row_prefix(container) == prefix
