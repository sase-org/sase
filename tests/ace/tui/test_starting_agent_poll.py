"""Countdown-tick in-flight marker poll (starting_to_running_row_latency).

The poll runs once per countdown tick and stat()s marker files for each
in-flight agent. When a marker lands or changes, the poll schedules one exact
artifact-delta reconcile so the row catches up within ~1 s even when the
inotify watcher misses the marker write.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading_refresh_polling as polling
from sase.ace.tui.actions.agents._loading_refresh import AgentLoadingRefreshMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index


@dataclass
class _FakeAgent:
    identity_key: str
    artifacts_dir: str | None
    status: str = "STARTING"
    start_time: datetime | None = None
    raw_suffix: str | None = None
    stop_time: datetime | None = None

    @property
    def identity(self) -> tuple[str, str, str | None]:
        return ("CLAUDE", self.identity_key, None)

    def get_artifacts_dir(self) -> str | None:
        return self.artifacts_dir


@dataclass
class _FakePanelIndex:
    hidden_starting_indices: list[int]


class _PollApp(AgentLoadingRefreshMixin):
    """Minimal harness exercising _poll_starting_agent_transitions."""

    def __init__(self) -> None:
        self._agents = []  # type: ignore[assignment]
        self._agents_with_children = []  # type: ignore[assignment]
        self._panel_index = _FakePanelIndex(hidden_starting_indices=[])
        self._inflight_poll_marker_cache = {}
        self._inflight_poll_scheduled = False
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_scheduled = False
        self._agents_artifact_delta_scheduled = None
        self._agents_artifact_delta_pending = None
        self._agents_refresh_debounce_armed = False
        self._timer_calls: list[tuple[float, Callable[[], Any]]] = []
        self._scheduled: list[Any] = []

    def _agent_panel_index(self) -> _FakePanelIndex:
        return self._panel_index

    def _spawn_inflight_agent_transition_poll_task(
        self,
        candidates: tuple[Any, ...],
    ) -> None:
        results = polling._collect_inflight_poll_results(candidates)
        self._apply_inflight_agent_transition_poll_results(
            results,
            {cache_key for cache_key, _, _ in candidates},
        )
        self._inflight_poll_scheduled = False

    def _spawn_agent_artifact_delta_refresh_task(
        self,
        request: Any,
    ) -> None:
        self._scheduled.append(
            (
                self._run_agent_artifact_delta_refresh,
                (tuple(request.artifact_dirs), request.source),
            )
        )

    def set_timer(self, delay: float, callback: Callable[[], Any]) -> None:
        self._timer_calls.append((delay, callback))


def _write_marker(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _cache_key(
    agent: _FakeAgent,
    artifacts_dir: Path,
) -> tuple[tuple[str, str, str | None], str]:
    return (agent.identity, str(artifacts_dir))


def _empty_marker_state() -> tuple[None, ...]:
    return tuple(None for _ in polling._INFLIGHT_POLL_MARKERS)


def test_steady_state_no_starting_agents_is_noop() -> None:
    """No STARTING agents → no stats, no refresh requests across N ticks."""
    app = _PollApp()
    # No agents, no STARTING indices → nothing to poll.
    for _ in range(5):
        app._poll_starting_agent_transitions()

    assert app._timer_calls == []
    assert app._inflight_poll_marker_cache == {}


def test_single_starting_agent_transition_fires_one_refresh(tmp_path: Path) -> None:
    """A STARTING agent whose meta mtime advances triggers exact deltas."""
    artifacts_dir = tmp_path / "starting-agent"
    meta_path = artifacts_dir / "agent_meta.json"
    _write_marker(meta_path, "{}")

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-a", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    # First tick: file already exists. The harness treats this as the
    # "watcher missed CREATE" appearance path and nudges a refresh.
    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1, (
        "first-observation with present meta should nudge once"
    )
    assert app._scheduled[0][1] == ((artifacts_dir,), "inflight_poll")

    # Subsequent tick without changes: cache hit, no new refresh.
    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1

    # Bump mtime to simulate the run_started_at write.
    st = os.stat(meta_path)
    new_ns = st.st_mtime_ns + 1_000_000_000
    os.utime(meta_path, ns=(new_ns, new_ns))

    scheduled_count_before = len(app._scheduled)

    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == scheduled_count_before, (
        "mtime change before the first task starts should merge into it"
    )
    assert app._scheduled[0][1] == ((artifacts_dir,), "inflight_poll")


def test_fan_out_of_five_transitions_coalesces_to_one_refresh(
    tmp_path: Path,
) -> None:
    """Five STARTING agents transitioning in the same tick → one refresh."""
    app = _PollApp()
    indices: list[int] = []
    for i in range(5):
        ad = tmp_path / f"agent-{i}"
        waiting = ad / "waiting.json"
        _write_marker(waiting, '{"waiting_for": ["parent"]}')
        agent = _FakeAgent(identity_key=f"cl-{i}", artifacts_dir=str(ad))
        app._agents.append(agent)  # type: ignore[arg-type]
        indices.append(i)
    app._panel_index = _FakePanelIndex(hidden_starting_indices=indices)

    app._poll_starting_agent_transitions()
    # First-observation marker presence for all 5 in one tick should
    # schedule one exact delta batch.
    assert len(app._scheduled) == 1
    assert len(app._scheduled[0][1][0]) == 5
    assert app._scheduled[0][1][1] == "inflight_poll"


def test_meta_file_appearance_fires_refresh(tmp_path: Path) -> None:
    """A STARTING agent whose meta is absent then appears triggers a refresh."""
    artifacts_dir = tmp_path / "late-agent"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-late", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    # Tick 1: meta does not exist yet. No nudge (nothing to flip).
    app._poll_starting_agent_transitions()
    assert app._timer_calls == []
    assert app._inflight_poll_marker_cache[_cache_key(agent, artifacts_dir)] == (
        _empty_marker_state()
    )

    # Tick 2: meta lands.
    _write_marker(meta_path, "{}")
    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1, "file appearance should schedule one delta"


def test_waiting_marker_appearance_fires_refresh(tmp_path: Path) -> None:
    """A STARTING agent whose waiting marker appears triggers a refresh."""
    artifacts_dir = tmp_path / "late-waiting-agent"
    artifacts_dir.mkdir()
    waiting_path = artifacts_dir / "waiting.json"

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-waiting", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    app._poll_starting_agent_transitions()
    assert app._timer_calls == []
    assert app._inflight_poll_marker_cache[_cache_key(agent, artifacts_dir)] == (
        _empty_marker_state()
    )

    _write_marker(waiting_path, '{"waiting_for": ["parent"]}')
    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1, "waiting marker appearance should refresh"


def test_waiting_marker_present_on_first_observation_fires_refresh(
    tmp_path: Path,
) -> None:
    """A pre-existing waiting marker triggers the missed-CREATE path."""
    artifacts_dir = tmp_path / "waiting-agent"
    waiting_path = artifacts_dir / "waiting.json"
    _write_marker(waiting_path, '{"waiting_for": ["parent"]}')

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-waiting-now", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1, (
        "first-observation with present waiting marker should nudge once"
    )


def test_unchanged_marker_signature_does_not_rearm_after_debounce(
    tmp_path: Path,
) -> None:
    """Unchanged marker signatures do not arm repeated timers."""
    artifacts_dir = tmp_path / "unchanged-waiting-agent"
    waiting_path = artifacts_dir / "waiting.json"
    _write_marker(waiting_path, '{"waiting_for": ["parent"]}')

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-unchanged", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1

    scheduled_count_before = len(app._scheduled)

    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == scheduled_count_before


def test_stuck_starting_agent_does_not_grow_cache(tmp_path: Path) -> None:
    """STARTING agent that vanishes is evicted; cache stays bounded."""
    artifacts_dir = tmp_path / "dead-agent"
    artifacts_dir.mkdir()

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-dead", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    # Tick once to populate the cache with absent marker signatures.
    app._poll_starting_agent_transitions()
    assert _cache_key(agent, artifacts_dir) in app._inflight_poll_marker_cache

    # Agent leaves the loaded roster entirely.
    app._agents = []  # type: ignore[assignment]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[])

    app._poll_starting_agent_transitions()
    assert app._inflight_poll_marker_cache == {}, (
        "cache must shrink when no STARTING agent remains"
    )


def test_old_starting_agent_stays_a_real_index_polling_candidate(
    tmp_path: Path,
) -> None:
    """An old STARTING row remains eligible for the marker poll.

    ``hidden_starting_indices`` no longer depends on how old the row's
    ``start_time`` is (regression coverage for the removed grace window):
    a real ``AgentPanelIndex`` built from an old STARTING agent still hides
    it, and the poll still nudges a refresh for it exactly as it would for
    a fresh claim.
    """
    real_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl-old",
        project_file="/r/p/p.sase",
        status="STARTING",
        start_time=datetime(2020, 1, 1, 0, 0, 0),
        agent_name="old-starting",
        raw_suffix="old-starting",
    )
    real_index = build_agent_panel_index([real_agent], dismissable_statuses=set())
    assert real_index.hidden_starting_indices == [0]

    artifacts_dir = tmp_path / "old-starting-agent"
    meta_path = artifacts_dir / "agent_meta.json"
    _write_marker(meta_path, "{}")

    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-old", artifacts_dir=str(artifacts_dir))
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(
        hidden_starting_indices=real_index.hidden_starting_indices
    )

    app._poll_starting_agent_transitions()
    assert len(app._scheduled) == 1, (
        "an old STARTING row must still be polled for its real transition"
    )


def test_agent_without_artifacts_dir_is_skipped() -> None:
    """An agent with no artifacts dir doesn't crash or fire a refresh."""
    app = _PollApp()
    agent = _FakeAgent(identity_key="cl-noart", artifacts_dir=None)
    app._agents = [agent]  # type: ignore[list-item]
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[0])

    app._poll_starting_agent_transitions()
    assert app._scheduled == []
    # No entry added since we skipped before recording state.
    assert app._inflight_poll_marker_cache == {}


