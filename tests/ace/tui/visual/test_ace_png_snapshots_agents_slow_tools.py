"""ACE PNG snapshots for the Agents metadata slow-tool fold ladder."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from textual.containers import VerticalScroll
from textual.geometry import Region

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.tools import build_slow_tool_sources
from sase.ace.tui.tools import cache as tools_cache_module
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel import _agent_display_header
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    get_cached_detail_header_summary,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = datetime(2026, 7, 28, 12, 10, tzinfo=UTC)
_SLOW_TOOLS_VISUAL_IDLE_TIMEOUT = 60.0
_ACTIVE_TOOLS_FOOTER_RE = re.compile(r">●</text><text[^>]*>\s*tools</text>")


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return _NOW if tz is None else _NOW.astimezone(tz)


def _result_pair(
    *,
    tool_use_id: str,
    tool_name: str,
    started_at: str,
    completed_at: str,
    duration_ms: int,
    status: str,
    tool_input_summary: dict[str, Any],
    tool_response_summary: dict[str, Any],
    error: str | None = None,
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
        **start,
        "recorded_at": completed_at,
        "event": "ToolResult",
        "status": status,
        "duration_ms": duration_ms,
        "completed_at": completed_at,
        "tool_response_summary": tool_response_summary,
    }
    if error:
        result["error"] = error
    return [start, result]


def _populate_slow_tool_calls(artifacts_dir: Path) -> None:
    records: list[dict[str, Any]] = []
    records.extend(
        _result_pair(
            tool_use_id="call_long_check",
            tool_name="Bash",
            started_at="2026-07-28T12:02:00+00:00",
            completed_at="2026-07-28T12:03:04+00:00",
            duration_ms=64_000,
            status="success",
            tool_input_summary={
                "description": "install dev dependencies",
                "command": (
                    "just check --keep-going --dir "
                    "/workspace/sase/feature/fold-slow-tool-commands "
                    "&& printf 'validation complete'\n"
                    "pytest tests/ace/tui/widgets/test_agent_slow_tools.py -q"
                ),
                "timeout": 600,
            },
            tool_response_summary={
                "exit_code": 0,
                "stdout_preview": "All checks passed · 22,871 passed, 7 skipped",
            },
        )
    )
    records.extend(
        _result_pair(
            tool_use_id="call_failed_read",
            tool_name="Read",
            started_at="2026-07-28T12:04:00+00:00",
            completed_at="2026-07-28T12:04:22+00:00",
            duration_ms=22_000,
            status="failure",
            tool_input_summary={
                "file_path": (
                    "/workspace/sase/src/sase/ace/tui/widgets/"
                    "prompt_panel/_agent_slow_tools.py"
                )
            },
            tool_response_summary={
                "success": False,
                "stderr_preview": "permission denied while opening the source",
            },
            error="permission denied",
        )
    )
    records.append(
        {
            "schema_version": 2,
            "recorded_at": "2026-07-28T12:06:00+00:00",
            "runtime": "codex",
            "source": "stream",
            "event": "ToolUse",
            "status": "pending",
            "tool_name": "Bash",
            "tool_use_id": "call_running_tests",
            "tool_input_summary": {
                "command": ("pytest tests/ace/tui -x -q --durations=20 --showlocals")
            },
            "tool_response_summary": {},
        }
    )

    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "tool_calls.jsonl").write_text(
        "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
        encoding="utf-8",
    )


def _slow_tool_agent(artifacts_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="slow-tools",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 28, 12, 0),
        run_start_time=datetime(2026, 7, 28, 12, 0),
        raw_suffix="20260728120000-slow-tools",
        agent_name="slow-tools",
        llm_provider="codex",
        model="gpt-5.6",
        artifacts_dir=str(artifacts_dir),
        workspace_num=17,
        activity="slow calls",
    )


async def _focus_slow_tool_section(page: AcePage) -> AgentPromptPanel:
    panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
    for _ in range(20):
        if panel.active_section_identity == "slow-tool-calls":
            await wait_for_state(
                page,
                lambda: _active_tools_footer_visible(page),
                description="loaded tools footer",
            )
            await wait_for_visual_idle(
                page,
                timeout=_SLOW_TOOLS_VISUAL_IDLE_TIMEOUT,
            )
            if (
                panel.active_section_identity == "slow-tool-calls"
                and _active_tools_footer_visible(page)
            ):
                if await _slow_tool_section_top_aligned(page, panel):
                    return panel
                continue
        await page.press("ctrl+j")
        # The first navigation request may enable the panel's layout reserve
        # and finish through a call-after-refresh retry. Let that retry and its
        # anchor paint converge before deciding whether another key is needed.
        await wait_for_visual_idle(page, timeout=_SLOW_TOOLS_VISUAL_IDLE_TIMEOUT)
    raise AssertionError("Timed out focusing slow-tool calls section")


async def _slow_tool_section_top_aligned(
    page: AcePage,
    panel: AgentPromptPanel,
) -> bool:
    """Pin the slow-tool section header to the metadata viewport top."""
    for _attempt in range(3):
        anchor = next(
            (
                candidate
                for candidate in getattr(panel, "_section_anchors", ())
                if candidate.identity == "slow-tool-calls"
            ),
            None,
        )
        if anchor is None:
            await page.pause()
            continue

        scroll = page.query_one_widget("#agent-prompt-scroll", VerticalScroll)
        panel_region = panel.virtual_region
        scroll.scroll_to_region(
            Region(
                panel_region.x,
                panel_region.y + anchor.row,
                max(1, panel_region.width),
                1,
            ),
            top=True,
            animate=False,
            x_axis=False,
            y_axis=True,
            immediate=True,
        )
        await wait_for_visual_idle(page, timeout=_SLOW_TOOLS_VISUAL_IDLE_TIMEOUT)
        if _metadata_viewport_top_section(page, panel) == "slow-tool-calls":
            return True
    return False


def _metadata_viewport_top_section(
    page: AcePage,
    panel: AgentPromptPanel,
) -> str | None:
    scroll = page.query_one_widget("#agent-prompt-scroll", VerticalScroll)
    document_row = max(0, int(scroll.scroll_y) - panel.virtual_region.y)
    return panel.resolve_section_at_row(document_row, width=panel.size.width)


def _active_tools_footer_visible(page: AcePage) -> bool:
    svg = page.export_svg(title="ACE active tools footer probe").replace("&#160;", " ")
    return _ACTIVE_TOOLS_FOOTER_RE.search(svg) is not None


async def test_agents_slow_tool_calls_fold_levels_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(_agent_display_header, "DateTime", _FixedDateTime)
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )
    pin_agents_visual_now(monkeypatch, _NOW.replace(tzinfo=None))
    tools_cache_module.tools_cache.clear()
    artifacts_dir = tmp_path / "visual-slow-tools"
    _populate_slow_tool_calls(artifacts_dir)
    agent = _slow_tool_agent(artifacts_dir)
    # This snapshot covers fold rendering, not asynchronous artifact discovery.
    # Prime the shared mtime cache so the metadata header and tools-availability
    # indicator start from the same source state under full-suite contention.
    assert build_slow_tool_sources(agent)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"slow-tools"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("h")
        await wait_for_visual_idle(page)
        await page.press("l")

        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await wait_for_state(
            page,
            lambda: (
                (summary := get_cached_detail_header_summary(panel, agent)) is not None
                and bool(summary.slow_tool_sources)
            ),
            description="slow-tool detail-header summary",
        )
        await page.press("left_square_bracket")
        await wait_for_visual_idle(page)
        await wait_for_svg_contains(page, "SLOW TOOL CALLS")
        await _focus_slow_tool_section(page)

        assert page.app.panel_fold_level is FoldLevel.COLLAPSED
        ace_png_visual.assert_page_png(
            page,
            "agents_slow_tool_calls_level_1_120x40",
            title="ACE agents slow tool calls level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await wait_for_svg_contains(page, "validation complete")
        await wait_for_visual_idle(page)
        assert await _slow_tool_section_top_aligned(page, panel)
        ace_png_visual.assert_page_png(
            page,
            "agents_slow_tool_calls_level_2_120x40",
            title="ACE agents slow tool calls level 2",
        )
