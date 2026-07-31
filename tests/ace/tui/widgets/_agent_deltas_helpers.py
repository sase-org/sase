"""Shared helpers for agent DELTAS rendering tests."""

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
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod


def clear_linked_delta_caches() -> None:
    linked_deltas_mod._linked_diff_text_cache.clear()
    linked_deltas_mod._linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_linked_delta_cache.clear()
    linked_deltas_mod._selected_agent_cache_monotonic.clear()


def make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 14, 23, 45),
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakePromptPanel(AgentDisplayMixin, AgentHintsDisplayMixin):
    def __init__(self) -> None:
        self.captured: list[object] = []

    def update(self, renderable: object) -> None:
        self.captured.append(renderable)


class WorkspaceDiffProvider:
    def __init__(self, diff_by_workspace: dict[str, str]) -> None:
        self.diff_by_workspace = diff_by_workspace

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        return (True, self.diff_by_workspace[Path(cwd).name])


def plain_of(renderable: object) -> str:
    if isinstance(renderable, Text):
        return renderable.plain
    if isinstance(renderable, Syntax):
        return str(renderable.code)
    if isinstance(renderable, Group):
        return "\n".join(plain_of(child) for child in renderable.renderables)
    return str(renderable)
