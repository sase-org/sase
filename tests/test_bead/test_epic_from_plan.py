"""Deterministic approved-epic frontmatter to bead DAG tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.cli_work_handler import launch_epic_bead_work
from sase.bead.epic_from_plan import create_and_launch_epic_from_plan
from sase.bead.model import BeadTier, IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter

from .cli_work_helpers import FakeLaunchResult


EPIC_PLAN = """---
tier: epic
title: Deterministic rollout
goal: Ship the rollout through an ordered DAG
model: claude/opus
changespec: rollout
bug_id: 12345
phases:
  - id: core
    title: Build the core
    depends_on: []
    description: Implement the shared core.
    size: small
  - id: cli
    title: Add the CLI
    depends_on: [core]
    size: medium
    model: codex/gpt-5.6-sol
  - id: smoke
    title: Exercise the rollout
    depends_on: [core, cli]
    size: large
---
# Plan

Execute the rollout.
"""


def test_create_and_launch_maps_frontmatter_in_order(
    project_dir: Path,
) -> None:
    plan_path = project_dir / "plans" / "rollout.md"
    plan_path.parent.mkdir()
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    commits: list[str] = []
    launched: list[str] = []

    with BeadProject(project_dir) as proj:

        def commit_plan_update(path: Path) -> bool:
            commits.append(path.read_text(encoding="utf-8"))
            # The plan link is committed immediately after the epic container,
            # before any phase child is allocated.
            frontmatter, _body, _had_frontmatter = parse_frontmatter(commits[-1])
            assert proj.get_epic_children(str(frontmatter["bead_id"])) == []
            return True

        def launch_work(project: BeadProject, epic_id: str) -> bool:
            launched.append(epic_id)
            assert [child.id for child in project.get_epic_children(epic_id)] == [
                f"{epic_id}.1",
                f"{epic_id}.2",
                f"{epic_id}.3",
            ]
            return True

        result = create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="sdd/plans/202607/rollout.md",
            commit_plan_update=commit_plan_update,
            launch_work=launch_work,
        )

        assert result.epic.tier is BeadTier.EPIC
        assert result.epic.title == "Deterministic rollout"
        assert result.epic.description == "Ship the rollout through an ordered DAG"
        assert result.epic.design == "sdd/plans/202607/rollout.md"
        assert result.epic.model == "claude/opus"
        assert result.epic.changespec_name == "rollout"
        assert result.epic.changespec_bug_id == "12345"
        assert [phase.id for phase in result.phases] == [
            f"{result.epic.id}.1",
            f"{result.epic.id}.2",
            f"{result.epic.id}.3",
        ]
        assert result.phases[0].description == "Implement the shared core."
        assert result.phases[1].description == (
            "Phase `cli` in approved epic plan `sdd/plans/202607/rollout.md`."
        )
        assert result.phases[1].model == "codex/gpt-5.6-sol"
        assert result.phases[2].model == ""
        assert [phase.size for phase in result.phases] == [
            PhaseSize.SMALL,
            PhaseSize.MEDIUM,
            PhaseSize.LARGE,
        ]
        assert [
            (dependency.issue_id, dependency.depends_on_id)
            for dependency in result.dependencies
        ] == [
            (result.phases[1].id, result.phases[0].id),
            (result.phases[2].id, result.phases[0].id),
            (result.phases[2].id, result.phases[1].id),
        ]

    assert len(commits) == 1
    linked_frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan_path.read_text(encoding="utf-8")
    )
    assert linked_frontmatter["bead_id"] == result.epic.id
    assert launched == [result.epic.id]


def test_creation_failure_removes_epic_and_restores_plan(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.epic_from_plan.auto_commit_bead_store",
        lambda _message: None,
    )

    with BeadProject(project_dir) as proj:
        monkeypatch.setattr(
            proj,
            "add_dependency",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("dep write failed")),
        )
        with pytest.raises(RuntimeError, match="dep write failed"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=lambda _path: True,
                launch_work=lambda _project, _epic_id: True,
            )
        assert proj.list_issues() == []

    assert plan_path.read_text(encoding="utf-8") == EPIC_PLAN


@pytest.mark.parametrize(
    ("message", "error_kwargs", "preserves_epic"),
    [
        pytest.param("launch failed", {}, False, id="zero-spawn"),
        pytest.param(
            "partial launch failed",
            {"agents_spawned": True},
            True,
            id="partial-spawn",
        ),
        pytest.param(
            "commit failed",
            {"agents_launched": True},
            True,
            id="post-launch-commit",
        ),
    ],
)
def test_epic_creation_rollback_respects_runner_spawn_boundary(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    error_kwargs: dict[str, bool],
    preserves_epic: bool,
) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(EPIC_PLAN, encoding="utf-8")
    monkeypatch.setattr(
        "sase.bead.epic_from_plan.auto_commit_bead_store",
        lambda _message: None,
    )

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match=message):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=lambda _path: True,
                launch_work=lambda _project, _epic_id: (_ for _ in ()).throw(
                    BeadWorkError(message, **error_kwargs)
                ),
            )
        issues = proj.list_issues()
        if preserves_epic:
            assert len(issues) == 4
            assert (
                len([issue for issue in issues if issue.issue_type is IssueType.PLAN])
                == 1
            )
        else:
            assert issues == []

    content = plan_path.read_text(encoding="utf-8")
    if preserves_epic:
        linked_frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
        assert linked_frontmatter["bead_id"]
    else:
        assert content == EPIC_PLAN


def test_existing_bead_link_refuses_duplicate_creation(project_dir: Path) -> None:
    plan_path = project_dir / "rollout.md"
    plan_path.write_text(
        EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-99"),
        encoding="utf-8",
    )

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match="refusing to create a duplicate"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="rollout.md",
                commit_plan_update=lambda _path: True,
                launch_work=lambda _project, _epic_id: True,
            )
        assert proj.list_issues() == []


def test_invalid_plan_creates_nothing_and_does_not_launch(
    project_dir: Path,
) -> None:
    plan_path = project_dir / "invalid.md"
    plan_path.write_text(
        EPIC_PLAN.replace("depends_on: [core]", "depends_on: [missing]"),
        encoding="utf-8",
    )
    commits: list[Path] = []
    launches: list[str] = []

    with BeadProject(project_dir) as proj:
        with pytest.raises(RuntimeError, match="failed deterministic validation"):
            create_and_launch_epic_from_plan(
                proj,
                plan_path=plan_path,
                plan_ref="invalid.md",
                commit_plan_update=lambda path: not commits.append(path),
                launch_work=lambda _project, epic_id: not launches.append(epic_id),
            )
        assert proj.list_issues() == []

    assert commits == []
    assert launches == []
    assert plan_path.read_text(encoding="utf-8") == EPIC_PLAN.replace(
        "depends_on: [core]", "depends_on: [missing]"
    )


@pytest.mark.usefixtures("fake_cli_work_xprompts")
def test_valid_plan_runs_real_bead_work_wave_path(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid epic reaches the real wave renderer and JIT launcher path."""
    from sase.agent.names import AgentNameWipeResult
    from sase.bead.model import Status

    plan_path = project_dir / "rollout.md"
    plan_path.write_text(
        EPIC_PLAN.replace("changespec: rollout\nbug_id: 12345\n", ""),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "sase.agent.names.wipe_agent_name_for_reuse",
        lambda name: AgentNameWipeResult(target_name=name, found=False),
    )

    def fake_launch(
        query: str,
        extra_env: object = None,
        segment_extra_env: object = None,
    ) -> FakeLaunchResult:
        del extra_env, segment_extra_env
        captured["query"] = query
        return FakeLaunchResult()

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.bead.sync.commit_bead_work_launch",
        lambda *_args, **_kwargs: False,
    )

    with BeadProject(project_dir) as proj:
        result = create_and_launch_epic_from_plan(
            proj,
            plan_path=plan_path,
            plan_ref="rollout.md",
            commit_plan_update=lambda _path: True,
            launch_work=lambda project, epic_id: launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=True,
                no_push=True,
            ),
        )

        assert proj.show(result.epic.id).is_ready_to_work is True
        launched_phases = [proj.show(phase.id) for phase in result.phases]
        assert all(phase.status is Status.OPEN for phase in launched_phases)
        assert all(phase.assignee == "" for phase in launched_phases)

    query = captured["query"]
    for phase in result.phases:
        assert f"#bd/work_phase_bead:{phase.id}" in query
        assert f"bead={phase.id}" in query
    assert f"#bd/land_epic:{result.epic.id}" in query
    assert f"bead={result.epic.id}" in query
    assert f"%w:{result.phases[0].id}" in query
    assert f"%w:{result.phases[0].id},{result.phases[1].id}" in query