def test_running_done_marker_present_on_first_observation_fires_refresh(
    tmp_path: Path,
) -> None:
    """A stale RUNNING row with an already-written done marker refreshes."""
    artifacts_dir = tmp_path / "running-agent"
    _write_marker(artifacts_dir / "done.json", '{"outcome": "completed"}')

    app = _PollApp()
    agent = _FakeAgent(
        identity_key="cl-running",
        artifacts_dir=str(artifacts_dir),
        status="RUNNING",
    )
    app._agents = [agent]  # type: ignore[list-item]

    app._poll_starting_agent_transitions()

    assert len(app._scheduled) == 1
    assert app._scheduled[0][1] == ((artifacts_dir,), "inflight_poll")


def test_running_done_marker_appearance_fires_refresh(tmp_path: Path) -> None:
    """RUNNING→DONE marker appearance reaches the exact delta path."""
    artifacts_dir = tmp_path / "running-to-done"
    artifacts_dir.mkdir()

    app = _PollApp()
    agent = _FakeAgent(
        identity_key="cl-running-done",
        artifacts_dir=str(artifacts_dir),
        status="RUNNING",
    )
    app._agents = [agent]  # type: ignore[list-item]

    app._poll_starting_agent_transitions()
    assert app._scheduled == []

    _write_marker(artifacts_dir / "done.json", '{"outcome": "completed"}')
    app._poll_starting_agent_transitions()

    assert len(app._scheduled) == 1
    assert app._scheduled[0][1] == ((artifacts_dir,), "inflight_poll")


