"""Configured-timezone regressions for ACE/TUI clocks."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.keymaps import StatisticsPaneKeymaps
from sase.ace.tui.logs import LogSource
from sase.ace.tui.modals.logs_pane_render import format_mtime
from sase.ace.tui.modals.logs_pane_toasts import (
    _format_session_started_at,
    _toast_timestamp,
)
from sase.ace.tui.modals.project_inventory_rendering import (
    _absolute_workspace_time,
)
from sase.ace.tui.modals.saved_agent_group_revival_rendering import (
    _saved_group_time_label,
)
from sase.ace.tui.modals.statistics_help_modal import StatisticsHelpModal
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_projects import (
    StatisticsProjectsRenderingMixin,
)
from sase.ace.tui.modals.procs_pane_render import _elapsed, _relative_time
from sase.ace.tui.proc_observer import ObservedProc
from sase.ace.tui import _proc_observer_log as po_log
from sase.ace.tui import _proc_observer_store as po_store
from sase.ace.tui.tools.cache import (
    ToolsCacheEntry,
    cached_tool_calls_end_reference,
    fetch_tool_calls_cached,
    get_cache_key,
    tools_cache,
)
from sase.ace.tui.tools.report import _timestamp_hhmmss
from sase.ace.tui.widgets.file_panel._display import FilePanelDisplayMixin
from sase.ace.tui.widgets.file_panel._fetch import FilePanelFetchMixin
from sase.ace.tui.widgets.file_panel._messages import file_cache
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    _format_timestamp as format_roster_timestamp,
)
from sase.ace.tui.widgets.tools_panel import AgentToolsPanel
from sase.logs import ToastRecord
from sase.procs import Proc
from sase.stats.ranges import StatsRange


def _display_epoch() -> float:
    return datetime(2026, 7, 3, 10, 24, 49, tzinfo=UTC).timestamp()


def _fake_agent() -> SimpleNamespace:
    return SimpleNamespace(
        cl_name="change",
        agent_type=SimpleNamespace(value="agent"),
        workspace_num=None,
        raw_suffix=None,
        get_artifacts_dir=lambda: None,
    )


def test_logs_render_configured_time_and_truthful_zone(
    tz_divergence: None,
    tmp_path: Path,
) -> None:
    path = tmp_path / "tui.log"
    path.write_text("line\n")
    epoch = _display_epoch()
    os.utime(path, (epoch, epoch))
    source = LogSource("tui", "TUI", "log", path, "text")
    record = ToastRecord(
        timestamp="2026-07-03T10:24:49Z",
        session_id="session",
        session_started_at="2026-07-03T09:00:00Z",
        pid=123,
        severity="information",
        title="",
        message="hello",
    )

    assert format_mtime(source) == "2026-07-03 06:24 EDT"
    assert _format_session_started_at(record.session_started_at) == (
        "2026-07-03 05:00 EDT"
    )
    assert _toast_timestamp(record) == "06:24:49"


def test_statistics_displays_use_configured_timezone(tz_divergence: None) -> None:
    epoch = _display_epoch()
    pane = StatisticsPane(auto_load=False)
    pane._loading = False
    pane._last_error = ""
    pane._last_result = SimpleNamespace(generated_at=epoch)  # type: ignore[assignment]
    modal = StatisticsHelpModal(
        current_view="overview",
        selected_range=StatsRange(100, 200, "exact range", "Last 7 days"),
        projects_group_by="project",
        xprompts_group_by="usage",
        project_label="All projects",
        generated_at=epoch,
        keymaps=StatisticsPaneKeymaps(),
    )

    assert pane._status_text().plain == "updated 06:24:49"
    assert "Last loaded — 2026-07-03 06:24:49 EDT." in modal._freshness_text().plain
    assert StatisticsProjectsRenderingMixin._format_timestamp(epoch) == "Jul 03 06:24"


def test_inventory_saved_group_and_roster_displays_use_configured_timezone(
    tz_divergence: None,
) -> None:
    epoch = _display_epoch()
    aware_utc = datetime.fromtimestamp(epoch, UTC)

    assert _absolute_workspace_time(epoch) == "2026-07-03 06:24"
    assert (
        _saved_group_time_label(
            "2026-07-03T10:24:49Z",
            now=datetime(2026, 7, 3, 11, 24, 49, tzinfo=UTC),
        )
        == "1h ago | 2026-07-03 06:24"
    )
    assert format_roster_timestamp(aware_utc) == "2026-07-03 06:24:49"


def test_task_rows_and_default_references_share_configured_wall_time(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = datetime(2026, 7, 3, 6, 24, 49)
    later = datetime(2026, 7, 3, 6, 25, 49)
    monkeypatch.setattr(
        "sase.ace.tui.modals.procs_pane_render.local_now", lambda: later
    )
    task = ObservedProc(
        proc_id="task",
        proc_type="sync",
        cl_name="change",
        project_file="project.sase",
        status="running",
        message="working",
        started_at=local,
    )

    assert po_store._local_datetime("2026-07-03T10:24:49Z") == local
    assert _relative_time(local) == "1m ago"
    assert _elapsed(task) == "1:00"


def test_proc_observer_mints_configured_wall_times(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = datetime(2026, 7, 3, 6, 24, 49)
    monkeypatch.setattr("sase.ace.tui._proc_observer_log.local_now", lambda: local)
    monkeypatch.setattr("sase.ace.tui._proc_observer_store.local_now", lambda: local)
    log = po_log.ObservedProcLog()
    log.append("hello")
    task = po_store.store_proc_row(
        Proc(
            proc_id="proc-1",
            label="sync change",
            kind="sync",
            status="running",
            command=["sase", "sync"],
            cwd="/tmp",
            origin="ace",
            created_at="2026-07-03T10:24:49Z",
            started_at=None,
            log_path="/tmp/proc-1.log",
        )
    )

    assert log.snapshot().lines[0].ts == local
    assert task.started_at == local


def test_tools_cache_uses_configured_wall_time(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = datetime(2026, 7, 3, 6, 24, 49)
    agent = _fake_agent()
    key = get_cache_key(agent)
    tools_cache[key] = ToolsCacheEntry(
        entries=(),
        fetch_time=local,
        artifact_mtime_ns=int(_display_epoch() * 1_000_000_000),
    )
    monkeypatch.setattr("sase.ace.tui.tools.cache.local_now", lambda: local)
    monkeypatch.setattr(
        "sase.ace.tui.tools.cache.read_tool_calls_for_agent",
        lambda _agent: [],
    )

    try:
        assert cached_tool_calls_end_reference(agent) == local
        fetch_tool_calls_cached(agent)
        assert tools_cache[key].fetch_time == local
    finally:
        tools_cache.pop(key, None)


def test_tools_panel_fallbacks_use_configured_wall_time(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = datetime(2026, 7, 3, 6, 24, 49)
    agent = _fake_agent()
    panel = SimpleNamespace(_fetch_tools_in_background=lambda _agent: ())
    monkeypatch.setattr("sase.ace.tui.widgets.tools_panel.local_now", lambda: local)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.supports_slow_tool_sources",
        lambda _agent: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.build_cached_slow_tool_sources",
        lambda _agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.build_slow_tool_sources",
        lambda _agent: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.rows_from_sources",
        lambda _sources: (),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.latest_cached_fetch_time",
        lambda _agent: None,
    )

    cached = AgentToolsPanel._cached_fetch_result(panel, agent)  # type: ignore[arg-type]
    background = AgentToolsPanel._fetch_tools_result_in_background(  # type: ignore[arg-type]
        panel,
        agent,
    )

    assert cached is not None and cached.fetch_time == local
    assert background.fetch_time == local

    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.supports_slow_tool_sources",
        lambda _agent: False,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.peek_tool_calls_cache_entry",
        lambda _agent: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.tools_panel.rows_from_entries",
        lambda _entries: (),
    )
    uncached = AgentToolsPanel._fetch_tools_result_in_background(  # type: ignore[arg-type]
        panel,
        agent,
    )
    assert uncached.fetch_time == local


def test_file_panel_fetch_and_display_fallback_use_configured_wall_time(
    tz_divergence: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = datetime(2026, 7, 3, 6, 24, 49)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._fetch.local_now",
        lambda: local,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._fetch.get_agent_diff",
        lambda _agent: "diff",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._fetch.get_cache_key",
        lambda _agent: "agent",
    )
    fetcher = SimpleNamespace()
    assert FilePanelFetchMixin._fetch_file_in_background(fetcher, object()) == "diff"  # type: ignore[arg-type]
    assert file_cache["agent"].fetch_time == local

    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._display.local_now",
        lambda: local,
    )
    display = SimpleNamespace(
        _linked_repo_name=None,
        _linked_repo_kind="linked",
        _linked_workspace_dir=None,
        _linked_fetched_at=None,
        _static_header_path=None,
        _full_content=None,
        _full_content_lexer="text",
        _content_mode="none",
        _content_fetched_at=None,
        _has_displayed_content=False,
        _last_file_content=None,
        _post_file_visibility=lambda **_kwargs: None,
        _consume_image_cleanup_segments=lambda: (),
        _render_full_content=lambda: None,
    )
    FilePanelDisplayMixin.display_linked_diff(  # type: ignore[arg-type]
        display,
        "repo",
        "/workspace",
        "diff",
        None,
    )
    assert display._linked_fetched_at == local
    file_cache.pop("agent", None)


def test_tool_report_filename_timestamp_uses_configured_timezone(
    tz_divergence: None,
) -> None:
    assert _timestamp_hhmmss("2026-07-03T10:24:49Z") == "062449"
    assert _timestamp_hhmmss("invalid") == "unknown"
