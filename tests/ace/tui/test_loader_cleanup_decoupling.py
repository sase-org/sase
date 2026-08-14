from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.logs import tui_telemetry
from tests._agent_loader_self_heal_helpers import make_agent


class _IdleNavigationGate:
    def is_navigating(self) -> bool:
        return False

    def time_until_idle(self) -> float:
        return 0.0


class _CleanupApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._loader_cleanup_running = False
        self._loader_cleanup_pending = False
        self._loader_cleanup_pending_request: Any = None
        self._loader_cleanup_async_tasks: set[asyncio.Task[None]] = set()
        self._nav_gate = _IdleNavigationGate()
        self.index_maintenance_calls: list[dict[str, Any]] = []

    def set_timer(self, _delay: float, _callback: object) -> None:
        raise AssertionError("idle cleanup must not arm a navigation timer")

    def _schedule_artifact_index_maintenance(self, **kwargs: Any) -> None:
        self.index_maintenance_calls.append(kwargs)


class _LoaderApplyApp(_CleanupApp):
    def __init__(self, dismissed_agent: Agent) -> None:
        super().__init__()
        self.current_tab = "patches"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._agent_search_query = ""
        self._agent_content_search_index = None
        self._agent_status_overrides: dict[Any, str] = {}
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._dismissed_agents = {dismissed_agent.identity}
        self._dismissed_agents_disk_signature = None
        self._dismissed_agents_disk_identities: set[Any] = set()
        self._dismissed_agents_disk_signature_initialized = True
        self._agents_loading = False
        self._agents_refresh_pending = False
        self._agents_refresh_pending_source = "unknown"
        self._agents_refresh_pending_full_history = False
        self._agents_refresh_pending_full_history_reason = None
        self._agents_refresh_pending_callbacks: list[Any] = []
        self._agents_refresh_scheduled = True
        self._agents_refresh_scheduled_source = "test"
        self._agents_refresh_scheduled_full_history = False
        self._agents_refresh_scheduled_full_history_reason = None
        self._agents_refresh_active_source = "unknown"
        self.applied = asyncio.Event()

    def _apply_loaded_agents_prepared(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self.applied.set()


async def _drain_cleanup_procs(app: _CleanupApp) -> None:
    for _ in range(200):
        tasks = tuple(app._loader_cleanup_async_tasks)
        if not app._loader_cleanup_running and not tasks:
            return
        if tasks:
            await asyncio.gather(*tasks)
        else:
            await asyncio.sleep(0)
    raise AssertionError("loader cleanup tasks did not drain")


@pytest.fixture(autouse=True)
def _clear_cleanup_cache() -> Iterator[None]:
    _loading._CLEANED_ARTIFACT_DIRS.clear()
    yield
    _loading._CLEANED_ARTIFACT_DIRS.clear()


@pytest.mark.asyncio
async def test_rows_apply_and_loading_clears_while_cleanup_is_blocked() -> None:
    dismissed_agent = make_agent()
    app = _LoaderApplyApp(dismissed_agent)
    cleanup_started = threading.Event()
    cleanup_release = threading.Event()
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    def blocked_cleanup(*_args: object) -> tuple[set[Any], set[str]]:
        cleanup_started.set()
        cleanup_release.wait(timeout=2.0)
        return set(), set()

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk."
            "_compute_external_dismissal_merge",
            return_value=None,
        ),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            return_value=_AgentDiskLoadResult(
                all_agents=[],
                dismissed_from_loader=[dismissed_agent],
                load_state=load_state,
            ),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
        patch(
            "sase.ace.tui.actions.agents._loading_disk.compute_loader_cleanup",
            side_effect=blocked_cleanup,
        ),
    ):
        refresh_task = asyncio.create_task(app._run_agents_async_refresh())
        await asyncio.wait_for(app.applied.wait(), timeout=1.0)
        await asyncio.wait_for(asyncio.to_thread(cleanup_started.wait, 1.0), 1.5)
        await asyncio.wait_for(refresh_task, timeout=0.5)

        assert app._agents_loading is False
        assert app._loader_cleanup_running is True
        assert cleanup_release.is_set() is False

        cleanup_release.set()
        await _drain_cleanup_procs(app)