def test_waiting_marker_removal_for_waiting_agent_fires_refresh(
    tmp_path: Path,
) -> None:
    """WAITING rows stay watched so a missed waiting.json removal converges."""
    artifacts_dir = tmp_path / "waiting-to-running"
    waiting_path = artifacts_dir / "waiting.json"
    _write_marker(waiting_path, '{"waiting_for": ["dep"]}')

    app = _PollApp()
    agent = _FakeAgent(
        identity_key="cl-waiting-removal",
        artifacts_dir=str(artifacts_dir),
        status="WAITING",
    )
    app._agents = [agent]  # type: ignore[list-item]

    app._poll_starting_agent_transitions()
    assert app._scheduled == [], "matching waiting marker should only seed baseline"

    waiting_path.unlink()
    app._poll_starting_agent_transitions()

    assert len(app._scheduled) == 1
    assert app._scheduled[0][1] == ((artifacts_dir,), "inflight_poll")


def test_terminal_agents_do_zero_stat_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No in-flight candidates means the poll never stats marker paths."""
    artifacts_dir = tmp_path / "done-agent"
    artifacts_dir.mkdir()
    app = _PollApp()
    app._agents = [
        _FakeAgent(
            identity_key="cl-done",
            artifacts_dir=str(artifacts_dir),
            status="DONE",
        )
    ]  # type: ignore[list-item]
    stat_calls = 0
    original_marker_signature = polling._marker_signature

    def _counting_marker_signature(path: Path) -> tuple[int, int] | None:
        nonlocal stat_calls
        stat_calls += 1
        return original_marker_signature(path)

    monkeypatch.setattr(polling, "_marker_signature", _counting_marker_signature)

    app._poll_starting_agent_transitions()

    assert stat_calls == 0
    assert app._scheduled == []
    assert app._inflight_poll_marker_cache == {}


def test_inflight_poll_stat_count_is_capped_newest_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The poll stats only the capped newest in-flight artifact dirs."""
    monkeypatch.setattr(polling, "MAX_LIVE_AGENT_WATCHES", 2)
    app = _PollApp()
    agents: list[_FakeAgent] = []
    for hour in (10, 11, 12):
        artifacts_dir = tmp_path / f"agent-{hour}"
        artifacts_dir.mkdir()
        agents.append(
            _FakeAgent(
                identity_key=f"cl-{hour}",
                artifacts_dir=str(artifacts_dir),
                status="RUNNING",
                start_time=datetime(2026, 9, 17, hour, 0, 0),
                raw_suffix=f"agent-{hour}",
            )
        )
    app._agents = agents  # type: ignore[assignment]
    stat_paths: list[Path] = []
    original_marker_signature = polling._marker_signature

    def _counting_marker_signature(path: Path) -> tuple[int, int] | None:
        stat_paths.append(path)
        return original_marker_signature(path)

    monkeypatch.setattr(polling, "_marker_signature", _counting_marker_signature)

    app._poll_starting_agent_transitions()

    assert len(stat_paths) == 2 * len(polling._INFLIGHT_POLL_MARKERS)
    stat_dirs = {path.parent for path in stat_paths}
    assert stat_dirs == {tmp_path / "agent-11", tmp_path / "agent-12"}
    assert app._scheduled == []


def test_inflight_poll_skips_while_agents_load_is_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The poll does not contend with an active agents load."""
    artifacts_dir = tmp_path / "loading-agent"
    _write_marker(artifacts_dir / "done.json", '{"outcome": "completed"}')
    app = _PollApp()
    app._agents_loading = True
    app._agents = [
        _FakeAgent(
            identity_key="cl-loading",
            artifacts_dir=str(artifacts_dir),
            status="RUNNING",
        )
    ]  # type: ignore[list-item]
    stat_calls = 0
    original_marker_signature = polling._marker_signature

    def _counting_marker_signature(path: Path) -> tuple[int, int] | None:
        nonlocal stat_calls
        stat_calls += 1
        return original_marker_signature(path)

    monkeypatch.setattr(polling, "_marker_signature", _counting_marker_signature)

    app._poll_starting_agent_transitions()

    assert stat_calls == 0
    assert app._scheduled == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
