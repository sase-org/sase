"""Shared builders for command availability tests."""

from __future__ import annotations

from typing import Any

from sase.ace.patch import Patch, CommitEntry
from sase.ace.tui.commands import CommandSpec, build_command_catalog
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType


def catalog_by_id() -> dict[str, CommandSpec]:
    return {c.id: c for c in build_command_catalog(load_keymap_registry({}))}


def make_patch(
    *,
    cl: str | None = "12345",
    status: str = "Ready",
    commits: list[CommitEntry] | None = None,
    **kwargs: Any,
) -> Patch:
    return Patch(
        name=kwargs.get("name", "test_cl"),
        description="test",
        parent=None,
        cl=cl,
        status=status,
        bug=kwargs.get("bug"),
        commits=commits,
        hooks=None,
        comments=None,
        mentors=None,
        file_path="/tmp/test.sase",
        line_number=1,
    )


def make_agent(*, status: str = "RUNNING", **kwargs: Any) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=kwargs.get("cl_name", "my_feature"),
        project_file="/tmp/test.sase",
        status=status,
        start_time=None,
        workspace_num=kwargs.get("workspace_num"),
        response_path=kwargs.get("response_path"),
        attempt_history=kwargs.get("attempt_history", []),
        pid=kwargs.get("pid"),
    )
