"""Tests for Agents-tab retry-edit name rewriting."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock, patch

from sase.ace.tui.actions.agent_workflow._entry_points import (
    EntryPointsMixin,
    _rewrite_retry_prompt_name,
)


@dataclass
class _Agent:
    raw_prompt: str | None
    agent_name: str | None = "foo"
    project_file: str = "/tmp/proj/proj.gp"
    cl_name: str = "branch"
    is_project_agent: bool = False

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt


class _App(EntryPointsMixin):
    def __init__(self, agent: _Agent) -> None:
        self.agent = agent
        self.launched: tuple[str, str, str, bool] | None = None
        self.notifications: list[tuple[str, str | None]] = []

    def _get_selected_agent(self) -> _Agent:
        return self.agent

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.launched = (raw_prompt, project_file, cl_name, is_project_agent)

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def test_rewrite_retry_prompt_prepends_name_when_missing() -> None:
    assert _rewrite_retry_prompt_name("Do work", "foo.1") == "%name:foo.1\nDo work"


def test_rewrite_retry_prompt_replaces_percent_name() -> None:
    assert (
        _rewrite_retry_prompt_name("%name:foo\nDo work", "foo.1")
        == "%name:foo.1\nDo work"
    )


def test_rewrite_retry_prompt_replaces_percent_n() -> None:
    assert (
        _rewrite_retry_prompt_name("%n:foo\nDo work", "foo.1") == "%name:foo.1\nDo work"
    )


def test_rewrite_retry_prompt_ignores_fenced_and_disabled_name_directives() -> None:
    prompt = (
        "```\n%name:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%n:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert _rewrite_retry_prompt_name(prompt, "foo.1") == f"%name:foo.1\n{prompt}"


@patch("sase.agent.names.allocate_retry_name", return_value="foo.1")
def test_retry_edit_agent_prepends_allocated_retry_name(
    _mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name="foo"))

    app._retry_edit_agent()

    assert app.launched == (
        "%name:foo.1\nDo work",
        "/tmp/proj/proj.gp",
        "branch",
        False,
    )
    assert app.notifications == []


@patch("sase.agent.names.allocate_retry_name", return_value="foo.1")
def test_retry_edit_agent_preserves_unnamed_agent_prompt(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name=None))

    app._retry_edit_agent()

    assert app.launched == ("Do work", "/tmp/proj/proj.gp", "branch", False)
    assert app.notifications == []
    assert not mock_allocate.called
