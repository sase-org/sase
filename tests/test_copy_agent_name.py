"""Tests for ClipboardMixin._copy_agent_name (Agents tab %n)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sase.ace.tui.actions.clipboard import ClipboardMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "workflow": "wf",
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeApp(ClipboardMixin):
    """Minimal stand-in app exposing only what _copy_agent_name needs."""

    def __init__(self, agent: Agent | None) -> None:
        self._agents = [agent] if agent is not None else []
        self.current_idx = 0
        self.notifications: list[tuple[str, str]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def test_copy_agent_name_uses_agent_name_when_set() -> None:
    agent = _make_agent(agent_name="explicit_name")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        app._copy_agent_name()

    mock_copy.assert_called_once_with("explicit_name")
    assert app.notifications == [("Copied: Agent Name (explicit_name)", "information")]


def test_copy_agent_name_falls_back_to_display_name() -> None:
    # No agent_name; workflow top-level entry → display_name == workflow.
    agent = _make_agent(agent_name=None, workflow="my_workflow")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        app._copy_agent_name()

    mock_copy.assert_called_once_with("my_workflow")
    assert app.notifications == [
        ("Copied: Agent Display Name (my_workflow)", "information")
    ]


def test_copy_agent_name_no_agent_selected() -> None:
    app = FakeApp(None)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.copy_to_system_clipboard",
        return_value=True,
    ) as mock_copy:
        app._copy_agent_name()

    mock_copy.assert_not_called()
    assert app.notifications == [("No agent selected", "warning")]


def test_copy_agent_name_clipboard_failure() -> None:
    agent = _make_agent(agent_name="explicit_name")
    app = FakeApp(agent)

    with patch(
        "sase.ace.tui.actions.clipboard._agents.copy_to_system_clipboard",
        return_value=False,
    ):
        app._copy_agent_name()

    assert app.notifications == [("Failed to copy to clipboard", "error")]
