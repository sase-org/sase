"""ACE TUI PNG visual snapshots for the populated Tools panel.

Covers the actual Agents-tab panel mode flow with a deterministic Codex
``tool_calls.jsonl`` fixture, so Codex stream-derived timelines stay protected
by the PNG visual suite.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import tools_panel as tools_panel_module
from sase.ace.tui.widgets.tools_panel import AgentToolsPanel
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _tools_agent(artifacts_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-tools",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 9, 10, 0, 0),
        stop_time=datetime(2026, 5, 9, 10, 5, 0),
        raw_suffix="20260509-100000-tools",
        agent_name="tools",
        llm_provider="codex",
        model="gpt-5.5",
        artifacts_dir=str(artifacts_dir),
    )


def _codex_pair(
    *,
    tool_use_id: str,
    tool_name: str,
    started_at: str,
    completed_at: str,
    status: str,
    tool_input_summary: dict[str, Any],
    tool_response_summary: dict[str, Any],
    duration_ms: int,
) -> list[dict[str, Any]]:
    start = {
        "schema_version": 2,
        "recorded_at": started_at,
        "runtime": "codex",
        "source": "stream",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary,
        "tool_response_summary": {},
    }
    result = {
        "schema_version": 2,
        "recorded_at": completed_at,
        "runtime": "codex",
        "source": "stream",
        "event": "ToolResult",
        "status": status,
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "duration_ms": duration_ms,
        "tool_input_summary": tool_input_summary,
        "tool_response_summary": tool_response_summary,
    }
    return [start, result]


def _codex_pending(
    *,
    tool_use_id: str,
    tool_name: str,
    recorded_at: str,
    tool_input_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": "codex",
        "source": "stream",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary,
        "tool_response_summary": {},
    }


def _legacy_codex_function_call(
    *,
    tool_use_id: str,
    tool_name: str,
    recorded_at: str,
    tool_input_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "recorded_at": recorded_at,
        "runtime": "codex",
        "source": "stream",
        "event": "FunctionCall",
        "status": "success",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "tool_input_summary": tool_input_summary,
        "tool_response_summary": {},
    }


def _populate_tool_calls(artifacts_dir: Path) -> None:
    """Write a deterministic Codex ``tool_calls.jsonl`` with mixed-status rows."""
    records: list[dict[str, Any]] = []
    records.extend(
        _codex_pair(
            tool_use_id="call_bash_pwd",
            tool_name="Bash",
            started_at="2026-05-09T14:00:30+00:00",
            completed_at="2026-05-09T14:00:31+00:00",
            status="success",
            tool_input_summary={"command": "pwd"},
            tool_response_summary={
                "exit_code": 0,
                "output_preview": "/workspace/sase\n",
            },
            duration_ms=842,
        )
    )
    records.extend(
        _codex_pair(
            tool_use_id="call_read_reader",
            tool_name="Read",
            started_at="2026-05-09T14:00:45+00:00",
            completed_at="2026-05-09T14:00:45+00:00",
            status="success",
            tool_input_summary={"file_path": "src/sase/ace/tui/tools/reader.py"},
            tool_response_summary={"content_preview": "class ToolCallEntry:"},
            duration_ms=37,
        )
    )
    records.extend(
        _codex_pair(
            tool_use_id="call_test_fail",
            tool_name="Bash",
            started_at="2026-05-09T14:01:10+00:00",
            completed_at="2026-05-09T14:01:10+00:00",
            status="failure",
            tool_input_summary={"command": "pytest tests/missing_test.py"},
            tool_response_summary={
                "exit_code": 2,
                "stderr_preview": "file or directory not found: tests/missing_test.py",
                "is_error": True,
            },
            duration_ms=15,
        )
    )
    records.append(
        _codex_pending(
            tool_use_id="call_edit_pending",
            tool_name="Edit",
            recorded_at="2026-05-09T14:01:30+00:00",
            tool_input_summary={"file_path": "docs/llms.md"},
        )
    )
    records.append(
        _legacy_codex_function_call(
            tool_use_id="call_legacy_read",
            tool_name="Read",
            recorded_at="2026-05-09T14:01:35+00:00",
            tool_input_summary={"file_path": "README.md"},
        )
    )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / "tool_calls.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, sort_keys=True)
            f.write("\n")


def _pin_tools_panel_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the Tools panel timestamp formatter to UTC for deterministic output."""
    utc = ZoneInfo("UTC")
    monkeypatch.setattr(tools_panel_module, "get_timezone", lambda: utc)


_FIXED_FETCH_TIME = datetime(2026, 5, 9, 14, 1, 35)


class _FixedDateTime(datetime):
    """``datetime`` subclass whose ``now()`` returns a fixed wall-clock value.

    The Tools panel embeds ``fetch_time`` (``datetime.now()`` at cache write)
    into the rendered ``refreshed HH:MM:SS`` line. Without pinning, the
    rendered time drifts every run and the PNG golden never matches.
    """

    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        del tz
        return _FIXED_FETCH_TIME


def _pin_tools_panel_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``datetime.now()`` calls in the Tools panel to a fixed wall-clock."""
    monkeypatch.setattr(tools_panel_module, "datetime", _FixedDateTime)


def _clear_tools_cache() -> None:
    tools_panel_module._tools_cache.clear()


async def _wait_for_tools_loaded(page: AcePage) -> None:
    def _check(state: dict[str, Any]) -> bool:
        del state
        try:
            panel = page.app.query_one("#agent-tools-panel", AgentToolsPanel)
        except Exception:
            return False
        entries = panel._last_entries
        return entries is not None and len(entries) > 0

    await page.wait_for(_check, timeout=5.0)


async def test_agents_tools_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _pin_tools_panel_timezone(monkeypatch)
    _pin_tools_panel_now(monkeypatch)
    _clear_tools_cache()

    artifacts_dir = tmp_path / "ace-run" / "20260509100000"
    _populate_tool_calls(artifacts_dir)
    agent = _tools_agent(artifacts_dir)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        # Wait for the debounced detail panel update so AgentDetail._current_agent
        # is populated; without it _next_panel_mode falls back to the short
        # AUTO -> INFO cycle (because is_agent_entry is checked on _current_agent).
        await wait_for_visual_idle(page)
        await page.press("right_square_bracket")
        await _wait_for_tools_loaded(page)
        await wait_for_visual_idle(page)
        panel = page.app.query_one("#agent-tools-panel", AgentToolsPanel)
        assert panel._last_entries is not None
        assert {entry.runtime for entry in panel._last_entries} == {"codex"}
        assert {entry.source for entry in panel._last_entries} == {"stream"}

        ace_png_visual.assert_page_png(
            page,
            "agents_tools_panel_populated_120x40",
            title="ACE agents tools panel populated with Codex rows",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
