"""Tests for the attempt-pinned detail rendering path."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets.prompt_panel._agent_display import (
    AgentDisplayMixin,
    _render_attempt_banner,
)


def _make_record(
    n: int, *, live_reply_path: str, status: str = "failed"
) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=n,
        status=status,
        start_epoch=1745337600.0 + n * 60,
        end_epoch=1745337660.0 + n * 60,
        model=None,
        used_fallback=False,
        error_snippet=f"err-{n}",
        error_full=f"Traceback (most recent call last):\n  ZeroDivisionError: {n}",
        live_reply_path=live_reply_path,
        timestamps_path="/nonexistent/live_reply_timestamps.jsonl",
    )


class _FakePanel(AgentDisplayMixin):
    """Test double exposing ``.update()`` calls as captured renderables."""

    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def _concat_plain(group: Group) -> str:
    parts: list[str] = []
    for r in group.renderables:
        if isinstance(r, Text):
            parts.append(r.plain)
        elif isinstance(r, Syntax):
            parts.append(str(r.code))
    return "\n".join(parts)


def test_render_attempt_pinned_emits_error_and_prompt_and_reply() -> None:
    with tempfile.TemporaryDirectory() as td:
        reply_path = os.path.join(td, "live_reply.md")
        with open(reply_path, "w") as f:
            f.write("partial reply from attempt 1\n")
        record = _make_record(1, live_reply_path=reply_path)
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="demo",
            project_file="/tmp/p.gp",
            status="FAILED",
            start_time=datetime(2026, 4, 23, 14, 0, 0),
            attempt_history=[record],
        )

        panel = _FakePanel()
        panel.attempt_pinned_number = 1
        panel.update_display(agent)

        assert panel.captured, "panel.update should have been invoked"
        rendered = panel.captured[-1]
        assert isinstance(rendered, Group)
        plain = _concat_plain(rendered)

        assert "Viewing Attempt 1 of 1" in plain
        assert "ZeroDivisionError" in plain
        assert "partial reply from attempt 1" in plain


def test_render_attempt_pinned_missing_attempt_shows_error() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/p.gp",
        status="FAILED",
        start_time=datetime(2026, 4, 23, 14, 0, 0),
        attempt_history=[],
    )
    panel = _FakePanel()
    panel.attempt_pinned_number = 5
    panel.update_display(agent)

    rendered = panel.captured[-1]
    assert isinstance(rendered, Text)
    assert "Attempt 5 not found" in rendered.plain


def test_render_attempt_pinned_handles_missing_reply_file() -> None:
    record = _make_record(1, live_reply_path="/nonexistent/path.md")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/p.gp",
        status="FAILED",
        start_time=datetime(2026, 4, 23, 14, 0, 0),
        attempt_history=[record],
    )

    panel = _FakePanel()
    panel.attempt_pinned_number = 1
    panel.update_display(agent)

    rendered = panel.captured[-1]
    assert isinstance(rendered, Group)
    plain = _concat_plain(rendered)
    assert "no partial reply captured" in plain


def test_attempt_banner_labels_attempt_of_total() -> None:
    record = _make_record(2, live_reply_path="/nonexistent/path.md")
    banner = _render_attempt_banner(record, total=3)
    assert "Viewing Attempt 2 of 3" in banner.plain
