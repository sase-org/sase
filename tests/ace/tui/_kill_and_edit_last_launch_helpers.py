"""Shared fixtures for kill-and-edit-last-launch TUI tests."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.actions.agent_workflow._launch_records import LaunchRecordContext
from sase.ace.tui.models.agent import AgentType
from sase.agent.launch_types import AgentLaunchResult

AgentIdentity = tuple[str, str, str | None]


@dataclass
class _FakeAgent:
    """Minimal duck-typed row used by the join and dispatch tests."""

    name: str
    raw_prompt: str | None = "Do work"
    status: str = "DONE"
    pid: int | None = None
    project_file: str = "/tmp/proj/proj.sase"
    cl_name: str = "branch"
    is_project_agent: bool = False
    restartable: bool = True
    is_clan_container: bool = False
    is_gate: bool = False
    agent_family: str | None = None
    agent_family_parallel: bool = False
    role_suffix: str | None = None
    phase_bead_id: str | None = None
    is_family_root_entry: bool = False
    artifacts_dir_value: str | None = None
    agent_type: AgentType = AgentType.RUNNING
    workspace_num: int | None = None

    @property
    def identity(self) -> AgentIdentity:
        return (self.agent_type, self.name, None)

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def agent_name(self) -> str:
        return self.name

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt

    def get_artifacts_dir(self) -> str | None:
        return self.artifacts_dir_value


def _context(display_name: str = "demo") -> LaunchRecordContext:
    return LaunchRecordContext(
        display_name=display_name,
        project_file=f"/tmp/projects/{display_name}/{display_name}.sase",
        cl_name=display_name,
        is_project_agent=True,
    )


def _artifacts_dir(project: str, timestamp: str) -> str:
    return f"/tmp/fake_projects/{project}/artifacts/ace-run/{timestamp}"


def _matchable_result(project: str, timestamp: str) -> AgentLaunchResult:
    """Build a result whose joinable artifact dir is a pure path computation.

    Leaving ``project_name``/``timestamp`` unset on the result routes
    ``artifact_dir_from_launch_result`` through its ``output_path`` fallback
    (a plain ``.../artifacts/<workflow>/<14-digit timestamp>`` parse), which
    needs no real project registration or on-disk fixture.
    """
    return AgentLaunchResult(
        pid=100,
        workspace_num=1,
        workspace_dir="/tmp/ws",
        output_path=f"{_artifacts_dir(project, timestamp)}/live_reply.md",
    )
