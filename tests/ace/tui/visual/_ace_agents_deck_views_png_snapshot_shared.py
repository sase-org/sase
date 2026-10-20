"""Shared Agents deck-view PNG snapshot fixtures and navigation helpers.

Public helpers for the ``test_ace_png_snapshots_agents_deck_views*`` split. This
module is private (``_``-prefixed); the helpers are public so each split test
module can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.widgets._agent_display_agent_session_helpers import (
    write_phase_content,
)

_STARTED = datetime(2026, 9, 24, 10, 0, 0)


def view_turn(
    tmp_path: Path,
    session: str,
    role: str,
    suffix: str,
    index: int,
    *,
    extra_reply_lines: int = 0,
    **overrides: object,
) -> Agent:
    """Build one concrete turn member with deterministic content and times."""
    directory = tmp_path / f"{session}-{suffix.strip('-')}"
    directory.mkdir(parents=True, exist_ok=True)
    write_phase_content(directory, role)
    if extra_reply_lines:
        with open(directory / "response.md", "a", encoding="utf-8") as handle:
            for line in range(extra_reply_lines):
                handle.write(f"{role} filler line {line:03d} keeps the block tall.\n")
    start = _STARTED + timedelta(minutes=2 * index)
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "visual-views",
        "project_file": "/workspace/sase/visual_views.sase",
        "status": "DONE",
        "start_time": start,
        "stop_time": start + timedelta(minutes=1),
        "raw_suffix": f"2026092410{index:02d}00",
        "artifacts_dir": str(directory),
        "response_path": str(directory / "response.md"),
        "agent_name": f"visual{session}{suffix}",
        "agent_session": f"visual{session}",
        "agent_session_role": role,
        "role_suffix": suffix,
        "model": "claude/opus",
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def title_plain(detail: AgentDetail, panel_index: int = 0) -> str:
    return detail.deck_area.panel(panel_index)._border_title.plain


async def goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)
