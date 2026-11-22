"""Roster-keyed memo for the countdown tick's in-flight marker poll.

The poll runs every countdown tick. Its candidate list (in-flight rows,
their resolved artifacts directories, newest-first cap) only changes with
the roster, so an unchanged roster must not re-walk every row or resolve
(``stat()``) artifacts directories on the UI thread each second. The
off-thread marker stats still run every tick, so marker transitions stay as
fresh as before.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading_refresh_polling as polling
from sase.ace.tui.actions.agents._loading_refresh import AgentLoadingRefreshMixin
from sase.ace.tui.actions.agents._roster_generation import (
    notify_roster_status_mutation,
    set_agents_roster,
)

_TICKS = 50


@dataclass
class _CountingAgent:
    identity_key: str
    artifacts_dir: Path | None
    status: str = "RUNNING"
    start_time: datetime | None = None
    raw_suffix: str | None = None
    stop_time: datetime | None = None
    resolve_calls: list[str] = field(default_factory=list)

    @property
    def identity(self) -> tuple[str, str, str | None]:
        return ("CLAUDE", self.identity_key, None)

    def get_artifacts_dir(self) -> str | None:
        self.resolve_calls.append(self.identity_key)
        if self.artifacts_dir is None or not self.artifacts_dir.is_dir():
            return None
        return str(self.artifacts_dir)


class _PollApp(AgentLoadingRefreshMixin):
    """Harness mirroring production: spawn stats, then re-read live keys."""

    def __init__(self) -> None:
        self._agents: list[Any] = []
        self._agents_with_children: list[Any] = []
        self._inflight_poll_marker_cache: dict[Any, Any] = {}
        self._inflight_poll_scheduled = False
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_scheduled = False
        self._agents_artifact_delta_scheduled = None
        self._agents_artifact_delta_pending = None
        self._agents_refresh_debounce_armed = False
        self._scheduled: list[tuple[tuple[Path, ...], str]] = []
        self.polled: list[tuple[Any, ...]] = []

    def _spawn_inflight_agent_transition_poll_task(
        self,
        candidates: tuple[Any, ...],
    ) -> None:
        self.polled.append(candidates)
        results = polling._collect_inflight_poll_results(candidates)
        live = self._inflight_agent_transition_poll_candidates()
        self._apply_inflight_agent_transition_poll_results(
            results,
            {cache_key for cache_key, _, _ in live},
        )
        self._inflight_poll_scheduled = False

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        on_complete: Callable[[], None] | None = None,
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> None:
        del on_complete, deleted_artifact_dirs
        self._scheduled.append((tuple(artifact_dirs), source))


def _agent(tmp_path: Path, key: str, *, status: str = "RUNNING") -> _CountingAgent:
    artifacts_dir = tmp_path / key
    artifacts_dir.mkdir()
    return _CountingAgent(identity_key=key, artifacts_dir=artifacts_dir, status=status)


def _install(app: _PollApp, agents: list[_CountingAgent]) -> None:
    set_agents_roster(app, agents_with_children=list(agents))


def _resolve_calls(agents: list[_CountingAgent]) -> int:
    return sum(len(agent.resolve_calls) for agent in agents)


def _polled_dirs(candidates: tuple[Any, ...]) -> set[Path]:
    return {candidate[2] for candidate in candidates}


def test_unchanged_roster_resolves_artifacts_dirs_once_across_ticks(
    tmp_path: Path,
) -> None:
    """Many unchanged ticks resolve each in-flight dir once, yet still poll."""
    app = _PollApp()
    running = [_agent(tmp_path, f"run-{i}") for i in range(3)]
    done = [_agent(tmp_path, f"done-{i}", status="DONE") for i in range(20)]
    for agent in done:
        agent.stop_time = datetime(2026, 11, 22, 9, 0, 0)
    _install(app, [*running, *done])

    for _ in range(_TICKS):
        app._poll_starting_agent_transitions()

    # One resolution per in-flight row for the whole run (terminal rows are
    # never resolved), versus two per row per tick before the memo.
    assert _resolve_calls(running) == len(running)
    assert _resolve_calls(done) == 0
    # The off-thread marker poll still ran on every tick with the same set.
    assert len(app.polled) == _TICKS
    assert all(
        _polled_dirs(polled) == {a.artifacts_dir for a in running}
        for polled in app.polled
    )


def test_marker_change_on_unchanged_roster_still_refreshes(tmp_path: Path) -> None:
    """Memoized candidates keep the per-tick marker freshness contract."""
    app = _PollApp()
    agent = _agent(tmp_path, "run-a")
    _install(app, [agent])

    for _ in range(5):
        app._poll_starting_agent_transitions()
    assert app._scheduled == []

    assert agent.artifacts_dir is not None
    (agent.artifacts_dir / "done.json").write_text('{"outcome": "completed"}')
    app._poll_starting_agent_transitions()

    assert app._scheduled == [((agent.artifacts_dir,), polling.INFLIGHT_POLL_SOURCE)]
    assert _resolve_calls([agent]) == 1


def test_in_place_status_mutation_recomputes_candidates(tmp_path: Path) -> None:
    """A generation bump drops a settled row and evicts its marker cache."""
    app = _PollApp()
    first = _agent(tmp_path, "run-a")
    second = _agent(tmp_path, "run-b")
    _install(app, [first, second])
    app._poll_starting_agent_transitions()
    assert len(app._inflight_poll_marker_cache) == 2

    second.status = "DONE"
    second.stop_time = datetime(2026, 11, 22, 9, 0, 0)
    notify_roster_status_mutation(app)
    app._poll_starting_agent_transitions()

    assert _polled_dirs(app.polled[-1]) == {first.artifacts_dir}
    assert len(app._inflight_poll_marker_cache) == 1


def test_roster_replacement_adds_new_inflight_row(tmp_path: Path) -> None:
    """A new roster (newly visible row) joins the poll on the next tick."""
    app = _PollApp()
    first = _agent(tmp_path, "run-a")
    _install(app, [first])
    app._poll_starting_agent_transitions()

    newcomer = _agent(tmp_path, "run-b")
    _install(app, [first, newcomer])
    app._poll_starting_agent_transitions()

    assert _polled_dirs(app.polled[-1]) == {first.artifacts_dir, newcomer.artifacts_dir}
    # Resolved once by the tick walk; the post-poll live-key read hits the memo.
    assert len(newcomer.resolve_calls) == 1


def test_missing_artifacts_dir_is_retried_every_tick_until_it_exists(
    tmp_path: Path,
) -> None:
    """Fail open: an unresolved in-flight row is re-resolved each tick."""
    app = _PollApp()
    ready = _agent(tmp_path, "run-ready")
    pending = _CountingAgent(identity_key="run-pending", artifacts_dir=None)
    pending.artifacts_dir = tmp_path / "run-pending"
    _install(app, [ready, pending])

    for _ in range(3):
        app._poll_starting_agent_transitions()
    assert _polled_dirs(app.polled[-1]) == {ready.artifacts_dir}
    assert len(pending.resolve_calls) >= 3
    ready_calls = len(ready.resolve_calls)

    pending.artifacts_dir.mkdir()
    (pending.artifacts_dir / "agent_meta.json").write_text("{}")
    app._poll_starting_agent_transitions()

    assert _polled_dirs(app.polled[-1]) == {ready.artifacts_dir, pending.artifacts_dir}
    # The resolution recomputed the candidates once, then reused them.
    assert len(ready.resolve_calls) == ready_calls + 1
    for _ in range(3):
        app._poll_starting_agent_transitions()
    assert len(ready.resolve_calls) == ready_calls + 1


def test_memo_is_bounded_to_one_roster_state(tmp_path: Path) -> None:
    """The memo replaces itself per roster state; it never accumulates."""
    app = _PollApp()
    for round_index in range(5):
        _install(app, [_agent(tmp_path, f"run-{round_index}")])
        app._poll_starting_agent_transitions()
        memo = app._inflight_poll_candidate_memo
        assert isinstance(memo, polling._InFlightCandidateMemo)
        assert len(memo.candidates) == 1
        assert memo.unresolved == ()


def test_gated_tick_does_not_touch_the_memo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An in-flight agents load still skips the poll (and any roster walk)."""
    app = _PollApp()
    agent = _agent(tmp_path, "run-a")
    _install(app, [agent])
    app._agents_loading = True
    calls: list[int] = []

    def _counting_key(*args: Any) -> tuple[object, ...]:
        del args
        calls.append(1)
        return ()

    monkeypatch.setattr(polling, "_inflight_candidate_memo_key", _counting_key)

    app._poll_starting_agent_transitions()

    assert calls == []
    assert agent.resolve_calls == []
    assert app.polled == []
