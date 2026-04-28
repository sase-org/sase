"""Tests for the Phase-3 header-only immediate render path.

``AgentPromptPanel.update_header_only`` is invoked from
``AgentDetail.update_display_immediate`` during j/k bursts. It must
render the agent-details header (and any inline error traceback)
without touching the artifact cache, listing the artifacts directory,
or opening prompt / reply / response files. The debounced full update
fills in the rest after the burst settles.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo_cl",
        "project_file": "/tmp/test.gp",
        "status": "RUNNING",
        "start_time": datetime(2026, 4, 22, 14, 0, 0),
        "model": "opus",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakePanel(AgentDisplayMixin):
    """Mixin-only test double recording ``self.update(...)`` calls."""

    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def _plain_of(renderable: object) -> str:
    """Flatten a Group/Text into its plain text for assertions."""
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Group):
        parts: list[str] = []
        for r in renderable.renderables:
            if isinstance(r, Text):
                parts.append(r.plain)
            elif isinstance(r, Syntax):
                parts.append(str(r.code))
        return "\n".join(parts)
    return str(renderable)


def test_update_header_only_renders_agent_details() -> None:
    panel = _FakePanel()
    agent = _make_agent(cl_name="my_change", cl_num="cl/123")

    panel.update_header_only(agent)

    assert panel.captured, "update_header_only should call self.update"
    plain = _plain_of(panel.captured[-1])
    assert "AGENT DETAILS" in plain
    assert "my_change" in plain
    assert "cl/123" in plain


def test_update_header_only_does_not_touch_disk(tmp_path: Path) -> None:
    """The cheap path must not open prompt/reply files or list artifacts."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    # Create artifacts that the *full* update_display would happily read,
    # so a regression that called the heavy path would be caught by the
    # listdir / open spies below.
    (artifacts_dir / "01_prompt.md").write_text("prompt body\n", encoding="utf-8")
    (artifacts_dir / "live_reply.md").write_text("live reply\n", encoding="utf-8")
    (artifacts_dir / "embedded_workflows.json").write_text(
        json.dumps([{"name": "propose", "args": {}}]),
        encoding="utf-8",
    )

    agent = _make_agent(artifacts_dir=str(artifacts_dir))

    real_listdir = os.listdir
    real_open = open

    listdir_calls: list[str] = []
    opened_paths: list[str] = []

    def spying_listdir(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        listdir_calls.append(str(path))
        return real_listdir(path, *args, **kwargs)

    def spying_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened_paths.append(str(file))
        return real_open(file, *args, **kwargs)

    panel = _FakePanel()
    with (
        patch("os.listdir", side_effect=spying_listdir),
        patch(
            "sase.agent.agent_artifacts_cache.os.listdir",
            side_effect=spying_listdir,
        ),
        patch("builtins.open", side_effect=spying_open),
    ):
        panel.update_header_only(agent)

    artifacts_str = str(artifacts_dir)
    leaked_listdirs = [p for p in listdir_calls if artifacts_str in p]
    leaked_opens = [p for p in opened_paths if artifacts_str in p]
    assert leaked_listdirs == [], (
        f"update_header_only must not list the artifacts dir: {leaked_listdirs}"
    )
    assert leaked_opens == [], (
        f"update_header_only must not open agent artifacts: {leaked_opens}"
    )


def test_update_header_only_does_not_call_full_update_display() -> None:
    """Regression guard: the immediate path must skip ``update_display``."""
    panel = _FakePanel()
    agent = _make_agent()

    full_calls: list[Agent] = []

    def fail_full(agent_arg: Agent) -> None:
        full_calls.append(agent_arg)

    # Patch the bound method on the instance so we don't disturb other tests.
    panel.update_display = fail_full  # type: ignore[method-assign]

    panel.update_header_only(agent)

    assert full_calls == [], "update_header_only should not delegate to update_display"


def test_update_header_only_includes_error_traceback() -> None:
    panel = _FakePanel()
    tb = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    raise ValueError('boom')\n"
        "ValueError: boom\n"
    )
    agent = _make_agent(
        status="FAILED",
        error_message="boom",
        error_traceback=tb,
    )

    panel.update_header_only(agent)

    rendered = panel.captured[-1]
    assert isinstance(rendered, Group)
    # Group should contain the header Text plus the traceback Syntax.
    has_syntax = any(isinstance(r, Syntax) for r in rendered.renderables)
    assert has_syntax, "error_traceback should render as a Syntax block"
    plain = _plain_of(rendered)
    assert "AGENT DETAILS" in plain
    assert "ValueError: boom" in plain


def test_update_header_only_skips_embedded_workflows_disk_read(
    tmp_path: Path,
) -> None:
    """``cheap=True`` must not call ``load_embedded_workflows``."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "embedded_workflows.json").write_text(
        json.dumps([{"name": "propose", "args": {}}]),
        encoding="utf-8",
    )

    agent = _make_agent(artifacts_dir=str(artifacts_dir))

    panel = _FakePanel()
    with patch(
        "sase.ace.tui.widgets.prompt_panel._agent_display_parts.load_embedded_workflows"
    ) as mock_load:
        panel.update_header_only(agent)

    assert mock_load.call_count == 0, (
        "cheap header-only path must not call load_embedded_workflows"
    )
    plain = _plain_of(panel.captured[-1])
    # Without the disk read, the Embedded Workflows field should be omitted.
    assert "Embedded Workflows" not in plain
