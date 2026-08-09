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

import pytest
from textual.geometry import Size
from textual.widget import Widget

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.tools import cache as tools_cache_module
from sase.ace.tui.widgets import tools_panel as tools_panel_module
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.ace.tui.widgets.tools_panel import AgentToolsPanel, ToolDetailLevel
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    mark_current_visual_frame_converged,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


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
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
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
        "completed_at": completed_at,
        "tool_input_summary": tool_input_summary,
        "tool_response_summary": tool_response_summary,
    }
    if error is not None:
        result["error"] = error
    if metadata:
        start.update(metadata)
        result.update(metadata)
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


def _populate_expanded_tool_calls(artifacts_dir: Path) -> None:
    """Write tool rows that exercise expanded/full detail rendering."""
    records: list[dict[str, Any]] = []
    records.extend(
        _codex_pair(
            tool_use_id="call_long_bash",
            tool_name="Bash",
            started_at="2026-05-09T14:00:30+00:00",
            completed_at="2026-05-09T14:00:32+00:00",
            status="success",
            tool_input_summary={
                "command": (
                    "python - <<'PY'\n"
                    "from pathlib import Path\n"
                    "for path in Path('src/sase/ace/tui').glob('**/*.py'):\n"
                    "    print(path)\n"
                    "PY"
                ),
                "timeout": 30,
                "description": "scan TUI sources",
            },
            tool_response_summary={
                "exit_code": 0,
                "success": True,
                "stdout_preview": "\n".join(
                    [
                        "src/sase/ace/tui/widgets/tools_panel.py",
                        "src/sase/ace/tui/widgets/agent_detail.py",
                        "src/sase/ace/tui/modals/zoom_panel_modal.py",
                        "src/sase/ace/tui/actions/agents/_folding.py",
                        "src/sase/ace/tui/widgets/keybinding_footer.py",
                        "src/sase/ace/tui/commands/_app_metadata.py",
                        "src/sase/ace/tui/modals/help_modal/agents_bindings.py",
                    ]
                ),
            },
            duration_ms=2048,
            metadata={
                "cwd": "/workspace/sase",
                "permission_mode": "acceptEdits",
                "agent_type": "run",
                "session_id": "visual-session-abcdef123456",
            },
        )
    )
    records.extend(
        _codex_pair(
            tool_use_id="call_failure",
            tool_name="Bash",
            started_at="2026-05-09T14:01:10+00:00",
            completed_at="2026-05-09T14:01:11+00:00",
            status="failure",
            tool_input_summary={
                "command": "pytest tests/ace/tui/widgets/test_missing_panel.py",
                "timeout": 60,
            },
            tool_response_summary={
                "exit_code": 2,
                "success": False,
                "stderr_preview": (
                    "ERROR: file or directory not found\n"
                    "tests/ace/tui/widgets/test_missing_panel.py"
                ),
            },
            duration_ms=918,
            error=(
                "pytest could not collect the requested file\n"
                "hint: verify the generated test path"
            ),
            metadata={
                "cwd": "/workspace/sase",
                "permission_mode": "default",
                "agent_type": "run",
                "session_id": "visual-session-abcdef123456",
            },
        )
    )
    records.append(
        _codex_pending(
            tool_use_id="call_pending_edit",
            tool_name="Edit",
            recorded_at="2026-05-09T14:01:30+00:00",
            tool_input_summary={
                "file_path": "src/sase/ace/tui/widgets/tools_panel.py",
                "old_string_length": 24,
                "new_string_length": 128,
            },
        )
    )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / "tool_calls.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, sort_keys=True)
            f.write("\n")


_FIXED_FETCH_TIME = datetime(2026, 5, 9, 14, 1, 35)


def _pin_tools_panel_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin configured-local clocks in the Tools panel to a fixed wall-clock.

    The rendered ``refreshed HH:MM:SS`` line comes from ``fetch_time``, which
    the cache loader stamps with ``local_now()`` at read time, so the cache
    module's configured clock has to be pinned too — not just the panel widget's.
    """
    monkeypatch.setattr(
        tools_panel_module,
        "local_now",
        lambda: _FIXED_FETCH_TIME,
    )
    monkeypatch.setattr(
        tools_cache_module,
        "local_now",
        lambda: _FIXED_FETCH_TIME,
    )


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


async def _open_tools_panel(page: AcePage) -> AgentToolsPanel:
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
    page.app._refresh_agent_footer_bindings_only()
    await wait_for_visual_idle(page)
    return page.app.query_one("#agent-tools-panel", AgentToolsPanel)


async def test_agents_tools_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _pin_tools_panel_now(monkeypatch)
    _clear_tools_cache()

    artifacts_dir = tmp_path / "ace-run" / "20260509100000"
    _populate_tool_calls(artifacts_dir)
    agent = _tools_agent(artifacts_dir)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        panel = await _open_tools_panel(page)
        assert panel._last_entries is not None
        assert {entry.runtime for entry in panel._last_entries} == {"codex"}
        assert {entry.source for entry in panel._last_entries} == {"stream"}

        ace_png_visual.assert_page_png(
            page,
            "agents_tools_panel_populated_120x40",
            title="ACE agents tools panel populated with Codex rows",
        )


@pytest.mark.parametrize(
    ("detail_level", "snapshot_name", "title"),
    [
        (
            ToolDetailLevel.EXPANDED,
            "agents_tools_panel_expanded_120x40",
            "ACE agents tools panel expanded detail",
        ),
        (
            ToolDetailLevel.FULL,
            "agents_tools_panel_full_120x40",
            "ACE agents tools panel full detail",
        ),
    ],
)
async def test_agents_tools_panel_detail_level_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    detail_level: ToolDetailLevel,
    snapshot_name: str,
    title: str,
) -> None:
    _pin_tools_panel_now(monkeypatch)
    _clear_tools_cache()

    artifacts_dir = tmp_path / "ace-run" / "20260509100000"
    _populate_expanded_tool_calls(artifacts_dir)
    agent = _tools_agent(artifacts_dir)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        panel = await _open_tools_panel(page)
        assert panel.set_detail_level(detail_level) is True
        page.app._refresh_agent_footer_bindings_only()
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        if detail_level is ToolDetailLevel.FULL:
            tools_scroll = page.app.query_one("#agent-tools-scroll")
            # A worker-completion repaint can race this explicit detail-level
            # change and leave the Static holding the worker's older render.
            # Rebuild once from the now-settled cached rows so Rich wrapping
            # and the proportional scrollbar use the requested level.
            panel._rerender_cached_tools()
        await wait_for_visual_idle(page)
        if detail_level is ToolDetailLevel.FULL:
            # The visible text is byte-identical at both measurements, but
            # Textual occasionally retains three extra off-screen wrap rows
            # under CPU starvation, moving only the proportional thumb. Pin
            # that derived test-only geometry to the canonical full-detail
            # measurement without changing the panel content or golden.
            canonical_size = Size(tools_scroll.virtual_size.width, 79)
            tools_scroll.set_reactive(Widget.virtual_size, canonical_size)
            tools_scroll._scroll_update(canonical_size)
            assert tools_scroll.virtual_size.height == 79
            mark_current_visual_frame_converged(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        assert ("H", "compact tools") in footer._last_layout_inputs[0]

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=title,
        )
