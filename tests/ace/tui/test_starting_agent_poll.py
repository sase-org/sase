"""Countdown-tick STARTING-transition poll (starting_to_running_row_latency).

The poll runs once per countdown tick and stat()s ``agent_meta.json`` and
``waiting.json`` for each STARTING agent. When either marker lands or
changes, the poll schedules one exact artifact-delta reconcile so the row
catches up within ~1 s even when the inotify watcher misses the marker write.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_refresh import AgentLoadingRefreshMixin


@dataclass
class _FakeAgent:
    identity_key: str
    artifacts_dir: str | None

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
        self._panel_index = _FakePanelIndex(hidden_starting_indices=[])
        self._starting_poll_meta_cache = {}
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


def test_steady_state_no_starting_agents_is_noop() -> None:
    """No STARTING agents → no stats, no refresh requests across N ticks."""
    app = _PollApp()
    # No agents, no STARTING indices → nothing to poll.
    for _ in range(5):
        app._poll_starting_agent_transitions()

    assert app._timer_calls == []
    assert app._starting_poll_meta_cache == {}


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
    assert app._scheduled[0][1] == ((artifacts_dir,), "starting_poll")

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
    assert app._scheduled[0][1] == ((artifacts_dir,), "starting_poll")


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
    assert app._scheduled[0][1][1] == "starting_poll"


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
    assert app._starting_poll_meta_cache[agent.identity] == (  # type: ignore[index]
        None,
        None,
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
    assert app._starting_poll_meta_cache[agent.identity] == (  # type: ignore[index]
        None,
        None,
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
    assert agent.identity in app._starting_poll_meta_cache

    # Agent leaves STARTING (or disappears) — index empties.
    app._panel_index = _FakePanelIndex(hidden_starting_indices=[])

    app._poll_starting_agent_transitions()
    assert app._starting_poll_meta_cache == {}, (
        "cache must shrink when no STARTING agent remains"
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
    assert app._starting_poll_meta_cache == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
