"""Repository resolution tests for :mod:`sase.ace.revert_agent`."""

from __future__ import annotations

from pathlib import Path

from sase.ace.revert_agent import (
    BulkRevertPreview,
    RevertPreview,
    RevertTarget,
    build_bulk_revert_execute_intent,
    build_bulk_revert_intent,
    build_revert_execute_intent,
    build_revert_intent,
    resolve_revert_repos,
)
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


def test_intent_builders_preserve_project_scope(tmp_path: Path) -> None:
    project_name = "gh_example__project"
    project_file = tmp_path / project_name / f"{project_name}.sase"
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=project_name,
        project_file=str(project_file),
        status="DONE",
        start_time=None,
        workspace_num=0,
        agent_name="foo",
    )
    target = RevertTarget(
        agent_name="foo",
        display_name="foo",
        workspace_dir=str(tmp_path / "workspace"),
    )

    preview_intent = build_revert_intent(agent, "foo", None)
    bulk_preview_intent = build_bulk_revert_intent((target,), (agent,), agent)
    execute_intent = build_revert_execute_intent(
        agent,
        RevertPreview(
            agent_name="foo",
            scope="agent",
            workspace_dir=str(tmp_path / "preview"),
        ),
        None,
    )
    bulk_execute_intent = build_bulk_revert_execute_intent(
        agent,
        BulkRevertPreview(
            workspace_dir=str(tmp_path / "preview"),
            targets=(target,),
        ),
    )

    assert agent.is_project_agent
    assert preview_intent.is_project_scoped
    assert bulk_preview_intent.is_project_scoped
    assert execute_intent.is_project_scoped
    assert bulk_execute_intent.is_project_scoped
