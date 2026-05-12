"""Shared helpers for agent display tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin
from sase.ace.tui.widgets.prompt_panel._agent_display_hints import (
    AgentHintsDisplayMixin,
)


def make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for testing."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakePromptPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    """Mixin-only test double recording ``self.update(...)`` calls."""

    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


def plain_of(renderable: object) -> str:
    """Flatten a prompt panel renderable into plain text for assertions."""
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(plain_of(child) for child in renderable.renderables)
    return str(renderable)


def make_artifact_agent(
    tmp_path: Path,
    *,
    status: str,
    raw_xprompt: str = "Launch from @src/raw.py",
    workspace_dir: str | None = None,
) -> Agent:
    artifacts_dir = tmp_path / f"{status.lower()}-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text(raw_xprompt, encoding="utf-8")
    (artifacts_dir / "01_prompt.md").write_text(
        "Expanded prompt body\n",
        encoding="utf-8",
    )
    response_path = artifacts_dir / "response.md"
    response_path.write_text("Final response body\n", encoding="utf-8")

    return make_agent(
        status=status,
        stop_time=datetime(2024, 1, 1, 14, 30, 0),
        artifacts_dir=str(artifacts_dir),
        response_path=str(response_path),
        workspace_dir=workspace_dir,
    )
