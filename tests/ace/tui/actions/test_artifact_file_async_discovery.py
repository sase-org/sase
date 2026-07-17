"""Tests for off-UI-thread artifact-file discovery."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._panel_artifact_files import (
    AgentPanelArtifactFileMixin,
)


class _DiscoveryAgent:
    """Minimal Agent stand-in for the artifact-cache key + discovery path."""

    def __init__(
        self,
        artifacts_dir: Path,
        *,
        identity: tuple[Any, ...] = ("run", "feature", "20260514100000"),
        status: str = "RUNNING",
    ) -> None:
        self.identity = identity
        self.status = status
        self.diff_path: str | None = None
        self.response_path: str | None = None
        self.extra_files: list[str] = []
        self._artifacts_dir = artifacts_dir

    def get_artifacts_dir(self) -> str:
        return str(self._artifacts_dir)


class _DiscoveryApp(AgentPanelArtifactFileMixin):
    """Light shim hosting just what the discovery helpers need."""

    def __init__(self, selected: _DiscoveryAgent | None) -> None:
        self._selected = selected
        self._artifact_file_page_cache: OrderedDict[tuple[Any, ...], list[Any]] = (
            OrderedDict()
        )
        self._artifact_file_discovery_inflight: dict[
            tuple[Any, ...], asyncio.Task[Any]
        ] = {}
        self.fire_calls = 0
        self.footer_refresh_calls = 0

    def _get_selected_agent(self) -> _DiscoveryAgent | None:
        return self._selected

    def _fire_debounced_detail_update(self) -> None:
        self.fire_calls += 1

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1


def _make_page(artifacts: list[Any]) -> Any:
    page = SimpleNamespace(
        artifact_files=artifacts,
        request=None,
        shared_snapshot=None,
    )
    return SimpleNamespace(value=page, used_daemon=False)


async def test_cached_artifact_files_returns_none_on_miss(tmp_path: Path) -> None:
    app = _DiscoveryApp(None)
    agent = _DiscoveryAgent(tmp_path)

    assert app._cached_artifact_files(agent) is None  # type: ignore[arg-type]


async def test_cached_artifact_files_returns_cached_copy(tmp_path: Path) -> None:
    app = _DiscoveryApp(None)
    agent = _DiscoveryAgent(tmp_path)
    row_key = app._artifact_file_cache_key(agent, agent.identity)  # type: ignore[arg-type]
    artifact = SimpleNamespace(path=str(tmp_path / "x"), kind="image", label="img")
    app._artifact_file_page_cache[row_key] = [artifact]

    cached = app._cached_artifact_files(agent)  # type: ignore[arg-type]

    assert cached == [artifact]
    assert cached is not app._artifact_file_page_cache[row_key]


async def test_schedule_discovery_runs_off_event_loop_and_refreshes_footer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _DiscoveryAgent(tmp_path)
    app = _DiscoveryApp(agent)
    artifact = SimpleNamespace(path=str(tmp_path / "a"), kind="chat", label="Chat")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._artifact_file_provider.read_artifact_files_for_tui",
        lambda *_args, **_kwargs: _make_page([artifact]),
    )

    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]
    inflight = app._artifact_file_discovery_inflight
    assert len(inflight) == 1
    task = next(iter(inflight.values()))

    await task

    row_key = app._artifact_file_cache_key(agent, agent.identity)  # type: ignore[arg-type]
    assert app._artifact_file_page_cache[row_key] == [artifact]
    assert app.fire_calls == 0
    assert app.footer_refresh_calls == 1
    assert row_key not in app._artifact_file_discovery_inflight


async def test_schedule_discovery_dedupes_in_flight_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple sync schedule calls coalesce into one task."""
    agent = _DiscoveryAgent(tmp_path)
    app = _DiscoveryApp(agent)
    call_count = 0

    def fake_read(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return _make_page([])

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._artifact_file_provider.read_artifact_files_for_tui",
        fake_read,
    )

    # Three back-to-back schedule calls without yielding: only the first
    # should land in the in-flight dict; the rest must hit the dedupe gate.
    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]
    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]
    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]

    assert len(app._artifact_file_discovery_inflight) == 1
    task = next(iter(app._artifact_file_discovery_inflight.values()))
    await task

    assert call_count == 1
    assert app._artifact_file_discovery_inflight == {}


async def test_discovery_continuation_skips_stale_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    agent_a = _DiscoveryAgent(
        tmp_path / "a", identity=("run", "feat-a", "20260514100000")
    )
    agent_b = _DiscoveryAgent(
        tmp_path / "b", identity=("run", "feat-b", "20260514100100")
    )
    app = _DiscoveryApp(agent_a)
    artifact = SimpleNamespace(path=str(tmp_path / "z"), kind="image", label="img")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._artifact_file_provider.read_artifact_files_for_tui",
        lambda *_args, **_kwargs: _make_page([artifact]),
    )

    app._schedule_artifact_file_discovery(agent_a)  # type: ignore[arg-type]
    # User navigates to a different agent before the worker resolves.
    app._selected = agent_b
    task = next(iter(app._artifact_file_discovery_inflight.values()))
    await task

    row_key_a = app._artifact_file_cache_key(agent_a, agent_a.identity)  # type: ignore[arg-type]
    assert app._artifact_file_page_cache[row_key_a] == [artifact]
    assert app.fire_calls == 0
    assert app.footer_refresh_calls == 0


async def test_schedule_discovery_noop_for_identity_none(tmp_path: Path) -> None:
    app = _DiscoveryApp(None)
    agent = _DiscoveryAgent(tmp_path)
    agent.identity = None  # type: ignore[assignment]

    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]

    assert app._artifact_file_discovery_inflight == {}


async def test_discovery_swallows_worker_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _DiscoveryAgent(tmp_path)
    app = _DiscoveryApp(agent)

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._artifact_file_provider.read_artifact_files_for_tui",
        boom,
    )

    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]
    task = next(iter(app._artifact_file_discovery_inflight.values()))
    await task

    row_key = app._artifact_file_cache_key(agent, agent.identity)  # type: ignore[arg-type]
    assert app._artifact_file_page_cache[row_key] == []
    assert app.fire_calls == 0
    assert app.footer_refresh_calls == 1


async def test_cancel_pending_artifact_file_discovery_cancels_inflight_tasks(
    tmp_path: Path,
) -> None:
    agent = _DiscoveryAgent(tmp_path)
    app = _DiscoveryApp(agent)
    started = asyncio.Event()
    release = asyncio.Event()

    async def stub(_agent: Any, row_key: tuple[Any, ...]) -> None:
        started.set()
        try:
            await release.wait()
        finally:
            inflight = app._artifact_file_discovery_inflight
            inflight.pop(row_key, None)

    app._run_artifact_file_discovery = stub  # type: ignore[method-assign]

    app._schedule_artifact_file_discovery(agent)  # type: ignore[arg-type]
    await started.wait()
    task = next(iter(app._artifact_file_discovery_inflight.values()))

    app._cancel_pending_artifact_file_discovery()

    assert app._artifact_file_discovery_inflight == {}
    with pytest.raises(asyncio.CancelledError):
        await task