@pytest.mark.asyncio
async def test_loader_cleanup_burst_runs_one_trailing_latest_request() -> None:
    app = _CleanupApp()
    agents = [
        make_agent(raw_suffix="20260717080001"),
        make_agent(raw_suffix="20260717080002"),
        make_agent(raw_suffix="20260717080003"),
    ]
    started = threading.Event()
    release = threading.Event()
    calls: list[set[Any]] = []

    def fake_cleanup(
        dismissed_snapshot: set[Any], _dismissed: list[Agent]
    ) -> tuple[set[Any], set[str]]:
        calls.append(set(dismissed_snapshot))
        if len(calls) == 1:
            started.set()
            release.wait(timeout=2.0)
        return set(), set()

    with patch(
        "sase.ace.tui.actions.agents._loading_disk.compute_loader_cleanup",
        side_effect=fake_cleanup,
    ):
        app._schedule_loader_cleanup(
            {agents[0].identity}, [agents[0]], source="one", load_kind="full"
        )
        await asyncio.wait_for(asyncio.to_thread(started.wait, 1.0), 1.5)
        app._schedule_loader_cleanup(
            {agents[1].identity}, [agents[1]], source="two", load_kind="full"
        )
        app._schedule_loader_cleanup(
            {agents[2].identity}, [agents[2]], source="three", load_kind="full"
        )
        release.set()
        await _drain_cleanup_procs(app)

    assert calls == [{agents[0].identity}, {agents[2].identity}]


@pytest.mark.asyncio
async def test_cleanup_applies_orphan_and_cache_bookkeeping_after_await() -> None:
    app = _CleanupApp()
    agent = make_agent()
    app._dismissed_agents = {agent.identity}

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk.compute_loader_cleanup",
            return_value=({agent.identity}, {"/tmp/cleaned"}),
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=True),
    ):
        app._schedule_loader_cleanup(
            {agent.identity}, [agent], source="test", load_kind="full"
        )
        await _drain_cleanup_procs(app)

    assert agent.identity not in app._dismissed_agents
    assert "/tmp/cleaned" in _loading._CLEANED_ARTIFACT_DIRS
    assert app.index_maintenance_calls == [
        {
            "dismissed": set(),
            "force": True,
            "source": "loader_cleanup",
        }
    ]


@pytest.mark.asyncio
async def test_slow_loader_stage_writes_durable_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_agent_loads.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_AGENT_LOADS_JSONL", str(path))
    app = _CleanupApp()

    app._record_slow_loader_stages(
        source="test",
        load_kind="full",
        stages={"disk": 2.25, "prep": 0.1, "apply": 0.01},
        agents=7,
    )
    await _drain_cleanup_procs(app)

    record = json.loads(path.read_text().strip())
    assert record["event"] == "tui_agent_load_slow"
    assert record["slow_stages"] == ["disk"]
    assert record["stages_seconds"]["disk"] == 2.25
    assert record["agents"] == 7


@pytest.mark.asyncio
async def test_slow_loader_stage_threshold_is_env_overridable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_agent_loads.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_AGENT_LOADS_JSONL", str(path))
    monkeypatch.setenv("SASE_TUI_LOADER_LOG_THRESHOLD_SECONDS", "0.05")
    app = _CleanupApp()

    app._record_slow_loader_stages(
        source="test",
        load_kind="full",
        stages={"disk": 0.1, "prep": 0.01},
    )
    await _drain_cleanup_procs(app)

    record = json.loads(path.read_text().strip())
    assert record["threshold_seconds"] == 0.05
    assert record["slow_stages"] == ["disk"]


@pytest.mark.asyncio
async def test_slow_loader_stage_threshold_ignores_invalid_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_agent_loads.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_AGENT_LOADS_JSONL", str(path))
    monkeypatch.setenv("SASE_TUI_LOADER_LOG_THRESHOLD_SECONDS", "not-a-number")
    app = _CleanupApp()

    app._record_slow_loader_stages(
        source="test",
        load_kind="full",
        stages={"disk": 2.25},
    )
    await _drain_cleanup_procs(app)

    record = json.loads(path.read_text().strip())
    assert record["threshold_seconds"] == 2.0
