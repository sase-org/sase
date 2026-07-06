from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import tools_panel as tools_panel_mod
from sase.ace.tui.widgets.tools_panel import _ToolsCacheEntry, get_cache_key

from ._tools_panel_helpers import _build_panel, _entry


def test_warm_cache_update_display_does_not_walk_artifacts_on_event_loop(
    tmp_path: Path,
) -> None:
    """Regression for the j/k slowdown: a warm-cache update_display must not
    invoke ``discover_related_tool_artifact_dirs`` (or any sibling-walking
    helper) on the Textual event loop. Throttling keeps repeated keystrokes
    cheap by suppressing worker spawns inside the minimum re-read interval.
    """
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )

    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[],
        fetch_time=datetime.now(),
        artifact_mtime_ns=1234,
        discovered_dirs=[artifacts_dir],
        parent_mtime_ns=5678,
        last_worker_monotonic=time.monotonic(),
    )

    with (
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs"
        ) as discover_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs_cached"
        ) as discover_cached_mock,
    ):
        try:
            panel = _build_panel()
            for _ in range(10):
                panel.update_display(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    run_worker = panel.run_worker
    update = panel.update
    assert isinstance(run_worker, MagicMock)
    assert isinstance(update, MagicMock)
    assert discover_mock.call_count == 0
    assert discover_cached_mock.call_count == 0
    assert run_worker.call_count == 0
    assert update.called


def test_cold_update_display_defers_missing_artifact_reads_to_worker(
    tmp_path: Path,
) -> None:
    """Cold panel refresh must not stat or read tool artifacts on the event loop."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )

    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache.pop(cache_key, None)

    with (
        patch("sase.ace.tui.tools.cache.read_tool_calls_for_agent") as read_mock,
        patch("sase.ace.tui.tools.cache._max_mtime_ns_for_paths") as mtime_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs"
        ) as discover_mock,
        patch(
            "sase.ace.tui.tools.reader.discover_related_tool_artifact_dirs_cached"
        ) as discover_cached_mock,
    ):
        panel = _build_panel()
        panel.update_display(agent)

    run_worker = panel.run_worker
    assert isinstance(run_worker, MagicMock)
    assert run_worker.call_count == 1
    assert run_worker.call_args.kwargs["thread"] is True
    assert read_mock.call_count == 0
    assert mtime_mock.call_count == 0
    assert discover_mock.call_count == 0
    assert discover_cached_mock.call_count == 0


def test_refresh_tools_defers_forced_codex_reread_to_worker(
    tmp_path: Path,
) -> None:
    """A forced refresh invalidates cache state but still schedules threaded IO."""
    artifacts_dir = tmp_path / "ace-run" / "20260514140000"
    artifacts_dir.mkdir(parents=True)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        artifacts_dir=str(artifacts_dir),
        raw_suffix=artifacts_dir.name,
    )
    cache_key = get_cache_key(agent)
    tools_panel_mod._tools_cache[cache_key] = _ToolsCacheEntry(
        entries=[
            _entry(
                runtime="codex",
                source="stream",
                status="pending",
                duration_ms=None,
                tool_input_summary={"command": "pwd"},
                tool_response_summary={},
            )
        ],
        fetch_time=datetime.now(),
        artifact_mtime_ns=1234,
        discovered_dirs=[artifacts_dir],
        parent_mtime_ns=artifacts_dir.parent.stat().st_mtime_ns,
        last_worker_monotonic=time.monotonic(),
    )

    with (
        patch("sase.ace.tui.tools.cache.read_tool_calls_for_agent") as read_mock,
        patch("sase.ace.tui.tools.cache._max_mtime_ns_for_paths") as mtime_mock,
    ):
        try:
            panel = _build_panel()
            panel.refresh_tools(agent)
        finally:
            tools_panel_mod._tools_cache.pop(cache_key, None)

    run_worker = panel.run_worker
    assert isinstance(run_worker, MagicMock)
    assert run_worker.call_count == 1
    assert run_worker.call_args.kwargs["thread"] is True
    assert read_mock.call_count == 0
    assert mtime_mock.call_count == 0
