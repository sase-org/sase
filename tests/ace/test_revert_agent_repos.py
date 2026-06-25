"""Repository resolution tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

from pathlib import Path

from sase.ace.revert_agent import resolve_revert_repos
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata


def test_resolve_revert_repos_includes_done_suffix_linked_repos(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    missing = tmp_path / "missing"
    nonsuffix = tmp_path / "nonsuffix"
    primary.mkdir()
    linked.mkdir()
    nonsuffix.mkdir()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file=str(tmp_path / "project.sase"),
        status="DONE",
        start_time=None,
        workspace_num=0,
        workspace_dir=str(primary),
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir=str(linked),
                workspace_strategy="suffix",
            ),
            LinkedRepoMetadata(
                name="missing",
                workspace_dir=str(missing),
                workspace_strategy="suffix",
            ),
            LinkedRepoMetadata(
                name="nonsuffix",
                workspace_dir=str(nonsuffix),
                workspace_strategy="shared",
            ),
        ),
    )

    repos = resolve_revert_repos(agent)

    assert [(repo.label, repo.is_primary) for repo in repos] == [
        ("primary", True),
        ("sase-core", False),
    ]
