"""Shared test helpers for file-panel diff behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType


def _make_running_agent(
    *,
    workspace_num: int = 1,
    workspace_dir: str | None = None,
    project_file: str = "/tmp/projects/myproj/myproj.sase",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file=project_file,
        status="RUNNING",
        start_time=None,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow="ace(run)-202604010000",
        raw_suffix="202604010000",
    )


def _make_root_plan_agent(workspace_num: int = 1) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my-feature",
        project_file="/tmp/projects/myproj/myproj.sase",
        status="PLAN APPROVED",
        start_time=datetime(2024, 1, 1, 14, 0),
        workspace_num=workspace_num,
        workflow="ace(plan)-202604010000",
        raw_suffix="202604010000",
        role_suffix="-plan",
        plan_chain_root=True,
    )


def _make_active_coder_followup(
    *,
    workspace_num: int,
    workspace_dir: str | None = None,
    project_file: str = "/tmp/projects/myproj/myproj.sase",
    start_time: datetime,
    raw_suffix: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature-code",
        project_file=project_file,
        status="PLAN APPROVED",
        start_time=start_time,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow="ace(run)-202604010000-code",
        raw_suffix=raw_suffix,
        parent_timestamp="202604010000",
        role_suffix="-code",
    )


def _setup_workspace(tmp_path: Path, name: str = "myproj_1") -> Path:
    workspace = tmp_path / name
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".git" / "index").write_bytes(b"\x00" * 16)
    return workspace


def _write_project_file(tmp_path: Path, primary_workspace: Path) -> Path:
    project_file = tmp_path / "projects" / "myproj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(
        f"WORKSPACE_DIR: {primary_workspace}\nNAME: my-feature\n",
        encoding="utf-8",
    )
    return project_file


def _git_diff(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cwd_calls: list[str] = []

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.cwd_calls.append(cwd)
        return (True, f"diff for call {self.calls}")


class _DiffTextProvider:
    """VCS provider stub returning a fixed unified diff."""

    def __init__(self, diff_text: str) -> None:
        self.diff_text = diff_text
        self.calls = 0

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        return (True, self.diff_text)


class _FailedDiffProvider:
    def __init__(self, *, raises: bool) -> None:
        self.raises = raises
        self.calls = 0

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.raises:
            raise TimeoutError("diff timed out")
        return (False, None)
