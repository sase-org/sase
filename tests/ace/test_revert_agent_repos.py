"""Repository resolution tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

from pathlib import Path

from sase.ace.revert_agent import resolve_revert_repos
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.linked_repos import record_opened_external_repo


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
            ),
            LinkedRepoMetadata(
                name="missing",
                workspace_dir=str(missing),
            ),
            LinkedRepoMetadata(
                name="nonsuffix",
                workspace_dir=str(nonsuffix),
            ),
        ),
    )

    repos = resolve_revert_repos(agent)

    assert [(repo.label, repo.is_primary) for repo in repos] == [
        ("primary", True),
        ("sase-core", False),
        ("nonsuffix", False),
    ]


def test_resolve_revert_repos_includes_opened_external_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    artifacts = tmp_path / "artifacts"
    external = primary / "sase" / "repos" / "external" / "gh" / "pallets" / "click"
    primary.mkdir()
    artifacts.mkdir()
    external.mkdir(parents=True)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    record_opened_external_repo(
        "gh:pallets/click",
        str(external),
        reason="port parser fix",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file=str(tmp_path / "project.sase"),
        status="DONE",
        start_time=None,
        workspace_num=0,
        workspace_dir=str(primary),
        artifacts_dir=str(artifacts),
    )

    repos = resolve_revert_repos(agent)

    assert [(repo.label, repo.repo_kind) for repo in repos] == [
        ("primary", "linked"),
        ("gh:pallets/click", "external"),
    ]
